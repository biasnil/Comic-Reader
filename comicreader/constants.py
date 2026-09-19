"""Shared constants: file types, storage locations, themes."""
import os
import sys
from pathlib import Path

from PIL import Image

APP_NAME = "Comic Reader"

# Project root when running from source, or PyInstaller's unpack folder inside the built exe
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ASSETS_DIR = BASE_DIR / "assets"
ICON_FILE = ASSETS_DIR / "icon.ico"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
COMIC_EXTS = {".cbz", ".cbr", ".cbt", ".cb7", ".cba", ".zip", ".rar", ".tar", ".7z", ".pdf"}

DATA_DIR = Path.home() / ".comic_reader"
STATE_FILE = DATA_DIR / "state.json"
OLD_STATE_FILE = Path.home() / ".comic_reader.json"  # v1 file, migrated automatically
LIBRARY_FILE = DATA_DIR / "library.json"


def _appdata_dir() -> Path:
    """%APPDATA%\\ComicReader on Windows, the platform's usual app-data folder elsewhere."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "ComicReader"


APPDATA_DIR = _appdata_dir()
THUMB_DIR = APPDATA_DIR / "thumbnails"        # cover images: <sha1 of path>.thumbnail
OLD_THUMB_DIR = DATA_DIR / "thumbs"           # where older versions kept covers (migrated)
THUMB_EXT = ".thumbnail"
THUMB_SIZE = (300, 450)
THUMB_QUALITY = 80

RESAMPLE = Image.Resampling.LANCZOS
FAST = Image.Resampling.BILINEAR
MAX_DIM = 8000  # never build a displayed image bigger than this on either side

THEMES = {
    "dark": dict(bg="#1e1e1e", panel="#2b2b2b", fg="#e6e6e6", muted="#9a9a9a",
                 accent="#4a90d9", select="#3a5f8a"),
    "light": dict(bg="#ffffff", panel="#ececec", fg="#1a1a1a", muted="#666666",
                  accent="#2a6fb0", select="#b7d3ef"),
    "contrast": dict(bg="#000000", panel="#000000", fg="#ffffff", muted="#ffff00",
                     accent="#00ffff", select="#0000cc"),
}
CANVAS_BGS = {"Black": "#000000", "Dark gray": "#1e1e1e", "Gray": "#808080", "White": "#ffffff"}

NIGHT_G = [int(i * 0.85) for i in range(256)]
NIGHT_B = [int(i * 0.55) for i in range(256)]

# our rotation angles are clockwise; PIL's ROTATE_* constants are counter-clockwise
ROT = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
       270: Image.Transpose.ROTATE_90}