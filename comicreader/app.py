"""The main window: wires the components together and implements reading actions.

Components (package/module):
  SourceFactory, Source     core/sources.py      reading pages out of CBZ/CBR/CBT/CB7/PDF/folders
  ComicSession, ComicQueue  core/session.py      what is open, and what is queued after it
  PageCache, ReadingStats   core/session.py      decoded-page LRU cache, reading time/pages counters
  Store                     core/storage.py      positions, bookmarks, favourites, settings
  KeyBindings               core/keybindings.py  rebindable keyboard actions
  PagedView, WebtoonView    ui/views.py          drawing the pages
  MenuBar, ProgressBar      ui/menubar.py, ui/widgets.py
  MouseController           ui/controls.py
  DropTarget                ui/dragdrop.py
  ThemeManager              ui/theme.py          themes and UI scale
  LibraryManager            library/manager.py   library database, scanning and window
"""
import json
import textwrap
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image

from .constants import APP_NAME, COMIC_EXTS, ICON_FILE, IMAGE_EXTS
from .ui.controls import MouseController
from .ui.dragdrop import HAS_DND, BaseTk, DropTarget
from .utils.helpers import apply_filter, human_size, natural_key
from .core.keybindings import KeyBindings
from .library.manager import LibraryManager
from .ui.menubar import MenuBar
from .core.session import ComicQueue, ComicSession, PageCache, ReadingStats
from .core.sources import EmptyComicError, SourceFactory
from .core.storage import Store
from .ui.theme import ThemeManager
from .ui.views import PagedView, WebtoonView
from .ui.widgets import ProgressBar


