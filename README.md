# Comic Reader

A desktop comic and manga reader written in Python with tkinter.

It reads CBZ, CBR, CBT, CB7, PDF and plain folders of images, remembers where you stopped, and opens on
a **library** of your comic folders with covers. It also has a continuous-scroll (webtoon) mode,
bookmarks, themes and rebindable keys.

## Quick start

```powershell
cd "C:\Users\Ivenlee_KR\Documents\Python File\Comic Reader"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py                      # or: python main.py "D:\Comics\Some Comic.cbz"
```

Only **Pillow** is required. Every other package switches on one feature, and a missing package only
disables that feature:

| Package        | Enables                                   | Notes                                            |
|----------------|-------------------------------------------|--------------------------------------------------|
| `pillow`       | everything (image decoding)               | required                                         |
| `pymupdf`      | PDF                                       |                                                  |
| `rarfile`      | CBR / RAR                                 | also needs WinRAR (`UnRAR.exe`) or 7-Zip installed |
| `py7zr`        | CB7 / CBA / 7z                            |                                                  |
| `tkinterdnd2`  | drag & drop onto the window               |                                                  |

## Supported files

CBZ/ZIP, CBR/RAR, CBT/TAR, CB7/CBA/7Z, PDF, and folders of images (sub-folders are included, pages are
sorted naturally so `page2` comes before `page10`). The format is detected from the file's header bytes,
not its extension, so a mis-named file still opens. Opening a single image opens its whole folder,
starting at that image.

If the comic contains a `ComicInfo.xml`, its title, series, number, author and manga flag are used
(for the library, the properties dialog and automatic right-to-left detection).

## Using it

**Opening**: the app starts on the library: pick a comic there. You can also use Ctrl+O (file),
Ctrl+Shift+O (folder), File > Open Recent, or drop files/folders on the window. Ctrl+L, the Library
menu or Esc goes back to the library, and "Continue" there returns to the comic you were reading. Dropping several comics queues them: `[` and `]` switch between them, and
pressing "next" twice at the last page moves to the next comic.

**Mouse**: click the left or right 30% of the window to turn the page, double-click the centre for
fullscreen, drag to pan, drag sideways to swipe when the page fits the width, wheel to scroll (or flip
pages, or zoom: View > Mouse Wheel), Ctrl+wheel to zoom.

**Reading modes** (View menu): single page, double-page spreads (cover and wide pages stay single),
webtoon (continuous vertical scroll), right-to-left for manga. Fit width / height / page / original size,
zoom, 90-degree rotation. The mode and direction are remembered per comic.

**Look**: dark / light / high-contrast theme, background colour, brightness, sepia and night filters,
UI scale up to 200%, optional auto-hiding progress bar.

### Default keys

| Key                  | Action                                        |
|----------------------|-----------------------------------------------|
| Right / Left         | next / previous page (swapped in RTL mode)    |
| PgDn / PgUp          | next / previous page                          |
| Backspace            | previous page                                 |
| Space / Shift+Space  | scroll down / up, turning the page at the edge |
| Home / End           | first / last page                             |
| Ctrl+G               | go to page                                    |
| 1 / 2 / 3 / 4        | fit width / height / page / original size     |
| + / - / 0            | zoom in / out / reset                         |
| R / Shift+R          | rotate clockwise / counter-clockwise          |
| D                    | toggle double-page                            |
| W                    | toggle webtoon mode                           |
| M                    | toggle right-to-left                          |
| F or F11 / Esc       | fullscreen / leave fullscreen                 |
| B                    | bookmark this page                            |
| Ctrl+D               | favourite this comic                          |
| [ / ]                | previous / next comic in the queue            |
| Ctrl+O / Ctrl+Shift+O| open file / open folder                       |
| Ctrl+L               | library / back to the comic                   |
| Ctrl+I               | comic properties                              |

Every key can be changed under **File > Keyboard Shortcuts**.

### Library

