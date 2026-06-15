@echo off
REM Create or update the local .venv environment for AFM Nanofiber Analyzer.
REM This path avoids conda and uses the Windows Python launcher.
setlocal
cd /d "%~dp0"

echo [1/4] Checking Python...
py -3 --version
if errorlevel 1 (
    echo.
    echo Python launcher "py" was not found.
    echo Please install Python 3.10 or later, then run this file again.
    pause
    exit /b 1
)

echo.
echo [2/4] Creating virtual environment...
py -3 -m venv .venv
if errorlevel 1 (
    echo Failed to create .venv.
    pause
    exit /b 1
)

echo.
echo [3/4] Upgrading pip...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo.
echo [4/4] Installing the package and dependencies...
REM Editable install resolves dependencies from pyproject.toml (the single source
REM of truth) and registers the afm-analyzer / afm-analyzer-cli console commands.
call ".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 (
    echo Failed to install the package.
    pause
    exit /b 1
)

echo.
echo Setup completed.
echo You can now start the application with 02_run_from_venv.bat.
exit /b 0
