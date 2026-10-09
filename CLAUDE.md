# CLAUDE.md: Comic Reader (handoff notes)

Read this first. It describes the project as it stands. The plugin brief is in
`docs/MANGA_TRANSLATOR_BRIEF.md`.

## What this is
A desktop comic/manga reader in **Python + tkinter** (Windows-first). Owner: Iven.
Project root: `C:\Users\Ivenlee_KR\Documents\Python File\Comic Reader\`
Run: `python main.py [file-or-folder]`. Build: `build.bat` (reader), `build.bat plugin`, `build.bat installer`.
It reads CBZ/ZIP, CBR/RAR, CBT/TAR, CB7/CBA/7Z, PDF and folders of images. It has single, double and webtoon
modes, RTL manga mode, a library with covers, bookmarks, favourites, themes, rebindable keys and reading stats.
The optional **Manga Translator plugin** translates Japanese pages to English (key `t`).

## Layout
```
main.py                     entry point (DPI awareness + AppUserModelID on Windows)
ComicReader.spec, build.bat, requirements.txt, README.md
assets/icon.ico, icon.png
comicreader/
  app.py                    ComicReader(BaseTk): main window, wires everything, reading actions
  constants.py              paths (DATA_DIR=~/.comic_reader, BASE_DIR handles sys._MEIPASS), themes, ROT
  core/  (no GUI code)
    sources.py              Source base + Zip/Rar/Tar/SevenZip/Pdf/Folder sources, SourceFactory (header-byte detection)
    session.py              ComicSession, ComicQueue, PageCache (LRU, placeholder on decode failure), ReadingStats
    storage.py              JsonFile (atomic write), Store (state.json), LibraryDB (library.json)
    keybindings.py          KeyBindings: register(name, label, callback, default_keys), overrides persisted
    translation.py          plugin contract: protocol, TranslationCache, paths, DEFAULT_SETTINGS, worker_command
  plugins/                  reader side of the plugin (tkinter allowed here)
    client.py               WorkerClient: starts the worker process, stdout -> queue
    controller.py           TranslatorController: image_for() hook, page queue, status, redraws
    installer.py            install/update/remove the plugin from GitHub Releases (sha256-checked)
    dialogs.py              TranslationSettingsDialog, PluginManagerDialog
  ui/ library/ utils/       unchanged (see their module docstrings)
plugins/manga_translator/   the plugin (no tkinter; runs as its own process)
  worker.py                 JSON-lines command loop; opens the comic itself via SourceFactory
  pipeline.py               PageTranslator.translate(img, rtl) -> (img, blocks)
  detector.py ocr.py inpaint.py translator.py typeset.py models.py
  MangaTranslator.spec, requirements.txt, assets/fonts (Comic Neue, OFL)
installer/ComicReader.iss   Inno Setup script (reader + optional plugin component)
.github/workflows/release.yml  tag v* -> setup.exe + zips; tag translator-v* -> plugin zip only
docs/MANGA_TRANSLATOR_BRIEF.md
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
- **Plugin:** the reader and worker share nothing but `core/translation.py`, which defines the message protocol
  (`PROTOCOL` must match, so bump it on breaking changes) and the on-disk cache. The worker writes
  `translations/<sha1(key)[:16]>/<page>.png/.json`; the reader only reads them. The worker is found in
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
- Iven prefers small, targeted changes: when only one file changes, change/report just that file.

## Next (see the brief for detail)
Phase 2: LaMa inpainting, a whole-comic progress window, translated-CBZ export, installer code signing.
Phase 3: a bubble text editor with re-typesetting, an in-process llama-cpp backend, manga-ocr as ONNX.
