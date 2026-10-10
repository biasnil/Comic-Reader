# Comic Reader

A desktop comic and manga reader written in Python with tkinter.

It reads CBZ, CBR, CBT, CB7, PDF and plain folders of images, remembers where you stopped, and opens on
a **library** of your comic folders with covers. It also has a continuous-scroll (webtoon) mode,
bookmarks, themes and rebindable keys.

The optional **Manga Translator** plugin translates Japanese manga pages into English while you read
(Koharu-style: detect the text, read it, erase it and draw the English in the bubble). See
[Manga Translator plugin](#manga-translator-plugin).

The optional **Bubble Reader** plugin reads the speech bubbles aloud in reading order with natural voices,
highlighting each one as it's read. See [Bubble Reader plugin](#bubble-reader-plugin).

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
| Ctrl+E               | edit this page's translations                 |
| P / Shift+P          | read bubbles aloud, pause / stop (Bubble Reader plugin) |
| . / ,                | next / previous bubble while reading aloud    |

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
the pages after it; the status bar shows progress. Translations are saved, so re-opening a comic shows
them instantly. On first use the plugin asks to download its text-detection model (95 MB, once).

| Translate menu                      | Does                                                                  |
|-------------------------------------|-----------------------------------------------------------------------|
| Translate Pages (T)                 | translation on/off                                                    |
| Translate Whole Comic               | every page in the background, with a progress window (Hide / Stop)    |
| Edit Translations… (Ctrl+E)         | change a bubble's English or pin its font size; the page is redrawn in a moment without re-running the AI |
| Retranslate This Page               | throw the page's translation away and do it again                     |
| Export Translated Comic (CBZ)…      | a `.cbz` with the translated pages (untranslated ones stay in Japanese), readable in any comic reader |
| Delete This Comic's Translations…   | remove them all                                                       |
| Translation Settings…               | translator, OCR, text removal, language, font, GPU                    |

**Translator (Translation Settings)**

| Translator | Setup |
|------------|-------|
| Local server, free (default) | Install [Ollama](https://ollama.com), run `ollama pull qwen2.5vl:7b`. Server URL `http://localhost:11434/v1`, model `qwen2.5vl:7b`. LM Studio works too (`http://localhost:1234/v1`). |
| Claude | Choose *Anthropic (Claude)* and enter an API key (or set `ANTHROPIC_API_KEY`). Default model `claude-opus-5-5`. |
| GGUF model file (llama.cpp) | Choose a `.gguf` file; it runs inside the plugin, no server needed. Needs the local OCR (it can't read images). From source: `pip install llama-cpp-python`. |
| OpenAI or another hosted OpenAI-compatible API | Its URL, model name and API key. |

All the text on a page goes to the model in one request, in reading order (right-to-left in manga mode),
so it translates with context.

**Reading the Japanese ("Read Japanese with")**

| Option | |
|--------|---|
| Local OCR model | manga-ocr converted to ONNX: accurate, offline, works in the exe. Downloads about 450 MB once. |
| The translator reads the image | no OCR; each bubble goes to the model as a picture, so it must be a vision model |
| manga-ocr package | the original (from source, `pip install manga-ocr`, installs PyTorch) |
| Automatic (default) | manga-ocr package if installed, else the local OCR model if downloaded, else the translator reads the image |

**Removing the Japanese ("Remove original text")**: plain bubbles are always filled with their background
colour. For text over artwork or screentone, **LaMa** (an inpainting AI, downloads about 200 MB once)
repaints what was under the text; without it OpenCV does a simpler job, and with neither the English goes
in a white box. *Automatic* uses LaMa once it's downloaded.

The English is word-wrapped and shrunk to fit each bubble, in Comic Neue Bold or a font you choose.
Rotation, filters and double-page spreads work on translated pages as usual.

**Where the AI models come from**: the text detector comes from manga-image-translator's GitHub release.
The local OCR model and LaMa come from this repo's **`models-v1`** release, which the **Models** workflow
creates (Actions tab > Models > Run workflow, once): it converts manga-ocr to ONNX, checks it against the
original, copies LaMa, and publishes both with their SHA-256 checksums. Every download is checked.

| Plugin package             | Enables                                   |
|----------------------------|-------------------------------------------|
| `numpy`, `onnxruntime`     | the plugin (required)                     |
| `anthropic`                | the Claude translator                     |
| `opencv-python-headless`   | simpler text removal on artwork when LaMa isn't downloaded |
| `llama-cpp-python`         | the GGUF model translator (optional)      |
| `manga-ocr`                | the original OCR package (optional, large) |
| `onnxruntime-directml`     | GPU on Windows, instead of `onnxruntime` (`onnxruntime-gpu` for NVIDIA CUDA) |

## Bubble Reader plugin

Reads a comic's speech bubbles **aloud**, one after another, in reading order: **right to left** for
manga (when the reader is in right-to-left mode, which switches on by itself for manga) and **left to right**
otherwise. The bubble being read is outlined and kept in view, and after the last bubble the page turns
and reading carries on. It uses the same natural Kokoro voices as EchoRead, fully offline. It is a separate
plugin from the Manga Translator: install either or both (setup.exe or **Plugins > Manage…**; from source,
`pip install -r plugins/bubble_reader/requirements.txt`). Without it, the Read Aloud menu doesn't appear.

| Key        | Read Aloud menu         |
|------------|-------------------------|
| P          | read aloud / pause / resume |
| . / ,      | next / previous bubble  |
| Shift+P    | stop                    |
| click a bubble | read from that bubble (while reading) |

**What it reads**

| Page | Text comes from |
|------|-----------------|
| translated by the Manga Translator (Translate Pages on) | the English translation, straight away |
| Japanese manga | manga-ocr (the local OCR model), read with a Japanese voice |
| English comic | RapidOCR, a small English OCR built into the plugin |

The plugin finds the bubbles with the same text detector as the translator (the 95 MB model is shared, not
downloaded twice). Pages are analysed ahead while you listen, and saved, so re-reading is instant.

**Settings (Read Aloud > Bubble Reader Settings…)**: English and Japanese voice (12 English, 5 Japanese),
speed (0.5x–2x), volume, the comic's language (automatic, Japanese or English), whether translated pages are
read in English, skipping **sound effects** (short text drawn over the art, like ドン or BAM!), turning the
page after the last bubble, and scrolling to the bubble being read. **Find This Page's Bubbles Again**
redoes a page (after changing the language, say).

On first use it asks to download what it needs, once: the text detector (95 MB, if the translator hasn't
already), the Japanese OCR model (about 450 MB, from this repo's `models-v1` release; only needed for
manga) and the Kokoro voices (about 350 MB, from Kokoro's GitHub releases). Everything then runs offline.

| Plugin package             | Enables                                   |
|----------------------------|-------------------------------------------|
| `numpy`, `onnxruntime`     | the plugin (required)                     |
| `pykokoro[cpu]==0.10.4`    | the Kokoro voices (pinned: its API changed in 0.10) |
| `pyopenjtalk-plus`         | Japanese pronunciation for the Japanese voices |
| `sounddevice`              | sound output (without it, or without a sound device, it reads silently) |
| `rapidocr-onnxruntime>=1.4`| reading English comics (Python 3.12 or older) |
| `wordninja`                | splits words that OCR glued together      |

## Where your data lives

Everything is stored in `%USERPROFILE%\.comic_reader\`:

| File            | Contents                                                             |
|-----------------|----------------------------------------------------------------------|
| `state.json`    | last page per comic, bookmarks, favourites, settings, key bindings, statistics |
| `library.json`  | the root folders and the scanned comics                              |
| `translations\` | per comic `<id>\`: `0007.png` translated page, `0007.clean.png` page without text (for editing), `0007.json` text and boxes |
| `models\`       | the plugins' downloaded models (detector, LaMa, local OCR, `kokoro\` voices) |
| `bubbles\`      | the Bubble Reader's analysed pages: `<id>\0007-ja.json` (boxes and text) |
| `plugins\`      | plugins installed from Plugins > Manage, and their log files          |

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
        plugins.py        the plugin registry: where each plugin's worker is, the message format
        translation.py    the Manga Translator contract: protocol, translation cache, paths
        bubbles.py        the Bubble Reader contract: protocol, settings, voices, bubble cache
        export.py         translated-CBZ export
    plugins/            reader side of the plugins: worker client, controllers, installer, dialogs, editor
    ui/
        views.py          PagedView (single/double) and WebtoonView
        menubar.py  widgets.py  controls.py  dialogs.py  dragdrop.py  theme.py
    library/
        scanner.py        builds records + covers, scans folders in a thread
        manager.py        LibraryManager
        window.py         the library page (LibraryView)
    utils/
        helpers.py        small stateless helpers
tools/export_models.py      builds the models-v1 release (manga-ocr to ONNX, LaMa); run by the Models workflow
plugins/common/             shared by the plugins: detector.py  models.py  mangaocr.py  layout.py
plugins/manga_translator/   the Manga Translator plugin (its own process)
    worker.py  pipeline.py  ocr.py  inpaint.py  translator.py  typeset.py
    MangaTranslator.spec  requirements.txt  assets/fonts/ (Comic Neue, OFL)
plugins/bubble_reader/      the Bubble Reader plugin (its own process)
    worker.py  analyze.py  speech.py  BubbleReader.spec  requirements.txt
docs/MANGA_TRANSLATOR_BRIEF.md  docs/BUBBLE_READER_BRIEF.md
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
.\build.bat plugin      # both plugins: dist\manga-translator\ and dist\bubble-reader\
.\build.bat installer   # reader + plugins + dist\ComicReader-Setup-dev.exe (needs Inno Setup 6)
```

Set `VERSION` first (`set VERSION=1.3.0`) to name the installer. The installer has Start Menu and desktop
shortcuts, an uninstaller, optional Manga Translator and Bubble Reader components and optional file associations. It
never touches your data in `.comic_reader`. Unsigned builds make Windows SmartScreen ask
"More info > Run anyway" the first time. To sign them, add a code-signing certificate as two repository
secrets, `SIGN_PFX_BASE64` (the .pfx, base64-encoded) and `SIGN_PFX_PASSWORD`; the release workflow then
signs the exe files and `setup.exe` by itself.

**Releases are built on GitHub** (`.github/workflows/release.yml`, on Windows runners):

| Push a tag          | The release gets                                                          |
|---------------------|---------------------------------------------------------------------------|
| `v1.3.0`            | `ComicReader-Setup-1.3.0.exe`, `ComicReader-1.3.0-win64.zip`, `MangaTranslator-plugin-win64.zip` + `.sha256` |
| `translator-v0.2.0` | only the plugin zip + `.sha256`: an update that Plugins > Manage offers   |
| `bubblereader-v0.1.1` | only `BubbleReader-plugin-win64.zip` + `.sha256`: likewise              |

The **Models** workflow (run by hand) publishes the optional AI models as the `models-v1` release.

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
- **Read Aloud is silent**: the status bar says "reading silently" when there's no sound device or
  `sounddevice` is missing; highlighting and page turning still work.
- **Read Aloud reads the wrong language**: set the comic's language in Bubble Reader Settings, then
  Read Aloud > Find This Page's Bubbles Again. Manga is read in Japanese when right-to-left is on.
- **"Japanese voices need pyopenjtalk-plus"**: `pip install pyopenjtalk-plus` (from source).
- **Read Aloud skips some text**: sound effects are skipped by default (Bubble Reader Settings).
- **"… isn't published yet: run the 'Models' workflow"**: the local OCR / LaMa options need the `models-v1`
  release; run Actions > Models once.
- **Edit Translations says to retranslate first**: pages translated before plugin 0.2.0 have no saved
  text-free page; Retranslate This Page once.

## Known limitations

- No screen-reader support (tkinter doesn't expose one); high-contrast theme, UI scale and full keyboard
  control are provided instead.
- Rotation applies to single and double-page modes, not webtoon mode.
- No page-turn animations, tabs or pinch-zoom (multiple comics are queued instead).