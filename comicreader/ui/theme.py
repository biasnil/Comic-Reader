"""Colour themes and UI scaling."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from ..constants import CANVAS_BGS, THEMES


class ThemeManager:
    """Restyles the ttk widgets of one window and scales its fonts."""

    FONT_NAMES = ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont")

    def __init__(self, root):
        self.root = root
        self.name = "dark"
        self.colors: dict = THEMES["dark"]
        self._base_fonts: dict[str, int] = {}
        for name in self.FONT_NAMES:  # remember the OS sizes so scaling is never cumulative
            try:
                self._base_fonts[name] = abs(tkfont.nametofont(name).cget("size")) or 9
            except tk.TclError:
                pass

    def apply(self, name: str) -> dict:
        self.name = name
        t = self.colors = THEMES[name]
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=t["panel"], foreground=t["fg"], fieldbackground=t["bg"],
                     bordercolor=t["muted"], lightcolor=t["panel"], darkcolor=t["panel"])
        st.configure("TFrame", background=t["panel"])
        st.configure("TLabel", background=t["panel"], foreground=t["fg"])
        st.configure("TButton", background=t["bg"], foreground=t["fg"])
        st.map("TButton", background=[("active", t["select"])])
        st.configure("TRadiobutton", background=t["panel"], foreground=t["fg"])
        st.configure("TEntry", fieldbackground=t["bg"], foreground=t["fg"], insertcolor=t["fg"])
        st.configure("TCombobox", fieldbackground=t["bg"], foreground=t["fg"],
                     background=t["bg"], arrowcolor=t["fg"])
        st.map("TCombobox", fieldbackground=[("readonly", t["bg"])],
               foreground=[("readonly", t["fg"])])
        st.configure("Treeview", background=t["bg"], fieldbackground=t["bg"], foreground=t["fg"])
        st.map("Treeview", background=[("selected", t["select"])],
               foreground=[("selected", t["fg"])])
        st.configure("Treeview.Heading", background=t["panel"], foreground=t["fg"])
        st.configure("Horizontal.TScale", background=t["panel"], troughcolor=t["bg"])
        st.configure("TScrollbar", background=t["panel"], troughcolor=t["bg"], arrowcolor=t["fg"])
        self.root.configure(bg=t["panel"])
        return t

    def set_scale(self, factor: float):
        for name, size in self._base_fonts.items():
            try:
                tkfont.nametofont(name).configure(size=max(6, round(size * factor)))
            except tk.TclError:
                pass
        ttk.Style(self.root).configure("Treeview", rowheight=max(18, round(22 * factor)))

    def canvas_bg(self, bg_name: str) -> str:
        """Reading-area colour: the user's choice, except in high-contrast mode."""
        if self.name == "contrast":
            return "#000000"
        return CANVAS_BGS.get(bg_name, "#1e1e1e")
