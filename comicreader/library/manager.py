"""LibraryManager: owns the library database, the background scan and the library page."""
import queue
import time
from pathlib import Path
from tkinter import filedialog, messagebox

from ..constants import APP_NAME, COMIC_EXTS, THUMB_DIR, THUMB_EXT
from ..core.storage import LibraryDB
from .scanner import LibraryScanner
from .window import LibraryView


class LibraryManager:
    def __init__(self, app):
        self.app = app
        self.db = LibraryDB()
        self.view: "LibraryView | None" = None
        self._scan_q: queue.Queue | None = None
        self._scan_stats = {"new": 0, "errors": 0}
        self._last_refresh = 0.0

    # ---- view --------------------------------------------------------------------------- #
    def build_view(self, parent) -> LibraryView:
        """Create the library page (once); the main window shows and hides it."""
        self.view = LibraryView(parent, self.app)
        if not self.db.items and not self.db.folders:
            self.view.set_status("Tip: Add Folder… scans a folder (and its sub-folders) for comics.")
        return self.view

    def save_view_state(self):
        if self.view is not None:
            self.view.save_state()

    def theme_changed(self):
        if self.view is not None:
            self.view.apply_theme()

    def scale_changed(self):
        if self.view is not None:
            self.view.apply_theme()
            self.view.refresh()

    def _notify(self, text: str):
        if self.view is not None:
            self.view.set_status(text)

    def startup_scan(self):
        """Pick up new comics and rebuild missing covers when the app starts."""
        targets = self.scan_targets()
        if targets and not self.scanning:
            self.start_scan(targets)

    # ---- adding / scanning ------------------------------------------------------------- #
    def scan_targets(self) -> list[str]:
        """Root folders plus comics that were added one by one."""
        return list(self.db.folders) + self.db.loose_files()

    def add_folder(self):
        folder = filedialog.askdirectory(title="Add a folder of comics to the library")
        if not folder:
            return
        folder = str(Path(folder).resolve())
        if folder in self.db.folders:
            self.app.flash("That folder is already in the library - rescanning it")
        self.db.add_folder(folder)
        self.db.save()
        if self.view is not None:
            self.view.go(None)  # show the new tile
        self.app.show_library()
        self.start_scan([folder])

    def remove_folder(self, folder: str):
        """Take a root folder (and its comics and covers) out of the library; files stay on disk."""
        parent = self.app
        if self.scanning:
            messagebox.showinfo(APP_NAME, "Wait for the library scan to finish first.", parent=parent)
            return
        n = len(self.db.keys_under(folder))
        if not messagebox.askyesno(
                "Remove folder",
                f"Remove '{folder}' from library?\n\nThis will remove {n} comic{'s' if n != 1 else ''} from your library "
                "but will not delete the original files.", parent=parent):
            return
        self.db.remove_folder(folder)
        self.db.save()
        if self.view is not None:
            self.view.go(None)

    def rebuild_covers(self):
        """Delete every cached cover and let a scan draw them again."""
        if self.scanning:
            self.app.flash("A library scan is already running")
            return
        if not messagebox.askyesno(APP_NAME, "Delete all cached covers and rebuild them?\n\n"
                                   "Your comics are not touched.", parent=self.app):
            return
        for f in THUMB_DIR.glob("*" + THUMB_EXT):
            try:
                f.unlink()
            except OSError:
                pass
        if self.view is not None:
            self.view.refresh(covers=True)
        self.start_scan(self.scan_targets())

    def add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(COMIC_EXTS))
        files = filedialog.askopenfilenames(title="Add comics to the library",
                                            filetypes=[("Comics and PDFs", exts), ("All files", "*.*")])
        if files:
            if self.view is not None:
                self.view.go(None)  # loose files show up at the top level
            self.start_scan([str(Path(f).resolve()) for f in files])

    def rescan(self):
        self.start_scan(self.scan_targets())

    def start_scan(self, targets):
        if self._scan_q is not None:
            self.app.flash("A library scan is already running")
            return
        if not targets:
            self.app.flash("Nothing to scan - add a folder first")
            return
        self._scan_q = queue.Queue()
        self._scan_stats = {"new": 0, "errors": 0}
        LibraryScanner(targets, self.db.signatures(), self._scan_q).start()
        self._notify("Scanning…")
        self.app.after(150, self.poll)

    @property
    def scanning(self) -> bool:
        return self._scan_q is not None

    def poll(self):
        """Apply whatever the scanner thread has produced so far (runs on the UI thread)."""
        q, done = self._scan_q, False
        try:
            while q is not None:
                msg = q.get_nowait()
                if msg[0] == "scan":
                    self._notify(f"Scanning: {msg[1]}   ({self._scan_stats['new']} added)")
                elif msg[0] == "item":
                    self.db.merge(msg[1], msg[2])
                    self._scan_stats["new"] += 1
                elif msg[0] == "error":
                    self._scan_stats["errors"] += 1
                elif msg[0] == "done":
                    for k in msg[1]:
                        self.db.remove(k)
                    done = True
        except queue.Empty:
            pass
        now = time.time()
        if self.view is not None and (done or (self.app.in_library
                                                and now - self._last_refresh > 1.5)):
            self._last_refresh = now
            self.view.refresh(covers=done)  # (skipped while the reader is on screen, except at the end)
        if done:
            self._scan_q = None
            self.db.save()
            s = self._scan_stats
            self._notify(f"Scan finished: {s['new']} added/updated, {s['errors']} skipped "
                         f"(unreadable or no images), {len(self.db.items)} in library.")
        else:
            self.app.after(150, self.poll)

    def save(self):
        self.db.save()