The library is the home screen (Ctrl+L or the Library menu returns to it). **Add Folder** adds a root folder (you can add as many as you like); it
shows up as one tile named after its parent and itself with the numbering removed, e.g.
`D:\Comics\DC\1. Absolute Series` becomes **DC - Absolute Series**. Open a tile to see its
sub-folders and comics, keep going deeper, and open a comic to read it. **Up**, Backspace or Alt+Left
goes back a level; the breadcrumb shows where you are. The library remembers the folder you were in.

Opening a comic queues the other comics in that folder, so `]` and `[` move to the next and previous
one. Folders are scanned in the background when the app starts, so new comics appear by themselves;
**Rescan** does it on demand. Grid or list view, search, sort (name, series, date added, last read) and
filters (favourites, unread, in progress, finished). Searching or filtering shows matching comics from
the folder you are in and everything below it. Right-click a comic to open it, favourite it, show it in
Explorer or remove it; right-click a root folder to remove it from the library (files on disk are never
touched). **File > Rebuild Cover Cache** redraws every cover.

## Where your data lives

Everything is stored in `%USERPROFILE%\.comic_reader\`:

| File            | Contents                                                             |
|-----------------|----------------------------------------------------------------------|
| `state.json`    | last page per comic, bookmarks, favourites, settings, key bindings, statistics |
| `library.json`  | the root folders and the scanned comics                              |

Cover thumbnails are kept separately in `%APPDATA%\ComicReader\thumbnails\` as `<id>.thumbnail`
files (JPEG, 300x450, named from a SHA-1 of the comic's path). They are rebuilt automatically if
missing, deleted when a comic or folder is removed, and covers from older versions
(`.comic_reader\thumbs`) are moved over on first start; you can delete that old folder afterwards.

Delete the `.comic_reader` folder to reset everything. Use **File > Export Progress / Import Progress** to move your
progress to another computer. An old v1 `~\.comic_reader.json` is picked up automatically.

## Project layout

```
main.py                 starts the app
requirements.txt
build.bat               builds a Windows .exe with PyInstaller
ComicReader.spec        PyInstaller recipe
assets/
    icon.ico            app icon (exe + window)
    icon.png
comicreader/
    app.py              main window (ComicReader): library and reader pages, wires everything together
    constants.py        file types, storage paths, asset paths, themes
    core/               no GUI code
        sources.py        one class per format + SourceFactory
        storage.py        Store (reading state) and LibraryDB
        session.py        ComicSession, ComicQueue, PageCache, ReadingStats
        keybindings.py    KeyBindings (rebindable actions)
    ui/
        views.py          PagedView (single/double) and WebtoonView
        menubar.py  widgets.py  controls.py  dialogs.py  dragdrop.py  theme.py
    library/
        scanner.py        builds records + covers, scans folders in a thread
        manager.py        LibraryManager
        window.py         the library page (LibraryView)
    utils/
        helpers.py        small stateless helpers
```

## Building an .exe

```powershell
.\build.bat             # folder build:  dist\ComicReader\ComicReader.exe
.\build.bat onefile     # single file:   dist\ComicReader.exe (slower to start)
```

The script creates `.venv` if needed, installs `requirements.txt` and PyInstaller, and runs PyInstaller.
The `assets\` folder is bundled into the build and `assets\icon.ico` becomes the exe icon; to change the
icon, replace that file and rebuild. CBR still needs WinRAR or 7-Zip installed on the machine that runs the exe.

## Troubleshooting

- **"CBR/RAR support needs..."**: `pip install rarfile` and install WinRAR (or 7-Zip).
- **"PDF support needs..."**: `pip install pymupdf`.
- **Drag & drop does nothing / a hint appears on the welcome screen**: `pip install tkinterdnd2`.
- **A page shows "failed to load"**: that image is corrupt; the rest of the comic still works.
- **Keys stop working after typing in the page box**: click the reading area (or press Enter in the box).

## Known limitations

- No screen-reader support (tkinter doesn't expose one); high-contrast theme, UI scale and full keyboard
  control are provided instead.
- Rotation applies to single and double-page modes, not webtoon mode.
- No page-turn animations, tabs or pinch-zoom (multiple comics are queued instead).