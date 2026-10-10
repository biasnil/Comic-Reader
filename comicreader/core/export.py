"""Writing a comic out as a CBZ with its translated pages in place of the originals (no GUI code).

Runs in a worker thread: it opens its own Source (PageCache isn't thread-safe; PdfSource takes
PDF_LOCK itself) and reads translated pages from the TranslationCache.
"""
import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

from .sources import SourceFactory
from .translation import TranslationCache


class ExportCancelled(Exception):
    pass


def comic_info(title: str, pages: int, manga: bool) -> str:
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<ComicInfo>\n"
            f"  <Title>{escape(title)}</Title>\n  <PageCount>{pages}</PageCount>\n"
            "  <LanguageISO>en</LanguageISO>\n"
            f"  <Manga>{'YesAndRightToLeft' if manga else 'No'}</Manga>\n"
            "  <Notes>Translated with Comic Reader's Manga Translator</Notes>\n</ComicInfo>\n")


def export_cbz(comic: Path, key: str, out: Path, title: str = "", manga: bool = True,
               progress=None, cancelled=lambda: False) -> tuple[int, int]:
    """Write `out`; returns (translated pages, total pages). Pages are stored as JPEG (quality 92)."""
    out = Path(out)
    src, _ = SourceFactory.open(Path(comic), interactive=False)
    cache = TranslationCache(key)
    tmp = out.with_name(out.name + ".part")
    translated = 0
    try:
        n = len(src)
        width = max(3, len(str(n)))
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:  # JPEGs don't compress further
            for i in range(n):
                if cancelled():
                    raise ExportCancelled()
                if cache.has(i):
                    with Image.open(cache.page_png(i)) as im:
                        img = im.convert("RGB")
                    translated += 1
                else:
                    img = src.load(i).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=92)
                zf.writestr(f"{i + 1:0{width}d}.jpg", buf.getvalue())
                if progress:
                    progress(i + 1, n)
            zf.writestr("ComicInfo.xml", comic_info(title or Path(comic).stem, n, manga))
        tmp.replace(out)
    finally:
        src.close()
        tmp.unlink(missing_ok=True)
    return translated, n
