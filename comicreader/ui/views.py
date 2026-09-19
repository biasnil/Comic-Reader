"""How pages get drawn on the canvas.

Two view classes share one small interface (BaseView):
  PagedView    - one page or a two-page spread at a time (single / double mode)
  WebtoonView  - every page stacked in one long vertical strip, loaded lazily

They talk to the main window through a `host`, which must provide:
  canvas, session, mode, fit, manga, zoom, rotation, page, span, view,
  get_image(i), style(img), canvas_bg(), on_view_page(page, span)
"""
import bisect

from PIL import Image, ImageTk

from ..constants import FAST, MAX_DIM, RESAMPLE, ROT


class BaseView:
    continuous = False  # True for views where scrolling itself changes the current page

    def __init__(self, host):
        self.host = host
        self.canvas = host.canvas
        self.last_size = (0, 0)  # canvas size at the last draw, used to ignore no-op <Configure>

    @property
    def active(self) -> bool:
        """True when this view currently has something on the canvas."""
        raise NotImplementedError

    def show(self, index: int, at: str = "top"):
        raise NotImplementedError

    def redraw(self, at: str | None = None):
        raise NotImplementedError

    def deactivate(self):
        raise NotImplementedError

    def on_scroll(self):
        """Called whenever the canvas scrolled."""


