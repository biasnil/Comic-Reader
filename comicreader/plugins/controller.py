"""TranslatorController: the reader's side of the Manga Translator plugin.

It hooks into the single page-image choke point: app.get_image(i) calls image_for(i, original).
When "Translate pages" is on and page i has a cached translation, that image is returned;
otherwise the original is returned and page i is queued for the worker. When the worker
finishes a page that is on screen, the view is redrawn. Views don't know any of this.

Pages are sent to the worker one at a time (so the queue can be re-prioritised as you read):
the pages on screen first, then the following pages, then earlier ones. Edits made in the
bubble editor are sent as separate "retypeset" jobs.

Worker start-up: hello (versions match?) -> configure (settings) -> configured lists models the
settings need -> offer to download them -> ready.
"""
import queue
import threading
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image

from ..constants import APP_NAME
from ..core.export import ExportCancelled, export_cbz
from ..core.translation import DEFAULT_SETTINGS, PROTOCOL, TranslationCache, comic_signature
from .client import WorkerClient


class TranslatorController:
    IMAGE_LIMIT = 8

    def __init__(self, app):
        self.app = app
        stored = app.store.settings.get("translator", {})
        self.settings = {**DEFAULT_SETTINGS, **(stored if isinstance(stored, dict) else {})}
        self.enabled = tk.BooleanVar(value=False)  # always starts off: starting the worker is slow
        self.client = WorkerClient()
        self.state = "off"        # off | starting | configuring | downloading | ready
        self.stage = ""           # what the worker is doing right now (for the status bar)
        self.cache: TranslationCache | None = None
        self._validated = False
        self.pending: "OrderedDict[int, None]" = OrderedDict()
        self.failed: set[int] = set()
        self.busy: tuple[int, str, int] | None = None   # (job, comic key, page) being translated
        self._edits: dict[int, tuple[str, int]] = {}    # retypeset job -> (comic key, page)
        self._job = 0
        self._images: "OrderedDict[int, Image.Image]" = OrderedDict()
        self._polling = False
        self.batch: dict | None = None                  # "translate whole comic" progress
        self.export: dict | None = None                 # a running CBZ export

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
        self.batch = None

    def shutdown(self):
        if self.export:
            self.export["cancel"] = True
        self.client.stop()
        self.state = "off"

    # ------------------------------------------------------------------------------------ #
    # Actions (keys / menus)
    # ------------------------------------------------------------------------------------ #
    def toggle(self):
        """Key T / Translate > Translate Pages."""
        self.set_enabled(not self.enabled.get())

    def set_enabled(self, on: bool):
        if on and not self._check_plugin():
            on = False
        self.enabled.set(on)
        if on:
            self._ensure_worker()
        else:
            self.pending.clear()
            self.batch = None
        self._redraw()
        self.app._update_status()

    def translate_all(self):
        """Queue every page of the comic, starting from the current one; shows a progress window."""
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
        todo = [p for p in order if p not in done]
        for p in todo:
            self.pending[p] = None
        self.batch = {"key": a.session.key, "pages": set(todo), "total": len(todo),
                      "done": 0, "failed": 0}
        if todo:
            from .dialogs import ProgressWindow
            ProgressWindow(a, f"Translating {a.session.title}", self.batch_progress,
                           stop=self.stop_batch)
        else:
            a.flash("Every page is already translated")
        self._kick()

    def batch_progress(self) -> tuple[int, int, str, bool]:
        """(done, total, text, finished) for the progress window."""
        b = self.batch
        if b is None:
            return 0, 0, "Stopped", True
        finished = b["done"] + b["failed"] >= b["total"]
        if finished:
            text = f"Finished: {b['done']} pages translated"
        elif self.state == "downloading":
            text = self.stage
        elif self.busy and self.busy[1] == b["key"]:
            text = f"Page {self.busy[2] + 1}: {self.stage}"
        else:
            text = "Starting…"
        if b["failed"]:
            text += f", {b['failed']} failed"
        return b["done"] + b["failed"], b["total"], text, finished

    def stop_batch(self):
        if self.batch:
            for p in self.batch["pages"]:
                self.pending.pop(p, None)
        self.batch = None
        self.app._update_status()

    def _batch_page(self, key: str, page: int, ok: bool):
        b = self.batch
        if b and b["key"] == key and page in b["pages"]:
            b["pages"].discard(page)
            b["done" if ok else "failed"] += 1

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
        self.batch = None
        self._redraw()

    def edit_page(self):
        """Translate > Edit Translations: the bubble editor for the page on screen."""
        a = self.app
        if not a.session.is_open or self.cache is None:
            return
        pages = [p for p in range(a.page, a.page + a.span) if self.cache.load_blocks(p)]
        if not pages:
            messagebox.showinfo(APP_NAME, "This page hasn't been translated yet.", parent=a)
            return
        from .editor import BubbleEditor
        BubbleEditor(a, self, pages)

    def retypeset(self, page: int, edits: list[dict]):
        """Send edited translations of `page` to the worker to be drawn again."""
        a = self.app
        if not self._check_plugin():
            return
        if not self.enabled.get():
            self.set_enabled(True)
        self._job += 1
        self._edits[self._job] = (a.session.key, page)
        if self.state == "ready":
            self.client.send("retypeset", job=self._job, key=a.session.key, page=page, blocks=edits)
        else:
            self._edits.pop(self._job)
            a.flash("The translator is still starting; try again in a moment")

    def apply_settings(self, settings: dict):
        """Called by the settings dialog: remember them and reconfigure a running worker."""
        self.settings = {**DEFAULT_SETTINGS, **settings}
        self.app.store.settings["translator"] = dict(self.settings)
        self.app.store.save()
        self.failed.clear()
        if self.client.running and self.state in ("ready", "configuring"):
            self.state = "configuring"
            self.client.send("configure", settings=self.settings)

    def _check_plugin(self) -> bool:
        if self.available:
            return True
        if messagebox.askyesno(
                APP_NAME, "Page translation needs the Manga Translator plugin, which isn't "
                "installed.\n\nOpen Plugins > Manage to install it?", parent=self.app):
            from .dialogs import PluginManagerDialog
            PluginManagerDialog(self.app)
        return False

    # ---- export ------------------------------------------------------------------------- #
    def export_comic(self):
        """Translate > Export Translated Comic: a CBZ with the translated pages."""
        a = self.app
        if not a.session.is_open or self.cache is None:
            return
        if self.export:
            a.flash("An export is already running")
            return
        self._validate()
        missing = a.session.count - len(self.cache.pages() & set(range(a.session.count)))
        if missing:
            answer = messagebox.askyesnocancel(
                APP_NAME, f"{missing} of {a.session.count} pages aren't translated yet.\n\n"
                "Yes: translate them first (export again when done)\n"
                "No: export now, keeping those pages in Japanese", parent=a)
            if answer is None:
                return
            if answer:
                self.translate_all()
                return
        path = filedialog.asksaveasfilename(
            parent=a, title="Export translated comic", defaultextension=".cbz",
            initialfile=f"{Path(a.session.title).stem} (EN).cbz",
            filetypes=[("Comic book archive", "*.cbz")])
        if not path:
            return
        job = {"done": 0, "total": a.session.count, "result": None, "cancel": False}
        self.export = job
        args = (a.session.path, a.session.key, Path(path), a.session.title, bool(a.manga.get()))

        def work():
            try:
                job["result"] = export_cbz(*args, progress=lambda d, t: job.update(done=d),
                                           cancelled=lambda: job["cancel"])
            except Exception as exc:  # reported on the UI thread
                job["result"] = exc

        threading.Thread(target=work, daemon=True).start()
        from .dialogs import ProgressWindow
        ProgressWindow(a, "Exporting translated comic", lambda: self._export_progress(path),
                       stop=lambda: job.update(cancel=True))

    def _export_progress(self, path: str) -> tuple[int, int, str, bool]:
        job = self.export
        if job is None:
            return 0, 0, "", True
        res = job["result"]
        if res is None:
            return job["done"], job["total"], f"Page {job['done']} of {job['total']}", False
        self.export = None
        if isinstance(res, ExportCancelled):
            return job["done"], job["total"], "Cancelled", True
        if isinstance(res, Exception):
            return job["done"], job["total"], f"Export failed: {res}", True
        translated, total = res
        return total, total, f"Saved {Path(path).name} ({translated} of {total} pages translated)", True

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
                self._batch_page(a.session.key, page, True)
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
        self._edits.clear()
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
            else:
                self.state = "configuring"
                self.client.send("configure", settings=self.settings)
        elif kind == "configured":
            if msg.get("missing_models"):
                self._offer_download(msg["missing_models"])
            else:
                self.state = "ready"
                self.stage = ""
                self._kick()
                a._update_status()
        elif kind == "download":
            pct = msg.get("done", 0) * 100 // max(1, msg.get("total", 1))
            self.stage = f"downloading {msg.get('name')} {pct}%"
            a._update_status()
        elif kind == "downloaded":
            self.state = "configuring"
            self.client.send("configure", settings=self.settings)  # check again, then ready
        elif kind == "stage":
            self.stage = msg.get("stage", "")
            a._update_status()
        elif kind == "done":
            self._finished(msg, ok=True)
        elif kind == "error":
            if self.state == "downloading":
                self._fail(f"Model download failed:\n{msg.get('message')}")
                return
            if msg.get("cmd") in ("hello", "configure"):
                self._fail(f"The translator couldn't start:\n{msg.get('message')}")
                return
            self._finished(msg, ok=False)
        elif kind == "exited":
            if self.state != "off":
                self.client.stop()
                self._fail(f"The translator stopped unexpectedly. Details are in:\n"
                           f"{WorkerClient.log_path()}")

    def _finished(self, msg: dict, ok: bool):
        """A translate or retypeset job ended (done or error)."""
        a = self.app
        job, page = msg.get("job"), msg.get("page")
        if job in self._edits:
            key, page = self._edits.pop(job)
            if key == a.session.key:
                self._images.pop(page, None)
                if ok:
                    self._refresh(page)
                else:
                    messagebox.showerror(APP_NAME, f"Couldn't redraw page {page + 1}:\n"
                                         f"{msg.get('message')}", parent=a)
            return
        if self.busy is None or (job is not None and job != self.busy[0]):
            if not ok:  # an error that isn't about a page (e.g. a bad setting)
                a.flash(f"Translator: {msg.get('message')}")
            return
        _, key, page = self.busy
        self.busy = None
        self._batch_page(key, page, ok)
        if key == a.session.key:
            if ok:
                self._images.pop(page, None)
                self._refresh(page)
            else:
                self.failed.add(page)
                a.flash(f"Page {page + 1} not translated: {msg.get('message')}")
        self._kick()

    def _offer_download(self, missing: list[dict]):
        size = sum(m.get("size", 0) for m in missing) / 1e6
        names = ", ".join(m.get("name", "?") for m in missing)
        amount = f"{size:.0f} MB" if size else "size unknown"
        if messagebox.askyesno(APP_NAME, f"These settings need to download {names} "
                               f"({amount}) once.\n\nDownload now?", parent=self.app):
            self.state = "downloading"
            self.stage = "downloading…"
            self.client.send("download")
        else:
            self._fail("Translation is off until the models are downloaded. You can pick other "
                       "options in Translate > Translation Settings.", show=True)
        self.app._update_status()

    def _fail(self, message: str, show: bool = True):
        """Stop, switch translation off and say why (the next toggle starts afresh)."""
        self.state = "off"
        self.busy = None
        self._edits.clear()
        self.pending.clear()
        self.batch = None
        self.enabled.set(False)
        self.client.stop()
        self._redraw()
        self.app._update_status()
        if show:
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
        if self.state in ("starting", "configuring"):
            return "translator starting…"
        if self.state == "downloading":
            return self.stage
        if self.busy and self.busy[1] == self.app.session.key:
            text = f"translating p.{self.busy[2] + 1} ({self.stage})"
            return text + (f", {len(self.pending)} queued" if self.pending else "")
        return "translated"
