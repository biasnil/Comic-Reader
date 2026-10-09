"""WorkerClient: starts the Manga Translator helper process and exchanges messages with it.

A reader thread turns the worker's stdout lines into messages on a queue; the UI drains that
queue with after() (the same pattern as library/manager.py), so tkinter is only touched on the
UI thread. stderr goes to a log file.
"""
import queue
import subprocess
import sys
import threading
from pathlib import Path

from ..constants import BASE_DIR
from ..core.translation import LOG_FILE, read_message, worker_command, write_message


class WorkerClient:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.messages: "queue.Queue[dict]" = queue.Queue()
        self._log = None

    @staticmethod
    def available() -> bool:
        return worker_command(BASE_DIR) is not None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        """Start the worker (raises RuntimeError if the plugin isn't installed)."""
        if self.running:
            return
        found = worker_command(BASE_DIR)
        if found is None:
            raise RuntimeError("The Manga Translator plugin isn't installed (Plugins > Manage…)")
        argv, cwd = found
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(
            argv, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
        # a fresh queue per process, so a late "exited" from an old one can't reach the new one
        self.messages = queue.Queue()
        threading.Thread(target=self._pump, args=(self.proc, self.messages), daemon=True).start()

    @staticmethod
    def _pump(proc: subprocess.Popen, out: queue.Queue):
        for line in proc.stdout:
            msg = read_message(line)
            if msg is not None:
                out.put(msg)
        out.put({"type": "exited", "code": proc.wait()})

    def send(self, cmd: str, **fields) -> bool:
        if not self.running:
            return False
        try:
            write_message(self.proc.stdin, {"cmd": cmd, **fields})
            return True
        except (OSError, ValueError):
            return False

    def stop(self):
        if self.proc is None:
            return
        self.send("quit")
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=2)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.proc.kill()
        self.proc = None
        if self._log:
            self._log.close()
            self._log = None

    @staticmethod
    def log_path() -> Path:
        return LOG_FILE
