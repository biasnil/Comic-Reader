"""Model files the plugin downloads on first use (into DATA_DIR/models/, never next to the exe)."""
import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from comicreader.core.translation import MODELS_DIR


@dataclass(frozen=True)
class ModelFile:
    name: str
    filename: str
    url: str
    sha256: str
    size: int

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.filename

    @property
    def present(self) -> bool:
        return self.path.exists() and self.path.stat().st_size == self.size


# ---- registry ---------------------------------------------------------------- #
DETECTOR = ModelFile(
    name="comic-text-detector",
    filename="comictextdetector.pt.onnx",
    url="https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/"
        "comictextdetector.pt.onnx",
    sha256="1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f",
    size=94_669_756,
)

REQUIRED = (DETECTOR,)


def missing() -> list[ModelFile]:
    return [m for m in REQUIRED if not m.present]


def download(model: ModelFile, progress=None, chunk: int = 1 << 20):
    """Download, check the SHA-256, then move into place. progress(done, total) is optional."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    part = model.path.with_suffix(model.path.suffix + ".part")
    digest = hashlib.sha256()
    req = urllib.request.Request(model.url, headers={"User-Agent": "ComicReader-MangaTranslator"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
        total = int(resp.headers.get("Content-Length") or model.size)
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
    if digest.hexdigest() != model.sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{model.name}: download is corrupt (checksum mismatch)")
    part.replace(model.path)
