"""Mouse handling for the reading area."""
import time


class MouseController:
    """Wheel, click zones, drag-to-pan, swipe and double-click on the reader canvas."""

    CLICK_SLOP = 6            # movement (px) below which a press/release counts as a click
    EDGE = 0.3                # left/right 30% of the width turn pages
    SWIPE_MIN = 120
    SWIPE_MAX_OFF_AXIS = 80
    FLIP_INTERVAL = 0.15      # seconds between page flips when the wheel flips pages

    def __init__(self, app):
        self.app = app
        self._press = None
        self._last_flip = 0.0

    def attach(self):
        a, c = self.app, self.app.canvas
        a.bind("<MouseWheel>", self.on_wheel)
        a.bind("<Button-4>", self.on_wheel)  # Linux
        a.bind("<Button-5>", self.on_wheel)
        a.bind("<Motion>", self.on_motion)
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)

    def on_motion(self, event):
        self.app.progress.poke()

    def on_wheel(self, event):
        a = self.app
        if a.in_library:  # the library scrolls itself; don't flip/zoom the hidden page
            return
        num = getattr(event, "num", 0)
        delta = 1 if num == 4 else -1 if num == 5 else (1 if event.delta > 0 else -1)
        if event.state & 0x4:  # Ctrl always zooms
            a.change_zoom(1.1 if delta > 0 else 1 / 1.1)
        elif event.state & 0x1:  # Shift scrolls sideways
            a.canvas.xview_scroll(-delta * 3, "units")
        else:
            behaviour = a.wheel.get()
            if behaviour == "zoom":
                a.change_zoom(1.1 if delta > 0 else 1 / 1.1)
            elif behaviour == "flip":
                now = time.time()
                if now - self._last_flip > self.FLIP_INTERVAL:
                    self._last_flip = now
                    a.prev_page() if delta > 0 else a.next_page()
            else:
                a.canvas.yview_scroll(-delta * 3, "units")

    def on_press(self, event):
        c = self.app.canvas
        c.focus_set()
        c.scan_mark(event.x, event.y)
        self._press = (event.x, event.y)

    def on_drag(self, event):
        self.app.canvas.scan_dragto(event.x, event.y, gain=1)

    def on_release(self, event):
        a = self.app
        if not self._press or not a.session.is_open:
            return
        dx, dy = event.x - self._press[0], event.y - self._press[1]
        if abs(dx) + abs(dy) < self.CLICK_SLOP:  # a click: left/right edges turn the page
            w = a.canvas.winfo_width()
            if event.x > w * (1 - self.EDGE):
                a.go_right()
            elif event.x < w * self.EDGE:
                a.go_left()
        elif (abs(dx) > self.SWIPE_MIN and abs(dy) < self.SWIPE_MAX_OFF_AXIS
              and not a.view.continuous and a.canvas.xview() == (0.0, 1.0)):
            a.go_right() if dx < 0 else a.go_left()  # swipe (page fits horizontally)

    def on_double(self, event):
        a = self.app
        w = a.canvas.winfo_width()
        if w * self.EDGE <= event.x <= w * (1 - self.EDGE):
            if a.dbl_action.get() == "fullscreen":
                a.toggle_fullscreen()
            else:
                a.set_fit("page" if a.fit.get() == "width" else "width")