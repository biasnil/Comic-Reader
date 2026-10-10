"""BubbleEditor: fix a translated page's bubbles by hand.

Lists each bubble's Japanese and English (from the page's saved JSON); change the English or pin
a font size, then Apply: the worker redraws the page on its saved text-free image (no models
run), and the reader shows the result. Translate > Edit Translations (Ctrl+E) opens it.
"""
import tkinter as tk
from tkinter import ttk

from .dialogs import _Dialog


class BubbleEditor(_Dialog):
    def __init__(self, app, controller, pages: list[int]):
        super().__init__(app, "Edit Translations")
        self.resizable(True, True)
        self.geometry("720x560")
        self.ctl = controller
        self.page = tk.IntVar(value=pages[0])
        self.blocks: list[dict] = []
        self._sel: int | None = None
        b = self.body

        top = ttk.Frame(b)
        top.pack(fill="x")
        ttk.Label(top, text="Page:").pack(side="left")
        pick = ttk.Combobox(top, state="readonly", width=8, values=[p + 1 for p in pages])
        pick.set(pages[0] + 1)
        pick.pack(side="left", padx=6)
        pick.bind("<<ComboboxSelected>>", lambda e: self.load(int(pick.get()) - 1))
        ttk.Label(top, text="Pick a bubble, change its English, then Apply.",
                  foreground="#888888").pack(side="left", padx=8)

        self.tree = ttk.Treeview(b, columns=("n", "ja", "en"), show="headings", height=9,
                                 selectmode="browse")
        for col, text, width in (("n", "#", 40), ("ja", "Japanese", 260), ("en", "English", 380)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=col != "n")
        self.tree.pack(fill="both", expand=True, pady=8)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._select())

        ttk.Label(b, text="English:").pack(anchor="w")
        self.text = tk.Text(b, height=4, wrap="word", undo=True)
        self.text.pack(fill="x")
        row = ttk.Frame(b)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Font size (0 = fit automatically):").pack(side="left")
        self.size = tk.IntVar(value=0)
        ttk.Spinbox(row, from_=0, to=120, width=5, textvariable=self.size).pack(side="left", padx=6)

        btns = ttk.Frame(b)
        btns.pack(fill="x")
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Apply", command=self.apply).pack(side="right", padx=6)
        self.bind("<Control-Return>", lambda e: self.apply())
        self.load(pages[0])

    # ---- data ---- #
    def load(self, page: int):
        self.page.set(page)
        data = self.ctl.cache.load_blocks(page) or {}
        self.blocks = [dict(d) for d in data.get("blocks", [])]
        self._sel = None
        self.tree.delete(*self.tree.get_children())
        for i, d in enumerate(self.blocks):
            self.tree.insert("", "end", iid=str(i), values=(i + 1, d.get("source", ""),
                                                            d.get("translation", "")))
        self.text.delete("1.0", "end")
        if self.blocks:
            self.tree.selection_set("0")

    def _store(self):
        """Keep what's in the text box / size field for the bubble being edited."""
        if self._sel is None:
            return
        d = self.blocks[self._sel]
        d["translation"] = self.text.get("1.0", "end").strip()
        try:
            d["fixed_size"] = max(0, int(self.size.get()))
        except (tk.TclError, ValueError):
            d["fixed_size"] = 0
        self.tree.item(str(self._sel), values=(self._sel + 1, d.get("source", ""), d["translation"]))

    def _select(self):
        self._store()
        sel = self.tree.selection()
        if not sel:
            return
        self._sel = int(sel[0])
        d = self.blocks[self._sel]
        self.text.delete("1.0", "end")
        self.text.insert("1.0", d.get("translation", ""))
        self.size.set(d.get("fixed_size", 0))
        self.text.focus_set()

    def apply(self):
        self._store()
        edits = [{"translation": d.get("translation", ""), "fixed_size": d.get("fixed_size", 0)}
                 for d in self.blocks]
        self.ctl.retypeset(self.page.get(), edits)
        self.app.flash(f"Redrawing page {self.page.get() + 1}…")
