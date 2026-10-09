"""Removing the original text from the page.

For each block the pixels around the text decide what happens:
  - plain background (a speech bubble): fill the text mask with the background colour;
  - busy background (text over artwork): OpenCV's Telea inpainting if opencv is installed,
    otherwise the text is left in place and the English gets a white outline instead.
Mode "fill" never uses OpenCV, "off" never erases anything.
"""
import numpy as np
from PIL import Image, ImageFilter

from .detector import TextBlock

try:
    import cv2
except ImportError:
    cv2 = None

PLAIN_SHARE = 0.85  # share of the pixels around the text close to their median: "plain background"


def _ring(mask: np.ndarray, grow: int) -> np.ndarray:
    m = Image.fromarray(mask.astype(np.uint8) * 255)
    big = np.asarray(m.filter(ImageFilter.MaxFilter(grow * 2 + 1))) > 0
    return big & ~mask


def clean(img: Image.Image, mask: np.ndarray, blocks: list[TextBlock], mode: str = "auto") -> Image.Image:
    """Return a copy of `img` with the text of `blocks` erased (block.erased says which were)."""
    if mode == "off" or not blocks:
        return img.copy()
    arr = np.asarray(img.convert("RGB")).copy()
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = gray.shape
    # grow the text mask a little so anti-aliased edges go too
    grown = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255)
                       .filter(ImageFilter.MaxFilter(5))) > 0
    busy = np.zeros((h, w), dtype=bool)

    for b in blocks:
        x1, y1, x2, y2 = b.box
        pad = 8
        x1, y1, x2, y2 = max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)
        local = grown[y1:y2, x1:x2]
        if not local.any():
            continue
        ring = _ring(local, 4)
        if not ring.any():
            continue
        ring_px = arr[y1:y2, x1:x2][ring]
        ring_gray = gray[y1:y2, x1:x2][ring]
        # a bubble outline or a stray stroke in the ring is fine; screentone or artwork isn't
        if (np.abs(ring_gray - np.median(ring_gray)) < 30).mean() > PLAIN_SHARE:
            colour = np.median(ring_px, axis=0).astype(np.uint8)
            arr[y1:y2, x1:x2][local] = colour
            b.erased = True
        elif mode == "auto" and cv2 is not None:
            busy[y1:y2, x1:x2] |= local
            b.erased = True
            b.extra["over_art"] = True   # the English needs an outline to stay readable

    if busy.any():
        arr = cv2.inpaint(arr, busy.astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA)
    return Image.fromarray(arr)
