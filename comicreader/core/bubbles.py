"""The contract between the reader and the Bubble Reader plugin (no GUI code).

The plugin (plugins/bubble_reader/worker.py) finds the speech bubbles on a page, reads their text
(manga-ocr for Japanese, RapidOCR for English) and speaks them with Kokoro voices. The reader
decides what to read, highlights the bubble being spoken and turns pages.

Messages, reader -> worker ("cmd"):
    hello                                   -> hello {protocol, version, problems}
    configure {settings}                    -> configured {missing_models: [{name, size}]}
    download                                -> download {name, done, total}* then downloaded
    analyze {job, comic, key, page, rtl}    -> bubbles {job, key, page, bubbles: [Bubble]}
    play {job, items: [{text, lang}], start}-> speaking {job, index}* then finished {job}
                                               (a new play, or stop, ends the previous one)
    pause / resume / stop
    set {speed?, volume?}                   (applies at once; speed from the next bubble on)
    quit
Any command can answer: error {cmd?, job?, message}. A notice {message} is informational.

Bubble: {"box": [x1, y1, x2, y2], "text": str, "lang": "ja" | "en", "sfx": bool}
in page pixels; "sfx" marks short sound-effect text drawn over the art (skippable).
Analysed pages are cached in DATA_DIR/bubbles/<comic_id>/<page>-<lang>.json.
"""
import json
from pathlib import Path

from ..constants import DATA_DIR
from .translation import comic_id

PROTOCOL = 1
BUBBLES_DIR = DATA_DIR / "bubbles"
CACHE_VERSION = 1   # bump when analysis changes so old caches are redone

ENGLISH_VOICES = {
    "af_heart": "Heart (US, female)", "af_bella": "Bella (US, female)",
    "af_nicole": "Nicole (US, female)", "af_sarah": "Sarah (US, female)",
    "af_sky": "Sky (US, female)", "am_adam": "Adam (US, male)",
    "am_michael": "Michael (US, male)", "am_puck": "Puck (US, male)",
    "bf_emma": "Emma (UK, female)", "bf_isabella": "Isabella (UK, female)",
    "bm_george": "George (UK, male)", "bm_lewis": "Lewis (UK, male)",
}
JAPANESE_VOICES = {
    "jf_alpha": "Alpha (female)", "jf_gongitsune": "Gongitsune (female)",
    "jf_nezumi": "Nezumi (female)", "jf_tebukuro": "Tebukuro (female)",
    "jm_kumo": "Kumo (male)",
}

DEFAULT_SETTINGS = {
    "voice_en": "af_heart",
    "voice_ja": "jf_alpha",
    "speed": 1.0,             # 0.5 .. 2.0
    "volume": 100,            # 0 .. 100
    "language": "auto",       # auto (manga/RTL = Japanese, else English) | ja | en
    "read_translated": True,  # a translated page (Manga Translator) is read in English
    "skip_sfx": True,         # don't read short sound effects drawn over the art
    "auto_turn": True,        # go on to the next page after the last bubble
    "follow": True,           # scroll so the bubble being read is visible
    "gpu": True,
}


class BubbleCache:
    """Analysed pages of one comic: DATA_DIR/bubbles/<comic_id>/<page>-<lang>.json."""

    def __init__(self, key: str, root: Path = BUBBLES_DIR):
        self.dir = Path(root) / comic_id(key)

    def path(self, page: int, lang: str) -> Path:
        return self.dir / f"{page:04d}-{lang}.json"

    def load(self, page: int, lang: str, sig: list) -> list[dict] | None:
        try:
            data = json.loads(self.path(page, lang).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("version") != CACHE_VERSION or data.get("sig") != sig:
            return None
        return data.get("bubbles")

    def save(self, page: int, lang: str, sig: list, bubbles: list[dict]):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path(page, lang).with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": CACHE_VERSION, "sig": sig, "bubbles": bubbles},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path(page, lang))


def bubbles_from_translation(data: dict) -> list[dict]:
    """A Manga Translator page JSON as bubbles to read: its English, in its reading order."""
    out = []
    for b in data.get("blocks", []):
        text = (b.get("translation") or "").strip()
        if not text:
            continue
        box = b.get("text_box") or b.get("box")
        short = len(text.strip("!?.… ")) <= 6 and " " not in text.strip()
        out.append({"box": list(box), "text": text, "lang": "en",
                    "sfx": bool(b.get("over_art")) and short})
    return out
