"""Drag & drop support (needs the optional `tkinterdnd2` package).

`BaseTk` is the class the main window inherits from: tkinterdnd2's Tk when the package is
installed, plain tkinter.Tk otherwise. `HAS_DND` tells the UI which of the two it got.
"""
import tkinter as tk
from pathlib import Path

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    BaseTk = TkinterDnD.Tk
    HAS_DND = True
except Exception:
    DND_FILES = None
    BaseTk = tk.Tk
    HAS_DND = False


class DropTarget:
    """Makes widgets accept dropped files and shows a dashed 'Drop to open' outline meanwhile."""

    def __init__(self, canvas: tk.Canvas, widgets, accent, on_drop):
        """
        canvas  : the canvas the outline is drawn on
        widgets : widgets that should accept drops
        accent  : callable returning the outline colour
        on_drop : callable(list[Path]) invoked with the dropped paths
        """
        self.canvas = canvas
        self.widgets = list(widgets)
        self.accent = accent
        self.on_drop = on_drop

    def attach(self):
        if not HAS_DND:
            return
        try:
            for w in self.widgets:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<DropEnter>>", self._enter)
                w.dnd_bind("<<DropLeave>>", self._leave)
                w.dnd_bind("<<Drop>>", self._drop)
        except Exception:
            pass

    def _enter(self, event):
        c, color = self.canvas, self.accent()
        w, h = max(c.winfo_width(), 60), max(c.winfo_height(), 60)
        c.delete("dropzone")
        c.create_rectangle(10, 10, w - 10, h - 10, outline=color, width=5, dash=(10, 6),
                           tags="dropzone")
        c.create_text(w // 2, h // 2, text="Drop to open", fill=color,
                      font=("Segoe UI", 28, "bold"), tags="dropzone")
        c.tag_raise("dropzone")
        return event.action

    def _leave(self, event):
        self.canvas.delete("dropzone")
        return event.action

    def _drop(self, event):
        self.canvas.delete("dropzone")
        try:
            paths = [Path(p) for p in self.canvas.tk.splitlist(event.data)]
        except tk.TclError:
            paths = [Path(event.data)]
        self.on_drop(paths)
        return event.action
