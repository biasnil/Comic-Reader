"""Building library records from comic files, and scanning folders off the UI thread."""
import hashlib
import os
import queue
import threading
import time
from pathlib import Path

from ..constants import COMIC_EXTS, RESAMPLE, THUMB_DIR
from ..core.sources import SourceFactory
from ..utils.helpers import natural_key


class LibraryItemBuilder:
    """Opens one comic, reads its metadata and writes a cover thumbnail."""

    THUMB_SIZE = (300, 440)

    @classmethod
    def build(cls, path: Path) -> dict:
        st = path.stat()
        src, _ = SourceFactory.open(path, interactive=False)  # raises if there are no pages
        try:
            meta = src.read_meta()
            idx = next((i for i, n in enumerate(src.names) if "cover" in n.lower()), 0)
            img = src.load(idx)
            img.thumbnail(cls.THUMB_SIZE, RESAMPLE)
            THUMB_DIR.mkdir(parents=True, exist_ok=True)
            thumb = hashlib.md5(str(path).encode("utf-8")).hexdigest() + ".jpg"
            img.convert("RGB").save(THUMB_DIR / thumb, quality=85)
            series = meta.get("series", "")
            number = meta.get("number") or meta.get("volume", "")
            title = meta.get("title") or (f"{series} #{number}" if series and number else path.stem)
            return {"title": title, "series": series, "number": number,
                    "writer": meta.get("writer", ""), "pages": len(src), "added": time.time(),
                    "sig": [st.st_mtime, st.st_size], "thumb": thumb,
                    "manga": meta.get("manga", "")}
        finally:
            src.close()


class LibraryScanner(threading.Thread):
    """Walks folders/files, builds library items and reports through a queue.

    Messages: ("scan", filename) ("item", key, item) ("error", key, text) ("done", missing_keys)
    """

    def __init__(self, targets, known: dict, out: queue.Queue):
        super().__init__(daemon=True)
        self.targets, self.known, self.out = targets, known, out

    @staticmethod
    def _walk(root: Path):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fn in sorted(filenames, key=natural_key):
                if Path(fn).suffix.lower() in COMIC_EXTS and not fn.startswith("."):
                    yield Path(dirpath) / fn

    def run(self):
        found, roots = set(), []
        try:
            for t in self.targets:
                t = Path(t)
                if t.is_dir():
                    roots.append(str(t))
                    files = self._walk(t)
                elif t.is_file():
                    files = [t]
                else:
                    continue
                for p in files:
                    key = str(p)
                    found.add(key)
                    try:
                        st = p.stat()
                        if self.known.get(key) == [st.st_mtime, st.st_size]:
                            continue  # unchanged since the last scan
                        self.out.put(("scan", p.name))
                        self.out.put(("item", key, LibraryItemBuilder.build(p)))
                    except Exception as exc:
                        self.out.put(("error", key, str(exc)))
            missing = [k for k in self.known
                       if k not in found and any(k.startswith(r + os.sep) for r in roots)]
        except Exception:
            missing = []
        self.out.put(("done", missing))
