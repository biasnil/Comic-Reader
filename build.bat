@echo off
rem Build Comic Reader into a Windows executable (recipe: ComicReader.spec).
rem   build.bat          folder build -> dist\ComicReader\ComicReader.exe   (recommended)
rem   build.bat onefile  single file  -> dist\ComicReader.exe               (slower to start)
rem Double-clicking it does the folder build.
setlocal
cd /d "%~dp0"

if /i "%~1"=="onefile" set "COMICREADER_ONEFILE=1"

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv ...
    python -m venv .venv || goto :error
)
set "PY=.venv\Scripts\python.exe"

"%PY%" -m pip install --upgrade pip || goto :error
"%PY%" -m pip install -r requirements.txt pyinstaller || goto :error
"%PY%" -m PyInstaller --noconfirm --clean ComicReader.spec || goto :error

echo.
if defined COMICREADER_ONEFILE (echo Done: dist\ComicReader.exe) else (echo Done: dist\ComicReader\ComicReader.exe)
pause
exit /b 0

:error
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1