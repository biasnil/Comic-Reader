# Brief: Manga Translator plugin, installer and releases

Owner: BiasNil. Status: Phases 1, 2 and 3 built (plugin 0.2.0). This document describes what was asked for and what exists.

## What BiasNil wants

1. **Two experiences from one product.**
   - **Comic Reader (Standard):** the reader as it is today. It stays small and fast, and none of the translation code or AI packages are loaded or bundled.
   - **Manga Translator:** a Koharu-style add-on that translates Japanese manga pages into English while you read.
2. **The translator is a plugin, not a separate app.** You install it, update it and remove it from inside the reader (Plugins > Manage…).
3. **Everything lives in this one repository** (`biasnil/comic-reader`). No second repo. The plugin source is in `plugins/manga_translator/`.
4. **Plugin downloads come from this repo's GitHub Releases.** The reader looks up the latest release, downloads the plugin, checks its checksum and installs it.
5. **A Windows `setup.exe` installer** with Start Menu and desktop shortcuts, an uninstaller, optional file associations, and an optional *Manga Translator* component (unticked by default).
6. **Automated releases.** Pushing a tag builds everything on GitHub's Windows machines and attaches the downloads to the release.

## Decisions taken (defaults; all can be changed)

| Question | Decision |
|---|---|
| How the plugin runs | A separate helper process (`manga-translator-worker.exe`), which the reader talks to over stdin/stdout. The reader gains no weight, a plugin crash can't take the reader down, and the plugin can be updated on its own. |
| OCR | No torch in the exe. Options: the local manga-ocr ONNX model (offline, downloads ~450 MB), the translation model reading image crops (needs a vision model), or the `manga-ocr` package from source. *Automatic* picks the best one available. |
| Default translator | A local OpenAI-compatible server: Ollama at `http://localhost:11434/v1` with `qwen2.5vl:7b`. It is free and offline. Claude (Anthropic API) is the other built-in choice, and LM Studio, llama.cpp's server and OpenAI also work. |
| GPU | Used automatically if onnxruntime has a GPU provider (CUDA / DirectML). The released build is CPU-only, so expect several seconds per page. |
| Font | Comic Neue Bold (SIL Open Font License), bundled with the plugin. |
| Text removal | Plain bubbles are filled with their background colour. Text over artwork is repainted by LaMa (if downloaded) or OpenCV; with neither, the English is drawn in a white box. |

## How it fits together

```
Reader (comicreader/)                       Plugin (plugins/manga_translator/)
  app.get_image(i)  ── the one choke point     worker.py   JSON lines on stdin/stdout
    └─ translator.image_for(i, original)       pipeline.py detect → OCR → translate → erase → typeset
         cached translation? show it           detector.py comic-text-detector (ONNX)
         else show original + queue page ──►   translator.py OpenAI-compatible / Anthropic
         ◄── "done" ── redraw if on screen     typeset.py  word-wrap, shrink-to-fit, bubble finding
                 shared contract: comicreader/core/translation.py
                 cache: %USERPROFILE%\.comic_reader\translations\<id>\0007.png + 0007.json
```

## Using it

- **T** (or Translate > Translate Pages) switches translation on. The page on screen is done first, then the next pages.
- Translate > **Translate Whole Comic** queues every page in the background.
- Translate > **Translation Settings…** chooses the translator, model, API key, OCR and text-removal options.
- On first use the 95 MB text-detection model downloads to `.comic_reader\models\`, after a prompt.

## Releasing

| Tag | Builds |
|---|---|
| `v1.3.0` | `ComicReader-Setup-1.3.0.exe`, `ComicReader-1.3.0-win64.zip`, `MangaTranslator-plugin-win64.zip` (+ `.sha256`) |
| `translator-v0.2.0` | only the plugin zip: an update that Plugins > Manage picks up |

Local builds: `build.bat` (reader), `build.bat plugin`, `build.bat installer` (needs Inno Setup 6).

## Phase 2 (built)

- **LaMa inpainting** for text over artwork and screentone (ONNX, downloads about 200 MB when chosen; OpenCV stays as the fallback).
- **Translate Whole Comic** progress window with Hide and Stop.
- **Export Translated Comic (CBZ)**: translated pages plus a ComicInfo.xml, readable anywhere.
- **Code signing** in the release workflow: switches on when the `SIGN_PFX_BASE64` / `SIGN_PFX_PASSWORD` secrets are added.

## Phase 3 (built)

- **Bubble editor** (Ctrl+E): change any bubble's English or pin its font size. The worker redraws the page on the saved text-free image, without running the AI again.
- **In-process llama.cpp** translator: pick a `.gguf` file, no server needed (uses the local OCR).
- **manga-ocr as ONNX**: accurate offline OCR that works in the exe without PyTorch (downloads about 450 MB when chosen).
- Optional models are published by the **Models** workflow as this repo's `models-v1` release, with checksums.
- A custom font (.ttf/.otf) can be chosen.

## Still to check

- Run **Actions > Models** once (creates `models-v1`), then **Actions > Release > Run workflow** for a test build. Neither has run yet.
- Try a real translator (Ollama or Claude) on a few chapters and tune the prompt or bubble fitting if needed.

## Ideas for later

Vertical English for narrow columns, per-comic glossary (character names), a canvas overlay that highlights the bubble being edited, batch export of a whole library folder.
