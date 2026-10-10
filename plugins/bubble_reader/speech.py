"""Speaking: Kokoro voices (pykokoro, as in EchoRead) and a sound output that never blocks.

Kokoro's model (about 350 MB) downloads on first use into DATA_DIR/models/kokoro/ (pykokoro
fetches it from GitHub releases and checks it). English uses the en-us / en-gb voices; Japanese
needs pyopenjtalk-plus for its pronunciation.
If there is no sound device (or sounddevice/PortAudio is missing) the output runs silently at
the right pace, so highlighting and page turning still work.
"""
import dataclasses
import threading
import time
from collections import OrderedDict

import numpy as np

from comicreader.core.translation import MODELS_DIR

KOKORO_DIR = MODELS_DIR / "kokoro"
KOKORO_SIZE = 353_000_000   # model + voices, for the download prompt


def kokoro_present() -> bool:
    return KOKORO_DIR.exists() and any(KOKORO_DIR.rglob("kokoro-v1.0*.onnx"))


def _provider(use_gpu: bool) -> str:
    if use_gpu:
        try:
            import onnxruntime
            if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
                return "cuda"
        except ImportError:
            pass
    return "cpu"


# ---- voices ------------------------------------------------------------------------ #
class Voice:
    """Text -> audio with Kokoro. One synthesis at a time; recent clips are kept for re-reading."""

    CACHE = 48

    def __init__(self, use_gpu: bool = True, progress=None):
        self.use_gpu = use_gpu
        self.progress = progress        # progress(filename, done, total) while downloading
        self._synth = None
        self._speed = 1.0
        self._lock = threading.Lock()
        self._cache: "OrderedDict[tuple, tuple[np.ndarray, int]]" = OrderedDict()

    def ensure(self):
        """Load Kokoro, downloading it the first time (pykokoro fetches files on first use)."""
        with self._lock:
            self._load()
            self._synth.synthesize_text("Ready.", language="en-us", voice="af_heart")

    def _load(self):
        if self._synth is not None:
            return
        from pykokoro import GenerationConfig, SynthesisConfig
        from pykokoro.synthesizer import KokoroSynthesizer

        def on_asset(event):
            if self.progress and event.bytes_total:
                self.progress(str(event.filename), int(event.bytes_done), int(event.bytes_total))

        KOKORO_DIR.mkdir(parents=True, exist_ok=True)
        self._synth = KokoroSynthesizer(SynthesisConfig(
            voice="af_heart", generation=GenerationConfig(lang="en-us", speed=self._speed),
            provider=_provider(self.use_gpu), asset_progress=on_asset, cache_dir=str(KOKORO_DIR)))

    def _set_speed(self, speed: float):
        if abs(speed - self._speed) > 1e-6:
            self._speed = speed
            cfg = self._synth.config
            self._synth.config = dataclasses.replace(
                cfg, generation=dataclasses.replace(cfg.generation, speed=speed))

    def synth(self, text: str, lang: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
        key = (text, voice, round(speed, 2))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            self._load()
            self._set_speed(speed)
            language = "ja" if lang == "ja" else ("en-gb" if voice.startswith("b") else "en-us")
            try:
                result = self._synth.synthesize_text(text, language=language, voice=voice)
            except Exception as exc:
                if lang == "ja" and "openjtalk" in str(exc).lower():
                    raise RuntimeError("Japanese voices need pyopenjtalk-plus "
                                       "(pip install pyopenjtalk-plus)") from exc
                raise
            clip = (np.asarray(result.audio, dtype=np.float32).reshape(-1), int(result.sample_rate))
            self._cache[key] = clip
            while len(self._cache) > self.CACHE:
                self._cache.popitem(last=False)
            return clip


# ---- sound output ---------------------------------------------------------------------- #
class Output:
    """Plays one clip at a time in the background; pause, resume, stop and volume at any moment."""

    def __init__(self, notice=None):
        self.notice = notice            # notice(text): tells the reader something once
        self.volume = 1.0
        self.paused = False
        self._sd = None
        self._stream = None
        self._done = threading.Event()
        self._done.set()
        self._audio = np.zeros(0, dtype=np.float32)
        self._pos = 0
        self._sr = 24000
        try:
            import sounddevice
            self._sd = sounddevice
        except (ImportError, OSError):
            self._silent("sounddevice / PortAudio isn't available")

    def _silent(self, why: str):
        if self._sd is not None or self.notice is None:
            self._sd = None
        if self.notice:
            self.notice(f"No sound output ({why}): reading silently.")
        self.notice = None   # say it once

    def start(self, audio: np.ndarray, sr: int):
        self.stop()
        self._audio, self._sr, self._pos = audio, sr, 0
        self._done = threading.Event()
        if self._sd is not None:
            try:
                self._stream = self._sd.OutputStream(samplerate=sr, channels=1, dtype="float32",
                                                     callback=self._callback,
                                                     finished_callback=self._done.set)
                self._stream.start()
                return
            except Exception as exc:  # no device, device busy, ...
                self._stream = None
                self._sd = None
                self._silent(str(exc).splitlines()[0] if str(exc) else "no device")
        threading.Thread(target=self._silent_run, args=(self._done,), daemon=True).start()

    def _callback(self, outdata, frames, time_info, status):  # the audio thread
        if self.paused:
            outdata.fill(0)
            return
        chunk = self._audio[self._pos:self._pos + frames]
        n = len(chunk)
        outdata[:n, 0] = chunk * self.volume
        outdata[n:] = 0
        self._pos += n
        if self._pos >= len(self._audio):
            raise self._sd.CallbackStop

    def _silent_run(self, done: threading.Event):
        step = 0.02
        while self._pos < len(self._audio) and not done.is_set():
            time.sleep(step)
            if not self.paused:
                self._pos += int(self._sr * step)
        done.set()

    def wait(self, stop: threading.Event) -> bool:
        """Wait for the clip to end; False if `stop` was set first."""
        while not self._done.wait(0.05):
            if stop.is_set():
                return False
        return not stop.is_set()

    def stop(self):
        self._done.set()
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
