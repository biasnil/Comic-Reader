"""Removing the original text from the page.

For each block the pixels around the text decide what happens:
  - plain background (a speech bubble): fill the text mask with the background colour;
  - busy background (text over artwork or screentone): LaMa inpainting (ONNX) when its model is
    downloaded, else OpenCV's Telea inpainting if opencv is installed, else the text is left in
    place and the English gets a white box instead.
Modes: "auto" (as above), "lama" (as above, the reader makes sure LaMa is downloaded),
"fill" (plain bubbles only), "off" (erase nothing).
"""
import numpy as np
from PIL import Image, ImageFilter

from .detector import TextBlock, providers

try:
    import cv2
except ImportError:
    cv2 = None

PLAIN_SHARE = 0.85  # share of the pixels around the text close to their median: "plain background"


def _ring(mask: np.ndarray, grow: int) -> np.ndarray:
    m = Image.fromarray(mask.astype(np.uint8) * 255)
    big = np.asarray(m.filter(ImageFilter.MaxFilter(grow * 2 + 1))) > 0
    return big & ~mask


# ---- LaMa -------------------------------------------------------------------------- #
class LamaInpainter:
    """LaMa (big-lama) exported to ONNX, run on a square crop around each busy block.

    Works with the common exports: inputs "image" (1,3,S,S) in 0..1 and "mask" (1,1,S,S) in {0,1}
    (found by their channel count, not their names); output (1,3,S,S) in 0..1 or 0..255.
    """

    def __init__(self, model_path, use_gpu: bool = True):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(model_path), opts, providers=providers(use_gpu))
        ins = self.session.get_inputs()
        self.image_in = next(i.name for i in ins if len(i.shape) == 4 and i.shape[1] == 3)
        self.mask_in = next(i.name for i in ins if len(i.shape) == 4 and i.shape[1] == 1)
        shape = next(i.shape for i in ins if i.name == self.image_in)
        self.size = shape[2] if isinstance(shape[2], int) else 512

    def inpaint(self, arr: np.ndarray, mask: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
        """Inpaint the `mask` pixels near `box` in `arr` (H, W, 3 uint8), in place."""
        h, w = mask.shape
        x1, y1, x2, y2 = box
        side = int(max(x2 - x1, y2 - y1) * 1.6) + 32       # the text plus context around it
        side = min(max(side, 128), max(h, w))
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        l = int(np.clip(cx - side // 2, 0, max(0, w - side)))
        t = int(np.clip(cy - side // 2, 0, max(0, h - side)))
        r, b = min(w, l + side), min(h, t + side)
        crop_m = mask[t:b, l:r]
        if not crop_m.any():
            return arr
        s = self.size
        img = Image.fromarray(arr[t:b, l:r]).resize((s, s), Image.Resampling.BICUBIC)
        m = Image.fromarray(crop_m.astype(np.uint8) * 255).resize((s, s), Image.Resampling.NEAREST)
        x = np.asarray(img, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        xm = (np.asarray(m, dtype=np.float32)[None, None] > 127).astype(np.float32)
        out = self.session.run(None, {self.image_in: x, self.mask_in: xm})[0][0]
        if out.max() <= 1.5:   # some exports return 0..1
            out = out * 255.0
        res = Image.fromarray(np.clip(out.transpose(1, 2, 0), 0, 255).astype(np.uint8))
        res = np.asarray(res.resize((r - l, b - t), Image.Resampling.BICUBIC))
        region = arr[t:b, l:r]
        region[crop_m] = res[crop_m]
        return arr


# ---- the page ---------------------------------------------------------------------- #
def clean(img: Image.Image, mask: np.ndarray, blocks: list[TextBlock], mode: str = "auto",
          lama: LamaInpainter | None = None) -> Image.Image:
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
    busy_blocks = []

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
        elif mode in ("auto", "lama") and (lama is not None or cv2 is not None):
            busy[y1:y2, x1:x2] |= local
            busy_blocks.append((x1, y1, x2, y2))
            b.erased = True
            b.extra["over_art"] = True   # the English needs an outline to stay readable

    if busy.any():
        if lama is not None:
            for box in busy_blocks:
                lama.inpaint(arr, busy, box)
        else:
            arr = cv2.inpaint(arr, busy.astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA)
    return Image.fromarray(arr)
