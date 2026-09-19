# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build recipe for Comic Reader.  Build with:  build.bat   (or: pyinstaller ComicReader.spec)
#
#   folder build (default):  dist\ComicReader\ComicReader.exe
#   single file:             set COMICREADER_ONEFILE=1 first (build.bat onefile does this)
#   icon / assets:           the whole assets\ folder is bundled; assets\icon.ico is the exe icon

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ONEFILE = os.environ.get("COMICREADER_ONEFILE") == "1"

ASSETS = os.path.join(SPECPATH, "assets")          # SPECPATH = folder containing this spec
_ico = os.path.join(ASSETS, "icon.ico")
ICON = _ico if os.path.exists(_ico) else None

datas, binaries, hiddenimports = [], [], []

# bundle assets\ so the running exe can find them (used for the window icon)
if os.path.isdir(ASSETS):
    datas.append((ASSETS, "assets"))
else:
    print("[spec] no assets folder found: building without an icon")

# packages that ship native files or load things dynamically; each one is optional
for pkg in ("tkinterdnd2",   # native tkdnd library used for drag & drop
            "pymupdf"):      # MuPDF binaries used for PDFs
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:
        print(f"[spec] skipping {pkg}: {exc}")
try:
    hiddenimports += collect_submodules("py7zr")  # py7zr loads its compressors dynamically
except Exception as exc:
    print(f"[spec] skipping py7zr: {exc}")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="ComicReader",
        console=False,   # windowed app: no console window
        upx=False,
        icon=ICON,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="ComicReader",
        console=False,
        upx=False,
        icon=ICON,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        upx=False,
        name="ComicReader",
    )
