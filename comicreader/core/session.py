"""The state of what is being read (as opposed to how it is drawn)."""
import re
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image

from ..utils.helpers import human_time, make_placeholder
from .sources import Source


class PageCache:
    """Small LRU cache of decoded pages; a page that fails to decode becomes a placeholder."""

    def __init__(self, limit: int = 6):
        self.limit = limit
        self._pages: "OrderedDict[int, Image.Image]" = OrderedDict()

    def __contains__(self, index: int) -> bool:
        return index in self._pages

    def clear(self):
        self._pages.clear()

    def get(self, index: int, source: Source) -> Image.Image:
        if index in self._pages:
            self._pages.move_to_end(index)
            return self._pages[index]
        try:
            img = source.load(index)
        except Exception as exc:
            img = make_placeholder(f"Page {index + 1} failed to load:\n{exc}")
        self._pages[index] = img
        while len(self._pages) > self.limit:
            self._pages.popitem(last=False)
        return img


class ComicQueue:
    """Comics dropped/opened together, read one after another."""

    def __init__(self):
        self.items: list[Path] = []
        self.pos = 0

    def __len__(self):
        return len(self.items)

    def set(self, items, pos: int = 0):
        self.items, self.pos = list(items), pos

    @property
    def has_next(self) -> bool:
        return self.pos + 1 < len(self.items)

    @property
    def has_prev(self) -> bool:
        return self.pos > 0

    @property
    def next_item(self) -> Path:
        return self.items[self.pos + 1]

    @property
    def prev_item(self) -> Path:
        return self.items[self.pos - 1]


class ComicSession:
    """The comic that is currently open: its Source, location, key and metadata."""

    def __init__(self):
        self.source: Source | None = None
        self.path: Path | None = None
        self.key = ""      # resolved path string, used as the id in every store
        self.meta: dict = {}

    @property
    def is_open(self) -> bool:
        return self.source is not None

    @property
    def count(self) -> int:
        return len(self.source) if self.source else 0

    @property
    def title(self) -> str:
        return self.meta.get("title") or (self.path.name if self.path else "")

    def attach(self, source: Source):
        """Make `source` the current comic and close the previous one."""
        old = self.source
        self.source = source
        self.path = source.location
        self.key = str(source.location.resolve())
        self.meta = source.read_meta()
        if old:
            old.close()

    def close(self):
        if self.source:
            self.source.close()
            self.source = None

    def detect_manga(self) -> bool:
        """Right-to-left guess from ComicInfo.xml's Manga tag or the file name."""
        flag = self.meta.get("manga", "").lower()
        if flag in ("yes", "yesandrighttoleft"):
            return True
        return bool(self.path and re.search(r"(?i)\bmanga\b|\[jp\]|\brtl\b", self.path.name))


class ReadingStats:
    """Accumulates reading time (idle gaps over 2 minutes don't count) and pages viewed."""

    IDLE_CAP = 120.0

    def __init__(self, store):
        self.store = store
        self._tick_at = 0.0
        self._counted_page = -1

    def begin_comic(self):
        self.store.stats["opened"] += 1
        self._tick_at = time.time()
        self._counted_page = -1

    def _per(self, key: str) -> dict:
        return self.store.stats["per"].setdefault(key, {"seconds": 0.0, "pages": 0})

    def tick(self, key: str):
        """Credit the time since the last tick to `key` (pass '' when nothing is open)."""
        now = time.time()
        if self._tick_at and key:
            dt = min(now - self._tick_at, self.IDLE_CAP)
            self.store.stats["seconds"] += dt
            self._per(key)["seconds"] += dt
        self._tick_at = now

    def page_viewed(self, key: str, page: int):
        if key and page != self._counted_page:
            self._counted_page = page
            self.store.stats["pages"] += 1
            self._per(key)["pages"] += 1

    def summary_text(self) -> str:
        st = self.store.stats
        top = sorted(st["per"].items(), key=lambda kv: -kv[1]["seconds"])[:5]
        lines = [f"Total reading time: {human_time(st['seconds'])}",
                 f"Pages viewed: {st['pages']}", f"Comics opened: {st['opened']}"]
        if top:
            lines.append("\nMost read:")
            lines += [f"  {Path(k).name}: {human_time(v['seconds'])}, {v['pages']} pages"
                      for k, v in top]
        return "\n".join(lines)
