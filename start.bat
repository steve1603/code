@echo off
REM One-command launcher for the finadvisor web UI (Windows).
REM
REM   start.bat                 -- start on http://127.0.0.1:8765
REM   start.bat --port 9000     -- extra args pass through to the server
REM
REM First run creates .venv\ and installs pypdf (PDF statement import).
REM PySide6 is NOT required -- the web UI is stdlib-only.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo error: Python not found. Install Python 3.10+ from https://python.org
    echo        and tick "Add python.exe to PATH" during setup.
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo error: Python 3.10+ required. Yours is older -- update from https://python.org
    exit /b 1
)

if not exist .venv (
    echo First run -- creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

python -c "import pypdf" >nul 2>nul
if errorlevel 1 (
    echo Installing pypdf ^(PDF statement import^)...
    pip install --quiet "pypdf>=4.0"
)

echo.
echo Starting finadvisor -- open the URL printed below in your browser.
echo (Ctrl+C stops the server. Your data lives in .\finances.json)
echo.
python -m finadvisor.web %*
