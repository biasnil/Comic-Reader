# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for the Manga Translator plugin's helper process.  Build with:
#     build.bat plugin        (or: pyinstaller plugins\manga_translator\MangaTranslator.spec)
# Output: dist\manga-translator\manga-translator-worker.exe (+ its files). The reader finds it
# in <reader folder>\plugins\manga-translator\ (installer) or %USERPROFILE%\.comic_reader\plugins\
# manga-translator\ (Plugins > Manage). Models are NOT bundled: they download on first use.

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

HERE = SPECPATH                                   # plugins\manga_translator
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

datas = [(os.path.join(HERE, "assets"), "plugins/manga_translator/assets")]   # the font
binaries, hiddenimports = [], []
hiddenimports += collect_submodules("plugins.manga_translator")
hiddenimports += collect_submodules("comicreader.core")

# packages with native files or dynamic imports; each one is optional
for pkg in ("onnxruntime", "pymupdf", "anthropic", "cv2"):
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
    excludes=["tkinter", "torch", "manga_ocr"],   # manga-ocr (torch) is a from-source extra
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="manga-translator-worker",
    console=True,    # talks over stdin/stdout; the reader starts it without a window
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="manga-translator")
