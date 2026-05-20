@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === musicDaShi - Automatic Performance Engine ===
echo.

python -c "import PySide6, mido, numpy, soundfile, scipy, sounddevice" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install -r "%~dp0requirements.txt"
    echo.
)

echo Starting...
python -m src.main
pause
