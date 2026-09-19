"""The library: the app's home screen (a page of the main window, not a separate window).

The folders you added show up as tiles. Open a tile to see its sub-folders and comics, keep
going deeper, and open a comic to read it. A search or a filter other than "All" switches to a
flat list of matching comics below the folder you are in.
"""
import math
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from ..constants import RESAMPLE, THUMB_DIR
from ..utils.helpers import folder_title, natural_key, reveal_in_folder


class LibraryView(ttk.Frame):
    SORTS = ("Name", "Series", "Date added", "Last read")
    FILTERS = ("All", "Favorites", "Unread", "In progress", "Finished")

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.manager = app.library
        self.store = app.store
        st = self.store.settings
        self.view = tk.StringVar(value=st.get("lib_view", "grid"))
        self.sort = tk.StringVar(value=st.get("lib_sort", "Name"))
        self.filter = tk.StringVar(value="All")
        self.query = tk.StringVar()
        # where we are: None = top level (the root folders), else a folder path
        self.current: str | None = st.get("lib_folder") or None
        if self.current and not self.manager.db.has_folder(self.current):
            self.current = None
        # what is shown at this level: dicts with kind ("root" | "folder" | "comic"), key, title,
        # thumb, and keys (the comics inside a folder, or just the comic itself)
        self.rows: list[dict] = []
        self._by_key: dict[str, dict] = {}
        self.selected: str | None = None
        self.cols = 1
        self._grid_off = 0
        self._thumbs: dict[str, ImageTk.PhotoImage] = {}
        self._draw_job = None
        self._search_job = None
        self._region = None      # last scrollregion / scroll position, so redraws don't feed on themselves
        self._scroll = None
        self.cell = (180, 300)

        self._build()
        self.apply_theme()
        self.refresh()
        # Alt+Left = up a level (only while the library is on screen)
        app.bind("<Alt-Left>", lambda e: self.go_up() if app.in_library else None, add="+")

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

        nav = ttk.Frame(self)
        nav.pack(side="top", fill="x", padx=6, pady=(0, 4))
        self.count_lbl = ttk.Label(nav, text="")
        self.count_lbl.pack(side="right", padx=(8, 0))
        self.up_btn = ttk.Button(nav, text="◀ Up", width=7, command=self.go_up)
        self.up_btn.pack(side="left")
        ttk.Button(nav, text="Home", command=lambda: self.go(None)).pack(side="left", padx=4)
        # shown only while a comic is open: jump back into it
        self.back_btn = ttk.Button(nav, text="", command=self.app.show_reader)
        self.crumb = ttk.Label(nav, text="", anchor="w")
        self.crumb.pack(side="left", fill="x", expand=True, padx=8)

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
        c.bind("<BackSpace>", lambda e: self.go_up())
        c.bind("<Return>", lambda e: self.open_selected())

        # list view
        self.lframe = ttk.Frame(self.body)
        cols = ("title", "series", "number", "writer", "pages", "progress", "lastread")
        self.tree = ttk.Treeview(self.lframe, columns=cols, show="headings", selectmode="browse")
        for col, text, w in (("title", "Title", 300), ("series", "Series", 160),
                             ("number", "#", 50), ("writer", "Author", 140),
                             ("pages", "Pages", 80), ("progress", "Progress", 80),
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
        self.tree.bind("<BackSpace>", lambda e: self.go_up())
        self.tree.bind("<Return>", lambda e: self.open_selected())
        self._show_view()

    def apply_theme(self):
        t, s = self.app.colors, self.app.ui_scale.get()
        self.gcanvas.configure(bg=t["bg"])
        self.cell = (int(180 * s), int(300 * s))
        self._thumbs.clear()
        self._schedule_draw()

    def set_status(self, text: str):
        self.status_lbl.config(text=text)

    def save_state(self):
        """Remember view, sort and the folder we are in (written with the other settings)."""
        st = self.store.settings
        st["lib_view"] = self.view.get()
        st["lib_sort"] = self.sort.get()
        st["lib_folder"] = self.current or ""

    def on_show(self):
        """The library just came on screen: progress and last-read may have changed."""
        self.refresh()
        self.gcanvas.focus_set()

    def _update_back_button(self):
        s = self.app.session
        if s.is_open:
            name = s.title if len(s.title) <= 32 else s.title[:31] + "…"
            self.back_btn.config(text=f"Continue: {name}  ▶")
            self.back_btn.pack(side="right")
        else:
            self.back_btn.pack_forget()

    # ---- navigation ----------------------------------------------------------------------- #
    def go(self, folder: str | None):
        """Show the contents of `folder` (None = the top level)."""
        self.current = folder
        self.selected = None
        self.gcanvas.yview_moveto(0)
        self.refresh()

    def go_up(self):
        cur = self.current
        if cur is None:
            return
        if cur in self.manager.db.folders:
            self.go(None)
        else:
            self.go(str(Path(cur).parent))

    def _trail(self) -> str:
        """'Library  ›  DC - Absolute Series  ›  Absolute Green Arrow'"""
        parts = ["Library"]
        cur = self.current
        if cur:
            here = Path(cur)
            roots = [r for r in self.manager.db.folders if here == Path(r) or Path(r) in here.parents]
            if roots:
                root = max(roots, key=len)
                parts.append(folder_title(root))
                parts.extend(here.relative_to(Path(root)).parts)
            else:
                parts.append(here.name)
        return "  ›  ".join(parts)

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

    def _sorted(self, keys: list[str]) -> list[str]:
        items, s = self.items, self.sort.get()
        if s == "Series":
            keys.sort(key=lambda k: (items[k].get("series", "").lower() or "\uffff",
                                     natural_key(items[k].get("number", "") or "0"),
                                     natural_key(items[k].get("title", ""))))
        elif s == "Date added":
            keys.sort(key=lambda k: -items[k].get("added", 0))
        elif s == "Last read":
            keys.sort(key=lambda k: -(self.store.last_read_time(k) or 0))
        else:
            keys.sort(key=lambda k: natural_key(items[k].get("title") or Path(k).stem))
        return keys

    def _comic_row(self, key: str) -> dict:
        return {"kind": "comic", "key": key, "thumb": self.items[key].get("thumb"),
                "title": self.items[key].get("title") or Path(key).stem, "keys": [key]}

    def _folder_row(self, kind: str, path: str, title: str, keys: list[str]) -> dict:
        # a folder's cover is the cover of the first comic inside it
        thumb = self.items[min(keys, key=natural_key)].get("thumb") if keys else None
        return {"kind": kind, "key": path, "title": title, "thumb": thumb, "keys": keys}

    def refresh(self, covers: bool = False):
        """Rebuild what is shown at the current level. covers=True also reloads cover images."""
        if covers:
            self._thumbs.clear()
        db, items = self.manager.db, self.items
        if self.current and not db.has_folder(self.current):
            self.current = None
        q, flt = self.query.get().strip().lower(), self.filter.get()
        if q or flt != "All":  # searching/filtering: flat list of matching comics below here
            keys = [k for k in db.keys_under(self.current) if self._matches(k, items[k], q, flt)]
            rows = [self._comic_row(k) for k in self._sorted(keys)]
            summary = f"{len(rows)} comics"
        else:
            subs, comics = db.browse(self.current)
            kind = "root" if self.current is None else "folder"
            rows = [self._folder_row(kind, p, t, ks) for p, t, ks in subs]
            rows += [self._comic_row(k) for k in self._sorted(comics)]
            summary = f"{len(subs)} folders, {len(comics)} comics"
        self.rows = rows
        self._by_key = {r["key"]: r for r in rows}
        if self.selected not in self._by_key:
            self.selected = None
        self.count_lbl.config(text=summary)
        self.crumb.config(text=self._trail())
        self.up_btn.state(["disabled"] if self.current is None else ["!disabled"])
        self._update_back_button()
        self._schedule_draw()

    def _progress(self, key: str) -> float:
        pg, pages = self.store.progress(key), self.items[key].get("pages", 0)
        return 0.0 if pg is None or not pages else min(1.0, (pg + 1) / pages)

    def _row_progress(self, row: dict) -> float:
        """A comic's own progress, or the average over the comics inside a folder."""
        keys = row["keys"]
        return sum(self._progress(k) for k in keys) / len(keys) if keys else 0.0

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

    def _thumb(self, name: str | None):
        """A cover from AppData, scaled for the current UI scale (None if it isn't there)."""
        if not name:
            return None
        if name in self._thumbs:
            return self._thumbs[name]
        try:
            s = self.app.ui_scale.get()
            img = Image.open(THUMB_DIR / name)
            img.thumbnail((int(150 * s), int(220 * s)), RESAMPLE)
            photo = ImageTk.PhotoImage(img)
        except Exception:
            return None  # not cached, so a rebuilt cover shows up on the next draw
        if len(self._thumbs) > 400:
            self._thumbs.clear()
        self._thumbs[name] = photo
        return photo

    def _empty_text(self) -> str:
        if not self.manager.db.folders and not self.items:
            return "Library is empty. Use Add Folder… and pick a folder with your comics."
        if self.query.get().strip() or self.filter.get() != "All":
            return "No comics match."
        return "Nothing here."

    def _draw_grid(self):
        c, t = self.gcanvas, self.app.colors
        c.delete("all")
        W, H = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        cw, chh = self.cell
        self.cols = cols = max(1, W // cw)
        self._grid_off = (W - cols * cw) // 2
        n = len(self.rows)
        nrows = math.ceil(n / cols) if n else 0
        region = (0, 0, W, max(nrows * chh, H))
        if region != self._region:  # configuring it fires the scroll callback, which redraws
            self._region = region
            c.configure(scrollregion=region)
        if not n:
            c.create_text(W // 2, H // 2, fill=t["muted"], font=tkfont.nametofont("TkDefaultFont"),
                          text=self._empty_text())
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
        row = self.rows[i]
        folder = row["kind"] != "comic"
        cw, chh = self.cell
        s = self.app.ui_scale.get()
        font = tkfont.nametofont("TkDefaultFont")
        cx = x + cw // 2
        if row["key"] == self.selected:
            c.create_rectangle(x + 4, y + 4, x + cw - 4, y + chh - 4, fill=t["select"], outline="")
        th = int(220 * s)
        photo = self._thumb(row["thumb"])
        if photo:
            w, h = photo.width(), photo.height()
            if folder:  # a stack of pages peeking out behind the cover marks a folder
                for d in (10, 5):
                    c.create_rectangle(cx - w // 2 + d, y + 10 - d // 2, cx + w // 2 + d,
                                       y + 10 + h - d // 2, fill=t["panel"], outline=t["muted"])
            c.create_image(cx, y + 10, image=photo, anchor="n")
        else:
            c.create_rectangle(cx - 50 * s, y + 10, cx + 50 * s, y + 10 + th, outline=t["muted"])
        c.create_text(cx, y + 16 + th, text=row["title"][:70], width=cw - 16, anchor="n",
                      justify="center", fill=t["fg"], font=font)
        if folder:
            n = len(row["keys"])
            info = f"▸ {n} comic{'s' if n != 1 else ''}"
        else:
            star = "★ " if self.store.is_favorite(row["key"]) else ""
            info = f"{star}{self.items[row['key']].get('pages', 0)} pages"
        c.create_text(cx, y + chh - 30, anchor="n", fill=t["muted"], font=font, text=info)
        prog = self._row_progress(row)
        bx0, bx1, by = x + 14, x + cw - 14, y + chh - 12
        c.create_rectangle(bx0, by, bx1, by + 5, fill=t["panel"], outline="")
        if prog:
            c.create_rectangle(bx0, by, bx0 + (bx1 - bx0) * prog, by + 5, fill=t["accent"], outline="")

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        for row in self.rows:
            key, prog = row["key"], self._row_progress(row)
            pct = f"{prog * 100:.0f}%" if prog else ""
            if row["kind"] == "comic":
                it = self.items[key]
                last = self.store.last_read_time(key)
                lr = time.strftime("%Y-%m-%d", time.localtime(last)) if last else ""
                star = "★ " if self.store.is_favorite(key) else ""
                values = (star + row["title"], it.get("series", ""), it.get("number", ""),
                          it.get("writer", ""), it.get("pages", 0), pct, lr)
            else:
                values = ("▸ " + row["title"], "", "", "", f"{len(row['keys'])} comics", pct, "")
            self.tree.insert("", "end", iid=key, values=values)
        if self.selected and self.tree.exists(self.selected):
            self.tree.selection_set(self.selected)

    # ---- grid interaction ---------------------------------------------------------------------- #
    def _on_grid_scroll(self, first, last):
        self.gsb.set(first, last)
        if (first, last) != self._scroll:  # only a real scroll needs a redraw
            self._scroll = (first, last)
            self._schedule_draw()

    def _on_grid_wheel(self, event):
        num = getattr(event, "num", 0)
        delta = 1 if num == 4 else -1 if num == 5 else (1 if event.delta > 0 else -1)
        self.gcanvas.yview_scroll(-delta * 4, "units")

    def _row_at(self, event) -> dict | None:
        c = self.gcanvas
        col = int((c.canvasx(event.x) - self._grid_off) // self.cell[0])
        row = int(c.canvasy(event.y) // self.cell[1])
        i = row * self.cols + col
        if 0 <= col < self.cols and 0 <= i < len(self.rows):
            return self.rows[i]
        return None

    def _select(self, row: dict | None):
        self.selected = row["key"] if row else None

    def _on_grid_click(self, event):
        self.gcanvas.focus_set()
        self._select(self._row_at(event))
        self._schedule_draw()

    def _on_grid_double(self, event):
        self._select(self._row_at(event))
        self.open_selected()

    def _on_grid_right(self, event):
        self.gcanvas.focus_set()
        row = self._row_at(event)
        self._select(row)
        self._schedule_draw()
        if row:
            self._popup(row, event.x_root, event.y_root)

    # ---- list interaction ------------------------------------------------------------------------ #
    def _on_tree_select(self, event):
        sel = self.tree.selection()
        self.selected = sel[0] if sel else None

    def _on_tree_double(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.selected = iid
            self.open_selected()

    def _on_tree_right(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.selected = iid
            self._popup(self._by_key[iid], event.x_root, event.y_root)

    def _popup(self, row: dict, x: int, y: int):
        m = tk.Menu(self, tearoff=0)
        if row["kind"] == "comic":
            m.add_command(label="Open", command=self.open_selected)
            m.add_command(label="Toggle favorite", command=self.toggle_favorite)
            m.add_command(label="Show in folder", command=self.reveal)
            m.add_separator()
            m.add_command(label="Remove from library", command=self.remove_selected)
        else:
            m.add_command(label="Open folder", command=self.open_selected)
            m.add_command(label="Show in folder", command=self.reveal)
            if row["kind"] == "root":
                m.add_separator()
                m.add_command(label="Remove folder from library…",
                              command=lambda: self.manager.remove_folder(row["key"]))
        m.tk_popup(x, y)

    # ---- actions ---------------------------------------------------------------------------------- #
    def open_selected(self):
        row = self._by_key.get(self.selected) if self.selected else None
        if not row:
            return
        if row["kind"] != "comic":
            self.go(row["key"])
            return
        key = row["key"]
        if not Path(key).exists():
            messagebox.showerror("Library", f"File not found:\n{key}", parent=self)
            return
        # the comics on screen become the reading queue, so ] and [ move through them
        queue = [r["key"] for r in self.rows if r["kind"] == "comic"]
        self.save_state()
        # open_path switches to the reader once the comic has opened; if it fails we stay here
        self.app.open_path(Path(key), queue_items=[Path(k) for k in queue], qpos=queue.index(key))

    def toggle_favorite(self):
        row = self._by_key.get(self.selected) if self.selected else None
        if row and row["kind"] == "comic":
            self.store.toggle_favorite(row["key"])
            self.refresh()

    def reveal(self):
        if self.selected:
            reveal_in_folder(self.selected)

    def remove_selected(self):
        row = self._by_key.get(self.selected) if self.selected else None
        if row and row["kind"] == "comic":
            self.manager.db.remove(row["key"])
            self.manager.db.save()
            self.selected = None
            self.refresh()