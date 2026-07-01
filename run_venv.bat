@echo off
REM Idempotent launcher for AFM Nanofiber Analyzer using a local .venv.
REM First run creates .venv and installs the package; later runs just start the app.
REM If .venv is later damaged, the launcher repairs it automatically (see below).
setlocal
cd /d "%~dp0"

REM Health check on every launch (cheap file-existence tests only):
REM   - interpreter missing -> clean rebuild
REM   - setup marker missing -> reinstall into the existing .venv
REM   - both present         -> run straight away
REM The marker lives inside .venv, so deleting the whole folder forces a rebuild.
if not exist ".venv\Scripts\python.exe" goto rebuild
if not exist ".venv\.afm_setup_done" goto reinstall
goto run

:rebuild
echo Checking Python...
py -3 --version
if errorlevel 1 (
    echo.
    echo Python launcher "py" was not found.
    echo Please install Python 3.10 or later, then run this file again.
    pause
    exit /b 1
)
REM A Python launcher is available, so a broken .venv can be safely removed for a
REM clean rebuild. Removing it first avoids the case where a deleted package still
REM has surviving dist-info metadata, which would make pip skip reinstalling it.
if exist ".venv" (
    echo Removing the incomplete .venv for a clean rebuild...
    rmdir /s /q ".venv"
)

echo.
echo Creating virtual environment...
py -3 -m venv .venv
if errorlevel 1 (
    echo Failed to create .venv.
    pause
    exit /b 1
)

echo.
echo Upgrading pip...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)
goto install

:reinstall
echo The setup marker is missing; reinstalling into the existing .venv...
goto install

:install
echo.
echo Installing the package and dependencies...
REM Editable install resolves dependencies from pyproject.toml (the single source
REM of truth) and registers the afm-analyzer / afm-analyzer-cli console commands.
call ".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 (
    echo Failed to install the package.
    pause
    exit /b 1
)

REM Record a successful setup so later launches skip straight to running.
> ".venv\.afm_setup_done" echo ok
echo.
echo Setup completed.

:run
if not exist ".venv\Scripts\python.exe" (
    echo .venv is unavailable and could not be prepared.
    echo Delete the .venv folder and run this file again.
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
