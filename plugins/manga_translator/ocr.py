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
import json
import os
import re

import numpy as np
from PIL import Image

from comicreader.core.translation import MODELS_DIR

from . import models
from .detector import TextBlock, providers

try:
    import manga_ocr  # noqa: F401  (only checking it is there; loading it is slow)
    HAS_MANGA_OCR = True
except ImportError:
    HAS_MANGA_OCR = False


def crop_block(img: Image.Image, block: TextBlock, pad: int = 6) -> Image.Image:
    x1, y1, x2, y2 = block.box
    w, h = img.size
    return img.crop((max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)))


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


def postprocess(text: str) -> str:
    """manga-ocr's own clean-up: no spaces, '…' as dots, half-width ASCII/digits made full-width."""
    text = "".join(text.split())
    text = text.replace("…", "...")
    text = re.sub("[・.]{2,}", lambda m: (m.end() - m.start()) * ".", text)
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


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


class OnnxMangaOcr:
    """manga-ocr's VisionEncoderDecoder as two ONNX graphs, decoded greedily.

    manga-ocr-vocab.json: {"vocab": [token per id], "image_size", "mean", "std",
                           "start_id", "eos_id", "special_ids", "max_length"}
    """

    def __init__(self, use_gpu: bool = True):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        prov = providers(use_gpu)
        self.encoder = ort.InferenceSession(str(models.OCR_ENCODER.path), opts, providers=prov)
        self.decoder = ort.InferenceSession(str(models.OCR_DECODER.path), opts, providers=prov)
        cfg = json.loads(models.OCR_VOCAB.path.read_text(encoding="utf-8"))
        self.vocab = cfg["vocab"]
        self.size = int(cfg.get("image_size", 224))
        self.mean = np.array(cfg.get("mean", [0.5] * 3), dtype=np.float32)[:, None, None]
        self.std = np.array(cfg.get("std", [0.5] * 3), dtype=np.float32)[:, None, None]
        self.start, self.eos = int(cfg["start_id"]), int(cfg["eos_id"])
        self.special = set(cfg.get("special_ids", []))
        self.max_length = int(cfg.get("max_length", 300))

    def _pixels(self, crop: Image.Image) -> np.ndarray:
        img = crop.convert("L").convert("RGB").resize((self.size, self.size), Image.Resampling.BILINEAR)
        x = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
        return ((x - self.mean) / self.std)[None].astype(np.float32)

    def read_one(self, crop: Image.Image) -> str:
        hidden = self.encoder.run(None, {"pixel_values": self._pixels(crop)})[0]
        ids = [self.start]
        for _ in range(self.max_length):
            logits = self.decoder.run(None, {"input_ids": np.array([ids], dtype=np.int64),
                                             "encoder_hidden_states": hidden})[0]
            nxt = int(logits[0, -1].argmax())
            if nxt == self.eos:
                break
            ids.append(nxt)
        tokens = [self.vocab[i] for i in ids[1:] if i not in self.special and 0 <= i < len(self.vocab)]
        return postprocess("".join(t[2:] if t.startswith("##") else t for t in tokens))

    def read(self, img: Image.Image, blocks: list[TextBlock]):
        for b in blocks:
            b.source = self.read_one(crop_block(img, b))
