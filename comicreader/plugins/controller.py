"""TranslatorController: the reader's side of the Manga Translator plugin.

It hooks into the single page-image choke point: app.get_image(i) calls image_for(i, original).
When "Translate pages" is on and page i has a cached translation, that image is returned;
otherwise the original is returned and page i is queued for the worker. When the worker
finishes a page that is on screen, the view is redrawn. Views don't know any of this.

Pages are sent to the worker one at a time (so the queue can be re-prioritised as you read):
the pages on screen first, then the following pages, then earlier ones.
"""
import queue
import tkinter as tk
from collections import OrderedDict
from tkinter import messagebox

from PIL import Image

from ..constants import APP_NAME
from ..core.translation import (DEFAULT_SETTINGS, PROTOCOL, TranslationCache, comic_signature)
from .client import WorkerClient


class TranslatorController:
    IMAGE_LIMIT = 8

    def __init__(self, app):
        self.app = app
        stored = app.store.settings.get("translator", {})
        self.settings = {**DEFAULT_SETTINGS, **(stored if isinstance(stored, dict) else {})}
        self.enabled = tk.BooleanVar(value=False)  # always starts off: starting the worker is slow
        self.client = WorkerClient()
        self.state = "off"        # off | starting | downloading | ready
        self.stage = ""           # what the worker is doing right now (for the status bar)
        self.cache: TranslationCache | None = None
        self._validated = False
        self.pending: "OrderedDict[int, None]" = OrderedDict()
        self.failed: set[int] = set()
        self.busy: tuple[int, str, int] | None = None   # (job, comic key, page) at the worker
        self._job = 0
        self._images: "OrderedDict[int, Image.Image]" = OrderedDict()
        self._polling = False

    @property
    def available(self) -> bool:
        return WorkerClient.available()

    # ------------------------------------------------------------------------------------ #
    # The choke point
    # ------------------------------------------------------------------------------------ #
    def image_for(self, index: int, original: Image.Image) -> Image.Image:
        if not self.enabled.get() or self.cache is None:
            return original
        if index in self._images:
            self._images.move_to_end(index)
            return self._images[index]
        self._validate()
        if self.cache.has(index):
            try:
                with Image.open(self.cache.page_png(index)) as im:
                    img = im.convert("RGB")
            except OSError:
                self.cache.clear(index)
            else:
                self._images[index] = img
                while len(self._images) > self.IMAGE_LIMIT:
                    self._images.popitem(last=False)
                return img
        if index not in self.failed:
            self.request(index)
        return original

    def _validate(self):
        """Once per comic: drop translations made from an older version of the file."""
        if not self._validated and self.cache is not None:
            self._validated = True
            self.cache.validate(comic_signature(self.app.session.path))

    # ------------------------------------------------------------------------------------ #
    # Comic lifecycle
    # ------------------------------------------------------------------------------------ #
    def comic_opened(self):
        """A new comic is open: forget the old one's queue (a page in flight just finishes)."""
        self.cache = TranslationCache(self.app.session.key)
        self._validated = False
        self.pending.clear()
        self.failed.clear()
        self._images.clear()

    def shutdown(self):
        self.client.stop()
        self.state = "off"

    # ------------------------------------------------------------------------------------ #
    # Actions (keys / menus)
    # ------------------------------------------------------------------------------------ #
    def toggle(self):
        """Key T / View > Translate Pages."""
        want = not self.enabled.get()
        self.set_enabled(want)

    def set_enabled(self, on: bool):
        if on and not self._check_plugin():
            on = False
        self.enabled.set(on)
        if on:
            self._ensure_worker()
        else:
            self.pending.clear()
        self._redraw()
        self.app._update_status()

    def translate_all(self):
        """Queue every page of the comic, starting from the current one."""
        a = self.app
        if not a.session.is_open:
            return
        if not self.enabled.get():
            self.set_enabled(True)
            if not self.enabled.get():
                return
        self._validate()
        done = self.cache.pages()
        self.failed.clear()
        order = list(range(a.page, a.session.count)) + list(range(0, a.page))
        for p in order:
            if p not in done:
                self.pending[p] = None
        a.flash(f"Translating {len(self.pending)} pages in the background")
        self._kick()

    def retranslate_page(self):
        a = self.app
        if not a.session.is_open or self.cache is None:
            return
        for p in range(a.page, a.page + a.span):
            self.cache.clear(p)
            self._images.pop(p, None)
            self.failed.discard(p)
        if not self.enabled.get():
            self.set_enabled(True)
        else:
            self._redraw()

    def clear_comic(self):
        a = self.app
        if not a.session.is_open or self.cache is None:
            return
        if not messagebox.askyesno(APP_NAME, "Delete the saved translations of this comic?",
                                   parent=a):
            return
        self.cache.clear()
        self._validated = False
        self.pending.clear()
        self.failed.clear()
        self._images.clear()
        self._redraw()

    def apply_settings(self, settings: dict):
        """Called by the settings dialog: remember them and reconfigure a running worker."""
        self.settings = {**DEFAULT_SETTINGS, **settings}
        self.app.store.settings["translator"] = dict(self.settings)
        self.app.store.save()
        self.failed.clear()
        if self.client.running and self.state == "ready":
            self.client.send("configure", settings=self.settings)
            self._kick()

    def _check_plugin(self) -> bool:
        if self.available:
            return True
        if messagebox.askyesno(
                APP_NAME, "Page translation needs the Manga Translator plugin, which isn't "
                "installed.\n\nOpen Plugins > Manage to install it?", parent=self.app):
            from .dialogs import PluginManagerDialog
            PluginManagerDialog(self.app)
        return False

    # ------------------------------------------------------------------------------------ #
    # Queue
    # ------------------------------------------------------------------------------------ #
    def request(self, page: int):
        if page not in self.pending and not (self.busy and self.busy[2] == page
                                             and self.busy[1] == self.app.session.key):
            self.pending[page] = None
        self._ensure_worker()
        self._kick()

    def _next_page(self) -> int:
        a = self.app
        visible = [p for p in range(a.page, a.page + a.span) if p in self.pending]
        if visible:
            return visible[0]
        return min(self.pending, key=lambda p: (p < a.page, abs(p - a.page)))

    def _kick(self):
        a = self.app
        if self.state != "ready" or self.busy is not None or not a.session.is_open:
            return
        while self.pending:
            page = self._next_page()
            del self.pending[page]
            if self.cache.has(page):
                continue
            self._job += 1
            self.busy = (self._job, a.session.key, page)
            self.stage = "queued"
            self.client.send("translate", job=self._job, comic=str(a.session.path),
                             key=a.session.key, page=page, rtl=bool(a.manga.get()))
            break
        a._update_status()

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
        self.busy = None
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
            self._fail(f"Translator error: {exc}")
        if self.client.running or not self.client.messages.empty():
            self.app.after(100, self._poll)
        else:
            self._polling = False

    def _handle(self, msg: dict):
        kind = msg.get("type")
        a = self.app
        if kind == "hello":
            if msg.get("protocol") != PROTOCOL:
                self._fail("The installed Manga Translator plugin doesn't match this version of "
                           "the reader. Update it under Plugins > Manage.")
            elif msg.get("problems"):
                self._fail("The Manga Translator can't run:\n\n" + "\n".join(msg["problems"]))
            elif msg.get("missing_models"):
                self._offer_download(msg["missing_models"])
            else:
                self._ready()
        elif kind == "download":
            pct = msg.get("done", 0) * 100 // max(1, msg.get("total", 1))
            self.stage = f"downloading {msg.get('name')} {pct}%"
            a._update_status()
        elif kind == "downloaded":
            self._ready()
        elif kind == "stage":
            self.stage = msg.get("stage", "")
            a._update_status()
        elif kind == "done":
            page = msg.get("page")
            current = self.busy and self.busy[1] == a.session.key
            self.busy = None
            if current:
                self._images.pop(page, None)
                self._refresh(page)
            self._kick()
        elif kind == "error":
            if self.state == "downloading":
                self._fail(f"Model download failed:\n{msg.get('message')}")
                return
            page, current = msg.get("page"), self.busy and self.busy[1] == a.session.key
            self.busy = None
            if page is not None and current:
                self.failed.add(page)
                a.flash(f"Page {page + 1} not translated: {msg.get('message')}")
            self._kick()
        elif kind == "exited":
            if self.state != "off":
                self.client.stop()
                self._fail(f"The translator stopped unexpectedly. Details are in:\n"
                           f"{WorkerClient.log_path()}")

    def _offer_download(self, missing: list[dict]):
        size = sum(m.get("size", 0) for m in missing) / 1e6
        names = ", ".join(m.get("name", "?") for m in missing)
        if messagebox.askyesno(APP_NAME, f"Page translation needs to download {names} "
                               f"({size:.0f} MB) once.\n\nDownload it now?", parent=self.app):
            self.state = "downloading"
            self.stage = "downloading…"
            self.client.send("download")
        else:
            self.client.stop()
            self.state = "off"
            self.enabled.set(False)
        self.app._update_status()

    def _ready(self):
        self.state = "ready"
        self.stage = ""
        self.client.send("configure", settings=self.settings)
        self._kick()

    def _fail(self, message: str):
        """Stop, switch translation off and say why (the next toggle starts afresh)."""
        self.state = "off"
        self.busy = None
        self.pending.clear()
        self.enabled.set(False)
        self.client.stop()
        self._redraw()
        self.app._update_status()
        messagebox.showerror(APP_NAME, message, parent=self.app)

    # ------------------------------------------------------------------------------------ #
    # Display
    # ------------------------------------------------------------------------------------ #
    def _refresh(self, page: int):
        """Redraw if `page` is on screen."""
        a = self.app
        if a.in_library or not a.session.is_open or not self.enabled.get():
            return
        view = a.view
        if view.continuous:
            if page in getattr(view, "items", {}):
                view.redraw()
        elif a.page <= page < a.page + a.span:
            view.show(a.page, at=None)

    def _redraw(self):
        a = self.app
        if a.session.is_open and not a.in_library and a.view.active:
            if a.view.continuous:
                a.view.redraw()
            else:
                a.view.show(a.page, at=None)

    def status_text(self) -> str:
        if not self.enabled.get():
            return ""
        if self.state == "starting":
            return "translator starting…"
        if self.state == "downloading":
            return self.stage
        if self.busy and self.busy[1] == self.app.session.key:
            text = f"translating p.{self.busy[2] + 1} ({self.stage})"
            return text + (f", {len(self.pending)} queued" if self.pending else "")
        return "translated"
