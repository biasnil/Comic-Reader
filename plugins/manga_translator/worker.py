"""The helper process: reads JSON commands on stdin, writes JSON messages on stdout.

Started by the reader (comicreader/plugins/client.py). Run from source as
    python -m plugins.manga_translator.worker        (from the repository root)
or as manga-translator-worker.exe when built with MangaTranslator.spec.
The protocol is described in comicreader/core/translation.py. Logs go to stderr.
"""
import os
import sys
import traceback
from pathlib import Path

if __package__ in (None, ""):  # started as a script (the frozen exe): make absolute imports work
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comicreader.core.translation import (DEFAULT_SETTINGS, PROTOCOL, TranslationCache,
                                          comic_signature, read_message, write_message)
from plugins.manga_translator import __version__


class Worker:
    def __init__(self, out=sys.stdout):
        self.out = out
        self.settings = dict(DEFAULT_SETTINGS)
        self.translator = None          # PageTranslator, built lazily (loading models is slow)
        self._source = None             # the comic currently open: (path, Source)

    def send(self, **msg):
        write_message(self.out, msg)

    # ---- commands --------------------------------------------------------------------- #
    def hello(self, msg):
        problems = []
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
        except ImportError as exc:
            problems.append(f"missing package: {exc.name} "
                            "(pip install -r plugins/manga_translator/requirements.txt)")
        self.send(type="hello", protocol=PROTOCOL, version=__version__, problems=problems)

    def configure(self, msg):
        from plugins.common import models
        new = {**DEFAULT_SETTINGS, **(msg.get("settings") or {})}
        if new != self.settings:
            self.settings = new
            self.translator = None
        missing = [{"name": m.name, "size": models.expected_size(m)} for m in models.missing(self.settings)]
        self.send(type="configured", missing_models=missing)

    def download(self, msg):
        from plugins.common import models
        for m in models.missing(self.settings):
            last = [-1]

            def progress(done, total, name=m.name):
                pct = done * 100 // max(1, total)
                if pct != last[0]:
                    last[0] = pct
                    self.send(type="download", name=name, done=done, total=total)
            models.download(m, progress)
        self.send(type="downloaded")

    def translate(self, msg):
        job, page = msg.get("job"), int(msg["page"])
        if self.translator is None:
            self.send(type="stage", job=job, page=page, stage="loading models")
            from plugins.manga_translator.pipeline import PageTranslator
            self.translator = PageTranslator(self.settings)
        img = self._open(Path(msg["comic"])).load(page)
        out, blocks, clean = self.translator.translate(
            img, rtl=bool(msg.get("rtl", True)),
            progress=lambda stage: self.send(type="stage", job=job, page=page, stage=stage))
        blocks["page"] = page
        cache = TranslationCache(msg["key"])
        cache.validate(comic_signature(Path(msg["comic"])))
        cache.write(page, out, blocks, clean)
        self.send(type="done", job=job, page=page, blocks=len(blocks["blocks"]))

    def retypeset(self, msg):
        """Redraw edited translations on the saved clean page (no models needed)."""
        from PIL import Image

        from plugins.manga_translator.pipeline import retypeset
        job, page = msg.get("job"), int(msg["page"])
        cache = TranslationCache(msg["key"])
        data = cache.load_blocks(page)
        if data is None or not cache.page_clean(page).exists():
            raise RuntimeError("This page was translated by an older version: retranslate it first")
        with Image.open(cache.page_clean(page)) as im:
            clean = im.convert("RGB")
        out, data = retypeset(clean, data, msg.get("blocks") or [], self.settings.get("font_file", ""))
        cache.write(page, out, data)
        self.send(type="done", job=job, page=page, blocks=len(data["blocks"]))

    def _open(self, path: Path):
        if self._source and self._source[0] == path:
            return self._source[1]
        from comicreader.core.sources import SourceFactory
        if self._source:
            self._source[1].close()
            self._source = None
        src, _ = SourceFactory.open(path, interactive=False)
        self._source = (path, src)
        return src

    # ---- loop ------------------------------------------------------------------------ #
    def run(self, stream=sys.stdin):
        handlers = {"hello": self.hello, "configure": self.configure, "download": self.download,
                    "translate": self.translate, "retypeset": self.retypeset}
        for line in stream:
            msg = read_message(line)
            if msg is None:
                continue
            cmd = msg.get("cmd")
            if cmd == "quit":
                break
            handler = handlers.get(cmd)
            if handler is None:
                self.send(type="error", message=f"unknown command {cmd!r}")
                continue
            try:
                handler(msg)
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                self.send(type="error", cmd=cmd, job=msg.get("job"), page=msg.get("page"),
                          message=str(exc) or exc.__class__.__name__)
        if self._source:
            self._source[1].close()


def main():
    # keep the real stdout for protocol messages only; anything else printed (by Python code
    # or by native libraries writing to fd 1) is redirected to stderr, i.e. the log file
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", closefd=False)
    Worker(out).run(stdin)


if __name__ == "__main__":
    main()
