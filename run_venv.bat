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
REM Accept the first interpreter that meets the ">=3.10" floor declared in
REM pyproject.toml. Checking the version here (not just that a launcher exists)
REM turns an unsupported Python into an actionable message, instead of letting
REM setup fail later inside pip's resolver with an unrelated-looking error.
set "PY_CMD="
call :check_python py -3
if not defined PY_CMD call :find_python_exe
if not defined PY_CMD (
    call :report_missing_python
    pause
    exit /b 1
)
%PY_CMD% --version
REM A supported Python is available, so a broken .venv can be safely removed for a
REM clean rebuild. Removing it first avoids the case where a deleted package still
REM has surviving dist-info metadata, which would make pip skip reinstalling it.
if exist ".venv" (
    echo Removing the incomplete .venv for a clean rebuild...
    rmdir /s /q ".venv"
)

echo.
echo Creating virtual environment...
%PY_CMD% -m venv .venv
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

REM ===== Subroutines =====

:check_python
REM Set PY_CMD to the given command when it runs and meets the version floor.
REM The argument is used as-is, so a quoted full path with spaces also works.
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=%*"
goto :eof

:find_python_exe
REM Fall back to python.exe on PATH when the "py" launcher is absent.
for /f "delims=" %%p in ('where python 2^>nul') do call :accept_python_path "%%p"
if defined PY_EXE call :check_python "%PY_EXE%"
goto :eof

:accept_python_path
REM Keep the first candidate that is a real interpreter. Reject the Windows App
REM Execution Alias stub under WindowsApps: running it opens the Microsoft Store
REM instead of Python, which would hijack the download guidance below. Batch
REM substring replacement is case-insensitive, so no external tool is needed.
set "CAND=%~1"
if not "%CAND%"=="%CAND:\WindowsApps\=%" goto :eof
if not defined PY_EXE set "PY_EXE=%CAND%"
goto :eof

:report_missing_python
REM Distinguish "installed but too old" from "not installed at all" so the user
REM knows whether to upgrade or to install Python for the first time.
set "PY_FOUND="
for /f "usebackq delims=" %%v in (`py -3 --version 2^>nul`) do set "PY_FOUND=%%v"
if not defined PY_FOUND if defined PY_EXE (
    for /f "usebackq delims=" %%v in (`"%PY_EXE%" --version 2^>nul`) do set "PY_FOUND=%%v"
)
echo.
if defined PY_FOUND (
    echo Found %PY_FOUND%, but Python 3.10 or later is required.
) else (
    echo Python 3.10 or later was not found.
)
echo.
echo Download and install Python 3.10 or later from the official site:
echo     https://www.python.org/downloads/
echo In the installer, keep "Add python.exe to PATH" checked.
echo Then run this file again.
goto :eof
