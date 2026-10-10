"""Plugin dialogs: translation and Bubble Reader settings, background-job progress, Plugins > Manage."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..constants import APP_NAME
from ..core.bubbles import DEFAULT_SETTINGS as BUBBLE_DEFAULTS
from ..core.bubbles import ENGLISH_VOICES, JAPANESE_VOICES
from ..core.plugins import ALL, PluginSpec
from ..core.translation import DEFAULT_SETTINGS
from ..utils.helpers import human_size, reveal_in_folder
from . import installer
from .client import WorkerClient


class _Dialog(tk.Toplevel):
    def __init__(self, app, title: str):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.transient(app)
        self.configure(bg=app.colors["panel"])
        self.resizable(False, False)
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda e: self.destroy())


# ---- settings ------------------------------------------------------------------------ #
class TranslationSettingsDialog(_Dialog):
    BACKENDS = {"Local server / OpenAI-compatible (Ollama, LM Studio…)": "openai",
                "Anthropic (Claude)": "anthropic",
                "GGUF model file, run inside the plugin (llama.cpp)": "llama-cpp"}
    OCR = {"Automatic": "auto",
           "Local OCR model (downloads about 450 MB once)": "local",
           "manga-ocr package (from source, needs PyTorch)": "manga-ocr",
           "The translator reads the image (vision model)": "llm"}
    INPAINT = {"Automatic": "auto",
               "LaMa: best on artwork (downloads about 200 MB once)": "lama",
               "Fill bubbles only": "fill",
               "Don't erase (white box behind the English)": "off"}

    def __init__(self, app):
        super().__init__(app, "Translation Settings")
        s = {**DEFAULT_SETTINGS, **app.translator.settings}
        self.vars = {
            "backend": tk.StringVar(value=self._label(self.BACKENDS, s["backend"])),
            "base_url": tk.StringVar(value=s["base_url"]),
            "model": tk.StringVar(value=s["model"]),
            "anthropic_model": tk.StringVar(value=s["anthropic_model"]),
            "api_key": tk.StringVar(value=s["api_key"]),
            "gguf_path": tk.StringVar(value=s["gguf_path"]),
            "ocr": tk.StringVar(value=self._label(self.OCR, s["ocr"])),
            "inpaint": tk.StringVar(value=self._label(self.INPAINT, s["inpaint"])),
            "target": tk.StringVar(value=s["target"]),
            "font_file": tk.StringVar(value=s["font_file"]),
            "gpu": tk.BooleanVar(value=bool(s["gpu"])),
        }
        b, row = self.body, 0

        def line(label, widget, browse=None):
            nonlocal row
            ttk.Label(b, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
            widget.grid(row=row, column=1, sticky="ew", pady=3)
            if browse:
                btn = ttk.Button(b, text="Browse…", command=browse)
                btn.grid(row=row, column=2, padx=(6, 0))
                widget.browse_button = btn
            row += 1
            return widget

        def note(text):
            nonlocal row
            ttk.Label(b, foreground="#888888", wraplength=460, justify="left", text=text
                      ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
            row += 1

        line("Translator:", ttk.Combobox(b, textvariable=self.vars["backend"], state="readonly",
                                         values=list(self.BACKENDS), width=50))
        self.url_entry = line("Server URL:", ttk.Entry(b, textvariable=self.vars["base_url"]))
        self.model_entry = line("Model:", ttk.Entry(b, textvariable=self.vars["model"]))
        self.claude_entry = line("Claude model:", ttk.Entry(b, textvariable=self.vars["anthropic_model"]))
        self.key_entry = line("API key:", ttk.Entry(b, textvariable=self.vars["api_key"], show="*"))
        self.gguf_entry = line("GGUF model file:", ttk.Entry(b, textvariable=self.vars["gguf_path"]),
                               browse=self._browse_gguf)
        note("The API key is stored in state.json; leave it blank to use the ANTHROPIC_API_KEY / "
             "OPENAI_API_KEY environment variable. A local server needs no key. When the "
             "translator reads the images itself it must be a vision model (qwen2.5vl, Claude). "
             "A GGUF model needs pip install llama-cpp-python and the local OCR.")
        line("Read Japanese with:", ttk.Combobox(b, textvariable=self.vars["ocr"], state="readonly",
                                                 values=list(self.OCR)))
        line("Remove original text:", ttk.Combobox(b, textvariable=self.vars["inpaint"],
                                                   state="readonly", values=list(self.INPAINT)))
        line("Translate into:", ttk.Entry(b, textvariable=self.vars["target"]))
        line("Font (.ttf/.otf):", ttk.Entry(b, textvariable=self.vars["font_file"]),
             browse=self._browse_font)
        note("Leave the font blank for the built-in Comic Neue Bold.")
        ttk.Checkbutton(b, text="Use the GPU when available", variable=self.vars["gpu"]
                        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1
        btns = ttk.Frame(b)
        btns.grid(row=row, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self.save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        b.columnconfigure(1, weight=1)
        self.vars["backend"].trace_add("write", lambda *_: self._sync())
        self._sync()

    @staticmethod
    def _label(table: dict, value: str) -> str:
        return next((k for k, v in table.items() if v == value), next(iter(table)))

    def _sync(self):
        backend = self.BACKENDS[self.vars["backend"].get()]
        state = lambda on: "normal" if on else "disabled"  # noqa: E731
        self.url_entry.configure(state=state(backend == "openai"))
        self.model_entry.configure(state=state(backend == "openai"))
        self.claude_entry.configure(state=state(backend == "anthropic"))
        self.key_entry.configure(state=state(backend != "llama-cpp"))
        self.gguf_entry.configure(state=state(backend == "llama-cpp"))
        self.gguf_entry.browse_button.configure(state=state(backend == "llama-cpp"))

    def _browse_gguf(self):
        path = filedialog.askopenfilename(parent=self, title="GGUF model",
                                          filetypes=[("GGUF model", "*.gguf"), ("All files", "*.*")])
        if path:
            self.vars["gguf_path"].set(path)

    def _browse_font(self):
        path = filedialog.askopenfilename(parent=self, title="Font for the English text",
                                          filetypes=[("Fonts", "*.ttf *.otf"), ("All files", "*.*")])
        if path:
            self.vars["font_file"].set(path)

    def save(self):
        v = self.vars
        settings = {
            "backend": self.BACKENDS[v["backend"].get()],
            "base_url": v["base_url"].get().strip(),
            "model": v["model"].get().strip(),
            "anthropic_model": v["anthropic_model"].get().strip() or DEFAULT_SETTINGS["anthropic_model"],
            "api_key": v["api_key"].get().strip(),
            "gguf_path": v["gguf_path"].get().strip(),
            "ocr": self.OCR[v["ocr"].get()],
            "inpaint": self.INPAINT[v["inpaint"].get()],
            "target": v["target"].get().strip() or "English",
            "font_file": v["font_file"].get().strip(),
            "gpu": bool(v["gpu"].get()),
        }
        if settings["backend"] == "llama-cpp" and settings["ocr"] == "llm":
            messagebox.showwarning(APP_NAME, "A GGUF model can't read images: choose the local OCR "
                                   "(or Automatic) under 'Read Japanese with'.", parent=self)
            return
        self.app.translator.apply_settings(settings)
        self.destroy()


# ---- progress ------------------------------------------------------------------------ #
class ProgressWindow(_Dialog):
    """A progress bar for a background job. poll() -> (done, total, text, finished).

    Closing it only hides it: the job goes on, and the window disappears when it ends.
    """

    def __init__(self, app, title: str, poll, stop=None):
        super().__init__(app, title)
        self.poll, self.stop = poll, stop
        self.text = tk.StringVar(value="Starting…")
        ttk.Label(self.body, textvariable=self.text, width=56).pack(anchor="w")
        self.bar = ttk.Progressbar(self.body, length=420, mode="determinate")
        self.bar.pack(fill="x", pady=8)
        row = ttk.Frame(self.body)
        row.pack(fill="x")
        self.close_btn = ttk.Button(row, text="Hide", command=self.withdraw)
        self.close_btn.pack(side="right")
        if stop:
            self.stop_btn = ttk.Button(row, text="Stop", command=self._stop)
            self.stop_btn.pack(side="right", padx=6)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.bind("<Escape>", lambda e: self.withdraw())
        self._tick()

    def _stop(self):
        self.stop()
        self.stop_btn.configure(state="disabled")

    def _tick(self):
        try:
            done, total, text, finished = self.poll()
            self.text.set(text)
            self.bar.configure(maximum=max(1, total), value=done)
        except tk.TclError:
            return  # destroyed
        if not finished:
            self.after(400, self._tick)
            return
        if self.state() == "withdrawn":
            self.destroy()
        else:
            self.close_btn.configure(text="Close", command=self.destroy)
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            if self.stop:
                self.stop_btn.configure(state="disabled")


# ---- plugin manager ---------------------------------------------------------------- #
class PluginManagerDialog(_Dialog):
    """Plugins > Manage: every plugin with Install / Update / Remove (from GitHub Releases)."""

    def __init__(self, app, focus: PluginSpec | None = None):
        super().__init__(app, "Plugins")
        self.panels = [PluginPanel(self, app, spec) for spec in ALL]
        for panel in self.panels:
            panel.pack(fill="x", pady=(0, 10))
        if focus is not None:
            next(p for p in self.panels if p.spec is focus).focus_highlight()
        ttk.Button(self.body, text="Close", command=self.destroy).pack(side="right")
        if not installer.supported():
            ttk.Label(self.body, foreground="#888888", wraplength=440, justify="left", text=(
                "Released plugin builds are for Windows. From source, install each plugin's "
                "requirements.txt (plugins/<name>/) instead.")).pack(side="left")


class PluginPanel(ttk.LabelFrame):
    """One plugin: its state, the latest release, and the buttons."""

    def __init__(self, dialog: PluginManagerDialog, app, spec: PluginSpec):
        super().__init__(dialog.body, text=spec.name, padding=10)
        self.app, self.spec = app, spec
        self.release: dict | None = None
        self._q: queue.Queue = queue.Queue()
        self._busy = False
        ttk.Label(self, text=spec.description, wraplength=440).pack(anchor="w", pady=(0, 6))
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, wraplength=440, justify="left").pack(anchor="w")
        self.bar = ttk.Progressbar(self, length=440, mode="determinate")
        self.bar.pack(fill="x", pady=6)
        row = ttk.Frame(self)
        row.pack(fill="x")
        self.check_btn = ttk.Button(row, text="Check for updates", command=self.check)
        self.check_btn.pack(side="left")
        self.install_btn = ttk.Button(row, text="Install", command=self.install, state="disabled")
        self.install_btn.pack(side="left", padx=6)
        self.remove_btn = ttk.Button(row, text="Remove", command=self.remove)
        self.remove_btn.pack(side="left")
        ttk.Button(row, text="Open folder", command=self.open_folder).pack(side="left", padx=6)
        self.refresh()
        if installer.supported():
            self.check()

    def focus_highlight(self):
        self.configure(text=f"{self.spec.name}  (needed for this)")

    def _controller(self):
        return self.app.plugin_controllers.get(self.spec.id)

    # ---- state ---- #
    def refresh(self, extra: str = ""):
        ver = installer.installed_version(self.spec)
        if WorkerClient(self.spec).available() and ver is None:
            text = "Available (running from source, or installed with the reader)."
        elif ver:
            text = f"Installed: version {ver}."
        else:
            text = "Not installed."
        if self.release:
            text += f"\nLatest release: {self.release['tag']} ({human_size(self.release['size'])})."
        self.status.set(text + (f"\n{extra}" if extra else ""))
        newer = self.release and self.release["version"] != ver
        self.install_btn.configure(
            state="normal" if (newer and installer.supported() and not self._busy) else "disabled",
            text="Update" if ver else "Install")
        self.remove_btn.configure(state="normal" if ver and not self._busy else "disabled")
        self.check_btn.configure(state="disabled" if self._busy else "normal")

    def _run(self, work, done):
        """Run work(progress) in a thread; done(result_or_exception) back on the UI thread."""
        self._busy = True
        self.refresh()

        def target():
            try:
                result = work(lambda d, t: self._q.put(("progress", d, t)))
            except Exception as exc:
                result = exc
            self._q.put(("done", result))
        threading.Thread(target=target, daemon=True).start()
        self._drain(done)

    def _drain(self, done):
        try:
            while True:
                msg = self._q.get_nowait()
                if msg[0] == "progress":
                    self.bar.configure(maximum=max(1, msg[2]), value=msg[1])
                else:
                    self._busy = False
                    if self.winfo_exists():
                        done(msg[1])
                    return
        except queue.Empty:
            pass
        except tk.TclError:  # dialog closed meanwhile
            return
        self.after(100, lambda: self._drain(done))

    # ---- actions ---- #
    def check(self):
        def done(result):
            if isinstance(result, Exception):
                self.refresh(str(result))
            else:
                self.release = result
                self.refresh()
        self.status.set("Checking GitHub…")
        self._run(lambda progress: installer.latest_release(self.spec), done)

    def install(self):
        if not self.release:
            return
        ctl = self._controller()
        if ctl is not None:
            ctl.shutdown()  # Windows can't replace a running exe

        def done(result):
            self.bar.configure(value=0)
            if isinstance(result, Exception):
                self.refresh(f"Install failed: {result}")
            else:
                self.refresh("Installed.")
                self.app.menubar.build()
        self._run(lambda progress: installer.install(self.spec, self.release, progress), done)

    def remove(self):
        if not messagebox.askyesno(APP_NAME, f"Remove the {self.spec.name} plugin?\n\nDownloaded "
                                   "models and saved results are kept.", parent=self):
            return
        ctl = self._controller()
        if ctl is not None:
            ctl.shutdown()
        installer.remove(self.spec)
        self.app.menubar.build()
        self.refresh("Removed.")

    def open_folder(self):
        self.spec.dir.mkdir(parents=True, exist_ok=True)
        reveal_in_folder(str(self.spec.dir))


# ---- Bubble Reader settings ----------------------------------------------------------- #
class BubbleReaderSettingsDialog(_Dialog):
    LANGUAGES = {"Automatic (manga = Japanese, otherwise English)": "auto",
                 "Japanese": "ja", "English": "en"}

    def __init__(self, app):
        super().__init__(app, "Bubble Reader Settings")
        s = {**BUBBLE_DEFAULTS, **app.bubble_reader.settings}
        self.vars = {
            "voice_en": tk.StringVar(value=ENGLISH_VOICES.get(s["voice_en"], s["voice_en"])),
            "voice_ja": tk.StringVar(value=JAPANESE_VOICES.get(s["voice_ja"], s["voice_ja"])),
            "speed": tk.DoubleVar(value=float(s["speed"])),
            "volume": tk.IntVar(value=int(s["volume"])),
            "language": tk.StringVar(value=next((k for k, v in self.LANGUAGES.items()
                                                 if v == s["language"]), next(iter(self.LANGUAGES)))),
            "read_translated": tk.BooleanVar(value=bool(s["read_translated"])),
            "skip_sfx": tk.BooleanVar(value=bool(s["skip_sfx"])),
            "auto_turn": tk.BooleanVar(value=bool(s["auto_turn"])),
            "follow": tk.BooleanVar(value=bool(s["follow"])),
            "gpu": tk.BooleanVar(value=bool(s["gpu"])),
        }
        b, row = self.body, 0

        def line(label, widget):
            nonlocal row
            ttk.Label(b, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
            widget.grid(row=row, column=1, sticky="ew", pady=3)
            row += 1
            return widget

        def check(text, var):
            nonlocal row
            ttk.Checkbutton(b, text=text, variable=var).grid(row=row, column=1, sticky="w", pady=2)
            row += 1

        line("English voice:", ttk.Combobox(b, textvariable=self.vars["voice_en"], state="readonly",
                                            values=list(ENGLISH_VOICES.values()), width=36))
        line("Japanese voice:", ttk.Combobox(b, textvariable=self.vars["voice_ja"], state="readonly",
                                             values=list(JAPANESE_VOICES.values())))
        self.speed_label = tk.StringVar()
        speed = ttk.Frame(b)
        ttk.Scale(speed, from_=0.5, to=2.0, variable=self.vars["speed"], command=self._show,
                  length=220).pack(side="left")
        ttk.Label(speed, textvariable=self.speed_label, width=6).pack(side="left", padx=6)
        line("Speed:", speed)
        self.volume_label = tk.StringVar()
        vol = ttk.Frame(b)
        ttk.Scale(vol, from_=0, to=100, variable=self.vars["volume"], command=self._show,
                  length=220).pack(side="left")
        ttk.Label(vol, textvariable=self.volume_label, width=6).pack(side="left", padx=6)
        line("Volume:", vol)
        line("Comic language:", ttk.Combobox(b, textvariable=self.vars["language"], state="readonly",
                                             values=list(self.LANGUAGES)))
        check("Read translated pages in English (Manga Translator)", self.vars["read_translated"])
        check("Skip sound effects drawn over the art", self.vars["skip_sfx"])
        check("Turn the page after the last bubble", self.vars["auto_turn"])
        check("Scroll to the bubble being read", self.vars["follow"])
        check("Use the GPU when available", self.vars["gpu"])
        ttk.Label(b, foreground="#888888", wraplength=420, justify="left", text=(
            "Keys while reading: P play / pause, . next bubble, , previous bubble, Shift+P stop. "
            "Click a bubble to read from there.")).grid(row=row, column=0, columnspan=2,
                                                         sticky="w", pady=(6, 0))
        row += 1
        btns = ttk.Frame(b)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self.save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        b.columnconfigure(1, weight=1)
        self._show()

    def _show(self, *_):
        self.speed_label.set(f"{self.vars['speed'].get():.1f}x")
        self.volume_label.set(f"{int(float(self.vars['volume'].get()))}%")

    def save(self):
        v = self.vars
        by_label = lambda table, label: next((k for k, name in table.items() if name == label), label)  # noqa: E731
        settings = {
            "voice_en": by_label(ENGLISH_VOICES, v["voice_en"].get()),
            "voice_ja": by_label(JAPANESE_VOICES, v["voice_ja"].get()),
            "speed": round(float(v["speed"].get()), 2),
            "volume": int(float(v["volume"].get())),
            "language": self.LANGUAGES[v["language"].get()],
            **{k: bool(v[k].get()) for k in ("read_translated", "skip_sfx", "auto_turn", "follow", "gpu")},
        }
        self.app.bubble_reader.apply_settings(settings)
        self.destroy()
