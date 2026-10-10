"""The plugins the reader knows about, where their helper processes live, and the message format.

Each plugin runs as its own helper process (a "worker") and talks to the reader with one JSON
object per line on stdin/stdout. A plugin is found, in this order:
  1. its source folder in this repository (plugins/<package>/), when running from source;
  2. DATA_DIR/plugins/<id>/<exe>   (installed or updated with Plugins > Manage);
  3. <reader exe folder>/plugins/<id>/<exe>   (installed by setup.exe).
Releases on GitHub carry each plugin as <asset> (+ <asset>.sha256).
"""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ..constants import DATA_DIR

GITHUB_REPO = "biasnil/comic-reader"
PLUGINS_DIR = DATA_DIR / "plugins"


@dataclass(frozen=True)
class PluginSpec:
    id: str              # folder name under DATA_DIR/plugins, e.g. "manga-translator"
    name: str            # shown in the UI
    package: str         # Python package under plugins/ in the repository
    exe: str             # the built worker
    asset: str           # its release zip
    tag_prefix: str      # release tags that carry only this plugin
    description: str

    @property
    def dir(self) -> Path:
        return PLUGINS_DIR / self.id

    @property
    def log_file(self) -> Path:
        return PLUGINS_DIR / f"{self.id}.log"


TRANSLATOR = PluginSpec(
    id="manga-translator", name="Manga Translator", package="manga_translator",
    exe="manga-translator-worker.exe", asset="MangaTranslator-plugin-win64.zip",
    tag_prefix="translator-v",
    description="Translates Japanese manga pages into English while you read (key T).")

BUBBLE_READER = PluginSpec(
    id="bubble-reader", name="Bubble Reader", package="bubble_reader",
    exe="bubble-reader-worker.exe", asset="BubbleReader-plugin-win64.zip",
    tag_prefix="bubblereader-v",
    description="Reads the speech bubbles aloud in reading order, highlighting each one (key P).")

ALL = (TRANSLATOR, BUBBLE_READER)


def worker_command(spec: PluginSpec, base_dir: Path) -> tuple[list[str], Path] | None:
    """(argv, cwd) to start `spec`'s worker, or None if the plugin isn't available."""
    if not getattr(sys, "frozen", False):
        if (Path(base_dir) / "plugins" / spec.package / "worker.py").exists():
            return [sys.executable, "-m", f"plugins.{spec.package}.worker"], Path(base_dir)
    for folder in (spec.dir, Path(sys.executable).resolve().parent / "plugins" / spec.id):
        exe = folder / spec.exe
        if exe.exists():
            return [str(exe)], folder
    return None


# ---- messages ------------------------------------------------------------------ #
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
