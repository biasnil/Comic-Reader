"""The contract between the reader and the Manga Translator plugin (no GUI code).

The plugin runs as a separate helper process (plugins/manga_translator/worker.py, or the
manga-translator-worker.exe built from it). The reader and the worker never share memory:
  - they talk over the worker's stdin/stdout, one JSON object per line (PROTOCOL below);
  - the worker writes finished pages into the on-disk cache (TranslationCache) and the
    reader only reads from it.
Both sides import this module, so paths and file names can't drift apart.

Cache layout:  DATA_DIR/translations/<comic_id>/
    meta.json         {"key": <session.key>, "sig": [mtime, size]}   (stale cache is wiped)
    0007.png          translated page 8
    0007.json         {"page": 7, "size": [w, h], "blocks": [{"box", "vertical", "source",
                       "translation", "text_box", "font_size"}, ...]}

Messages, reader -> worker ("cmd"):
    hello                                   -> hello {protocol, version, missing_models, problems}
    configure {settings}                    -> configured
    download                                -> download {name, done, total}* then downloaded
    translate {job, comic, key, page, rtl}  -> stage {job, page, stage}* then done {job, page, blocks}
    quit
Any command can answer: error {job?, page?, message}.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

from ..constants import DATA_DIR

PROTOCOL = 1
PLUGIN_NAME = "manga-translator"
WORKER_EXE = "manga-translator-worker.exe"
RELEASE_ASSET = "MangaTranslator-plugin-win64.zip"
GITHUB_REPO = "biasnil/comic-reader"

TRANSLATIONS_DIR = DATA_DIR / "translations"
MODELS_DIR = DATA_DIR / "models"
PLUGINS_DIR = DATA_DIR / "plugins"
PLUGIN_DIR = PLUGINS_DIR / PLUGIN_NAME          # where Plugins > Manage installs the worker
LOG_FILE = PLUGINS_DIR / f"{PLUGIN_NAME}.log"

DEFAULT_SETTINGS = {
    "backend": "openai",                         # openai (any OpenAI-compatible server) | anthropic
    "base_url": "http://localhost:11434/v1",     # Ollama; LM Studio is http://localhost:1234/v1
    "model": "qwen2.5vl:7b",                     # model name for the OpenAI-compatible server
    "anthropic_model": "claude-opus-5-5",
    "api_key": "",                               # blank: OPENAI_API_KEY / ANTHROPIC_API_KEY
    "ocr": "auto",                               # auto | manga-ocr | llm (the LLM reads the crops)
    "inpaint": "auto",                           # auto | fill | off
    "target": "English",
    "gpu": True,
}


def comic_id(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def comic_signature(path: Path) -> list:
    """[mtime, size] of a comic file (or folder): when it changes, old translations are dropped."""
    try:
        st = Path(path).stat()
        return [int(st.st_mtime), st.st_size if Path(path).is_file() else 0]
    except OSError:
        return [0, 0]


def write_message(stream, msg: dict):
    stream.write(json.dumps(msg, ensure_ascii=False) + "\n")
    stream.flush()


def read_message(line: str) -> dict | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None


# ---- cache ------------------------------------------------------------------- #
class TranslationCache:
    """Translated pages of one comic on disk."""

    def __init__(self, key: str, root: Path = TRANSLATIONS_DIR):
        self.key = key
        self.dir = Path(root) / comic_id(key)

    def page_png(self, page: int) -> Path:
        return self.dir / f"{page:04d}.png"

    def page_json(self, page: int) -> Path:
        return self.dir / f"{page:04d}.json"

    def has(self, page: int) -> bool:
        return self.page_png(page).exists()

    def pages(self) -> set[int]:
        out = set()
        for f in self.dir.glob("*.png"):
            if f.stem.isdigit():
                out.add(int(f.stem))
        return out

    def validate(self, sig: list):
        """Drop the cache if the comic file changed since it was translated."""
        meta_file = self.dir / "meta.json"
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = None
        if meta is not None and meta.get("sig") == sig:
            return
        if meta is not None:
            self.clear()
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            meta_file.write_text(json.dumps({"key": self.key, "sig": sig}), encoding="utf-8")
        except OSError:
            pass

    def clear(self, page: int | None = None):
        if page is None:
            shutil.rmtree(self.dir, ignore_errors=True)
            return
        for f in (self.page_png(page), self.page_json(page)):
            try:
                f.unlink()
            except OSError:
                pass

    def write(self, page: int, img, blocks: dict):
        """Write the JSON first and the PNG last (atomically): a PNG means the page is done."""
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.page_json(page).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(blocks, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.page_json(page))
        tmp = self.page_png(page).with_suffix(".png.tmp")
        img.save(tmp, format="PNG")
        tmp.replace(self.page_png(page))

    def load_blocks(self, page: int) -> dict | None:
        try:
            return json.loads(self.page_json(page).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


# ---- where is the worker? ---------------------------------------------------- #
def worker_command(base_dir: Path) -> tuple[list[str], Path] | None:
    """(argv, cwd) to start the worker, or None if the plugin isn't available.

    Order: the plugin source next to the reader's source (development), then a worker
    downloaded through Plugins > Manage, then one the installer put next to the exe.
    """
    if not getattr(sys, "frozen", False):
        if (Path(base_dir) / "plugins" / "manga_translator" / "worker.py").exists():
            return [sys.executable, "-m", "plugins.manga_translator.worker"], Path(base_dir)
    for folder in (PLUGIN_DIR, Path(sys.executable).resolve().parent / "plugins" / PLUGIN_NAME):
        exe = folder / WORKER_EXE
        if exe.exists():
            return [str(exe)], folder
    return None
