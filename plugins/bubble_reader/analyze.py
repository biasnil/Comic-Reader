"""Finding the bubbles on a page and reading their text.

detect (comic-text-detector) -> reading order (right-to-left for manga) -> per bubble:
  Japanese: manga-ocr (the ONNX export from the models-v1 release, or the manga-ocr package)
  English:  RapidOCR (small ONNX models that come inside the rapidocr-onnxruntime package)
Each bubble also gets an "sfx" flag: short text that isn't inside a light speech bubble.
"""
import re

import numpy as np
from PIL import Image

from plugins.common import models
from plugins.common.detector import TextDetector, reading_order
from plugins.common.mangaocr import OnnxMangaOcr, crop_block

try:
    import manga_ocr  # noqa: F401  (only checking it is there)
    HAS_MANGA_OCR = True
except ImportError:
    HAS_MANGA_OCR = False

try:
    import wordninja
except ImportError:
    wordninja = None

MAX_BUBBLES = 60
KANA = re.compile(r"[぀-ヿ一-鿿]")


def japanese_ocr_needs_download() -> bool:
    return not HAS_MANGA_OCR and not models.local_ocr_available()


# ---- text clean-up ---------------------------------------------------------------- #
def normalize_english(text: str) -> str:
    """Comic lettering, as OCR reads it, made speakable: glued words split, ALL CAPS made
    sentence case (a voice would otherwise spell some words out), hyphenated breaks joined."""
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)      # SOME- THING -> SOMETHING
    if wordninja is not None:                          # WHEREDOYOU -> WHERE DO YOU
        def split(m):
            parts = wordninja.split(m.group(0))
            return " ".join(parts) if len(parts) > 1 and all(len(p) > 1 or p.lower() in "ai"
                                                              for p in parts) else m.group(0)
        text = re.sub(r"[A-Za-z]{9,}", split, text)
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        text = text.lower()
        text = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
        text = re.sub(r"\bi\b", "I", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_japanese(text: str) -> str:
    text = "".join(text.split())
    return text.replace("．．．", "…").replace("...", "…")


def in_light_bubble(gray: np.ndarray, box, pad: int = 8) -> bool:
    """True when the margin just around the text is plain and light: text inside a speech
    bubble or caption box, not lettered over the artwork."""
    h, w = gray.shape
    x1, y1, x2, y2 = box
    ox1, oy1, ox2, oy2 = max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)
    ring = np.ones((oy2 - oy1, ox2 - ox1), dtype=bool)
    ring[y1 - oy1:y2 - oy1, x1 - ox1:x2 - ox1] = False
    values = gray[oy1:oy2, ox1:ox2][ring]
    return values.size > 0 and (values > 200).mean() > 0.8


def is_sfx(text: str, lang: str, in_bubble: bool) -> bool:
    """Short text drawn over the art (BAM!, ドン) rather than said in a bubble."""
    if in_bubble:
        return False
    core = re.sub(r"[\s!?！？.…・ー〜~\-]", "", text)
    if lang == "ja":
        return 0 < len(core) <= 6
    return 0 < len(core) <= 10 and len(text.split()) <= 2


def group_lines(words: list[tuple]) -> list[list[tuple]]:
    """(centre y, height, x, text) boxes -> lines top to bottom, each sorted left to right."""
    lines: list[list[tuple]] = []
    for w in sorted(words):
        if lines and abs(w[0] - lines[-1][0][0]) < 0.5 * max(w[1], lines[-1][0][1], 1):
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w[2]) for line in lines]


# ---- readers -------------------------------------------------------------------------- #
class EnglishOcr:
    def __init__(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError("Reading English needs: pip install rapidocr-onnxruntime") from exc
        self.engine = RapidOCR()

    def read(self, crop: Image.Image) -> str:
        if min(crop.size) < 48:   # tiny lettering reads better a little larger
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.BICUBIC)
        result, _ = self.engine(np.asarray(crop.convert("RGB")))
        words = []   # (centre y, height, left x, text); RapidOCR often returns single words
        for box, text, score in result or []:
            if float(score) >= 0.5 and text.strip():
                ys = [p[1] for p in box]
                xs = [p[0] for p in box]
                words.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), text.strip()))
        return normalize_english(" ".join(" ".join(t for *_, t in line)
                                          for line in group_lines(words)))


class JapaneseOcr:
    def __init__(self, use_gpu: bool):
        if models.local_ocr_available():
            self._onnx = OnnxMangaOcr(use_gpu)
            self._pip = None
        elif HAS_MANGA_OCR:
            from manga_ocr import MangaOcr
            self._onnx, self._pip = None, MangaOcr()
        else:
            raise RuntimeError("The Japanese OCR model isn't downloaded yet")

    def read(self, crop: Image.Image) -> str:
        text = self._onnx.read_one(crop) if self._onnx else self._pip(crop.convert("RGB"))
        return normalize_japanese(text)


# ---- the page ------------------------------------------------------------------------- #
class PageAnalyzer:
    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        self._detector = None
        self._readers: dict[str, object] = {}

    def _reader(self, lang: str):
        if lang not in self._readers:
            self._readers[lang] = JapaneseOcr(self.use_gpu) if lang == "ja" else EnglishOcr()
        return self._readers[lang]

    def analyze(self, img: Image.Image, rtl: bool, lang: str) -> list[dict]:
        """Bubbles in reading order: [{"box", "text", "lang", "sfx"}]."""
        if self._detector is None:
            self._detector = TextDetector(models.DETECTOR.path, use_gpu=self.use_gpu)
        img = img.convert("RGB")
        gray = np.asarray(img.convert("L"))
        blocks, _mask = self._detector.detect(img)
        blocks = reading_order(blocks, rtl)[:MAX_BUBBLES]
        reader = self._reader(lang)
        out = []
        for b in blocks:
            text = reader.read(crop_block(img, b))
            if not text or not re.search(r"\w", text):
                continue
            if lang == "en" and KANA.search(text):
                continue   # stray Japanese on an English page (signs, credits)
            in_bubble = in_light_bubble(gray, b.box)
            out.append({"box": [int(v) for v in b.box], "text": text, "lang": lang,
                        "sfx": is_sfx(text, lang, in_bubble)})
        return out


def resolve_language(setting: str, rtl: bool) -> str:
    if setting in ("ja", "en"):
        return setting
    return "ja" if rtl else "en"

