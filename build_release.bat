@echo off
setlocal

cd /d "%~dp0"

set "VERSION=%~1"
if not defined VERSION (
    echo [ERROR] Usage: build_release.bat v0.1.2
    exit /b 1
)

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
    exit /b 1
)

echo [INFO] Using Python: %PYTHON_CMD%

call %PYTHON_CMD% -m unittest discover -s tests
if errorlevel 1 exit /b 1

call %PYTHON_CMD% -m PyInstaller qrcode_gui.spec --noconfirm --clean
if errorlevel 1 exit /b 1

set "EXE_NAME=qrcode_gui-%VERSION%-windows-x64.exe"
set "RELEASE_DIR=dist\ip-to-qr-%VERSION%-windows-x64"
set "ZIP_NAME=ip-to-qr-%VERSION%-windows-x64.zip"

if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"

copy /y "dist\qrcode_gui.exe" "dist\%EXE_NAME%" >nul
copy /y "dist\qrcode_gui.exe" "%RELEASE_DIR%\qrcode_gui.exe" >nul
copy /y "README.md" "%RELEASE_DIR%\README.md" >nul

if exist "dist\%ZIP_NAME%" del /f /q "dist\%ZIP_NAME%"
powershell -NoProfile -Command "Compress-Archive -Path '%CD%\%RELEASE_DIR%\*' -DestinationPath '%CD%\dist\%ZIP_NAME%'"
if errorlevel 1 exit /b 1

echo [INFO] Release assets created:
echo [INFO]   dist\%EXE_NAME%
echo [INFO]   dist\%ZIP_NAME%

exit /b 0
