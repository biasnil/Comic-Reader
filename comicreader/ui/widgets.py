"""Reusable widgets."""
import tkinter as tk
from tkinter import ttk


class ProgressBar(ttk.Frame):
    """Bottom bar: page slider, status text and a 'jump to page' box.

    With auto-hide on, the bar floats over the canvas (so the page never resizes) and
    disappears 2.5 s after the mouse last moved.
    """

    HIDE_MS = 2500

    def __init__(self, master, on_jump):
        """on_jump: callable(page_index) used by both the slider and the entry box."""
        super().__init__(master)
        self.on_jump = on_jump
        self.status = tk.StringVar()
        self._slider_var = tk.DoubleVar(value=1)
        self._lock = False          # True while we move the slider ourselves
        self._slider_job = None
        self._before = None
        self._autohide = False
        self._visible = True
        self._hide_job = None

        self.slider = ttk.Scale(self, from_=1, to=2, orient="horizontal",
                                variable=self._slider_var, command=self._on_slider,
                                takefocus=False)
        self.slider.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 0))
        ttk.Label(self, textvariable=self.status, anchor="w").grid(
            row=1, column=0, sticky="ew", padx=8, pady=2)
        self.entry = ttk.Entry(self, width=5, justify="center")
        self.entry.grid(row=1, column=1, padx=(4, 0))
        self.entry.bind("<Return>", self._on_entry)
        self.total_lbl = ttk.Label(self, text="/ 0")
        self.total_lbl.grid(row=1, column=2, padx=(2, 8))
        self.columnconfigure(0, weight=1)

    # ---- content -------------------------------------------------------------------- #
    def set_pages(self, n: int):
        self.slider.configure(to=max(2, n))
        self.slider.state(["!disabled"] if n > 1 else ["disabled"])
        self.total_lbl.config(text=f"/ {n}")

    def set_page(self, page: int):
        self._lock = True
        self._slider_var.set(page + 1)
        self._lock = False
        try:
            typing = self.focus_get() is self.entry
        except KeyError:  # focus_get can raise while a combobox popup is open
            typing = False
        if not typing:
            self.entry.delete(0, "end")
            self.entry.insert(0, str(page + 1))

    def set_status(self, text: str):
        self.status.set(text)

    # ---- user input ------------------------------------------------------------------- #
    def _on_slider(self, value):
        if self._lock:
            return
        if self._slider_job:
            self.after_cancel(self._slider_job)
        page = int(round(float(value))) - 1
        self._slider_job = self.after(150, lambda: self._fire(page))  # wait until dragging pauses

    def _fire(self, page: int):
        self._slider_job = None
        self.on_jump(page)

    def _on_entry(self, event):
        try:
            n = int(self.entry.get())
        except ValueError:
            return
        self.on_jump(n - 1)

    # ---- docking / auto-hide ------------------------------------------------------------ #
    def dock(self, before):
        """Pack the bar at the bottom, above `before` (the main frame)."""
        self._before = before
        self._apply_mode()

    def set_autohide(self, flag: bool):
        self._autohide = flag
        self._apply_mode()

    def _apply_mode(self):
        if self._hide_job:
            self.after_cancel(self._hide_job)
            self._hide_job = None
        self.pack_forget()
        self.place_forget()
        if self._autohide:
            self._visible = False
            self.poke()
        else:
            self._visible = True
            self.pack(side="bottom", fill="x", before=self._before)

    def poke(self):
        """Show the bar (if auto-hide is on) and restart the hide timer."""
        if not self._autohide:
            return
        if not self._visible:
            self.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")
            self.lift()
            self._visible = True
        if self._hide_job:
            self.after_cancel(self._hide_job)
        self._hide_job = self.after(self.HIDE_MS, self._hide)

    def _hide(self):
        self._hide_job = None
        if self._autohide and self._visible:
            self.place_forget()
            self._visible = False
