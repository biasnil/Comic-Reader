"""The Bubble Reader helper process: JSON commands on stdin, JSON messages on stdout.

Started by the reader (comicreader/plugins/bubble_reader.py). From source:
    python -m plugins.bubble_reader.worker        (from the repository root)
or as bubble-reader-worker.exe (BubbleReader.spec). Protocol: comicreader/core/bubbles.py.

Three threads: this one reads commands and handles the quick ones (pause, stop, volume...) at
once; a task thread does the slow ones in order (configure, download, analyze); a player thread
speaks the bubbles, preparing the next one's audio while the current one plays.
"""
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

if __package__ in (None, ""):  # started as a script (the frozen exe): make absolute imports work
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comicreader.core.bubbles import DEFAULT_SETTINGS, PROTOCOL, BubbleCache
from comicreader.core.plugins import read_message, write_message
from comicreader.core.translation import comic_signature
from plugins.bubble_reader import __version__

GAP = 0.25   # seconds of quiet between two bubbles


class Player:
    """Speaks a list of items; a new play() or stop() ends the one before."""

    def __init__(self, worker: "Worker"):
        self.worker = worker
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.output = None

    def _out(self):
        if self.output is None:
            from plugins.bubble_reader.speech import Output
            self.output = Output(notice=lambda text: self.worker.send(type="notice", message=text))
            self.output.volume = self.worker.settings["volume"] / 100
        return self.output

    def play(self, job, items: list[dict], start: int):
        self.stop()
        self._stop = threading.Event()
        out = self._out()
        out.paused = False
        self._thread = threading.Thread(target=self._run, args=(job, items, start, self._stop, out),
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self.output is not None:
            self.output.stop()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        self._thread = None

    def pause(self, paused: bool):
        if self.output is not None:
            self.output.paused = paused

    def _clip(self, item: dict):
        s = self.worker.settings
        voice = s["voice_ja"] if item.get("lang") == "ja" else s["voice_en"]
        return self.worker.voice().synth(item["text"], item.get("lang", "en"), voice, float(s["speed"]))

    def _run(self, job, items, start, stop: threading.Event, out):
        try:
            upcoming = None
            for i in range(start, len(items)):
                clip = upcoming if upcoming is not None else self._clip(items[i])
                upcoming = None
                if stop.is_set():
                    return
                self.worker.send(type="speaking", job=job, index=i)
                out.start(*clip)
                if i + 1 < len(items):
                    upcoming = self._clip(items[i + 1])   # made while this one plays
                if not out.wait(stop):
                    return
                if stop.wait(GAP):
                    return
            self.worker.send(type="finished", job=job)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            if not stop.is_set():
                self.worker.send(type="error", cmd="play", job=job,
                                 message=str(exc) or exc.__class__.__name__)


class Worker:
    def __init__(self, out=sys.stdout):
        self.out = out
        self._out_lock = threading.Lock()
        self.settings = dict(DEFAULT_SETTINGS)
        self._analyzer = None
        self._voice = None
        self._sources = {}   # the open comic: {path: Source}
        self.tasks: "queue.Queue[dict | None]" = queue.Queue()
        self.player = Player(self)
        threading.Thread(target=self._task_loop, daemon=True).start()

    def send(self, **msg):
        with self._out_lock:
            write_message(self.out, msg)

    # ---- lazily created engines ------------------------------------------------------ #
    def voice(self):
        if self._voice is None:
            from plugins.bubble_reader.speech import Voice
            self._voice = Voice(self.settings["gpu"], progress=self._download_progress)
        return self._voice

    def analyzer(self):
        if self._analyzer is None:
            from plugins.bubble_reader.analyze import PageAnalyzer
            self._analyzer = PageAnalyzer(self.settings["gpu"])
        return self._analyzer

    def _download_progress(self, name: str, done: int, total: int):
        pct = done * 100 // max(1, total)
        if pct != getattr(self, "_last_pct", None) or done == total:
            self._last_pct = pct
            self.send(type="download", name=name, done=done, total=total)

    # ---- quick commands (this thread) --------------------------------------------------- #
    def hello(self, msg):
        problems = []
        for module, package in (("numpy", "numpy"), ("onnxruntime", "onnxruntime"),
                                ("pykokoro", "pykokoro")):
            try:
                __import__(module)
            except ImportError:
                problems.append(f"missing package: {package} "
                                "(pip install -r plugins/bubble_reader/requirements.txt)")
        self.send(type="hello", protocol=PROTOCOL, version=__version__, problems=problems)

    def set(self, msg):
        if "speed" in msg:
            self.settings["speed"] = max(0.5, min(2.0, float(msg["speed"])))
        if "volume" in msg:
            self.settings["volume"] = max(0, min(100, int(msg["volume"])))
            if self.player.output is not None:
                self.player.output.volume = self.settings["volume"] / 100

    # ---- slow commands (task thread, in order) ------------------------------------------ #
    def _task_loop(self):
        while True:
            msg = self.tasks.get()
            if msg is None:
                return
            cmd = msg.get("cmd")
            try:
                getattr(self, f"task_{cmd}")(msg)
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                self.send(type="error", cmd=cmd, job=msg.get("job"), page=msg.get("page"),
                          message=str(exc) or exc.__class__.__name__)

    def _missing(self) -> list:
        from plugins.bubble_reader.analyze import japanese_ocr_needs_download
        from plugins.bubble_reader.speech import KOKORO_SIZE, kokoro_present
        from plugins.common import models
        files = [models.DETECTOR]
        if self.settings["language"] in ("auto", "ja") and japanese_ocr_needs_download():
            files += models.OCR_FILES
        out = [(m.name, models.expected_size(m), m) for m in files if not m.present]
        if not kokoro_present():
            out.append(("Kokoro voices", KOKORO_SIZE, None))
        return out

    def task_configure(self, msg):
        new = {**DEFAULT_SETTINGS, **(msg.get("settings") or {})}
        if new["gpu"] != self.settings["gpu"]:
            self._analyzer = None
            self._voice = None
        self.settings = new
        self.set(new)
        missing = self._missing()
        self.send(type="configured", missing_models=[{"name": n, "size": size} for n, size, _ in missing])
        if not missing:   # load Kokoro now, so the first bubble doesn't wait for it
            threading.Thread(target=self._warm_up, daemon=True).start()

    def _warm_up(self):
        try:
            self.voice().ensure()
        except Exception:
            traceback.print_exc(file=sys.stderr)   # reported properly when reading starts

    def task_download(self, msg):
        from plugins.common import models
        for name, _size, model in self._missing():
            if model is not None:
                models.download(model, lambda d, t, n=name: self._download_progress(n, d, t))
            else:
                self.voice().ensure()   # pykokoro downloads Kokoro (progress via the callback)
        self.send(type="downloaded")

    def task_analyze(self, msg):
        from plugins.bubble_reader.analyze import resolve_language
        job, page, key = msg.get("job"), int(msg["page"]), msg["key"]
        comic = Path(msg["comic"])
        lang = resolve_language(self.settings["language"], bool(msg.get("rtl")))
        cache, sig = BubbleCache(key), comic_signature(comic)
        bubbles = cache.load(page, lang, sig)
        if bubbles is None:
            img = self._source(comic).load(page)
            bubbles = self.analyzer().analyze(img, bool(msg.get("rtl")), lang)
            cache.save(page, lang, sig, bubbles)
        self.send(type="bubbles", job=job, key=key, page=page, bubbles=bubbles)

    def _source(self, path: Path):
        if path not in self._sources:
            from comicreader.core.sources import SourceFactory
            for src in self._sources.values():
                src.close()
            self._sources = {path: SourceFactory.open(path, interactive=False)[0]}
        return self._sources[path]

    # ---- loop -------------------------------------------------------------------------- #
    def run(self, stream=sys.stdin):
        quick = {"hello": self.hello, "set": self.set,
                 "play": lambda m: self.player.play(m.get("job"), m.get("items") or [],
                                                    int(m.get("start", 0))),
                 "stop": lambda m: self.player.stop(),
                 "pause": lambda m: self.player.pause(True),
                 "resume": lambda m: self.player.pause(False)}
        slow = {"configure", "download", "analyze"}
        for line in stream:
            msg = read_message(line)
            if msg is None:
                continue
            cmd = msg.get("cmd")
            if cmd == "quit":
                break
            if cmd in slow:
                self.tasks.put(msg)
                continue
            handler = quick.get(cmd)
            if handler is None:
                self.send(type="error", message=f"unknown command {cmd!r}")
                continue
            try:
                handler(msg)
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                self.send(type="error", cmd=cmd, job=msg.get("job"),
                          message=str(exc) or exc.__class__.__name__)
        self.player.stop()
        self.tasks.put(None)
        time.sleep(0.05)
        for src in self._sources.values():
            src.close()


def main():
    # the real stdout carries protocol messages only; everything else goes to stderr (the log)
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", closefd=False)
    Worker(out).run(stdin)


if __name__ == "__main__":
    main()
