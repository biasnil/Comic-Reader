"""Where a text block's speech bubble is: flood-fill the light area around the block's centre."""
import numpy as np
from PIL import Image, ImageDraw

from .detector import TextBlock


def bubble_box(page: Image.Image, block: TextBlock) -> tuple[int, int, int, int]:
    """The text area for `block`: the inside of its speech bubble, or the block itself."""
    w, h = page.size
    x1, y1, x2, y2 = block.box
    bw, bh = x2 - x1, y2 - y1
    # look this far around the block for the bubble's outline
    px, py = max(int(bw * 1.5), 120), max(int(bh * 0.6), 80)
    cx1, cy1 = max(0, x1 - px), max(0, y1 - py)
    cx2, cy2 = min(w, x2 + px), min(h, y2 + py)
    gray = np.asarray(page.crop((cx1, cy1, cx2, cy2)).convert("L"))
    light = gray > 200
    sx, sy = (x1 + x2) // 2 - cx1, (y1 + y2) // 2 - cy1
    if not light[sy, sx] or light.mean() > 0.97:
        return block.box  # not in a light bubble (or no outline in sight)
    region = _flood(light, sx, sy)
    ys, xs = np.nonzero(region)
    if not len(xs) or xs.min() == 0 or ys.min() == 0 or xs.max() == light.shape[1] - 1 or ys.max() == light.shape[0] - 1:
        return block.box  # leaked out of the search area: not a closed bubble
    rx1, ry1, rx2, ry2 = xs.min(), ys.min(), xs.max(), ys.max()
    # a rectangle inside an ellipse covers ~70% of each side; centre it on the bubble's mass
    mx, my = xs.mean(), ys.mean()
    hw, hh = (rx2 - rx1) * 0.36, (ry2 - ry1) * 0.36
    tx1, ty1 = int(cx1 + mx - hw), int(cy1 + my - hh)
    tx2, ty2 = int(cx1 + mx + hw), int(cy1 + my + hh)
    # never smaller than the original text block
    return min(tx1, x1), min(ty1, y1), max(tx2, x2), max(ty2, y2)


def _flood(light: np.ndarray, sx: int, sy: int) -> np.ndarray:
    """4-connected flood fill of True pixels from (sx, sy), done with PIL for speed."""
    img = Image.fromarray(light.astype(np.uint8) * 255).copy()  # copy: fromarray may share a read-only buffer
    ImageDraw.floodfill(img, (int(sx), int(sy)), 128)
    return np.asarray(img) == 128
