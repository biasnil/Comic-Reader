@echo off
rem Build Comic Reader into a Windows executable (recipe: ComicReader.spec).
rem   build.bat            folder build -> dist\ComicReader\ComicReader.exe   (recommended)
rem   build.bat onefile    single file  -> dist\ComicReader.exe               (slower to start)
rem   build.bat plugin     both plugins -> dist\manga-translator\manga-translator-worker.exe
rem                                       dist\bubble-reader\bubble-reader-worker.exe
rem   build.bat installer  reader + plugin + setup.exe -> dist\ComicReader-Setup-<version>.exe
rem                        (needs Inno Setup 6: https://jrsoftware.org/isinfo.php)
rem Double-clicking it does the folder build.
setlocal
cd /d "%~dp0"

set "TARGET=%~1"
if /i "%TARGET%"=="onefile" set "COMICREADER_ONEFILE=1"
if not defined VERSION set "VERSION=dev"

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv ...
    python -m venv .venv || goto :error
)
set "PY=.venv\Scripts\python.exe"

if not exist "Icon\assets\icon.ico" echo WARNING: Icon\assets\icon.ico not found - the exe will use the default icon.

"%PY%" -m pip install --upgrade pip || goto :error
"%PY%" -m pip install -r requirements.txt pyinstaller || goto :error

if /i "%TARGET%"=="plugin" goto :plugin

"%PY%" -m PyInstaller --noconfirm --clean ComicReader.spec || goto :error
if /i not "%TARGET%"=="installer" goto :done

:plugin
rem the plugin's packages go in after the reader is built, so the reader exe doesn't pick them up
"%PY%" -m pip install -r plugins\manga_translator\requirements.txt || goto :error
"%PY%" -m PyInstaller --noconfirm --clean plugins\manga_translator\MangaTranslator.spec || goto :error
"%PY%" -m pip install -r plugins\bubble_reader\requirements.txt || goto :error
"%PY%" -m PyInstaller --noconfirm --clean plugins\bubble_reader\BubbleReader.spec || goto :error
if /i not "%TARGET%"=="installer" goto :done

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 not found - install it from https://jrsoftware.org/isinfo.php
    goto :error
)
"%ISCC%" /DAppVersion=%VERSION% installer\ComicReader.iss || goto :error

:done
echo.
if /i "%TARGET%"=="plugin" (echo Done: dist\manga-translator\ and dist\bubble-reader\) else if /i "%TARGET%"=="installer" (echo Done: dist\ComicReader-Setup-%VERSION%.exe) else if defined COMICREADER_ONEFILE (echo Done: dist\ComicReader.exe) else (echo Done: dist\ComicReader\ComicReader.exe)
pause
exit /b 0

:error
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1
