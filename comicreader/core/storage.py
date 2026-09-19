"""Persistent data: reading state (small, saved often) and the library index (bigger)."""
import json
import os
import shutil
import time
from pathlib import Path

from ..constants import LIBRARY_FILE, OLD_STATE_FILE, OLD_THUMB_DIR, STATE_FILE, THUMB_DIR, THUMB_EXT
from ..utils.helpers import folder_title, natural_key, thumb_name


class JsonFile:
    """A JSON file that is read leniently and written atomically."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self, default):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def save(self, data):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


class Store:
    """Everything the reader remembers: positions, bookmarks, favourites, settings, stats..."""

    MAX_REMEMBERED = 500
    MAX_RECENT = 15

    def __init__(self):
        self._file = JsonFile(STATE_FILE)
        raw = self._file.load(None)
        if raw is None:  # first run of v2: pick up the old v1 file
            raw = JsonFile(OLD_STATE_FILE).load({})
        self.data: dict = raw if isinstance(raw, dict) else {}
        for k in ("files", "settings", "percomic", "bookmarks", "lastread", "keys"):
            self.data.setdefault(k, {})
        for k in ("favorites", "recent"):
            self.data.setdefault(k, [])
        st = self.data.setdefault("stats", {})
        st.setdefault("seconds", 0.0)
        st.setdefault("pages", 0)
        st.setdefault("opened", 0)
        st.setdefault("per", {})

    def save(self):
        self._file.save(self.data)

    # ---- simple sections --------------------------------------------------- #
    @property
    def settings(self) -> dict:
        return self.data["settings"]

    @property
    def key_overrides(self) -> dict:
        return self.data["keys"]

    @property
    def stats(self) -> dict:
        return self.data["stats"]

    # ---- reading position -------------------------------------------------- #
    def last_page(self, key: str) -> int:
        return self.data["files"].get(key, 0)

    def progress(self, key: str):
        """Last page reached, or None if the comic has never been opened."""
        return self.data["files"].get(key)

    def remember_position(self, key: str, page: int):
        files = self.data["files"]
        files.pop(key, None)  # re-insert so the dict stays ordered oldest -> newest
        files[key] = page
        while len(files) > self.MAX_REMEMBERED:
            files.pop(next(iter(files)))
        self.touch(key)
        self.save()

    def touch(self, key: str):
        self.data["lastread"][key] = time.time()

    def last_read_time(self, key: str):
        return self.data["lastread"].get(key)

    # ---- per-comic view settings ---------------------------------------------- #
    def percomic(self, key: str) -> dict:
        return self.data["percomic"].get(key, {})

    def set_percomic(self, key: str, manga: bool, mode: str):
        self.data["percomic"][key] = {"manga": manga, "mode": mode}

    # ---- bookmarks / favourites / recent ------------------------------------------ #
    def bookmarks(self, key: str) -> list[int]:
        return self.data["bookmarks"].get(key, [])

    def toggle_bookmark(self, key: str, page: int) -> bool:
        """Returns True if the page is now bookmarked."""
        marks = self.data["bookmarks"].setdefault(key, [])
        if page in marks:
            marks.remove(page)
            added = False
        else:
            marks.append(page)
            marks.sort()
            added = True
        if not marks:
            self.data["bookmarks"].pop(key, None)
        self.save()
        return added

    def is_favorite(self, key: str) -> bool:
        return key in self.data["favorites"]

    def toggle_favorite(self, key: str) -> bool:
        """Returns True if the comic is now a favourite."""
        favs = self.data["favorites"]
        if key in favs:
            favs.remove(key)
            state = False
        else:
            favs.append(key)
            state = True
        self.save()
        return state

    def add_recent(self, path: str):
        rec = self.data["recent"]
        if path in rec:
            rec.remove(path)
        rec.insert(0, path)
        del rec[self.MAX_RECENT:]

    def existing_recent(self) -> list[str]:
        return [p for p in self.data["recent"] if Path(p).exists()]

    # ---- export / import of reading progress ---------------------------------------- #
    def export_progress(self) -> dict:
        d = self.data
        return {k: d[k] for k in ("files", "bookmarks", "favorites", "lastread", "stats", "percomic")}

    def import_progress(self, inc: dict):
        """Merge an exported file into this store, keeping the furthest progress."""
        d = self.data
        for k, p in inc.get("files", {}).items():
            d["files"][k] = max(d["files"].get(k, 0), int(p))
        for k, marks in inc.get("bookmarks", {}).items():
            d["bookmarks"][k] = sorted(set(d["bookmarks"].get(k, [])) | set(marks))
        d["favorites"] = sorted(set(d["favorites"]) | set(inc.get("favorites", [])))
        for k, t in inc.get("lastread", {}).items():
            d["lastread"][k] = max(d["lastread"].get(k, 0), t)
        for k, v in inc.get("percomic", {}).items():
            d["percomic"].setdefault(k, v)
        ist, st = inc.get("stats", {}), d["stats"]
        for field in ("seconds", "pages", "opened"):
            st[field] = max(st[field], ist.get(field, 0))
        for k, v in ist.get("per", {}).items():
            cur = st["per"].setdefault(k, {"seconds": 0.0, "pages": 0})
            cur["seconds"] = max(cur["seconds"], v.get("seconds", 0))
            cur["pages"] = max(cur["pages"], v.get("pages", 0))
        self.save()


class LibraryDB:
    """The scanned library: the root folders you added plus one record per comic.

    Records are keyed by the comic's full path. The folder tree you browse in the library
    window is not stored: it is worked out from those paths (see browse()).
    """

    def __init__(self):
        self._file = JsonFile(LIBRARY_FILE)
        d = self._file.load({})
        self.folders: list[str] = list(d.get("folders", []))  # root folders, as added
        self.items: dict[str, dict] = dict(d.get("items", {}))
        if self._migrate_thumbs():
            self.save()

    def save(self):
        self._file.save({"folders": self.folders, "items": self.items})

    def _migrate_thumbs(self) -> bool:
        """Older versions kept md5-named .jpg covers in ~/.comic_reader/thumbs; copy them to AppData."""
        changed = False
        for key, it in self.items.items():
            old_name = it.get("thumb") or ""
            if old_name.endswith(THUMB_EXT):
                continue
            new_name = ""
            old = OLD_THUMB_DIR / old_name if old_name else None
            if old is not None and old.exists():
                try:
                    THUMB_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(old, THUMB_DIR / thumb_name(key))
                    new_name = thumb_name(key)
                except OSError:
                    pass
            if it.get("thumb", "") != new_name:
                it["thumb"] = new_name  # "" -> the next scan rebuilds this cover
                changed = True
        return changed

    def signatures(self) -> dict:
        """path -> [mtime, size] for the scanner to skip unchanged files.

        A comic whose cover file is missing gets None, so the next scan rebuilds it.
        """
        out = {}
        for k, v in self.items.items():
            thumb = v.get("thumb")
            out[k] = v.get("sig") if thumb and (THUMB_DIR / thumb).exists() else None
        return out

    # ---- folders ------------------------------------------------------------------ #
    @staticmethod
    def _prefix(folder: str) -> str:
        return folder.rstrip(os.sep) + os.sep

    def add_folder(self, folder: str):
        if folder not in self.folders:
            self.folders.append(folder)

    def has_folder(self, folder: str) -> bool:
        pre = self._prefix(folder)
        return folder in self.folders or any(k.startswith(pre) for k in self.items)

    def keys_under(self, folder: str | None = None) -> list[str]:
        """Every comic below `folder` (any depth); None means the whole library."""
        if folder is None:
            return list(self.items)
        pre = self._prefix(folder)
        return [k for k in self.items if k.startswith(pre)]

    def loose_files(self) -> list[str]:
        """Comics that were added one by one and are not inside any root folder."""
        pres = [self._prefix(r) for r in self.folders]
        return [k for k in self.items if not any(k.startswith(p) for p in pres)]

    def browse(self, folder: str | None):
        """What one level of the library shows.

        Returns (subfolders, comics). subfolders is a list of (path, title, comic_keys) where
        comic_keys are all comics anywhere below it; comics are the files directly in `folder`.
        folder=None is the top level: one tile per root folder, plus any loose comics.
        """
        if folder is None:
            roots = sorted(self.folders, key=lambda r: natural_key(folder_title(r)))
            pres = [(r, self._prefix(r)) for r in roots]
            buckets: dict[str, list[str]] = {r: [] for r in roots}
            loose = []
            for k in self.items:
                hit = False
                for r, pre in pres:
                    if k.startswith(pre):
                        buckets[r].append(k)
                        hit = True
                if not hit:
                    loose.append(k)
            return [(r, folder_title(r), buckets[r]) for r in roots], loose
        pre = self._prefix(folder)
        groups: dict[str, list[str]] = {}
        comics = []
        for k in self.items:
            if k.startswith(pre):
                head, sep, _ = k[len(pre):].partition(os.sep)
                if sep:
                    groups.setdefault(head, []).append(k)
                else:
                    comics.append(k)
        subs = [(pre + name, name, keys)
                for name, keys in sorted(groups.items(), key=lambda kv: natural_key(kv[0]))]
        return subs, comics

    def remove_folder(self, folder: str) -> int:
        """Forget a root folder and its comics (and their covers). Files on disk are untouched."""
        keys = self.keys_under(folder)
        for k in keys:
            self.remove(k)
        if folder in self.folders:
            self.folders.remove(folder)
        return len(keys)

    # ---- comics ------------------------------------------------------------------- #
    def merge(self, key: str, item: dict):
        old = self.items.get(key)
        if old:  # a rescan must not reset the "date added"
            item["added"] = old.get("added", item["added"])
        self.items[key] = item

    def remove(self, key: str):
        it = self.items.pop(key, None)
        if it and it.get("thumb"):
            try:
                (THUMB_DIR / it["thumb"]).unlink()
            except OSError:
                pass