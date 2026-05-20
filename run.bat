@echo off
cd /d "%~dp0"

echo === musicDaShi — 自动演奏引擎 ===
echo.

REM Check if dependencies need installing
python -c "import PySide6, mido, numpy, soundfile, scipy, sounddevice" 2>nul
if %errorlevel% neq 0 (
    echo 正在安装依赖...
    pip install -r requirements.txt
    echo.
)

echo 启动应用中...
python -m src.main
pause
