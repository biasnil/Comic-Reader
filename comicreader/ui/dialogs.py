"""Dialog windows."""
import tkinter as tk
from tkinter import ttk

from ..utils.helpers import key_string, pretty_key


class KeysDialog(tk.Toplevel):
    """Shows every action with its keys and lets the user replace, add, clear or reset them."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.keys = app.keys
        self.title("Keyboard Shortcuts")
        self.geometry("520x560")
        self.transient(app)
        self.configure(bg=app.colors["panel"])
        self.tree = ttk.Treeview(self, columns=("action", "keys"), show="headings",
                                 selectmode="browse")
        self.tree.heading("action", text="Action")
        self.tree.heading("keys", text="Keys")
        self.tree.column("action", width=300)
        self.tree.column("keys", width=180)
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        row = ttk.Frame(self)
        row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(row, text="Replace key…", command=lambda: self.capture(False)).pack(side="left")
        ttk.Button(row, text="Add key…", command=lambda: self.capture(True)).pack(side="left", padx=4)
        ttk.Button(row, text="Clear", command=self.clear).pack(side="left")
        ttk.Button(row, text="Reset all", command=self.reset).pack(side="left", padx=4)
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        self.fill()

    def fill(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for name, action in self.keys.actions.items():
            keys = ", ".join(pretty_key(k) for k in self.keys.keys_for(name))
            self.tree.insert("", "end", iid=name, values=(action.label, keys))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def capture(self, add: bool):
        name = self._selected()
        if not name:
            return
        win = tk.Toplevel(self)
        win.title("Press a key")
        win.transient(self)
        win.configure(bg=self.app.colors["panel"])
        ttk.Label(win, padding=20, text=f"Press the key(s) for:\n{self.keys.actions[name].label}\n\n"
                                        "(Esc cancels)").pack()
        try:
            win.wait_visibility()
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()

        def on_key(e):
            if e.keysym.endswith(("_L", "_R")) or e.keysym in ("Caps_Lock", "Num_Lock"):
                return
            if e.keysym == "Escape":
                win.destroy()
                return
            self.keys.set_key(name, key_string(e), add)
            win.destroy()
            self.fill()

        win.bind("<Key>", on_key)

    def clear(self):
        name = self._selected()
        if name:
            self.keys.clear(name)
            self.fill()

    def reset(self):
        self.keys.reset()
        self.fill()
