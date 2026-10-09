"""OCR of the detected text blocks.

Two ways to read the Japanese:
  manga-ocr  local model (pip install manga-ocr; pulls in torch, ~2 GB). Handles vertical text.
  llm        no local OCR: the translator gets an image crop of each block and reads it itself
             (needs a vision-capable model, e.g. Claude or qwen2.5vl in Ollama).
"auto" uses manga-ocr when it is installed, otherwise the LLM.
"""
import os

from PIL import Image

from comicreader.core.translation import MODELS_DIR

from .detector import TextBlock

try:
    import manga_ocr  # noqa: F401  (only checking it is there; loading it is slow)
    HAS_MANGA_OCR = True
except ImportError:
    HAS_MANGA_OCR = False


def crop_block(img: Image.Image, block: TextBlock, pad: int = 6) -> Image.Image:
    x1, y1, x2, y2 = block.box
    w, h = img.size
    return img.crop((max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)))


def resolve_mode(mode: str) -> str:
    if mode == "manga-ocr" and not HAS_MANGA_OCR:
        raise RuntimeError("OCR is set to manga-ocr but it isn't installed (pip install manga-ocr)")
    if mode == "auto":
        return "manga-ocr" if HAS_MANGA_OCR else "llm"
    return mode


class MangaOcrReader:
    """Wraps manga_ocr.MangaOcr, loaded on first use (its model goes under DATA_DIR/models)."""

    def __init__(self):
        self._model = None

    def read(self, img: Image.Image, blocks: list[TextBlock]):
        if self._model is None:
            os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
            from manga_ocr import MangaOcr
            self._model = MangaOcr()
        for b in blocks:
            b.source = self._model(crop_block(img, b).convert("RGB")).strip()
