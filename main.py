"""
Comic Reader - start the application.

Run:      python main.py [file-or-folder]
Install:  pip install pillow pymupdf rarfile py7zr tkinterdnd2
          (pymupdf = PDF, rarfile + WinRAR/UnRAR = CBR, py7zr = CB7, tkinterdnd2 = drag & drop;
           a missing library only disables that one feature)

Layout:
    main.py                  <- you are here
    assets/                  icon.ico (exe + window icon), icon.png
    comicreader/
        app.py               main window (ComicReader)
        constants.py         file types, storage paths, themes
        core/                no GUI: sources.py  storage.py  session.py  keybindings.py
        ui/                  widgets & drawing: views.py  menubar.py  widgets.py  controls.py
                             dialogs.py  dragdrop.py  theme.py
        library/             scanner.py  manager.py  window.py
        utils/               helpers.py
"""
import sys

from comicreader.app import ComicReader


def main():
    if sys.platform == "win32":  # crisp rendering on high-DPI displays
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
            # own taskbar identity, so the taskbar shows our icon instead of Python's
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("ComicReader.App")
        except Exception:
            pass
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    ComicReader(initial).mainloop()


if __name__ == "__main__":
    main()
