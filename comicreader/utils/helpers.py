"""Small stateless helper functions shared by several modules."""
import io
import os
import re
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from ..constants import IMAGE_EXTS, NIGHT_B, NIGHT_G


# ---- file names / metadata -------------------------------------------------- #
def natural_key(text: str):
    """Sort key so that page2 comes before page10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def is_page_name(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    if any(p.startswith(".") or p == "__MACOSX" for p in parts):
        return False
    return Path(parts[-1]).suffix.lower() in IMAGE_EXTS


def index_entries(entries):
    """Split archive entries into (sorted page names, ComicInfo.xml name or None)."""
    pages, meta = [], None
    for n in entries:
        if is_page_name(n):
            pages.append(n)
        elif meta is None and n.replace("\\", "/").rsplit("/", 1)[-1].lower() == "comicinfo.xml":
            meta = n
    pages.sort(key=natural_key)
    return pages, meta


def parse_comicinfo(data: bytes) -> dict:
    root = ET.fromstring(data)

    def g(tag):
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else ""

    info = {"title": g("Title"), "series": g("Series"), "number": g("Number"),
            "volume": g("Volume"), "writer": g("Writer"), "summary": g("Summary"),
            "manga": g("Manga"), "genre": g("Genre"), "pages": g("PageCount")}
    return {k: v for k, v in info.items() if v}


# ---- images ------------------------------------------------------------------ #
def decode_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.split()[-1])
        return flat
    return img.convert("RGB")


def make_placeholder(message: str) -> Image.Image:
    """A grey page with a message, shown when a page can't be decoded."""
    img = Image.new("RGB", (900, 1200), "#2b2b2b")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:
        font = ImageFont.load_default()
    y = 480
    for paragraph in message.split("\n"):
        for line in textwrap.wrap(paragraph, 48) or [""]:
            draw.text((60, y), line, fill="#dddddd", font=font)
            y += 40
    return img


def apply_filter(img: Image.Image, mode: str, brightness: float) -> Image.Image:
    if mode == "sepia":
        img = ImageOps.colorize(ImageOps.grayscale(img), "#2b1d0e", "#ffeccc")
    elif mode == "night":
        r, g, b = img.split()
        img = Image.merge("RGB", (r, g.point(NIGHT_G), b.point(NIGHT_B)))
    if abs(brightness - 1.0) > 0.01:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    return img


# ---- formatting / OS ------------------------------------------------------------ #
def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def human_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def reveal_in_folder(path: str):
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])
    except OSError:
        pass


# ---- keyboard ---------------------------------------------------------------------- #
KEY_NAMES = {"Next": "PgDn", "Prior": "PgUp", "BackSpace": "Backspace", "space": "Space",
             "plus": "+", "minus": "-", "equal": "=", "bracketleft": "[",
             "bracketright": "]", "Escape": "Esc", "Return": "Enter", "Control": "Ctrl"}
SHIFTABLE = {"space", "Tab", "Return", "Left", "Right", "Up", "Down", "Prior", "Next",
             "Home", "End", "BackSpace"}


def pretty_key(k: str) -> str:
    return "+".join(KEY_NAMES.get(p) or (p.upper() if len(p) == 1 else p) for p in k.split("-"))


def key_string(event) -> str:
    """Normalise a Tk key event to e.g. 'Control-Shift-o' or 'Right'."""
    ks = event.keysym
    shift = bool(event.state & 0x1)
    if len(ks) == 1 and ks.isalpha():
        base = ks.lower()
    else:
        base = ks
        shift = shift and ks in SHIFTABLE
    mods = (["Control"] if event.state & 0x4 else []) + (["Shift"] if shift else [])
    return "-".join(mods + [base])