# --------------------------------------------------------------------------- #
class PagedView(BaseView):
    """Single page, or a double-page spread (right-to-left order for manga)."""

    def __init__(self, host):
        super().__init__(host)
        self.base: Image.Image | None = None  # the composed (and rotated) page(s), unscaled
        self.photo = None                      # keep a reference or Tk drops the image

    @property
    def active(self) -> bool:
        return self.base is not None

    # ---- spreads ---------------------------------------------------------------- #
    @staticmethod
    def _is_wide(img: Image.Image) -> bool:
        return img.width > img.height

    def span_at(self, index: int) -> int:
        """How many pages are shown starting at `index` (1 or 2)."""
        h = self.host
        if h.mode.get() != "double" or not h.session.is_open:
            return 1
        if index == 0 or index + 1 >= h.session.count:
            return 1  # cover / last odd page stays single
        if self._is_wide(h.get_image(index)) or self._is_wide(h.get_image(index + 1)):
            return 1  # spreads that are already wide stay single
        return 2

    def compose(self, index: int, span: int) -> Image.Image:
        h = self.host
        first = h.get_image(index)
        if span == 1:
            return first
        second = h.get_image(index + 1)
        pair = [second, first] if h.manga.get() else [first, second]
        height = max(im.height for im in pair)
        pair = [im if im.height == height
                else im.resize((round(im.width * height / im.height), height), RESAMPLE)
                for im in pair]
        out = Image.new("RGB", (sum(im.width for im in pair), height), h.canvas_bg())
        x = 0
        for im in pair:
            out.paste(im, (x, 0))
            x += im.width
        return out

    # ---- View interface ------------------------------------------------------------ #
    def show(self, index: int, at: str = "top"):
        h = self.host
        span = self.span_at(index)
        base = self.compose(index, span)
        if h.rotation:
            base = base.transpose(ROT[h.rotation])
        self.base = base
        self.redraw(at)
        h.on_view_page(index, span)
        self.canvas.after(30, self._prefetch)

    def redraw(self, at: str | None = None):
        if self.base is None:
            return
        h, c = self.host, self.canvas
        c.update_idletasks()
        cw, ch = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        iw, ih = self.base.size
        fit = h.fit.get()
        if fit == "width":
            scale = cw / iw
        elif fit == "height":
            scale = ch / ih
        elif fit == "page":
            scale = min(cw / iw, ch / ih)
        else:
            scale = 1.0
        scale = min(scale * h.zoom, MAX_DIM / max(iw, ih))
        nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))

        prev_top = c.yview()[0]
        img = self.base if (nw, nh) == (iw, ih) else self.base.resize((nw, nh), RESAMPLE)
        self.photo = ImageTk.PhotoImage(h.style(img))

        c.delete("all")
        c.create_image(max(0, (cw - nw) // 2), max(0, (ch - nh) // 2),
                       image=self.photo, anchor="nw")
        c.configure(scrollregion=(0, 0, max(cw, nw), max(ch, nh)))
        self.last_size = (c.winfo_width(), c.winfo_height())
        c.xview_moveto(0)
        if at == "bottom":
            c.yview_moveto(1.0)
        elif at == "top":
            c.yview_moveto(0)
        else:
            c.yview_moveto(prev_top)

    def deactivate(self):
        self.base = None
        self.photo = None

    def _prefetch(self):
        """Decode the next couple of pages in the background of the UI thread's idle time."""
        h = self.host
        if h.view is not self or not h.session.is_open:
            return
        nxt = h.page + h.span
        for i in (nxt, nxt + 1):
            if i < h.session.count and i not in h.cache:
                h.get_image(i)
                self.canvas.after(50, self._prefetch)
                return


# --------------------------------------------------------------------------- #
class WebtoonView(BaseView):
    """Continuous vertical scroll. Only pages near the viewport are loaded and drawn.

    Pages that haven't been decoded yet are laid out with an estimated height (the average
    of the known ones); as real sizes arrive the layout is corrected while keeping the page
    at the top of the screen where it was.
    """

    continuous = True

    def __init__(self, host):
        super().__init__(host)
        self._active = False
        self.sizes: dict[int, tuple[int, int]] = {}   # page -> real pixel size, once known
        self.offsets: list[float] = [0.0]              # y of each page top, plus the total
        self.items: dict[int, int] = {}                # page -> canvas item id
        self.photos: dict[int, ImageTk.PhotoImage] = {}
        self._job = None

    @property
    def active(self) -> bool:
        return self._active

    # ---- geometry ---------------------------------------------------------------- #
    def _disp_size(self, size, cw):
        h = self.host
        w, ht = size
        s = h.zoom if h.fit.get() == "original" else (cw * h.zoom) / w
        return max(1, round(w * s)), max(1, round(ht * s))

    def _recompute(self):
        c = self.canvas
        n = self.host.session.count
        cw = max(c.winfo_width(), 100)
        known = [self._disp_size(sz, cw)[1] for sz in self.sizes.values()]
        est = sum(known) / len(known) if known else cw * 1.5
        off, y, maxw = [0.0] * (n + 1), 0.0, cw
        for i in range(n):
            off[i] = y
            sz = self.sizes.get(i)
            if sz:
                w, h = self._disp_size(sz, cw)
                maxw = max(maxw, w)
                y += h
            else:
                y += est
        off[n] = y
        self.offsets = off
        c.configure(scrollregion=(0, 0, maxw, max(y, 1)))
        self.last_size = (c.winfo_width(), c.winfo_height())

    # ---- View interface -------------------------------------------------------------- #
    def deactivate(self):
        if not self._active:
            return
        self._active = False
        self.sizes, self.items, self.photos = {}, {}, {}
        self.canvas.delete("all")
        self.canvas.xview_moveto(0)

    def show(self, index: int, at: str = "top"):
        h, c = self.host, self.canvas
        if not self._active:
            self._active = True
            self.sizes, self.items, self.photos = {}, {}, {}
            c.delete("all")
        h.page, h.span = index, 1
        self._recompute()
        total = self.offsets[-1]
        c.yview_moveto(self.offsets[index] / total if total else 0)
        c.xview_moveto(0)
        self.update()
        h.on_view_page(h.page, 1)

    def redraw(self, at: str | None = None):
        """Zoom/size/filter changed: rebuild the geometry but keep the reading position."""
        if not (self._active and self.host.session.is_open):
            return
        c, off, n = self.canvas, self.offsets, self.host.session.count
        top = c.canvasy(0)
        a = min(n - 1, max(0, bisect.bisect_right(off, top) - 1))
        frac = (top - off[a]) / max(1.0, off[a + 1] - off[a])
        for item in self.items.values():
            c.delete(item)
        self.items.clear()
        self.photos.clear()
        self._recompute()
        newtop = self.offsets[a] + frac * (self.offsets[a + 1] - self.offsets[a])
        c.yview_moveto(newtop / max(1.0, self.offsets[-1]))
        self.update()

    def on_scroll(self):
        if self._active and self._job is None:
            self._job = self.canvas.after_idle(self.update)

    def update(self):
        """Load the pages near the viewport, draw them, drop far-away ones."""
        self._job = None
        h, c = self.host, self.canvas
        if not (self._active and h.session.is_open):
            return
        n = h.session.count
        cw, ch = max(c.winfo_width(), 100), max(c.winfo_height(), 100)

        for _ in range(3):  # loading real sizes shifts offsets; re-settle a few times
            off = self.offsets
            top = c.canvasy(0)
            anchor = min(n - 1, max(0, bisect.bisect_right(off, top) - 1))
            delta = top - off[anchor]
            lo = max(0, bisect.bisect_right(off, top - ch * 0.5) - 1)
            hi = min(n - 1, bisect.bisect_right(off, top + ch * 1.5) - 1)
            loaded = 0
            for i in range(lo, hi + 1):
                if i in self.sizes:
                    continue
                if loaded >= 3:
                    break
                self.sizes[i] = h.get_image(i).size
                loaded += 1
            if not loaded:
                break
            self._recompute()
            c.yview_moveto((self.offsets[anchor] + delta) / max(1.0, self.offsets[-1]))

        off = self.offsets
        top = c.canvasy(0)
        lo = max(0, bisect.bisect_right(off, top - ch * 0.5) - 1)
        hi = min(n - 1, bisect.bisect_right(off, top + ch * 1.5) - 1)
        for i in [k for k in self.items if k < lo - 1 or k > hi + 1]:
            c.delete(self.items.pop(i))
            self.photos.pop(i, None)
        for i in range(lo, hi + 1):
            if i in self.items or i not in self.sizes:
                continue
            raw = h.get_image(i)
            w, ht = self._disp_size(raw.size, cw)
            img = raw if raw.size == (w, ht) else raw.resize((w, ht), FAST)
            photo = ImageTk.PhotoImage(h.style(img))
            self.photos[i] = photo
            self.items[i] = c.create_image(max(0, (cw - w) // 2), int(off[i]),
                                           image=photo, anchor="nw")
        if any(i not in self.sizes for i in range(lo, hi + 1)):
            self._job = c.after(20, self.update)

        idx = min(n - 1, max(0, bisect.bisect_right(off, top + 4) - 1))
        if top + ch >= off[-1] - 2:
            idx = n - 1
        if idx != h.page:
            h.on_view_page(idx, 1)
