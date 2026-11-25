@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.13 -m venv .venv || goto fail
)
".venv\Scripts\python.exe" -c "import tkinter" || goto fail
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r requirements-win.lock || goto fail
".venv\Scripts\python.exe" -I pilot.py || goto fail
exit /b 0
:fail
echo Cannot start the read-only pilot. Install Python 3.13 x64 from python.org with Tcl/Tk and the Python launcher enabled.
pause
exit /b 1
