"""Page sources: one class per container format, and a factory that picks the right one.

This module has no GUI dependency; the only thing it may need from the user (a PDF password)
is requested through SourceFactory.password_provider, which the main window sets.

Every Source exposes the same small interface (names, load(i), read_meta(), close()),
so the rest of the program never needs to know what kind of file it is reading.
"""
import tarfile
import threading
import zipfile
from pathlib import Path

from PIL import Image

from ..constants import IMAGE_EXTS
from ..utils.helpers import decode_image, index_entries, is_page_name, natural_key, parse_comicinfo

try:
    import pymupdf  # current PyMuPDF name
except ImportError:
    try:
        import fitz as pymupdf  # very old PyMuPDF
    except ImportError:
        pymupdf = None
try:
    import rarfile
except ImportError:
    rarfile = None
try:
    import py7zr
except ImportError:
    py7zr = None

if rarfile is not None:  # use WinRAR's UnRAR.exe / 7-Zip if they're in the usual places
    for _p in (r"C:\Program Files\WinRAR\UnRAR.exe", r"C:\Program Files (x86)\WinRAR\UnRAR.exe"):
        if Path(_p).exists():
            rarfile.UNRAR_TOOL = _p
            break
    _seven = r"C:\Program Files\7-Zip\7z.exe"
    if Path(_seven).exists() and hasattr(rarfile, "SEVENZIP_TOOL"):
        rarfile.SEVENZIP_TOOL = _seven


class ComicError(Exception):
    """A comic could not be opened or read."""


class EmptyComicError(ComicError):
    """The container opened fine but holds no image pages."""


# --------------------------------------------------------------------------- #
class Source:
    """Base class: an ordered list of pages that can be loaded one at a time."""

    kind = ""

    def __init__(self):
        self.names: list[str] = []
        self.location: Path = Path(".")
        self.meta_name: str | None = None

    def __len__(self):
        return len(self.names)

    def load(self, index: int) -> Image.Image:
        raise NotImplementedError

    def _read_raw(self, name: str) -> bytes:
        raise NotImplementedError

    def read_meta(self) -> dict:
        """ComicInfo.xml metadata (title, series, writer, ...), if the comic has any."""
        if self.meta_name:
            try:
                return parse_comicinfo(self._read_raw(self.meta_name))
            except Exception:
                pass
        return {}

    def close(self):
        pass


class ZipSource(Source):  # .cbz / .zip
    kind = "ZIP/CBZ"

    def __init__(self, path: Path, password_provider=None):
        super().__init__()
        self.zf = zipfile.ZipFile(path)
        self.names, self.meta_name = index_entries(
            i.filename for i in self.zf.infolist() if not i.is_dir())

    def _read_raw(self, name):
        return self.zf.read(name)

    def load(self, index):
        return decode_image(self.zf.read(self.names[index]))

    def close(self):
        self.zf.close()


class RarSource(Source):  # .cbr / .rar
    kind = "RAR/CBR"

    def __init__(self, path: Path, password_provider=None):
        super().__init__()
        if rarfile is None:
            raise ComicError("CBR/RAR support needs:  pip install rarfile\n"
                             "(and WinRAR / UnRAR.exe installed)")
        try:
            self.rf = rarfile.RarFile(path)
        except rarfile.Error as exc:
            raise ComicError(f"Could not open RAR archive: {exc}")
        self.names, self.meta_name = index_entries(
            i.filename for i in self.rf.infolist() if not i.is_dir())

    def _read_raw(self, name):
        try:
            return self.rf.read(name)
        except rarfile.RarCannotExec:
            raise ComicError("No RAR extractor found. Install WinRAR (UnRAR.exe) "
                             "or convert this CBR to CBZ.")

    def load(self, index):
        return decode_image(self._read_raw(self.names[index]))

    def close(self):
        self.rf.close()


class TarSource(Source):  # .cbt / .tar
    kind = "TAR/CBT"

    def __init__(self, path: Path, password_provider=None):
        super().__init__()
        self.tf = tarfile.open(path)
        self._members = {m.name: m for m in self.tf.getmembers() if m.isfile()}
        self.names, self.meta_name = index_entries(self._members)

    def _read_raw(self, name):
        return self.tf.extractfile(self._members[name]).read()

    def load(self, index):
        return decode_image(self._read_raw(self.names[index]))

    def close(self):
        self.tf.close()


