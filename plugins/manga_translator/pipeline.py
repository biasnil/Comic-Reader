"""PageTranslator: detect -> OCR -> translate -> erase -> typeset, for one page image.

retypeset() redraws edited translations on a page's saved clean image without running the models.
"""
from PIL import Image

from plugins.common import models
from plugins.common.detector import TextBlock, TextDetector, reading_order

from . import inpaint, ocr, typeset
from .translator import make_backend

MAX_BLOCKS = 60  # pages with more "text" than this are usually screentone noise


def _overlap(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    return ix * iy / small


class PageTranslator:
    def __init__(self, settings: dict):
        self.settings = dict(settings)
        gpu = settings.get("gpu", True)
        self.detector = TextDetector(models.DETECTOR.path, use_gpu=gpu)
        self.ocr_mode = ocr.resolve_mode(settings.get("ocr", "auto"), settings.get("backend", ""))
        if self.ocr_mode == "manga-ocr":
            self.reader = ocr.MangaOcrReader()
        elif self.ocr_mode == "local":
            if not models.local_ocr_available():
                raise RuntimeError("The local OCR model isn't downloaded (set 'Read Japanese with' "
                                   "to the local OCR in Translation Settings to download it)")
            self.reader = ocr.OnnxMangaOcr(gpu)
        else:
            self.reader = None
        mode = settings.get("inpaint", "auto")
        self.lama = None
        if mode == "lama" or (mode == "auto" and models.lama_available()):
            self.lama = inpaint.LamaInpainter(models.LAMA.path, gpu)
        self.backend = make_backend(settings)

    def translate(self, img: Image.Image, rtl: bool = True,
                  progress=None) -> tuple[Image.Image, dict, Image.Image]:
        """Returns (translated page, JSON-ready dict of its blocks, page with the text erased)."""
        step = progress or (lambda stage: None)
        img = img.convert("RGB")

        step("detect")
        blocks, mask = self.detector.detect(img)
        blocks = reading_order(blocks, rtl)[:MAX_BLOCKS]
        result = {"page_size": list(img.size), "ocr": self.ocr_mode, "blocks": []}
        if not blocks:
            return img, result, img

        if self.reader is not None:
            step("ocr")
            self.reader.read(img, blocks)
            blocks = [b for b in blocks if b.source]
            if not blocks:
                return img, result, img

        step("translate")
        with_images = self.ocr_mode == "llm"
        items = [(b.source, ocr.crop_block(img, b)) for b in blocks]
        answers = self.backend.translate(items, self.settings.get("target", "English"), with_images)
        for i, b in enumerate(blocks, 1):
            src, dst = answers.get(i, (b.source, ""))
            b.source = b.source or src
            b.translation = dst
        blocks = [b for b in blocks if b.translation.strip()]

        step("clean")
        cleaned = inpaint.clean(img, mask, blocks, self.settings.get("inpaint", "auto"), self.lama)

        step("typeset")
        self._place(cleaned, blocks)
        out = typeset.draw_blocks(cleaned, blocks, self.settings.get("font_file", ""))
        result["blocks"] = [b.to_json() for b in blocks]
        return out, result, cleaned

    @staticmethod
    def _place(page: Image.Image, blocks: list[TextBlock]):
        for b in blocks:
            b.text_box = typeset.bubble_box(page, b)
        # two blocks in one bubble would both claim the whole bubble: keep their own boxes
        for i, a in enumerate(blocks):
            for b in blocks[i + 1:]:
                if _overlap(a.text_box, b.text_box) > 0.3:
                    a.text_box, b.text_box = a.box, b.box


def retypeset(clean: Image.Image, data: dict, edits: list[dict], font_file: str = "") -> tuple[Image.Image, dict]:
    """Apply `edits` ([{translation, fixed_size}] in block order) and redraw on the clean page."""
    blocks = [TextBlock.from_json(d) for d in data.get("blocks", [])]
    for b, e in zip(blocks, edits):
        b.translation = str(e.get("translation", b.translation))
        b.fixed_size = max(0, int(e.get("fixed_size", b.fixed_size) or 0))
    out = typeset.draw_blocks(clean, blocks, font_file)
    data = dict(data, blocks=[b.to_json() for b in blocks])
    return out, data
