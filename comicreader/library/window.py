"""The library window: grid of covers or a list, with search, sort and filters."""
import math
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from ..constants import RESAMPLE, THUMB_DIR
from ..utils.helpers import natural_key, reveal_in_folder


class LibraryWindow(tk.Toplevel):
    SORTS = ("Name", "Series", "Date added", "Last read")
    FILTERS = ("All", "Favorites", "Unread", "In progress", "Finished")

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.manager = app.library
        self.store = app.store
        self.title("Library")
        self.geometry("1050x720")
        st = self.store.settings
        self.view = tk.StringVar(value=st.get("lib_view", "grid"))
        self.sort = tk.StringVar(value=st.get("lib_sort", "Name"))
        self.filter = tk.StringVar(value="All")
        self.query = tk.StringVar()
        self.rows: list[str] = []
        self.selected: str | None = None
        self.cols = 1
        self._grid_off = 0
        self._thumbs: dict[str, ImageTk.PhotoImage] = {}
        self._draw_job = None
        self._search_job = None
        self.cell = (180, 300)

        self._build()
        self.apply_theme()
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())

    @property
    def items(self) -> dict:
        return self.manager.db.items

    # ---- construction ----------------------------------------------------------------- #
    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x", padx=6, pady=6)
        ttk.Button(bar, text="Add Folder…", command=self.manager.add_folder).pack(side="left")
        ttk.Button(bar, text="Add Files…", command=self.manager.add_files).pack(side="left", padx=4)
        ttk.Button(bar, text="Rescan", command=self.manager.rescan).pack(side="left")
        ttk.Label(bar, text="  Search:").pack(side="left")
        ttk.Entry(bar, textvariable=self.query, width=22).pack(side="left")
        self.query.trace_add("write", lambda *a: self._debounced_refresh())
        ttk.Label(bar, text="  Sort:").pack(side="left")
        cb = ttk.Combobox(bar, textvariable=self.sort, values=self.SORTS, width=11, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(bar, text="  Show:").pack(side="left")
        cf = ttk.Combobox(bar, textvariable=self.filter, values=self.FILTERS, width=11,
                          state="readonly")
        cf.pack(side="left")
        cf.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Radiobutton(bar, text="Grid", variable=self.view, value="grid",
                        command=self._on_view).pack(side="left", padx=(12, 0))
        ttk.Radiobutton(bar, text="List", variable=self.view, value="list",
                        command=self._on_view).pack(side="left")
        self.count_lbl = ttk.Label(bar, text="")
        self.count_lbl.pack(side="right")

        self.status_lbl = ttk.Label(self, text="", anchor="w")
        self.status_lbl.pack(side="bottom", fill="x", padx=8, pady=2)

        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)

        # grid view: one canvas, only the visible rows are drawn
        self.gframe = ttk.Frame(self.body)
        self.gcanvas = tk.Canvas(self.gframe, highlightthickness=0, yscrollincrement=40)
        self.gsb = ttk.Scrollbar(self.gframe, orient="vertical", command=self.gcanvas.yview)
        self.gcanvas.configure(yscrollcommand=self._on_grid_scroll)
        self.gsb.pack(side="right", fill="y")
        self.gcanvas.pack(side="left", fill="both", expand=True)
        c = self.gcanvas
        c.bind("<Configure>", lambda e: self._schedule_draw())
        c.bind("<Button-1>", self._on_grid_click)
        c.bind("<Double-Button-1>", self._on_grid_double)
        c.bind("<Button-3>", self._on_grid_right)
        c.bind("<MouseWheel>", self._on_grid_wheel)
        c.bind("<Button-4>", self._on_grid_wheel)
        c.bind("<Button-5>", self._on_grid_wheel)

        # list view
        self.lframe = ttk.Frame(self.body)
        cols = ("title", "series", "number", "writer", "pages", "progress", "lastread")
        self.tree = ttk.Treeview(self.lframe, columns=cols, show="headings", selectmode="browse")
        for col, text, w in (("title", "Title", 300), ("series", "Series", 160),
                             ("number", "#", 50), ("writer", "Author", 140),
                             ("pages", "Pages", 60), ("progress", "Progress", 80),
                             ("lastread", "Last read", 100)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor="w")
        lsb = ttk.Scrollbar(self.lframe, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_tree_double)
        self.tree.bind("<Button-3>", self._on_tree_right)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Open", command=self.open_selected)
        self.menu.add_command(label="Toggle favorite", command=self.toggle_favorite)
        self.menu.add_command(label="Show in folder", command=self.reveal)
        self.menu.add_separator()
        self.menu.add_command(label="Remove from library", command=self.remove_selected)
        self._show_view()

    def apply_theme(self):
        t, s = self.app.colors, self.app.ui_scale.get()
        self.configure(bg=t["panel"])
        self.gcanvas.configure(bg=t["bg"])
        self.cell = (int(180 * s), int(300 * s))
        self._thumbs.clear()
        self._schedule_draw()

    def set_status(self, text: str):
        self.status_lbl.config(text=text)

    def close(self):
        self.store.settings["lib_view"] = self.view.get()
        self.store.settings["lib_sort"] = self.sort.get()
        self.manager.window = None
        self.destroy()

    # ---- data ------------------------------------------------------------------------------ #
    def _debounced_refresh(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(250, self.refresh)

    def _on_view(self):
        self._show_view()
        self._schedule_draw()

    def _matches(self, key: str, it: dict, q: str, flt: str) -> bool:
        hay = " ".join((it.get("title", ""), it.get("series", ""), it.get("writer", ""),
                        Path(key).name)).lower()
        if q and q not in hay:
            return False
        pg, pages = self.store.progress(key), it.get("pages", 0)
        if flt == "Favorites":
            return self.store.is_favorite(key)
        if flt == "Unread":
            return pg is None
        if flt == "In progress":
            return pg is not None and pg + 1 < pages
        if flt == "Finished":
            return pg is not None and pg + 1 >= pages
        return True

    def refresh(self):
        items = self.items
        q, flt = self.query.get().strip().lower(), self.filter.get()
        rows = [k for k, it in items.items() if self._matches(k, it, q, flt)]
        s = self.sort.get()
        if s == "Series":
            rows.sort(key=lambda k: (items[k].get("series", "").lower() or "\uffff",
                                     natural_key(items[k].get("number", "") or "0"),
                                     natural_key(items[k].get("title", ""))))
        elif s == "Date added":
            rows.sort(key=lambda k: -items[k].get("added", 0))
        elif s == "Last read":
            rows.sort(key=lambda k: -(self.store.last_read_time(k) or 0))
        else:
            rows.sort(key=lambda k: natural_key(items[k].get("title") or Path(k).stem))
        self.rows = rows
        if self.selected not in items:
            self.selected = None
        self.count_lbl.config(text=f"{len(rows)} / {len(items)} comics")
        self._schedule_draw()

    def _progress(self, key: str) -> float:
        pg, pages = self.store.progress(key), self.items[key].get("pages", 0)
        return 0.0 if pg is None or not pages else min(1.0, (pg + 1) / pages)

    # ---- drawing ------------------------------------------------------------------------------ #
    def _show_view(self):
        self.gframe.pack_forget()
        self.lframe.pack_forget()
        (self.gframe if self.view.get() == "grid" else self.lframe).pack(fill="both", expand=True)

    def _schedule_draw(self):
        if self._draw_job is None:
            self._draw_job = self.after_idle(self._draw)

    def _draw(self):
        self._draw_job = None
        if self.view.get() == "grid":
            self._draw_grid()
        else:
            self._fill_tree()

    def _thumb(self, key: str, it: dict):
        if key in self._thumbs:
            return self._thumbs[key]
        photo = None
        if it.get("thumb"):
            try:
                s = self.app.ui_scale.get()
                img = Image.open(THUMB_DIR / it["thumb"])
                img.thumbnail((int(150 * s), int(220 * s)), RESAMPLE)
                photo = ImageTk.PhotoImage(img)
            except Exception:
                photo = None
        if len(self._thumbs) > 400:
            self._thumbs.clear()
        self._thumbs[key] = photo
        return photo

    def _draw_grid(self):
        c, t = self.gcanvas, self.app.colors
        c.delete("all")
        W, H = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        cw, chh = self.cell
        self.cols = cols = max(1, W // cw)
        self._grid_off = (W - cols * cw) // 2
        n = len(self.rows)
        nrows = math.ceil(n / cols) if n else 0
        c.configure(scrollregion=(0, 0, W, max(nrows * chh, H)))
        if not n:
            c.create_text(W // 2, H // 2, fill=t["muted"], font=tkfont.nametofont("TkDefaultFont"),
                          text="Library is empty. Use Add Folder… to scan your comics.")
            return
        top = c.canvasy(0)
        r0, r1 = max(0, int(top // chh)), min(nrows - 1, int((top + H) // chh))
        for r in range(r0, r1 + 1):
            for col in range(cols):
                i = r * cols + col
                if i >= n:
                    break
                self._draw_cell(i, self._grid_off + col * cw, r * chh)

    def _draw_cell(self, i: int, x: int, y: int):
        c, t = self.gcanvas, self.app.colors
        key = self.rows[i]
        it = self.items[key]
        cw, chh = self.cell
        s = self.app.ui_scale.get()
        font = tkfont.nametofont("TkDefaultFont")
        if key == self.selected:
            c.create_rectangle(x + 4, y + 4, x + cw - 4, y + chh - 4, fill=t["select"], outline="")
        th = int(220 * s)
        photo = self._thumb(key, it)
        if photo:
            c.create_image(x + cw // 2, y + 10, image=photo, anchor="n")
        else:
            c.create_rectangle(x + cw // 2 - 50 * s, y + 10, x + cw // 2 + 50 * s, y + 10 + th,
                               outline=t["muted"])
        title = it.get("title") or Path(key).stem
        c.create_text(x + cw // 2, y + 16 + th, text=title[:70], width=cw - 16, anchor="n",
                      justify="center", fill=t["fg"], font=font)
        star = "★ " if self.store.is_favorite(key) else ""
        c.create_text(x + cw // 2, y + chh - 30, anchor="n", fill=t["muted"], font=font,
                      text=f"{star}{it.get('pages', 0)} pages")
        prog = self._progress(key)
        bx0, bx1, by = x + 14, x + cw - 14, y + chh - 12
        c.create_rectangle(bx0, by, bx1, by + 5, fill=t["panel"], outline="")
        if prog:
            c.create_rectangle(bx0, by, bx0 + (bx1 - bx0) * prog, by + 5, fill=t["accent"], outline="")

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        for key in self.rows:
            it = self.items[key]
            last = self.store.last_read_time(key)
            lr = time.strftime("%Y-%m-%d", time.localtime(last)) if last else ""
            prog = self._progress(key)
            star = "★ " if self.store.is_favorite(key) else ""
            self.tree.insert("", "end", iid=key, values=(
                star + (it.get("title") or Path(key).stem), it.get("series", ""),
                it.get("number", ""), it.get("writer", ""), it.get("pages", 0),
                f"{prog * 100:.0f}%" if prog else "", lr))
        if self.selected and self.tree.exists(self.selected):
            self.tree.selection_set(self.selected)

    # ---- grid interaction ---------------------------------------------------------------------- #
    def _on_grid_scroll(self, first, last):
        self.gsb.set(first, last)
        self._schedule_draw()

    def _on_grid_wheel(self, event):
        num = getattr(event, "num", 0)
        delta = 1 if num == 4 else -1 if num == 5 else (1 if event.delta > 0 else -1)
        self.gcanvas.yview_scroll(-delta * 4, "units")

    def _key_at(self, event):
        c = self.gcanvas
        col = int((c.canvasx(event.x) - self._grid_off) // self.cell[0])
        row = int(c.canvasy(event.y) // self.cell[1])
        i = row * self.cols + col
        if 0 <= col < self.cols and 0 <= i < len(self.rows):
            return self.rows[i]
        return None

    def _on_grid_click(self, event):
        self.selected = self._key_at(event)
        self._schedule_draw()

    def _on_grid_double(self, event):
        self.selected = self._key_at(event)
        self.open_selected()

    def _on_grid_right(self, event):
        self.selected = self._key_at(event)
        self._schedule_draw()
        if self.selected:
            self.menu.tk_popup(event.x_root, event.y_root)

    # ---- list interaction ------------------------------------------------------------------------ #
    def _on_tree_select(self, event):
        sel = self.tree.selection()
        self.selected = sel[0] if sel else None

    def _on_tree_double(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.selected = row
            self.open_selected()

    def _on_tree_right(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.selected = row
            self.menu.tk_popup(event.x_root, event.y_root)

    # ---- actions ---------------------------------------------------------------------------------- #
    def open_selected(self):
        key = self.selected
        if not key:
            return
        if not Path(key).exists():
            messagebox.showerror("Library", f"File not found:\n{key}", parent=self)
            return
        app = self.app
        self.close()
        app.open_path(Path(key))

    def toggle_favorite(self):
        if self.selected:
            self.store.toggle_favorite(self.selected)
            self.refresh()

    def reveal(self):
        if self.selected:
            reveal_in_folder(self.selected)

    def remove_selected(self):
        if self.selected and self.selected in self.items:
            self.manager.db.remove(self.selected)
            self.manager.db.save()
            self.selected = None
            self.refresh()
