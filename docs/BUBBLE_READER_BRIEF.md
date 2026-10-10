# Brief: Bubble Reader plugin

Owner: BiasNil. Status: version 0.1.0 built and tested from source and as a frozen (PyInstaller) build;
the Windows build has not been run yet.

## What BiasNil wants

- Something like **EchoRead** (BiasNil's offline Speechify-style reader), but for comics: read the
  **speech bubbles aloud**, one after another.
- **Automatic reading direction:** left to right for English comics, right to left for Japanese manga.
- Anything else that makes sense for a bubble reader.
- It must be **its own plugin, called Bubble Reader**, separate from the Manga Translator.

## Decisions taken (the two open questions defaulted)

| Question | Decision |
|---|---|
| Untranslated manga page | Read in **Japanese** with a Japanese voice. A page the Manga Translator has translated (Translate Pages on) is read in **English** from its saved translation. |
| English comics | **Yes**: RapidOCR (small ONNX OCR inside the `rapidocr-onnxruntime` package) reads them. |
| Voices | **Kokoro via `pykokoro`**, the same engine as EchoRead. Pinned to 0.10.4 because 0.10 removed the `KokoroPipeline` API EchoRead uses. |
| Direction | Follows the reader's right-to-left setting, which already switches on by itself for manga (ComicInfo or file name). The comic's language setting (auto / ja / en) can override it. |

## What it does

- **Read Aloud (P)**: reads the bubbles of the page(s) on screen in reading order, then turns the page and
  carries on; stops at the end of the comic.
- **Highlight**: the bubble being spoken is outlined in the accent colour and scrolled into view (fit width,
  webtoon).
- **Controls**: pause/resume (P), next/previous bubble (. and ,), stop (Shift+P), **click a bubble** to read
  from it.
- **No waiting**: the next bubble's audio is made while the current one plays; the next page is analysed
  while the current one is read; analysed pages are saved (`.comic_reader\bubbles\`).
- **Sound effects** (short text over the art, outside a light bubble) are skipped by default.
- **Settings**: English voice (12), Japanese voice (5), speed 0.5x–2x, volume, language, read translated
  pages in English, skip sound effects, turn pages, follow the bubble, GPU.
- **Silent fallback**: without a sound device it still highlights and turns pages at speaking pace.

## How it fits together

```
Reader (comicreader/)                          Plugin (plugins/bubble_reader/, its own process)
  plugins/bubble_reader.py  BubbleReaderController   worker.py   commands on stdin, three threads:
    which pages, which text (translation or OCR)        main: hello/set/play/pause/resume/stop at once
    highlight via view.page_box_to_canvas()             tasks: configure / download / analyze in order
    click via view.canvas_to_page()                     player: speaks, preparing the next clip meanwhile
    auto page turn on "finished"                     analyze.py  detect -> order -> OCR (ja/en) -> sfx flag
                                                     speech.py   Kokoro (pykokoro) + sound output
  shared contract: comicreader/core/bubbles.py      shared code: plugins/common/ (detector, models,
  plugin registry: comicreader/core/plugins.py                    mangaocr, layout) with the translator
```

## Downloads on first use

Text detector (95 MB, shared with the translator), Japanese OCR model (about 450 MB, from `models-v1`; only
for manga) and Kokoro voices (about 350 MB, from Kokoro's GitHub releases), each once.

## Tested

- From source: the English test page read as "Where do you think you're going?!", "Home. I'm tired of all
  this.", "Meanwhile, across the city...", "Wait for me!" (RapidOCR 1.4.4, words regrouped into lines);
  the sample manga page read right to left with the real manga-ocr ONNX model from `models-v1`.
- In the app: reading, highlight, status, clicking a bubble, end-of-comic stop, reading the translator's
  English without OCR, the Plugins window with both plugins.
- Frozen with PyInstaller (Linux): analysis and English + Japanese speech work.

## Not yet checked

- The Windows build and real sound output (the sandbox has no sound device).
- The installed size on Windows: about 780 MB on Linux, mostly Japanese pronunciation dictionaries
  (pyopenjtalk, SudachiPy) and OpenCV.

## Ideas for later

Different voices per character (by bubble position or user tagging), word-by-word highlighting from
Kokoro's word timings (as EchoRead does), exporting a chapter as an audiobook, reading narration boxes in a
separate narrator voice.
