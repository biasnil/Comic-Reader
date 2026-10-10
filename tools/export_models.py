"""Build the Manga Translator's optional models and their manifest (for the models-v1 release).

Run where Hugging Face is reachable (the "Models" GitHub workflow does this):
    pip install torch transformers onnx onnxruntime fugashi unidic-lite   (CPU-only torch is enough)
    python tools/export_models.py out
Writes into out/:
    manga-ocr-encoder.onnx   manga-ocr's ViT encoder:  pixel_values (1,3,224,224) -> last_hidden_state
    manga-ocr-decoder.onnx   its BERT decoder:  input_ids (1,n), encoder_hidden_states -> logits (1,n,V)
    manga-ocr-vocab.json     tokens + preprocessing/decoding settings (read by ocr.OnnxMangaOcr)
    lama_fp32.onnx           LaMa inpainting, copied from Carve/LaMa-ONNX
    models.json              {"files": {name: {"sha256", "size"}}}: the plugin checks downloads against it
The exported OCR is checked against the PyTorch model before anything is written to the manifest.
"""
import hashlib
import inspect
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

MANGA_OCR = os.environ.get("MANGA_OCR_MODEL", "kha-white/manga-ocr-base")  # env: test with a local model
LAMA_URL = "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx"
OPSET = 17


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


# ---- manga-ocr ----------------------------------------------------------------------- #
def image_side(size) -> int:
    """The model's input side from an image processor's `size`: an int, a dict, or (transformers 5)
    a SizeDict object with .height / .shortest_edge attributes."""
    if isinstance(size, (int, float)):
        return int(size)
    for key in ("height", "shortest_edge", "width"):
        value = size.get(key) if isinstance(size, dict) else getattr(size, key, None)
        if value:
            return int(value)
    raise ValueError(f"can't read the image size from {size!r}")


def export_manga_ocr(out: Path):
    import numpy as np
    import onnxruntime as ort
    import torch
    from transformers import AutoImageProcessor, AutoTokenizer, VisionEncoderDecoderModel

    # plain ("eager") attention traces to ONNX more reliably than the SDPA default
    model = VisionEncoderDecoderModel.from_pretrained(MANGA_OCR, attn_implementation="eager").eval()
    tok = AutoTokenizer.from_pretrained(MANGA_OCR)
    proc = AutoImageProcessor.from_pretrained(MANGA_OCR)
    size = image_side(proc.size)
    extra = {"dynamo": False} if "dynamo" in inspect.signature(torch.onnx.export).parameters else {}

    model.requires_grad_(False)   # inference only: the exporter can't trace weights that track gradients

    # the wrappers own the model (as a submodule), so its weights export as weights
    class Encoder(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):
            h = self.m.encoder(pixel_values=pixel_values).last_hidden_state
            if getattr(self.m, "enc_to_dec_proj", None) is not None:
                h = self.m.enc_to_dec_proj(h)   # only when encoder/decoder widths differ
            return h

    class Decoder(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, input_ids, encoder_hidden_states):
            return self.m.decoder(input_ids=input_ids, encoder_hidden_states=encoder_hidden_states).logits

    encoder, decoder = Encoder(model).eval(), Decoder(model).eval()

    pixels = torch.randn(1, 3, size, size)
    with torch.no_grad():
        hidden = encoder(pixels)
        vocab = model.decoder.config.vocab_size   # sample tokens that exist in any vocabulary
        ids = torch.tensor([[model.config.decoder_start_token_id or tok.cls_token_id, 10 % vocab, 20 % vocab]])
        torch.onnx.export(encoder, (pixels,), out / "manga-ocr-encoder.onnx",
                          input_names=["pixel_values"], output_names=["last_hidden_state"],
                          dynamic_axes={"pixel_values": {0: "batch"}, "last_hidden_state": {0: "batch"}},
                          opset_version=OPSET, **extra)
        torch.onnx.export(decoder, (ids, hidden), out / "manga-ocr-decoder.onnx",
                          input_names=["input_ids", "encoder_hidden_states"], output_names=["logits"],
                          dynamic_axes={"input_ids": {0: "batch", 1: "seq"},
                                        "encoder_hidden_states": {0: "batch", 1: "enc_seq"},
                                        "logits": {0: "batch", 1: "seq"}},
                          opset_version=OPSET, **extra)
        want_h = hidden.numpy()
        want_l = decoder(ids, hidden).numpy()

    # the ONNX graphs must give the same numbers as PyTorch
    enc = ort.InferenceSession(str(out / "manga-ocr-encoder.onnx"), providers=["CPUExecutionProvider"])
    dec = ort.InferenceSession(str(out / "manga-ocr-decoder.onnx"), providers=["CPUExecutionProvider"])
    got_h = enc.run(None, {"pixel_values": pixels.numpy()})[0]
    got_l = dec.run(None, {"input_ids": ids.numpy(), "encoder_hidden_states": want_h})[0]
    assert np.allclose(got_h, want_h, atol=1e-3), "encoder output differs from PyTorch"
    assert np.allclose(got_l, want_l, atol=1e-2), "decoder output differs from PyTorch"

    eos = getattr(model.generation_config, "eos_token_id", None) or model.config.eos_token_id
    if isinstance(eos, (list, tuple)):   # newer transformers may store several
        eos = eos[0] if eos else None
    cfg = {
        "source": MANGA_OCR,
        "vocab": tok.convert_ids_to_tokens(list(range(len(tok)))),
        "image_size": size,
        "mean": list(proc.image_mean),
        "std": list(proc.image_std),
        "start_id": int(model.config.decoder_start_token_id or tok.cls_token_id),
        "eos_id": int(eos if eos is not None else tok.sep_token_id),
        "special_ids": [int(i) for i in tok.all_special_ids],
        "max_length": 300,
    }
    (out / "manga-ocr-vocab.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


# ---- LaMa ------------------------------------------------------------------------------ #
def fetch_lama(out: Path):
    req = urllib.request.Request(LAMA_URL, headers={"User-Agent": "ComicReader-models"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(out / "lama_fp32.onnx", "wb") as fh:
        shutil.copyfileobj(resp, fh, 1 << 20)
    import onnxruntime as ort   # make sure it loads and looks like the expected export
    s = ort.InferenceSession(str(out / "lama_fp32.onnx"), providers=["CPUExecutionProvider"])
    channels = sorted(i.shape[1] for i in s.get_inputs())
    assert channels == [1, 3], f"unexpected LaMa inputs: {[i.shape for i in s.get_inputs()]}"


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "models-out")
    out.mkdir(parents=True, exist_ok=True)
    export_manga_ocr(out)
    fetch_lama(out)
    files = {f.name: {"sha256": sha256(f), "size": f.stat().st_size}
             for f in sorted(out.iterdir()) if f.name != "models.json"}
    (out / "models.json").write_text(json.dumps({"files": files}, indent=1), encoding="utf-8")
    for name, info in files.items():
        print(f"{name:28s} {info['size'] / 1e6:8.1f} MB  {info['sha256']}")


if __name__ == "__main__":
    main()