class ComicReader(BaseTk):
    def __init__(self, initial: str | None = None):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1150x820")
        self.minsize(640, 440)
        if ICON_FILE.exists():
            try:
                self.iconbitmap(default=str(ICON_FILE))  # also used by dialogs and the library window
            except tk.TclError:
                pass  # non-Windows: keep the default icon

        # ---- model / services ---- #
        self.store = Store()
        self.themer = ThemeManager(self)
        self.keys = KeyBindings(self.store)
        self.session = ComicSession()
        self.queue = ComicQueue()
        self.stats = ReadingStats(self.store)
        self.cache = PageCache()
        self.library = LibraryManager(self)
        SourceFactory.password_provider = lambda: simpledialog.askstring(
            APP_NAME, "This PDF is password protected:", show="*", parent=self)

        # ---- user-visible options (tk variables so the menus can bind to them) ---- #
        s = self.store.settings
        self.mode = tk.StringVar(value=s.get("mode") or ("double" if s.get("double") else "single"))
        self.fit = tk.StringVar(value=s.get("fit", "width"))          # width|height|page|original
        self.manga = tk.BooleanVar(value=False)
        self.theme = tk.StringVar(value=s.get("theme", "dark"))
        self.bgname = tk.StringVar(value=s.get("bg", "Dark gray"))
        self.filter = tk.StringVar(value=s.get("filter", "none"))
        self.brightness = tk.DoubleVar(value=s.get("brightness", 1.0))
        self.ui_scale = tk.DoubleVar(value=s.get("ui_scale", 1.0))
        self.wheel = tk.StringVar(value=s.get("wheel", "scroll"))     # scroll|flip|zoom
        self.dbl_action = tk.StringVar(value=s.get("dbl", "fullscreen"))
        self.autohide = tk.BooleanVar(value=s.get("autohide", False))

        # ---- view state ---- #
        self.page = 0
        self.span = 1
        self.zoom = 1.0
        self.rotation = 0
        self._end_armed = False
        self._resize_job = None
        self.view = None

        # ---- UI ---- #
        self._register_actions()
        self._build_ui()
        self.paged = PagedView(self)
        self.webtoon = WebtoonView(self)
        self.view = self.paged
        self.menubar = MenuBar(self)
        self.keys.on_change = self.menubar.build
        self.keys.rebuild()
        self.menubar.build()
        self.mouse = MouseController(self)
        self.mouse.attach()
        self.bind("<Key>", self._on_key)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.dropper = DropTarget(self.canvas, [self.canvas, self],
                                  lambda: self.colors["accent"], self.open_many)
        self.dropper.attach()

        self.apply_theme()
        self.apply_scale()
        self.apply_bar_mode()
        self._show_welcome()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if initial:
            self.after(200, lambda: self.open_many([Path(initial)]))

    @property
    def colors(self) -> dict:
        return self.themer.colors

    # ------------------------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------------------------ #
    def _register_actions(self):
        add = self.keys.register
        add("open_file", "Open file…", self.ask_open_file, ["Control-o"])
        add("open_folder", "Open folder…", self.ask_open_folder, ["Control-Shift-o"])
        add("library", "Open library", self.library.open_window, ["Control-l"])
        add("info", "Comic properties", self.show_info, ["Control-i"])
        add("go_right", "Right: next page (previous in RTL)", self.go_right, ["Right"])
        add("go_left", "Left: previous page (next in RTL)", self.go_left, ["Left"])
        add("next_page", "Next page", self.next_page, ["Next"])
        add("prev_page", "Previous page", self.prev_page, ["Prior", "BackSpace"])
        add("scroll_next", "Scroll down / next page", lambda: self.smart_scroll(1), ["space"])
        add("scroll_prev", "Scroll up / previous page", lambda: self.smart_scroll(-1),
            ["Shift-space"])
        add("scroll_down", "Scroll down a little", lambda: self.canvas.yview_scroll(3, "units"),
            ["Down"])
        add("scroll_up", "Scroll up a little", lambda: self.canvas.yview_scroll(-3, "units"),
            ["Up"])
        add("first_page", "First page", lambda: self.show_page(0), ["Home"])
        add("last_page", "Last page", self.last_page, ["End"])
        add("goto", "Go to page…", self.goto_page, ["Control-g"])
        add("next_comic", "Next comic in queue", self.next_comic, ["bracketright"])
        add("prev_comic", "Previous comic in queue", self.prev_comic, ["bracketleft"])
        add("fit_width", "Fit width", lambda: self.set_fit("width"), ["1"])
        add("fit_height", "Fit height", lambda: self.set_fit("height"), ["2"])
        add("fit_page", "Fit page", lambda: self.set_fit("page"), ["3"])
        add("fit_original", "Original size", lambda: self.set_fit("original"), ["4"])
        add("zoom_in", "Zoom in", lambda: self.change_zoom(1.15), ["plus", "equal", "KP_Add"])
        add("zoom_out", "Zoom out", lambda: self.change_zoom(1 / 1.15), ["minus", "KP_Subtract"])
        add("zoom_reset", "Reset zoom", lambda: self.change_zoom(None), ["0"])
        add("rotate_right", "Rotate 90° clockwise", lambda: self.rotate(90), ["r"])
        add("rotate_left", "Rotate 90° counter-clockwise", lambda: self.rotate(-90), ["Shift-r"])
        add("toggle_double", "Toggle double-page", lambda: self._toggle_mode("double"), ["d"])
        add("toggle_webtoon", "Toggle webtoon mode", lambda: self._toggle_mode("webtoon"), ["w"])
        add("toggle_manga", "Toggle right-to-left", self.toggle_manga, ["m"])
        add("fullscreen", "Fullscreen", self.toggle_fullscreen, ["f", "F11"])
        add("exit_fullscreen", "Leave fullscreen", lambda: self.attributes("-fullscreen", False),
            ["Escape"])
        add("bookmark", "Bookmark this page", self.toggle_bookmark, ["b"])
        add("favorite", "Favourite this comic", self.toggle_favorite, ["Control-d"])

    def _build_ui(self):
        self.progress = ProgressBar(self, on_jump=self._jump_from_bar)
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill="both", expand=True)
        self.main_frame.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.main_frame, highlightthickness=0)
        self.vs = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.hs = ttk.Scrollbar(self.main_frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self._yscroll, xscrollcommand=self.hs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vs.grid(row=0, column=1, sticky="ns")
        self.hs.grid(row=1, column=0, sticky="ew")
        self.progress.dock(before=self.main_frame)

    def _show_welcome(self):
        self.paged.deactivate()
        self.canvas.delete("all")
        tip = ("Ctrl+O  open a comic / PDF        Ctrl+Shift+O  open a folder of images\n"
               "Ctrl+L  library                  Drop files or folders here to open them"
               if HAS_DND else
               "Ctrl+O  open a comic / PDF        Ctrl+Shift+O  open a folder of images\n"
               "Ctrl+L  library\n\nFor drag & drop:  pip install tkinterdnd2")
        self.canvas.create_text(24, 24, anchor="nw", fill="#888888", font=("Segoe UI", 12), text=tip)
        self._update_status()

    # ------------------------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------------------------ #
    def _on_key(self, event):
        try:
            w = self.focus_get()
        except KeyError:
            w = None
        if isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
            return  # typing in the page box shouldn't trigger shortcuts
        if self.keys.dispatch(event):
            return "break"

    def _yscroll(self, first, last):
        self.vs.set(first, last)
        if self.view:
            self.view.on_scroll()

    def _on_canvas_configure(self, event):
        view = self.view
        if not view.active or (event.width, event.height) == view.last_size:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, lambda: self.view.redraw())

    def _jump_from_bar(self, page: int):
        self.canvas.focus_set()
        if self.session.is_open and page != self.page:
            self.show_page(page)

    # ------------------------------------------------------------------------------------ #
    # View plumbing used by the views
    # ------------------------------------------------------------------------------------ #
    def get_image(self, index: int) -> Image.Image:
        return self.cache.get(index, self.session.source)

    def style(self, img: Image.Image) -> Image.Image:
        return apply_filter(img, self.filter.get(), self.brightness.get())

    def canvas_bg(self) -> str:
        return self.themer.canvas_bg(self.bgname.get())

    def on_view_page(self, page: int, span: int):
        """A view tells us which page(s) it is now showing."""
        self.page, self.span = page, span
        self.stats.tick(self.session.key)
        self.stats.page_viewed(self.session.key, page)
        self._update_status()
        self.progress.set_page(page)

    def _select_view(self):
        view = self.webtoon if self.mode.get() == "webtoon" else self.paged
        if view is not self.view:
            self.view.deactivate()
            self.view = view
        self.cache.limit = 10 if view.continuous else 6
        return view

    # ------------------------------------------------------------------------------------ #
    # Opening comics
    # ------------------------------------------------------------------------------------ #
    def ask_open_file(self):
        exts = " ".join(f"*{e}" for e in sorted(COMIC_EXTS) + sorted(IMAGE_EXTS))
        path = filedialog.askopenfilename(
            title="Open comic", filetypes=[("Comics, PDFs and images", exts), ("All files", "*.*")])
        if path:
            self.open_path(Path(path))

    def ask_open_folder(self):
        path = filedialog.askdirectory(title="Open folder of images")
        if path:
            self.open_path(Path(path))

    def open_many(self, paths):
        """Open dropped files/folders: the first one now, the rest queued."""
        items: list[Path] = []
        for p in map(Path, paths):
            if p.is_dir():
                kids = sorted((k for k in p.iterdir() if k.is_file()),
                              key=lambda k: natural_key(k.name))
                has_imgs = any(k.suffix.lower() in IMAGE_EXTS for k in kids)
                comics = [k for k in kids if k.suffix.lower() in COMIC_EXTS]
                if comics and not has_imgs:  # a folder of comics
                    items.extend(comics)
                else:                        # a folder of page images
                    items.append(p)
            elif p.is_file() and (len(paths) == 1 or p.suffix.lower() in COMIC_EXTS | IMAGE_EXTS):
                items.append(p)
        if not items:
            self.flash("Nothing to open")
            return
        self.open_path(items[0], queue_items=items, qpos=0)

    def open_path(self, path: Path, start: int | None = None,
                  queue_items: list[Path] | None = None, qpos: int = 0) -> bool:
        path = Path(path)
        try:
            src, s0 = SourceFactory.open(path)
        except EmptyComicError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return False
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open:\n{path}\n\n{exc}")
            return False

        self._leave_current()
        self.session.attach(src)
        self.queue.set(queue_items if queue_items is not None else [path], qpos)
        self.cache.clear()
        self.zoom, self.rotation = 1.0, 0

        key = self.session.key
        per = self.store.percomic(key)
        self.manga.set(per.get("manga", self.session.detect_manga()))
        if per.get("mode") in ("single", "double", "webtoon"):
            self.mode.set(per["mode"])
        self.store.add_recent(str(self.session.path))
        self.store.touch(key)
        self.stats.begin_comic()
        self.progress.set_pages(self.session.count)

        if start is None:
            start = s0 if s0 is not None else self.store.last_page(key)
        self.update_idletasks()
        self.show_page(start)
        self.canvas.focus_set()
        return True

    def _leave_current(self):
        """Save the position/time of the comic we're about to replace."""
        self.stats.tick(self.session.key)
        self._remember_position()
        self.view.deactivate()

    def _remember_position(self):
        if self.session.is_open:
            self.store.remember_position(self.session.key, self.page)

    def _save_percomic(self):
        if self.session.is_open:
            self.store.set_percomic(self.session.key, self.manga.get(), self.mode.get())

    def next_comic(self):
        if self.queue.has_next:
            self.open_path(self.queue.next_item, queue_items=self.queue.items,
                           qpos=self.queue.pos + 1)
        else:
            self.flash("No more comics in the queue")

    def prev_comic(self):
        if self.queue.has_prev:
            self.open_path(self.queue.prev_item, queue_items=self.queue.items,
                           qpos=self.queue.pos - 1)
        else:
            self.flash("No previous comic in the queue")

    # ------------------------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------------------------ #
    def show_page(self, index: int, at: str = "top"):
        if not self.session.is_open:
            return
        index = max(0, min(index, self.session.count - 1))
        self._end_armed = False
        self._select_view().show(index, at)

    def next_page(self):
        if not self.session.is_open:
            return
        nxt = self.page + self.span
        if nxt >= self.session.count:
            if self.queue.has_next:
                if self._end_armed:  # second press at the end: go to the next comic
                    self.next_comic()
                else:
                    self._end_armed = True
                    self.flash(f"End. Press again for next: {self.queue.next_item.name}")
            else:
                self.flash("Last page")
            return
        self.show_page(nxt, at="top")

    def prev_page(self):
        if not self.session.is_open:
            return
        if self.page <= 0:
            self.flash("First page")
            return
        target = self.page - 1
        if (self.mode.get() == "double" and self.page - 2 >= 0
                and self.paged.span_at(self.page - 2) == 2):
            target = self.page - 2
        self.show_page(target, at="bottom")

    def last_page(self):
        if self.session.is_open:
            self.show_page(self.session.count - 1)

    def go_right(self):
        self.prev_page() if self.manga.get() else self.next_page()

    def go_left(self):
        self.next_page() if self.manga.get() else self.prev_page()

    def goto_page(self):
        if not self.session.is_open:
            return
        n = simpledialog.askinteger(APP_NAME, f"Go to page (1-{self.session.count}):",
                                    parent=self, minvalue=1, maxvalue=self.session.count)
        if n is not None:
            self.show_page(n - 1)

    def smart_scroll(self, direction: int):
        """Scroll most of a screen; at the very edge, turn the page instead."""
        if not self.session.is_open:
            return
        top, bottom = self.canvas.yview()
        step = (bottom - top) * 0.85
        if direction > 0:
            if bottom >= 0.999:
                self.next_page()
            else:
                self.canvas.yview_moveto(top + step)
        else:
            if top <= 0.001:
                self.prev_page()
            else:
                self.canvas.yview_moveto(top - step)

    # ------------------------------------------------------------------------------------ #
    # View settings
    # ------------------------------------------------------------------------------------ #
    def set_fit(self, mode: str):
        self.fit.set(mode)
        self.on_fit_change()

    def on_fit_change(self):
        self.zoom = 1.0
        self.view.redraw("top")
        self._update_status()

    def _toggle_mode(self, target: str):
        self.mode.set("single" if self.mode.get() == target else target)
        self.on_layout_change()

    def toggle_manga(self):
        self.manga.set(not self.manga.get())
        self.on_layout_change()

    def on_layout_change(self):
        """Mode or reading direction changed."""
        self._save_percomic()
        if self.session.is_open:
            self.show_page(self.page)
        else:
            self._update_status()

    def restyle(self):
        """Filter / brightness / background changed: redraw with the new look."""
        self.view.redraw()

    def change_zoom(self, factor: float | None):
        self.zoom = 1.0 if factor is None else max(0.2, min(8.0, self.zoom * factor))
        self.view.redraw()
        self._update_status()

    def rotate(self, delta: int):
        self.rotation = (self.rotation + delta) % 360
        if self.session.is_open and not self.view.continuous:
            self.show_page(self.page)
        else:
            self._update_status()

    def toggle_fullscreen(self):
        self.attributes("-fullscreen", not bool(self.attributes("-fullscreen")))

    def apply_theme(self):
        self.themer.apply(self.theme.get())
        self.canvas.configure(bg=self.canvas_bg())
        self.library.theme_changed()
        self.restyle()

    def on_bg_change(self):
        self.canvas.configure(bg=self.canvas_bg())
        self.restyle()

    def apply_scale(self):
        self.themer.set_scale(self.ui_scale.get())
        self.library.scale_changed()

    def apply_bar_mode(self):
        self.progress.set_autohide(self.autohide.get())

    # ------------------------------------------------------------------------------------ #
    # Status, bookmarks, favourites, info
    # ------------------------------------------------------------------------------------ #
    def _update_status(self, message: str | None = None):
        if message:
            self.progress.set_status(message)
            return
        s = self.session
        if not s.is_open:
            self.progress.set_status("No comic open")
            return
        pages = f"{self.page + 1}" if self.span == 1 else f"{self.page + 1}-{self.page + 2}"
        parts = [s.title, f"Page {pages} / {s.count}",
                 f"{self.mode.get()}, fit {self.fit.get()}, {round(self.zoom * 100)}%"]
        flags = []
        if self.manga.get():
            flags.append("RTL")
        if self.rotation:
            flags.append(f"rot {self.rotation}°")
        if self.page in self.store.bookmarks(s.key):
            flags.append("bookmarked")
        if self.store.is_favorite(s.key):
            flags.append("★")
        if len(self.queue) > 1:
            flags.append(f"queue {self.queue.pos + 1}/{len(self.queue)}")
        if flags:
            parts.append(" ".join(flags))
        self.progress.set_status("  |  ".join(parts))
        self.title(f"{s.path.name} - {APP_NAME}")

    def flash(self, message: str):
        """Show a short message in the status line, then go back to the normal status."""
        self._update_status(message)
        self.progress.poke()
        self.after(1500, self._update_status)

    def toggle_bookmark(self):
        if not self.session.is_open:
            return
        added = self.store.toggle_bookmark(self.session.key, self.page)
        self.flash(f"Bookmarked page {self.page + 1}" if added
                   else f"Bookmark removed (page {self.page + 1})")

    def toggle_favorite(self):
        if self.session.is_open:
            state = self.store.toggle_favorite(self.session.key)
            self.flash("Added to favourites" if state else "Removed from favourites")

    def show_info(self):
        s = self.session
        if not s.is_open:
            return
        m = s.meta
        try:
            size = human_size(s.path.stat().st_size) if s.path.is_file() else "folder"
        except OSError:
            size = "?"
        marks = ", ".join(str(p + 1) for p in self.store.bookmarks(s.key)) or "none"
        lines = [("Title", m.get("title") or s.path.stem), ("Series", m.get("series", "")),
                 ("Number / Volume", " / ".join(x for x in (m.get("number"), m.get("volume")) if x)),
                 ("Author", m.get("writer", "")), ("Genre", m.get("genre", "")),
                 ("Pages", str(s.count)), ("Format", s.source.kind), ("Size", size),
                 ("Reading direction", "Right-to-left" if self.manga.get() else "Left-to-right"),
                 ("Bookmarks", marks), ("Path", str(s.path))]
        text = "\n".join(f"{k}: {v}" for k, v in lines if v)
        if m.get("summary"):
            text += "\n\n" + textwrap.shorten(m["summary"], 400)
        messagebox.showinfo("Comic properties", text, parent=self)

    def show_stats(self):
        self.stats.tick(self.session.key)
        messagebox.showinfo("Reading statistics", self.stats.summary_text(), parent=self)

    def export_progress(self):
        self._remember_position()
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="comic_progress.json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(self.store.export_progress(), indent=1),
                                  encoding="utf-8")
            self.flash("Progress exported")
        except OSError as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def import_progress(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            inc = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not read file:\n{exc}")
            return
        self.store.import_progress(inc)
        self.flash("Progress imported")

    # ------------------------------------------------------------------------------------ #
    def on_close(self):
        self.stats.tick(self.session.key)
        self._remember_position()
        self._save_percomic()
        self.store.settings.update({
            "mode": self.mode.get(), "fit": self.fit.get(), "theme": self.theme.get(),
            "bg": self.bgname.get(), "filter": self.filter.get(),
            "brightness": self.brightness.get(), "ui_scale": self.ui_scale.get(),
            "wheel": self.wheel.get(), "dbl": self.dbl_action.get(),
            "autohide": self.autohide.get()})
        self.library.close_window()
        self.store.save()
        self.library.save()
        self.session.close()
        self.destroy()
