"""The window's menu bar."""
import tkinter as tk
from pathlib import Path

from ..constants import CANVAS_BGS
from .dialogs import KeysDialog


class MenuBar:
    """Builds File / View / Go menus for the main window.

    build() can be called again at any time (it is, after a key is rebound) so the
    accelerator text always matches the current key bindings.
    """

    def __init__(self, app):
        self.app = app

    def build(self):
        a = self.app
        bar = tk.Menu(a)
        bar.add_cascade(label="File", menu=self._file_menu(bar))
        bar.add_cascade(label="View", menu=self._view_menu(bar))
        bar.add_cascade(label="Go", menu=self._go_menu(bar))
        a.config(menu=bar)

    def _cmd(self, menu, action, label=None):
        act = self.app.keys.actions[action]
        menu.add_command(label=label or act.label, accelerator=self.app.keys.accelerator(action),
                         command=act.callback)

    # ---- File -------------------------------------------------------------------------- #
    def _file_menu(self, bar):
        a = self.app
        f = tk.Menu(bar, tearoff=0)
        self._cmd(f, "open_file")
        self._cmd(f, "open_folder")
        recent = tk.Menu(f, tearoff=0, postcommand=lambda: self._fill_recent(recent))
        f.add_cascade(label="Open Recent", menu=recent)
        f.add_separator()
        self._cmd(f, "library")
        f.add_command(label="Add Files to Library…", command=a.library.add_files)
        f.add_command(label="Add Folder to Library…", command=a.library.add_folder)
        f.add_separator()
        self._cmd(f, "info")
        f.add_command(label="Reading Statistics…", command=a.show_stats)
        f.add_command(label="Export Progress…", command=a.export_progress)
        f.add_command(label="Import Progress…", command=a.import_progress)
        f.add_command(label="Keyboard Shortcuts…", command=lambda: KeysDialog(a))
        f.add_separator()
        f.add_command(label="Exit", command=a.on_close)
        return f

    def _fill_recent(self, menu: tk.Menu):
        menu.delete(0, "end")
        rec = self.app.store.existing_recent()
        if not rec:
            menu.add_command(label="(empty)", state="disabled")
        for p in rec:
            menu.add_command(label=Path(p).name, command=lambda p=p: self.app.open_path(Path(p)))

    # ---- View -------------------------------------------------------------------------- #
    def _view_menu(self, bar):
        a = self.app
        v = tk.Menu(bar, tearoff=0)
        for label, val in (("Single Page", "single"), ("Double Page", "double"),
                           ("Webtoon (continuous scroll)", "webtoon")):
            v.add_radiobutton(label=label, variable=a.mode, value=val,
                              command=a.on_layout_change)
        v.add_checkbutton(label="Right-to-Left (Manga)", accelerator=a.keys.accelerator("toggle_manga"),
                          variable=a.manga, command=a.on_layout_change)
        v.add_separator()
        for label, val, act in (("Fit Width", "width", "fit_width"),
                                ("Fit Height", "height", "fit_height"),
                                ("Fit Page", "page", "fit_page"),
                                ("Original Size", "original", "fit_original")):
            v.add_radiobutton(label=label, accelerator=a.keys.accelerator(act), variable=a.fit,
                              value=val, command=a.on_fit_change)
        v.add_separator()
        for action in ("zoom_in", "zoom_out", "zoom_reset", "rotate_right", "rotate_left"):
            self._cmd(v, action)
        v.add_separator()

        bgm = tk.Menu(v, tearoff=0)
        for name in CANVAS_BGS:
            bgm.add_radiobutton(label=name, variable=a.bgname, value=name, command=a.on_bg_change)
        v.add_cascade(label="Background", menu=bgm)

        brm = tk.Menu(v, tearoff=0)
        for pct in range(50, 160, 10):
            brm.add_radiobutton(label=f"{pct}%", variable=a.brightness, value=pct / 100,
                                command=a.restyle)
        v.add_cascade(label="Brightness", menu=brm)

        flm = tk.Menu(v, tearoff=0)
        for label, val in (("None", "none"), ("Sepia", "sepia"), ("Night (warm)", "night")):
            flm.add_radiobutton(label=label, variable=a.filter, value=val, command=a.restyle)
        v.add_cascade(label="Colour Filter", menu=flm)

        thm = tk.Menu(v, tearoff=0)
        for label, val in (("Dark", "dark"), ("Light", "light"), ("High contrast", "contrast")):
            thm.add_radiobutton(label=label, variable=a.theme, value=val, command=a.apply_theme)
        v.add_cascade(label="Theme", menu=thm)

        scm = tk.Menu(v, tearoff=0)
        for pct in (100, 125, 150, 175, 200):
            scm.add_radiobutton(label=f"{pct}%", variable=a.ui_scale, value=pct / 100,
                                command=a.apply_scale)
        v.add_cascade(label="UI Scale", menu=scm)

        whm = tk.Menu(v, tearoff=0)
        for label, val in (("Scroll", "scroll"), ("Flip pages", "flip"), ("Zoom", "zoom")):
            whm.add_radiobutton(label=label, variable=a.wheel, value=val)
        v.add_cascade(label="Mouse Wheel", menu=whm)

        dbm = tk.Menu(v, tearoff=0)
        for label, val in (("Toggle fullscreen", "fullscreen"), ("Toggle fit width/page", "fit")):
            dbm.add_radiobutton(label=label, variable=a.dbl_action, value=val)
        v.add_cascade(label="Double-click Centre", menu=dbm)

        v.add_checkbutton(label="Auto-hide Progress Bar", variable=a.autohide,
                          command=a.apply_bar_mode)
        v.add_separator()
        self._cmd(v, "fullscreen")
        return v

    # ---- Go ---------------------------------------------------------------------------- #
    def _go_menu(self, bar):
        a = self.app
        g = tk.Menu(bar, tearoff=0)
        for action in ("next_page", "prev_page", "first_page", "last_page", "goto"):
            self._cmd(g, action)
        g.add_separator()
        self._cmd(g, "next_comic")
        self._cmd(g, "prev_comic")
        g.add_separator()
        self._cmd(g, "bookmark")
        self._cmd(g, "favorite")
        bm = tk.Menu(g, tearoff=0, postcommand=lambda: self._fill_bookmarks(bm))
        g.add_cascade(label="Bookmarks", menu=bm)
        return g

    def _fill_bookmarks(self, menu: tk.Menu):
        a = self.app
        menu.delete(0, "end")
        marks = a.store.bookmarks(a.session.key) if a.session.is_open else []
        if not marks:
            menu.add_command(label="(none)", state="disabled")
        for p in marks:
            menu.add_command(label=f"Page {p + 1}", command=lambda p=p: a.show_page(p))
