"""manga-ocr as ONNX (exported by tools/export_models.py): Japanese OCR without PyTorch.

Two graphs (encoder, decoder) decoded greedily, plus helpers both plugins use to cut a text block
out of a page and to clean up the text the way manga-ocr does.
"""
import json
import re

import numpy as np
from PIL import Image

from . import models
from .detector import TextBlock, providers


def crop_block(img: Image.Image, block: TextBlock, pad: int = 6) -> Image.Image:
    x1, y1, x2, y2 = block.box
    w, h = img.size
    return img.crop((max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)))


def postprocess(text: str) -> str:
    """manga-ocr's own clean-up: no spaces, '…' as dots, half-width ASCII/digits made full-width."""
    text = "".join(text.split())
    text = text.replace("…", "...")
    text = re.sub("[・.]{2,}", lambda m: (m.end() - m.start()) * ".", text)
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


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
