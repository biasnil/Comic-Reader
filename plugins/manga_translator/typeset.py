"""Drawing the translation into each cleaned block: word-wrap, shrink-to-fit, centred.

Japanese is usually set in narrow vertical columns, a bad shape for English. When the block sits
in a light speech bubble, the bubble is found by flood-filling from the block's centre and the
text gets the largest rectangle that comfortably fits inside it.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from plugins.common.detector import TextBlock
from plugins.common.layout import bubble_box  # noqa: F401  (pipeline places text with it)

FONT_FILE = Path(__file__).resolve().parent / "assets" / "fonts" / "ComicNeue-Bold.ttf"
MIN_SIZE = 9
MAX_SIZE = 44
LINE_SPACING = 1.12


def load_font(size: int, font_file: str = "") -> ImageFont.FreeTypeFont:
    """`font_file` (a .ttf/.otf chosen in the settings) first, then the bundled font, then fallbacks."""
    for name in (font_file, str(FONT_FILE), "comicbd.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        if not name:
            continue
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


# ---- fitting ------------------------------------------------------------------------ #
def wrap(text: str, font, width: int, split_words: bool = True) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if font.getlength(trial) <= width:
                line = trial
                continue
            if line:
                lines.append(line)
            while split_words and font.getlength(word) > width and len(word) > 1:  # hyphenate
                cut = len(word) - 1
                while cut > 1 and font.getlength(word[:cut] + "-") > width:
                    cut -= 1
                lines.append(word[:cut] + "-")
                word = word[cut:]
            line = word
        if line:
            lines.append(line)
    return lines


def fit(text: str, box_w: int, box_h: int, font_file: str = "",
        fixed: int = 0) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Largest font size at which `text` fits the box. Returns (font, lines, line_height).

    Words are only hyphenated when no size fits without that. `fixed` > 0 forces that size.
    """
    if fixed > 0:
        font = load_font(fixed, font_file)
        return font, wrap(text, font, box_w), int(fixed * LINE_SPACING)
    for split_words in (False, True):
        lo, hi = MIN_SIZE, max(MIN_SIZE, min(MAX_SIZE, box_h))
        best = None
        while lo <= hi:  # binary search on the size
            size = (lo + hi) // 2
            font = load_font(size, font_file)
            lines = wrap(text, font, box_w, split_words)
            line_h = int(size * LINE_SPACING)
            if len(lines) * line_h <= box_h and all(font.getlength(l) <= box_w for l in lines):
                best = (font, lines, line_h)
                lo = size + 1
            else:
                hi = size - 1
        if best is not None:
            return best
    # doesn't fit even at the minimum size: draw it anyway, overflowing
    font = load_font(MIN_SIZE, font_file)
    return font, wrap(text, font, box_w), int(MIN_SIZE * LINE_SPACING)


def draw_blocks(page: Image.Image, blocks: list[TextBlock], font_file: str = "") -> Image.Image:
    out = page.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    gray = np.asarray(out.convert("L"))
    for b in blocks:
        text = b.translation.strip()
        if not text:
            continue
        tx1, ty1, tx2, ty2 = b.text_box or b.box
        margin = 2
        bw, bh = max(8, tx2 - tx1 - 2 * margin), max(8, ty2 - ty1 - 2 * margin)
        font, lines, line_h = fit(text, bw, bh, font_file, b.fixed_size)
        b.font_size = font.size
        total = len(lines) * line_h
        y = (ty1 + ty2) / 2 - total / 2
        if b.erased:
            dark_bg = gray[ty1:ty2, tx1:tx2].mean() < 110 if ty2 > ty1 and tx2 > tx1 else False
            fill, outline = ("white", "black") if dark_bg else ("black", "white")
            stroke = max(2, font.size // 8) if dark_bg or b.extra.get("over_art") else 0
        else:  # the Japanese is still there: cover it and the English with a white box
            widest = max(font.getlength(l) for l in lines)
            cx = (tx1 + tx2) / 2
            x1, y1, x2, y2 = b.box
            draw.rounded_rectangle((min(x1, cx - widest / 2 - 4), min(y1, y - 3),
                                    max(x2, cx + widest / 2 + 4), max(y2, y + total + 3)),
                                   radius=6, fill="white")
            fill, outline, stroke = "black", "white", 0
        for line in lines:
            x = (tx1 + tx2) / 2 - font.getlength(line) / 2
            draw.text((x, y), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=outline)
            y += line_h
    return out
