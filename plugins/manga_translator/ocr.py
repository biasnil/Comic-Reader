"""OCR of the detected text blocks.

Ways to read the Japanese (setting "ocr"):
  local      manga-ocr exported to ONNX (tools/export_models.py): runs on onnxruntime, no PyTorch,
             so it works in the built exe. Its three files download on first use.
  manga-ocr  the original manga-ocr package (pip install manga-ocr; pulls in PyTorch, ~2 GB).
  llm        no OCR: the translator gets an image crop of each block and reads it itself
             (needs a vision-capable model, e.g. Claude or qwen2.5vl in Ollama).
  auto       manga-ocr if installed, else local if downloaded, else llm (local if the translator
             is llama-cpp, which can't read images).
"""
import os

from PIL import Image

from comicreader.core.translation import MODELS_DIR
from plugins.common import models
from plugins.common.detector import TextBlock
from plugins.common.mangaocr import OnnxMangaOcr, crop_block, postprocess  # noqa: F401  (used by pipeline)

try:
    import manga_ocr  # noqa: F401  (only checking it is there; loading it is slow)
    HAS_MANGA_OCR = True
except ImportError:
    HAS_MANGA_OCR = False


def resolve_mode(mode: str, backend: str = "") -> str:
    text_only = backend == "llama-cpp"
    if mode == "manga-ocr" and not HAS_MANGA_OCR:
        raise RuntimeError("OCR is set to manga-ocr but it isn't installed (pip install manga-ocr)")
    if mode == "auto":
        if HAS_MANGA_OCR:
            return "manga-ocr"
        if models.local_ocr_available() or text_only:
            return "local"
        return "llm"
    if mode == "llm" and text_only:
        raise RuntimeError("The llama.cpp translator can't read images: set 'Read Japanese with' "
                           "to the local OCR")
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
