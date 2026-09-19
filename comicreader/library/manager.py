"""LibraryManager: owns the library database, the background scan and the window."""
import queue
import time
from pathlib import Path
from tkinter import filedialog

from ..constants import COMIC_EXTS
from ..core.storage import LibraryDB
from .scanner import LibraryScanner
from .window import LibraryWindow


class LibraryManager:
    def __init__(self, app):
        self.app = app
        self.db = LibraryDB()
        self.window: "LibraryWindow | None" = None
        self._scan_q: queue.Queue | None = None
        self._scan_stats = {"new": 0, "errors": 0}
        self._last_refresh = 0.0

    # ---- window ---------------------------------------------------------------------- #
    @property
    def window_open(self) -> bool:
        return self.window is not None and self.window.winfo_exists()

    def open_window(self):
        if self.window_open:
            self.window.lift()
            self.window.focus_force()
            return
        self.window = LibraryWindow(self.app)
        if not self.db.items and not self.db.folders:
            self.window.set_status("Tip: Add Folder… scans a folder (and sub-folders) for comics.")

    def close_window(self):
        if self.window_open:
            self.window.close()

    def theme_changed(self):
        if self.window_open:
            self.window.apply_theme()

    def scale_changed(self):
        if self.window_open:
            self.window.apply_theme()
            self.window.refresh()

    def _notify(self, text: str):
        if self.window_open:
            self.window.set_status(text)

    # ---- adding / scanning ------------------------------------------------------------- #
    def add_folder(self):
        folder = filedialog.askdirectory(title="Add a folder of comics to the library")
        if folder:
            folder = str(Path(folder).resolve())
            self.db.add_folder(folder)
            self.start_scan([folder])

    def add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(COMIC_EXTS))
        files = filedialog.askopenfilenames(title="Add comics to the library",
                                            filetypes=[("Comics and PDFs", exts), ("All files", "*.*")])
        if files:
            self.start_scan([str(Path(f).resolve()) for f in files])

    def rescan(self):
        self.start_scan(list(self.db.folders))

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
        if self.window_open and (done or now - self._last_refresh > 1.5):
            self._last_refresh = now
            self.window.refresh()
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
