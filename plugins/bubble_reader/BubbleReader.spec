# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for the Bubble Reader plugin's helper process.  Build with:
#     build.bat plugin        (builds both plugins; or: pyinstaller plugins\bubble_reader\BubbleReader.spec)
# Output: dist\bubble-reader\bubble-reader-worker.exe (+ its files). The reader finds it in
# <reader folder>\plugins\bubble-reader\ (installer) or %USERPROFILE%\.comic_reader\plugins\
# bubble-reader\ (Plugins > Manage). Models aren't bundled: they download on first use.

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

HERE = SPECPATH                                   # plugins\bubble_reader
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

datas, binaries, hiddenimports = [], [], []
try:   # wordninja is a single module; its word list sits in a folder next to it
    import wordninja
    datas.append((os.path.join(os.path.dirname(wordninja.__file__), "wordninja"), "wordninja"))
except ImportError:
    print("[spec] skipping wordninja's word list")
hiddenimports += collect_submodules("plugins.bubble_reader")
hiddenimports += collect_submodules("plugins.common")
hiddenimports += collect_submodules("comicreader.core")

# packages with native files, data files or dynamic imports; each one is optional
for pkg in ("onnxruntime", "pymupdf",
            # Kokoro (pykokoro) and its pronunciation stack
            "pykokoro", "kokorog2p", "espeakng_runtime", "g2lex", "lexphon", "onnxvoice",
            "phrasplit", "audiosig", "soxr", "soundfile", "_soundfile_data", "platformdirs",
            "pyopenjtalk", "sudachipy", "sudachidict_core",  # Japanese pronunciation + dictionaries
            "sounddevice", "_sounddevice_data",            # sound output (PortAudio on Windows)
            "rapidocr_onnxruntime", "wordninja"):          # English OCR + word splitting
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:
        print(f"[spec] skipping {pkg}: {exc}")
try:
    hiddenimports += collect_submodules("py7zr")
except Exception as exc:
    print(f"[spec] skipping py7zr: {exc}")

a = Analysis(
    [os.path.join(HERE, "worker.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # manga-ocr (torch) is a from-source extra; spaCy (~160 MB with its helpers) can be pulled
    # in by optional imports but isn't used (no long-text splitting)
    excludes=["tkinter", "torch", "manga_ocr", "spacy", "thinc", "blis", "srsly", "cymem",
              "preshed", "murmurhash", "wasabi", "catalogue", "confection", "weasel"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="bubble-reader-worker",
    console=True,    # talks over stdin/stdout; the reader starts it without a window
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="bubble-reader")