class SevenZipSource(Source):  # .cb7 / .cba / .7z
    kind = "7z/CB7"

    def __init__(self, path: Path, password_provider=None):
        super().__init__()
        if py7zr is None:
            raise ComicError("CB7/7Z support needs:  pip install py7zr")
        self.sz = py7zr.SevenZipFile(path)
        self.names, self.meta_name = index_entries(
            i.filename for i in self.sz.list() if not i.is_directory)

    def _read_raw(self, name):
        try:
            return self.sz.read([name])[name].read()
        finally:
            self.sz.reset()  # py7zr needs this before the next read()

    def load(self, index):
        return decode_image(self._read_raw(self.names[index]))

    def close(self):
        self.sz.close()


PDF_LOCK = threading.RLock()  # MuPDF isn't thread-safe; the library scanner runs in a thread


class PdfSource(Source):  # .pdf
    kind = "PDF"
    RENDER_SCALE = 2.0  # 2.0 = 144 dpi

    def __init__(self, path: Path, password_provider=None):
        """password_provider: callable() -> str | None, asked if the PDF is encrypted."""
        super().__init__()
        if pymupdf is None:
            raise ComicError("PDF support needs:  pip install pymupdf")
        with PDF_LOCK:
            self.doc = pymupdf.open(path)
            if self.doc.needs_pass:
                pw = password_provider() if password_provider else None
                if not pw or not self.doc.authenticate(pw):
                    raise ComicError("PDF is password protected.")
            self.names = [f"Page {i + 1}" for i in range(self.doc.page_count)]

    def read_meta(self):
        with PDF_LOCK:
            md = self.doc.metadata or {}
        out = {"title": (md.get("title") or "").strip(), "writer": (md.get("author") or "").strip()}
        return {k: v for k, v in out.items() if v}

    def load(self, index):
        with PDF_LOCK:
            page = self.doc.load_page(index)
            m = pymupdf.Matrix(self.RENDER_SCALE, self.RENDER_SCALE)
            pix = page.get_pixmap(matrix=m, alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def close(self):
        with PDF_LOCK:
            self.doc.close()


class FolderSource(Source):  # folder of numbered images
    kind = "Folder"

    def __init__(self, folder: Path, recursive: bool = True):
        super().__init__()
        self.root = Path(folder)
        it = self.root.rglob("*") if recursive else self.root.glob("*")
        files = [p for p in it if p.is_file() and is_page_name(str(p.relative_to(self.root)))]
        files.sort(key=lambda p: natural_key(str(p.relative_to(self.root))))
        self.files = files
        self.names = [str(p.relative_to(self.root)) for p in files]
        if (self.root / "ComicInfo.xml").exists():
            self.meta_name = "ComicInfo.xml"

    def _read_raw(self, name):
        return (self.root / name).read_bytes()

    def load(self, index):
        return decode_image(self.files[index].read_bytes())


# --------------------------------------------------------------------------- #
class SourceFactory:
    """Looks at a path (by its header bytes, not its extension) and builds the right Source."""

    ARCHIVES = {"zip": ZipSource, "rar": RarSource, "tar": TarSource,
                "7z": SevenZipSource, "pdf": PdfSource}
    password_provider = None  # set by the GUI; callable() -> str | None

    @staticmethod
    def detect_kind(path: Path) -> str:
        if path.is_dir():
            return "folder"
        with open(path, "rb") as fh:
            head = fh.read(1024)
        if b"%PDF-" in head:
            return "pdf"
        if head.startswith(b"PK"):
            return "zip"
        if head.startswith(b"Rar!\x1a\x07"):
            return "rar"
        if head.startswith(b"7z\xbc\xaf\x27\x1c"):
            return "7z"
        if path.suffix.lower() in IMAGE_EXTS:
            return "image"
        if tarfile.is_tarfile(path):
            return "tar"
        raise ComicError("Unrecognised file type (not CBZ/CBR/CBT/CB7/PDF/image).")

    @classmethod
    def open(cls, path: Path, interactive: bool = True) -> tuple[Source, int | None]:
        """Returns (source, start_index); start_index is set when opening a single image."""
        path = Path(path)
        kind = cls.detect_kind(path)
        start = None
        if kind in cls.ARCHIVES:
            src = cls.ARCHIVES[kind](path, cls.password_provider if interactive else None)
            src.location = path
        elif kind == "folder":
            src = FolderSource(path)
            src.location = path
        else:  # a single image -> read its whole folder, start on that image
            src = FolderSource(path.parent, recursive=False)
            try:
                start = src.files.index(path)
            except ValueError:
                start = 0
            src.location = path.parent
        if len(src) == 0:
            src.close()
            raise EmptyComicError(f"No image pages found in:\n{path}")
        return src, start
