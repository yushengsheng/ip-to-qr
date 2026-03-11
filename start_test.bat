@echo off
setlocal

cd /d "%~dp0"

set "CHECK_ONLY="
if /I "%~1"=="--check" set "CHECK_ONLY=1"

set "PYTHON_CMD="

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
)

if not defined PYTHON_CMD (
    py -3 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
    )
)

if not defined PYTHON_CMD (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] No Python interpreter was found.
    echo Install Python 3 first, then run this script again.
    pause
    exit /b 1
)

echo [INFO] Using Python: %PYTHON_CMD%

call %PYTHON_CMD% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] tkinter is not available in the current Python environment.
    echo Reinstall Python with Tcl/Tk support, or use a Python build that includes tkinter.
    pause
    exit /b 1
)

call %PYTHON_CMD% -c "import qrcode; from PIL import Image, ImageTk" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing required Python packages...
    call %PYTHON_CMD% -m pip install qrcode[pil] pillow
    if errorlevel 1 (
        echo [ERROR] Failed to install qrcode/pillow dependencies.
        pause
        exit /b 1
    )
)

if defined CHECK_ONLY (
    echo [INFO] Environment check passed.
    exit /b 0
)

echo [INFO] Starting qrcode_gui.py ...
call %PYTHON_CMD% qrcode_gui.py

if errorlevel 1 (
    echo.
    echo [ERROR] The app exited with an error.
    pause
    exit /b 1
)

exit /b 0
