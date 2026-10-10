# Comic Reader

A desktop comic and manga reader written in Python with tkinter.

It reads CBZ, CBR, CBT, CB7, PDF and plain folders of images, remembers where you stopped, and opens on
a **library** of your comic folders with covers. It also has a continuous-scroll (webtoon) mode,
bookmarks, themes and rebindable keys.

The optional **Manga Translator** plugin translates Japanese manga pages into English while you read
(Koharu-style: detect the text, read it, erase it and draw the English in the bubble). See
[Manga Translator plugin](#manga-translator-plugin).

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
| T                    | translate pages on/off (Manga Translator plugin) |

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

## Manga Translator plugin

A plugin that translates Japanese manga into English page by page. It lives in this repository
(`plugins/manga_translator/`) but runs as its own helper process, so the reader stays as small and fast as
before. Without the plugin, the Translate menu doesn't appear.

**Installing**
- **Installer:** tick *Manga Translator plugin* in `ComicReader-Setup-<version>.exe`.
- **From the reader:** **Plugins > Manage…** downloads the latest plugin from this repo's GitHub Releases,
  checks its SHA-256 and installs it to `%USERPROFILE%\.comic_reader\plugins\manga-translator\`.
  The same window updates or removes it.
- **From source:** `pip install -r plugins/manga_translator/requirements.txt`. `python main.py` finds the plugin by itself.

**Using it**: press **T** (or Translate > Translate Pages). The page on screen is translated first, then
the pages after it; the status bar shows progress. **Translate Whole Comic** queues every page.
Translations are saved, so re-opening a comic shows them instantly. **Retranslate This Page** and
**Delete This Comic's Translations** redo them. On first use the plugin asks to download its text-detection
model (95 MB, once).

**Translator (Translate > Translation Settings…)**

| Translator | Setup |
|------------|-------|
| Local, free (default) | Install [Ollama](https://ollama.com), run `ollama pull qwen2.5vl:7b`. Server URL `http://localhost:11434/v1`, model `qwen2.5vl:7b`. LM Studio works too (`http://localhost:1234/v1`). |
| Claude | Choose *Anthropic (Claude)* and enter an API key (or set `ANTHROPIC_API_KEY`). Default model `claude-opus-5-5`. |
| OpenAI or another hosted OpenAI-compatible API | Its URL, model name and API key. |

All the text on a page goes to the model in one request, in reading order (right-to-left in manga mode),
so it translates with context. By default the model reads the Japanese from an image of each bubble, so
it must be a vision model. With `pip install manga-ocr` (large: it installs PyTorch) the text is read
locally instead, and any text model works.

**How a page is done**: comic-text-detector (ONNX) finds the text and a pixel mask of it. Then the text is
read and translated, plain bubbles are filled with their background colour, text over artwork is
inpainted (needs `opencv-python-headless`) or covered with a white box, and the English is word-wrapped
and shrunk to fit the bubble in Comic Neue Bold. Rotation, filters and double-page spreads work on
translated pages as usual.

| Plugin package             | Enables                                   |
|----------------------------|-------------------------------------------|
| `numpy`, `onnxruntime`     | the plugin (required)                     |
| `anthropic`                | the Claude translator                     |
| `opencv-python-headless`   | erasing text drawn over artwork           |
| `manga-ocr`                | local Japanese OCR (optional, large)      |
| `onnxruntime-directml`     | GPU on Windows, instead of `onnxruntime` (`onnxruntime-gpu` for NVIDIA CUDA) |

## Where your data lives

Everything is stored in `%USERPROFILE%\.comic_reader\`:

| File            | Contents                                                             |
|-----------------|----------------------------------------------------------------------|
| `state.json`    | last page per comic, bookmarks, favourites, settings, key bindings, statistics |
| `library.json`  | the root folders and the scanned comics                              |
| `translations\` | translated pages: `<id>\0007.png` + `0007.json` (text, boxes) per comic |
| `models\`       | the plugin's downloaded models                                        |
| `plugins\`      | the plugin installed from Plugins > Manage, and its log file          |

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
Icon/assets/
    icon.ico            app icon (exe + window)
    icon.png
installer/ComicReader.iss   Inno Setup script for setup.exe
.github/workflows/release.yml  builds the releases on GitHub (see Releases below)
comicreader/
    app.py              main window (ComicReader): library and reader pages, wires everything together
    constants.py        file types, storage paths, asset paths, themes
    core/               no GUI code
        sources.py        one class per format + SourceFactory
        storage.py        Store (reading state) and LibraryDB
        session.py        ComicSession, ComicQueue, PageCache, ReadingStats
        keybindings.py    KeyBindings (rebindable actions)
        translation.py    the plugin contract: messages, translation cache, paths
    plugins/            reader side of the plugin: worker client, controller, installer, dialogs
    ui/
        views.py          PagedView (single/double) and WebtoonView
        menubar.py  widgets.py  controls.py  dialogs.py  dragdrop.py  theme.py
    library/
        scanner.py        builds records + covers, scans folders in a thread
        manager.py        LibraryManager
        window.py         the library page (LibraryView)
    utils/
        helpers.py        small stateless helpers
plugins/manga_translator/   the Manga Translator plugin (its own process)
    worker.py  pipeline.py  detector.py  ocr.py  inpaint.py  translator.py  typeset.py  models.py
    MangaTranslator.spec  requirements.txt  assets/fonts/ (Comic Neue, OFL)
docs/MANGA_TRANSLATOR_BRIEF.md
```

## Building an .exe

```powershell
.\build.bat             # folder build:  dist\ComicReader\ComicReader.exe
.\build.bat onefile     # single file:   dist\ComicReader.exe (slower to start)
```

The script creates `.venv` if needed, installs `requirements.txt` and PyInstaller, and runs PyInstaller.
The `Icon\assets\` folder is bundled into the build and `Icon\assets\icon.ico` becomes the exe icon (and the installer's icon); to change the
icon, replace that file and rebuild. CBR still needs WinRAR or 7-Zip installed on the machine that runs the exe.

### Plugin, installer and releases

```powershell
.\build.bat plugin      # dist\manga-translator\manga-translator-worker.exe
.\build.bat installer   # reader + plugin + dist\ComicReader-Setup-dev.exe (needs Inno Setup 6)
```

Set `VERSION` first (`set VERSION=1.3.0`) to name the installer. The installer has Start Menu and desktop
shortcuts, an uninstaller, an optional Manga Translator component and optional file associations. It
never touches your data in `.comic_reader`. It is not code-signed yet, so Windows SmartScreen asks
"More info > Run anyway" the first time.

**Releases are built on GitHub** (`.github/workflows/release.yml`, on Windows runners):

| Push a tag          | The release gets                                                          |
|---------------------|---------------------------------------------------------------------------|
| `v1.3.0`            | `ComicReader-Setup-1.3.0.exe`, `ComicReader-1.3.0-win64.zip`, `MangaTranslator-plugin-win64.zip` + `.sha256` |
| `translator-v0.2.0` | only the plugin zip + `.sha256`: an update that Plugins > Manage offers   |

```powershell
git tag v1.3.0
git push origin v1.3.0
```

## Troubleshooting

- **"CBR/RAR support needs..."**: `pip install rarfile` and install WinRAR (or 7-Zip).
- **"PDF support needs..."**: `pip install pymupdf`.
- **Drag & drop does nothing / a hint appears on the welcome screen**: `pip install tkinterdnd2`.
- **A page shows "failed to load"**: that image is corrupt; the rest of the comic still works.
- **Keys stop working after typing in the page box**: click the reading area (or press Enter in the box).
- **Translation: "Can't reach http://localhost:11434…"**: start Ollama (or LM Studio's server), or pick another
  translator under Translate > Translation Settings.
- **Translation: bubbles come back empty or wrong**: the model must be able to read images (e.g. `qwen2.5vl`,
  Claude), or install `manga-ocr` so the text is read locally.
- **Translation is slow**: text detection runs on the CPU (several seconds a page). A GPU build of onnxruntime
  (`onnxruntime-directml` / `onnxruntime-gpu`) speeds it up. Meanwhile, Translate Whole Comic works ahead in the background.
- **The translator stopped unexpectedly**: details are in `.comic_reader\plugins\manga-translator.log`.
- **Translation of a password-protected PDF**: not supported (the plugin opens the comic by itself).

## Known limitations

- No screen-reader support (tkinter doesn't expose one); high-contrast theme, UI scale and full keyboard
  control are provided instead.
- Rotation applies to single and double-page modes, not webtoon mode.
- No page-turn animations, tabs or pinch-zoom (multiple comics are queued instead).