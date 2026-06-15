@echo off
REM Start AFM Nanofiber Analyzer from the local .venv created by 01_setup_venv.bat.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo .venv was not found.
    echo Please run 01_setup_venv.bat first.
    pause
    exit /b 1
)

call ".venv\Scripts\python.exe" "%~dp0Main.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo Main.py exited with error code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
