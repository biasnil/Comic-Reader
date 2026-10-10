"""Text detection with comic-text-detector (ONNX): text blocks plus a pixel mask of the text.

The model takes a 1024x1024 RGB image (the page scaled so its long side is 1024, padded at the
bottom/right) and returns:
    blk  (1, N, 7)  YOLO candidates: cx, cy, w, h, objectness, 2 class scores (1024 space)
    seg  (1, 1, 1024, 1024)  text pixel probability
    det  (1, 2, 1024, 1024)  text-line maps (unused here)
Tall webtoon strips are cut into overlapping tiles so text stays large enough to detect.
"""
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

import onnxruntime as ort

SIZE = 1024
CONF = 0.4
NMS_IOU = 0.35
MASK_THRESHOLD = 0.3


@dataclass
class TextBlock:
    box: tuple[int, int, int, int]      # x1, y1, x2, y2 in page pixels
    score: float
    vertical: bool = False
    source: str = ""                    # OCR'd text
    translation: str = ""
    text_box: tuple[int, int, int, int] | None = None   # where the English goes
    font_size: int = 0
    fixed_size: int = 0                 # set in the editor: draw at this size instead of fitting
    erased: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]

    def to_json(self) -> dict:
        return {"box": list(self.box), "vertical": self.vertical, "source": self.source,
                "translation": self.translation,
                "text_box": list(self.text_box) if self.text_box else None,
                "font_size": self.font_size, "fixed_size": self.fixed_size,
                "erased": self.erased, "over_art": bool(self.extra.get("over_art"))}

    @classmethod
    def from_json(cls, d: dict) -> "TextBlock":
        b = cls(tuple(d["box"]), 1.0, vertical=d.get("vertical", False),
                source=d.get("source", ""), translation=d.get("translation", ""),
                text_box=tuple(d["text_box"]) if d.get("text_box") else None,
                font_size=d.get("font_size", 0), fixed_size=d.get("fixed_size", 0),
                erased=d.get("erased", False))
        if d.get("over_art"):
            b.extra["over_art"] = True
        return b


def providers(use_gpu: bool) -> list[str]:
    available = ort.get_available_providers()
    order = ["CUDAExecutionProvider", "DmlExecutionProvider", "CoreMLExecutionProvider"] if use_gpu else []
    return [p for p in order if p in available] + ["CPUExecutionProvider"]


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> list[int]:
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        ratio = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        # also drop boxes mostly inside the kept one (a block and a piece of it)
        inside = inter / (areas[order[1:]] + 1e-6)
        order = order[1:][(ratio <= iou) & (inside < 0.8)]
    return keep


class TextDetector:
    def __init__(self, model_path, use_gpu: bool = True):
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(model_path), opts, providers=providers(use_gpu))

    # ---- one 1024 pass ----------------------------------------------------------- #
    def _run(self, img: Image.Image) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Boxes (n,4), scores (n,) and a text-probability mask, all in `img` pixels."""
        w, h = img.size
        r = SIZE / max(w, h)
        nw, nh = max(1, round(w * r)), max(1, round(h * r))
        canvas = Image.new("RGB", (SIZE, SIZE))
        canvas.paste(img.convert("RGB").resize((nw, nh), Image.Resampling.BILINEAR), (0, 0))
        x = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        blk, seg, _ = self.session.run(None, {"images": x})

        cand = blk[0]
        scores = cand[:, 4] * cand[:, 5:].max(axis=1)
        cand, scores = cand[scores > CONF], scores[scores > CONF]
        cx, cy, bw, bh = cand[:, 0], cand[:, 1], cand[:, 2], cand[:, 3]
        boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1) / r
        boxes = np.clip(boxes, 0, [w, h, w, h])

        prob = Image.fromarray((seg[0, 0, :nh, :nw] * 255).astype(np.uint8))
        mask = np.asarray(prob.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32) / 255
        return boxes, scores, mask

    # ---- whole page (tiled when tall) -------------------------------------------- #
    def detect(self, img: Image.Image) -> tuple[list[TextBlock], np.ndarray]:
        """Text blocks and a boolean text mask the size of the page."""
        w, h = img.size
        tile_h = int(w * 1.5)
        if h <= w * 2:
            tiles = [(0, h)]
        else:  # webtoon: overlapping tiles of 1.5 x width
            step = int(tile_h * 0.75)
            tiles = [(y, min(h, y + tile_h)) for y in range(0, max(1, h - tile_h + step), step)]
            if tiles[-1][1] < h:
                tiles.append((max(0, h - tile_h), h))
        all_boxes, all_scores = [], []
        mask = np.zeros((h, w), dtype=np.float32)
        for top, bottom in tiles:
            boxes, scores, m = self._run(img.crop((0, top, w, bottom)))
            boxes[:, [1, 3]] += top
            all_boxes.append(boxes)
            all_scores.append(scores)
            np.maximum(mask[top:bottom], m, out=mask[top:bottom])
        boxes = np.concatenate(all_boxes) if all_boxes else np.zeros((0, 4))
        scores = np.concatenate(all_scores) if all_scores else np.zeros((0,))

        blocks = []
        for i in nms(boxes, scores, NMS_IOU) if len(boxes) else []:
            x1, y1, x2, y2 = (int(round(v)) for v in boxes[i])
            if x2 - x1 < 6 or y2 - y1 < 6:
                continue
            blocks.append(TextBlock((x1, y1, x2, y2), float(scores[i]),
                                    vertical=(y2 - y1) > (x2 - x1) * 1.2))
        return blocks, mask > MASK_THRESHOLD


def reading_order(blocks: list[TextBlock], rtl: bool) -> list[TextBlock]:
    """Top to bottom in rows; right-to-left within a row for manga, else left-to-right."""
    rows: list[list[TextBlock]] = []
    for b in sorted(blocks, key=lambda b: b.box[1]):
        for row in rows:
            top = min(r.box[1] for r in row)
            bottom = max(r.box[3] for r in row)
            overlap = min(bottom, b.box[3]) - max(top, b.box[1])
            if overlap > 0.5 * min(b.height, bottom - top):
                row.append(b)
                break
        else:
            rows.append([b])
    out = []
    for row in rows:
        out += sorted(row, key=lambda b: (b.box[0] + b.box[2]) / 2, reverse=rtl)
    return out
