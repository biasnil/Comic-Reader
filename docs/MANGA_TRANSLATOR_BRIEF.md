# Brief: Manga Translator plugin, installer and releases

Owner: Iven. Status: Phase 1 built (this document describes what was asked for and what exists).

## What Iven wants

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
| OCR | No torch in the exe. By default the translation model reads the Japanese from image crops of each bubble, so it needs a vision model. `manga-ocr` is used automatically when it is installed (from source; it is ~2 GB). |
| Default translator | A local OpenAI-compatible server: Ollama at `http://localhost:11434/v1` with `qwen2.5vl:7b`. It is free and offline. Claude (Anthropic API) is the other built-in choice, and LM Studio, llama.cpp's server and OpenAI also work. |
| GPU | Used automatically if onnxruntime has a GPU provider (CUDA / DirectML). The released build is CPU-only, so expect several seconds per page. |
| Font | Comic Neue Bold (SIL Open Font License), bundled with the plugin. |
| Text removal | Plain bubbles are filled with their background colour. Text over artwork is inpainted with OpenCV. When neither works, the English is drawn in a white box. LaMa inpainting is phase 2. |

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

## Next phases

- **Phase 2:** LaMa inpainting for text over artwork, a progress window for "translate whole comic", export of a translated CBZ, and code signing for the installer (removes the SmartScreen warning).
- **Phase 3:** an editor to fix a bubble's translation and re-typeset it from the saved JSON, an in-process llama-cpp backend, and a manga-ocr ONNX export so local OCR works in the exe without torch.
