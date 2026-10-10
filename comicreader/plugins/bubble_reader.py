"""BubbleReaderController: the reader's side of the Bubble Reader plugin.

Read Aloud (key P) reads the speech bubbles of the page(s) on screen in reading order: right to
left for manga (the reader's RTL setting), left to right otherwise. The bubble being spoken is
outlined and kept in view; after the last bubble the page turns and reading carries on.

Where the text comes from, per page:
  - a page the Manga Translator has translated (and Translate Pages is on): its English;
  - otherwise the plugin finds the bubbles and reads them with OCR (Japanese or English).
The next pages are analysed ahead while the current one is read.

Worker start-up: hello -> configure -> configured lists models to download -> ready.
"""
import queue
import tkinter as tk
from tkinter import messagebox

from ..constants import APP_NAME
from ..core.bubbles import DEFAULT_SETTINGS, PROTOCOL, BubbleCache, bubbles_from_translation
from ..core.plugins import BUBBLE_READER
from .client import WorkerClient

HIGHLIGHT_TAG = "bubble_hl"


class BubbleReaderController:
    def __init__(self, app):
        self.app = app
        stored = app.store.settings.get("bubble_reader", {})
        self.settings = {**DEFAULT_SETTINGS, **(stored if isinstance(stored, dict) else {})}
        self.client = WorkerClient(BUBBLE_READER)
        self.reading = tk.BooleanVar(value=False)   # Read Aloud is on (playing or paused)
        self.paused = False
        self.state = "off"        # off | starting | configuring | downloading | ready
        self.stage = ""
        self.pages: dict[tuple[str, int], list[dict]] = {}   # (comic key, page) -> bubbles
        self._asked: set[tuple[str, int]] = set()            # analysis requested
        self.spread: tuple[int, ...] = ()
        self.items: list[dict] = []    # what is being read: bubbles + their page
        self.current: int | None = None
        self._job = 0
        self._polling = False
        self._start_at = 0

    @property
    def available(self) -> bool:
        return self.client.available()

    # ------------------------------------------------------------------------------------ #
    # Actions (keys / menus / mouse)
    # ------------------------------------------------------------------------------------ #
    def toggle(self):
        """P: start reading, or pause / resume."""
        if not self.reading.get():
            self.start()
        elif self.paused:
            self.paused = False
            self.client.send("resume")
        else:
            self.paused = True
            self.client.send("pause")
        self.app._update_status()

    def start(self, at: int = 0):
        a = self.app
        if not a.session.is_open:
            return
        if not self._check_plugin():
            self.reading.set(False)
            return
        self.reading.set(True)
        self.paused = False
        self._ensure_worker()
        self._read_spread(at)

    def stop(self):
        if self.reading.get() or self.items:
            self.client.send("stop")
        self.reading.set(False)
        self.paused = False
        self.items, self.current, self.spread = [], None, ()
        self._job += 1     # late messages from the old reading are ignored
        self._clear_highlight()
        self.app._update_status()

    def next_bubble(self):
        if self.reading.get() and self.items:
            nxt = (self.current or 0) + 1
            if nxt < len(self.items):
                self._play(nxt)
            else:
                self._turn()

    def prev_bubble(self):
        if self.reading.get() and self.items:
            self._play(max(0, (self.current or 0) - 1))

    def on_click(self, x: int, y: int) -> bool:
        """A click on the page while reading: read from the bubble under it. True if handled."""
        if not self.reading.get() or not self.items:
            return False
        c = self.app.canvas
        hit = self.app.view.canvas_to_page(c.canvasx(x), c.canvasy(y))
        if hit is None:
            return False
        page, px, py = hit
        for i, it in enumerate(self.items):
            x1, y1, x2, y2 = it["box"]
            if it["page"] == page and x1 - 10 <= px <= x2 + 10 and y1 - 10 <= py <= y2 + 10:
                self.paused = False
                self._play(i)
                return True
        return False

    def reread_page(self):
        """Forget this page's bubbles and find them again (after changing language, say)."""
        a = self.app
        if not a.session.is_open:
            return
        for p in range(a.page, a.page + a.span):
            self.pages.pop((a.session.key, p), None)
            self._asked.discard((a.session.key, p))
            cache = BubbleCache(a.session.key)
            for f in cache.dir.glob(f"{p:04d}-*.json"):
                f.unlink(missing_ok=True)
        if self.reading.get():
            self._read_spread(0)

    def apply_settings(self, settings: dict):
        old = self.settings
        self.settings = {**DEFAULT_SETTINGS, **settings}
        self.app.store.settings["bubble_reader"] = dict(self.settings)
        self.app.store.save()
        if self.client.running and self.state != "off":
            self.client.send("set", speed=self.settings["speed"], volume=self.settings["volume"])
            if any(old.get(k) != self.settings[k] for k in ("language", "gpu", "voice_en", "voice_ja")):
                self.state = "configuring"
                self.client.send("configure", settings=self.settings)
                if old.get("language") != self.settings["language"]:
                    self.pages.clear()
                    self._asked.clear()

    def _check_plugin(self) -> bool:
        if self.available:
            return True
        if messagebox.askyesno(
                APP_NAME, "Reading bubbles aloud needs the Bubble Reader plugin, which isn't "
                "installed.\n\nOpen Plugins > Manage to install it?", parent=self.app):
            from .dialogs import PluginManagerDialog
            PluginManagerDialog(self.app, BUBBLE_READER)
        return False

    # ------------------------------------------------------------------------------------ #
    # Reader hooks
    # ------------------------------------------------------------------------------------ #
    def comic_opened(self):
        if self.reading.get():
            self.client.send("stop")
        self.items, self.current, self.spread = [], None, ()
        self._clear_highlight()

    def page_shown(self, page: int, span: int):
        """The view moved: when reading, read the new page(s)."""
        if not self.reading.get():
            return
        spread = tuple(range(page, page + span))
        if spread != self.spread:
            self.paused = False
            self._read_spread(0)

    def after_draw(self):
        """The canvas was redrawn: put the highlight back."""
        self._highlight(follow=False)

    def shutdown(self):
        self.client.stop()
        self.state = "off"
        self.reading.set(False)

    def status_text(self) -> str:
        if not self.reading.get():
            return ""
        if self.state in ("starting", "configuring"):
            return "starting…"
        if self.state == "downloading":
            return self.stage
        if not self.items:
            return "finding bubbles…"
        n = (self.current or 0) + 1
        return f"{'paused' if self.paused else 'reading'} {n}/{len(self.items)}"

    # ------------------------------------------------------------------------------------ #
    # What to read
    # ------------------------------------------------------------------------------------ #
    def _bubbles(self, page: int) -> list[dict] | None:
        """Bubbles of `page`, or None while the plugin is still finding them."""
        a = self.app
        tr = getattr(a, "translator", None)
        if (self.settings["read_translated"] and tr is not None and tr.enabled.get()
                and tr.cache is not None and tr.cache.has(page)):
            data = tr.cache.load_blocks(page)
            if data:
                return bubbles_from_translation(data)
        key = (a.session.key, page)
        if key in self.pages:
            return self.pages[key]
        self._analyze(page)
        return None

    def _analyze(self, page: int):
        a = self.app
        key = (a.session.key, page)
        if key in self._asked or not (0 <= page < a.session.count):
            return
        self._asked.add(key)
        if self.state == "ready":
            self.client.send("analyze", job=self._job, comic=str(a.session.path), key=a.session.key,
                             page=page, rtl=bool(a.manga.get()))

    def _read_spread(self, at: int = 0):
        a = self.app
        self.client.send("stop")
        self._job += 1
        self.spread = tuple(range(a.page, a.page + a.span))
        self.items, self.current = [], None
        self._clear_highlight()
        self._start_at = at
        self._maybe_play()

    def _maybe_play(self):
        """Start reading once every page of the spread has its bubbles."""
        if not self.reading.get() or self.state != "ready" or self.items:
            self.app._update_status()
            return
        found = [self._bubbles(p) for p in self.spread]
        if any(b is None for b in found):
            self.app._update_status()
            return
        items = []
        for page, bubbles in zip(self.spread, found):
            for b in bubbles:
                if b.get("sfx") and self.settings["skip_sfx"]:
                    continue
                items.append({**b, "page": page})
        self.items = items
        nxt = self.spread[-1] + 1 if self.spread else 0
        for p in range(nxt, nxt + max(1, len(self.spread))):   # get the next page(s) ready meanwhile
            self._bubbles(p)
        if not items:
            self.app.flash("No bubbles on this page")
            if self.settings["auto_turn"]:
                self.app.after(900, self._turn_if_still(self._job))
            return
        self._play(min(self._start_at, len(items) - 1))

    def _play(self, index: int):
        self._job += 1
        self.current = index
        self.paused = False
        self.client.send("play", job=self._job, start=index,
                         items=[{"text": it["text"], "lang": it["lang"]} for it in self.items])
        self._highlight(follow=True)
        self.app._update_status()

    def _turn_if_still(self, job: int):
        return lambda: self._turn() if job == self._job and self.reading.get() else None

    def _turn(self):
        a = self.app
        if not a.session.is_open:
            return
        if a.page + a.span >= a.session.count:
            self.stop()
            a.flash("End of the comic")
            return
        a.next_page()   # page_shown() then reads the new page

    # ------------------------------------------------------------------------------------ #
    # Highlight
    # ------------------------------------------------------------------------------------ #
    def _clear_highlight(self):
        try:
            self.app.canvas.delete(HIGHLIGHT_TAG)
        except tk.TclError:
            pass

    def _highlight(self, follow: bool):
        self._clear_highlight()
        a = self.app
        if (not self.reading.get() or self.current is None or self.current >= len(self.items)
                or a.in_library):
            return
        it = self.items[self.current]
        rect = a.view.page_box_to_canvas(it["page"], it["box"])
        if rect is None:
            return
        pad = 6
        x1, y1, x2, y2 = rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad
        c = a.canvas
        c.create_rectangle(x1, y1, x2, y2, outline=a.colors["accent"], width=4, tags=HIGHLIGHT_TAG)
        if follow and self.settings["follow"]:
            self._scroll_to(y1, y2)

    def _scroll_to(self, y1: float, y2: float):
        c = self.app.canvas
        try:
            total = float(str(c.cget("scrollregion")).split()[3])
        except (IndexError, ValueError):
            return
        top, view_h = c.canvasy(0), c.winfo_height()
        if total <= view_h or (y1 >= top and y2 <= top + view_h):
            return
        target = max(0.0, (y1 + y2) / 2 - view_h / 2)
        c.yview_moveto(target / total)
        self.app.view.on_scroll()

    # ------------------------------------------------------------------------------------ #
    # Worker process
    # ------------------------------------------------------------------------------------ #
    def _ensure_worker(self):
        if self.state != "off" and self.client.running:
            return
        try:
            self.client.start()
        except (RuntimeError, OSError) as exc:
            self._fail(str(exc))
            return
        self.state = "starting"
        self._asked.clear()
        self.client.send("hello")
        self._start_polling()

    def _start_polling(self):
        if not self._polling:
            self._polling = True
            self.app.after(100, self._poll)

    def _poll(self):
        try:
            while True:
                self._handle(self.client.messages.get_nowait())
        except queue.Empty:
            pass
        except Exception as exc:  # a bug handling a message must not kill the polling loop
            self._fail(f"Bubble Reader error: {exc}")
        if self.client.running or not self.client.messages.empty():
            self.app.after(100, self._poll)
        else:
            self._polling = False

    def _handle(self, msg: dict):
        kind = msg.get("type")
        a = self.app
        if kind == "hello":
            if msg.get("protocol") != PROTOCOL:
                self._fail("The installed Bubble Reader plugin doesn't match this version of the "
                           "reader. Update it under Plugins > Manage.")
            elif msg.get("problems"):
                self._fail("The Bubble Reader can't run:\n\n" + "\n".join(msg["problems"]))
            else:
                self.state = "configuring"
                self.client.send("configure", settings=self.settings)
        elif kind == "configured":
            if msg.get("missing_models"):
                self._offer_download(msg["missing_models"])
                return
            self.state = "ready"
            self.stage = ""
            self._asked.clear()      # (re)send the analyses asked for while starting
            if self.reading.get():
                self._read_spread(self._start_at)
        elif kind == "download":
            pct = msg.get("done", 0) * 100 // max(1, msg.get("total", 1))
            self.stage = f"downloading {msg.get('name')} {pct}%"
            a._update_status()
        elif kind == "downloaded":
            self.state = "configuring"
            self.client.send("configure", settings=self.settings)
        elif kind == "bubbles":
            self.pages[(msg.get("key"), msg.get("page"))] = msg.get("bubbles") or []
            if msg.get("key") == a.session.key and msg.get("page") in self.spread:
                self._maybe_play()
        elif kind == "speaking":
            if msg.get("job") == self._job:
                self.current = msg.get("index", 0)
                self._highlight(follow=True)
                a._update_status()
        elif kind == "finished":
            if msg.get("job") == self._job and self.reading.get():
                self._clear_highlight()
                if self.settings["auto_turn"]:
                    self._turn()
                else:
                    self.stop()
        elif kind == "notice":
            a.flash(msg.get("message", ""))
        elif kind == "error":
            if self.state == "downloading":
                self._fail(f"Download failed:\n{msg.get('message')}")
            elif msg.get("cmd") in ("hello", "configure"):
                self._fail(f"The Bubble Reader couldn't start:\n{msg.get('message')}")
            elif msg.get("cmd") == "analyze":
                key = (msg.get("key") or a.session.key, msg.get("page"))
                self.pages[key] = []     # nothing to read there; carry on
                a.flash(f"Couldn't read the bubbles of page {(msg.get('page') or 0) + 1}: "
                        f"{msg.get('message')}")
                self._maybe_play()
            elif msg.get("job") == self._job:
                self.stop()
                messagebox.showerror(APP_NAME, f"Reading aloud stopped:\n{msg.get('message')}",
                                     parent=a)
        elif kind == "exited":
            if self.state != "off":
                self.client.stop()
                self._fail(f"The Bubble Reader stopped unexpectedly. Details are in:\n"
                           f"{self.client.log_path()}")

    def _offer_download(self, missing: list[dict]):
        size = sum(m.get("size", 0) for m in missing) / 1e6
        names = ", ".join(m.get("name", "?") for m in missing)
        if messagebox.askyesno(APP_NAME, f"Reading aloud needs to download {names} "
                               f"(about {size:.0f} MB) once.\n\nDownload now?", parent=self.app):
            self.state = "downloading"
            self.stage = "downloading…"
            self.client.send("download")
        else:
            self._fail("Reading aloud is off until those are downloaded.")
        self.app._update_status()

    def _fail(self, message: str):
        self.state = "off"
        self.client.stop()
        self.stop()
        messagebox.showerror(APP_NAME, message, parent=self.app)
