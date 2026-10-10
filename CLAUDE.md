# CLAUDE.md: Comic Reader (handoff notes)

Read this first. It describes the project as it stands. The plugin briefs are
`docs/MANGA_TRANSLATOR_BRIEF.md` and `docs/BUBBLE_READER_BRIEF.md`.

## What this is
A desktop comic/manga reader in **Python + tkinter** (Windows-first).
Owner: **BiasNil** (pen name). Always call the owner BiasNil, never "Iven" (that's only in the Windows user folder below).
Project root: `C:\Users\Ivenlee_KR\Documents\Python File\Comic Reader\`
Run: `python main.py [file-or-folder]`. Build: `build.bat` (reader), `build.bat plugin`, `build.bat installer`.
It reads CBZ/ZIP, CBR/RAR, CBT/TAR, CB7/CBA/7Z, PDF and folders of images. It has single, double and webtoon
modes, RTL manga mode, a library with covers, bookmarks, favourites, themes, rebindable keys and reading stats.
Two optional plugins: **Manga Translator** translates Japanese pages to English (key `t`); **Bubble Reader**
reads the speech bubbles aloud in reading order with Kokoro voices (key `p`).

## Layout
```
main.py                     entry point (DPI awareness + AppUserModelID on Windows)
ComicReader.spec, build.bat, requirements.txt, README.md
Icon/assets/icon.ico, icon.png   app/exe/installer icon (keep it here: BiasNil wants it in Icon\assets)
comicreader/
  app.py                    ComicReader(BaseTk): main window, wires everything, reading actions
  constants.py              paths (DATA_DIR=~/.comic_reader, BASE_DIR handles sys._MEIPASS), themes, ROT
  core/  (no GUI code)
    sources.py              Source base + Zip/Rar/Tar/SevenZip/Pdf/Folder sources, SourceFactory (header-byte detection)
    session.py              ComicSession, ComicQueue, PageCache (LRU, placeholder on decode failure), ReadingStats
    storage.py              JsonFile (atomic write), Store (state.json), LibraryDB (library.json)
    keybindings.py          KeyBindings: register(name, label, callback, default_keys), overrides persisted
    plugins.py              plugin registry: PluginSpec (TRANSLATOR, BUBBLE_READER), worker_command, messages
    translation.py          Manga Translator contract: protocol, TranslationCache, paths, DEFAULT_SETTINGS
    bubbles.py              Bubble Reader contract: protocol, settings, voices, BubbleCache
    export.py               export_cbz(): translated-CBZ export (own Source, runs in a thread)
  plugins/                  reader side of the plugins (tkinter allowed here)
    client.py               WorkerClient(spec): starts a plugin's worker process, stdout -> queue
    controller.py           TranslatorController: image_for() hook, page queue, batch progress, edits, export
    bubble_reader.py        BubbleReaderController: what to read, highlight, click, auto page turn
    editor.py               BubbleEditor: edit a page's English / pin font sizes -> "retypeset" job
    installer.py            install/update/remove plugins from GitHub Releases (sha256-checked)
    dialogs.py              Translation/BubbleReader settings, ProgressWindow, PluginManagerDialog (+ PluginPanel)
  ui/ library/ utils/       unchanged (see their module docstrings)
plugins/common/             shared by both plugins (no tkinter)
  detector.py               comic-text-detector ONNX, TextBlock (to_json/from_json), reading order
  models.py                 model registry (detector pinned; others via models-v1 models.json)
  mangaocr.py               OnnxMangaOcr, crop_block, postprocess
  layout.py                 bubble_box (flood-fill the speech bubble around a block)
plugins/manga_translator/   the translator (no tkinter; runs as its own process)
  worker.py                 JSON-lines command loop; opens the comic itself via SourceFactory
  pipeline.py               PageTranslator.translate(img, rtl) -> (img, blocks, clean); retypeset()
  ocr.py                    mode resolution, MangaOcrReader (pip manga-ocr); "llm" reads crops
  inpaint.py                bubble fill, LamaInpainter (ONNX), OpenCV fallback
  translator.py             OpenAIBackend (urllib), AnthropicBackend (SDK), LlamaCppBackend (GGUF)
  typeset.py                fitting/drawing
  MangaTranslator.spec, requirements.txt, assets/fonts (Comic Neue, OFL)
plugins/bubble_reader/      the bubble reader (no tkinter; runs as its own process)
  worker.py                 three threads: commands, tasks (configure/download/analyze), player
  analyze.py                detect -> order -> OCR (manga-ocr ja / RapidOCR en) -> sfx flag
  speech.py                 Voice (pykokoro 0.10.4, pinned), Output (sounddevice or silent)
  BubbleReader.spec, requirements.txt
installer/ComicReader.iss   Inno Setup script (reader + optional plugin component)
.github/workflows/release.yml  tag v* -> setup.exe + zips; translator-v* / bubblereader-v* -> that plugin only;
                            signs everything when SIGN_PFX_BASE64 / SIGN_PFX_PASSWORD secrets exist
.github/workflows/models.yml   manual: tools/export_models.py -> "models-v1" release (manga-ocr ONNX,
                            LaMa ONNX, models.json with SHA-256s) that models.py downloads from
tools/export_models.py
docs/MANGA_TRANSLATOR_BRIEF.md, docs/BUBBLE_READER_BRIEF.md
```

## How the pieces connect (important)
- Views never touch sources directly. They call `host.get_image(i)`, which is
  `app.translator.image_for(i, app.cache.get(i, session.source))`, then `host.style(img)`.
  **This is the single choke point for page images.**
- `app.on_view_page(page, span)` is how a view reports what is on screen.
- `Store` keys everything by `session.key` (the resolved path string). Settings are written back in `app.on_close()`;
  translator settings live in `store.settings["translator"]`.
- New keyboard actions go in `ComicReader._register_actions()`; menus pick them up via `MenuBar._cmd(menu, name)`.
- Background work pattern: thread + `queue.Queue`, drained on the UI thread with `app.after(...)`.
  Never touch tkinter from a worker thread.
- `PDF_LOCK` (sources.py) guards MuPDF. `PageCache` is NOT thread-safe.
- **Plugins** are listed in `core/plugins.py` (add a PluginSpec to add one; Plugins > Manage, the installer
  and worker discovery all follow it). The view hooks `page_box_to_canvas` / `canvas_to_page` and
  `host.after_draw()` exist for overlays like the Bubble Reader's highlight.
- **Translator:** the reader and worker share nothing but `core/translation.py`, which defines the message protocol
  (`PROTOCOL` must match, so bump it on breaking changes) and the on-disk cache. The worker writes
  `translations/<sha1(key)[:16]>/<page>.png/.clean.png/.json`; the reader only reads them (editing goes
  through the worker's `retypeset` command). The worker is found in
  this order: the repo source (not frozen), then `DATA_DIR/plugins/manga-translator/`, then `<exe dir>/plugins/manga-translator/`.

## Conventions to keep
- Every optional dependency is imported in try/except. A missing package disables only that feature and
  the UI shows a hint. Pillow is the only hard requirement of the reader; the plugin's packages are in
  `plugins/manga_translator/requirements.txt`.
- Module docstring at the top of every file; section banners like `# ---- name ---- #`.
- Modern type hints (`str | None`), pathlib everywhere, no GUI imports in `core/` or `plugins/manga_translator/`.
- Data lives under `DATA_DIR` (`~/.comic_reader/`): models, translations and the plugin, never next to the exe.
- If you add packages that load native libs or submodules dynamically, update the right spec
  (`ComicReader.spec` or `MangaTranslator.spec`), the requirements file and the README tables.
- `build.bat` and `installer/*.iss` use CRLF line endings.
- Keep README.md in sync (features, keys table, troubleshooting).
- BiasNil prefers small, targeted changes: when only one file changes, change/report just that file.

## Status
Manga Translator: phases 1-3 built (plugin 0.2.0, protocol 2). Bubble Reader: 0.1.0 (protocol 1), see its brief.
The models-v1 release exists (manga-ocr ONNX verified working; LaMa mirrored). Not yet verified for real: the Windows
builds/installer (never run on Windows), real sound output, translation quality with a real LLM. Ideas after that are listed in the brief.

## Testing notes (cloud sandbox)
- tkinter is only available for python3.12 (`apt-get install python3-tk`); run the GUI under `xvfb-run`.
- Fake OpenAI-compatible / Anthropic servers on localhost stand in for real LLMs; set `NO_PROXY=127.0.0.1`.
- Stand-in ONNX models can be built with the `onnx` package (use `ir_version=8` for onnxruntime).
- No sound device here: the Bubble Reader's output falls back to silent timing. pykokoro downloads Kokoro
  from GitHub (works here); Hugging Face is blocked. RapidOCR >= 1.4 needs Python <= 3.12 (python3.12 here).
