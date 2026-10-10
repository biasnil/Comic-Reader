"""Model files the plugin downloads on first use (into DATA_DIR/models/, never next to the exe).

  comic-text-detector  always needed. Pinned URL and SHA-256.
  lama                 inpainting of text drawn over artwork (inpaint = "lama", or "auto" once present).
  manga-ocr (ONNX)     local Japanese OCR without PyTorch (ocr = "local", or "auto" once present).

The optional models are published as assets of this repository's `models-v1` release by the
"Models" GitHub workflow (tools/export_models.py), together with models.json: a manifest of
{"files": {filename: {"sha256", "size"}}} that downloads are checked against. If that release
doesn't exist yet, LaMa falls back to its original Hugging Face upload (checked by size only).
"""
import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from comicreader.core.translation import GITHUB_REPO, MODELS_DIR, MODELS_TAG

RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/download/{MODELS_TAG}/"
MANIFEST_URL = RELEASE_URL + "models.json"
HEADERS = {"User-Agent": "ComicReader-MangaTranslator"}


@dataclass(frozen=True)
class ModelFile:
    name: str
    filename: str
    url: str
    sha256: str | None = None      # None: taken from the release manifest
    size: int | None = None
    fallback_url: str | None = None

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.filename

    @property
    def present(self) -> bool:
        if not self.path.exists():
            return False
        return self.size is None or self.path.stat().st_size == self.size


# ---- registry ---------------------------------------------------------------- #
DETECTOR = ModelFile(
    name="comic-text-detector",
    filename="comictextdetector.pt.onnx",
    url="https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/"
        "comictextdetector.pt.onnx",
    sha256="1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f",
    size=94_669_756,
)
LAMA = ModelFile(
    name="LaMa inpainting",
    filename="lama_fp32.onnx",
    url=RELEASE_URL + "lama_fp32.onnx",
    fallback_url="https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
)
OCR_ENCODER = ModelFile("manga-ocr encoder", "manga-ocr-encoder.onnx", RELEASE_URL + "manga-ocr-encoder.onnx")
OCR_DECODER = ModelFile("manga-ocr decoder", "manga-ocr-decoder.onnx", RELEASE_URL + "manga-ocr-decoder.onnx")
OCR_VOCAB = ModelFile("manga-ocr vocabulary", "manga-ocr-vocab.json", RELEASE_URL + "manga-ocr-vocab.json")
OCR_FILES = (OCR_ENCODER, OCR_DECODER, OCR_VOCAB)


def needed(settings: dict) -> list[ModelFile]:
    """The models these settings require."""
    files = [DETECTOR]
    if settings.get("inpaint") == "lama":
        files.append(LAMA)
    if settings.get("ocr") == "local":
        files += OCR_FILES
    return files


def missing(settings: dict | None = None) -> list[ModelFile]:
    return [m for m in needed(settings or {}) if not m.present]


def expected_size(model: ModelFile) -> int:
    """Download size in bytes, from the registry or the manifest (0 if unknown)."""
    if model.size:
        return model.size
    entry = _manifest_entry(model.filename)
    return int(entry.get("size", 0)) if entry else 0


def lama_available() -> bool:
    return LAMA.present


def local_ocr_available() -> bool:
    return all(m.present for m in OCR_FILES)


# ---- downloading -------------------------------------------------------------- #
_manifest: dict | None = None


def _manifest_entry(filename: str) -> dict | None:
    global _manifest
    if _manifest is None:
        try:
            req = urllib.request.Request(MANIFEST_URL, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                _manifest = json.loads(resp.read().decode("utf-8")).get("files", {})
        except (OSError, ValueError):
            _manifest = {}
    return _manifest.get(filename)


def _resolve(model: ModelFile) -> tuple[str, str | None, int | None]:
    """(url, sha256, size) to download `model` from."""
    if model.sha256:
        return model.url, model.sha256, model.size
    entry = _manifest_entry(model.filename)
    if entry:
        return model.url, entry.get("sha256"), entry.get("size")
    if model.fallback_url:
        return model.fallback_url, None, None
    raise RuntimeError(f"{model.name} isn't published yet: run the 'Models' workflow on GitHub "
                       f"(it creates the {MODELS_TAG} release)")


def download(model: ModelFile, progress=None, chunk: int = 1 << 20):
    """Download, check the SHA-256 (or size), then move into place. progress(done, total)."""
    url, sha256, size = _resolve(model)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    part = model.path.with_suffix(model.path.suffix + ".part")
    digest = hashlib.sha256()
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or size or 0)
            done = 0
            while True:
                data = resp.read(chunk)
                if not data:
                    break
                out.write(data)
                digest.update(data)
                done += len(data)
                if progress:
                    progress(done, total)
    except OSError as exc:
        part.unlink(missing_ok=True)
        host = urllib.parse.urlparse(url).hostname
        raise RuntimeError(f"Couldn't download {model.name} from {host}: "
                           f"{getattr(exc, 'reason', exc)}") from exc
    bad = (sha256 and digest.hexdigest() != sha256) or (size and done != size) or done == 0
    if bad:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{model.name}: download is corrupt (checksum mismatch)")
    part.replace(model.path)
