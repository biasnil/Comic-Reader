"""PageTranslator: detect -> OCR -> translate -> erase -> typeset, for one page image."""
from PIL import Image

from . import inpaint, models, ocr, typeset
from .detector import TextBlock, TextDetector, reading_order
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
        self.detector = TextDetector(models.DETECTOR.path, use_gpu=settings.get("gpu", True))
        self.ocr_mode = ocr.resolve_mode(settings.get("ocr", "auto"))
        self.reader = ocr.MangaOcrReader() if self.ocr_mode == "manga-ocr" else None
        self.backend = make_backend(settings)

    def translate(self, img: Image.Image, rtl: bool = True, progress=None) -> tuple[Image.Image, dict]:
        """Returns the translated page and a JSON-ready dict of its blocks."""
        step = progress or (lambda stage: None)
        img = img.convert("RGB")

        step("detect")
        blocks, mask = self.detector.detect(img)
        blocks = reading_order(blocks, rtl)[:MAX_BLOCKS]
        result = {"page_size": list(img.size), "ocr": self.ocr_mode, "blocks": []}
        if not blocks:
            return img, result

        if self.reader is not None:
            step("ocr")
            self.reader.read(img, blocks)
            blocks = [b for b in blocks if b.source]

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
        cleaned = inpaint.clean(img, mask, blocks, self.settings.get("inpaint", "auto"))

        step("typeset")
        self._place(cleaned, blocks)
        out = typeset.draw_blocks(cleaned, blocks)
        result["blocks"] = [b.to_json() for b in blocks]
        return out, result

    @staticmethod
    def _place(page: Image.Image, blocks: list[TextBlock]):
        for b in blocks:
            b.text_box = typeset.bubble_box(page, b)
        # two blocks in one bubble would both claim the whole bubble: keep their own boxes
        for i, a in enumerate(blocks):
            for b in blocks[i + 1:]:
                if _overlap(a.text_box, b.text_box) > 0.3:
                    a.text_box, b.text_box = a.box, b.box
