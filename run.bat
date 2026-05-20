@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Add local FluidSynth DLLs to PATH
if exist "%~dp0fluidsynth_lib\bin" (
    set "PATH=%~dp0fluidsynth_lib\bin;%PATH%"
)

REM pyfluidsynth hardcodes C:\tools\fluidsynth\bin as DLL search path
if not exist "C:\tools\fluidsynth\bin" (
    mkdir "C:\tools\fluidsynth\bin" 2>nul
    if exist "%~dp0fluidsynth_lib\bin\*.dll" (
        xcopy /y /q "%~dp0fluidsynth_lib\bin\*.dll" "C:\tools\fluidsynth\bin\" 2>nul
    )
)

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
