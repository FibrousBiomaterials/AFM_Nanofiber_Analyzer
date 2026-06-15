@echo off
REM Set up this project against an existing Anaconda or Miniconda installation.
REM Run from Anaconda Prompt if automatic conda detection fails.
setlocal
cd /d "%~dp0"

echo [1/4] Searching for Anaconda or Miniconda Python...
set "ANACONDA_PYTHON="
set "CONDA_ROOT="

REM Prefer the already-active conda environment so users can choose their own install.
if defined CONDA_PREFIX (
    if exist "%CONDA_PREFIX%\python.exe" (
        set "ANACONDA_PYTHON=%CONDA_PREFIX%\python.exe"
        set "CONDA_ROOT=%CONDA_PREFIX%"
        goto found_python
    )
)

REM Check the common Windows install locations used by Anaconda and Miniconda.
for %%P in (
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "%LOCALAPPDATA%\anaconda3\python.exe"
    "%LOCALAPPDATA%\miniconda3\python.exe"
    "%ProgramData%\anaconda3\python.exe"
    "%ProgramData%\miniconda3\python.exe"
) do (
    if exist "%%~P" (
        set "ANACONDA_PYTHON=%%~P"
        for %%D in ("%%~dpP.") do set "CONDA_ROOT=%%~fD"
        goto found_python
    )
)

REM Fall back to conda on PATH when the installation is not in a standard location.
where conda >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%P in ('conda run python -c "import sys; print(sys.executable)" 2^>nul') do (
        if exist "%%~P" (
            set "ANACONDA_PYTHON=%%~P"
            for %%D in ("%%~dpP.") do set "CONDA_ROOT=%%~fD"
            goto found_python
        )
    )
)

echo Anaconda or Miniconda Python was not found.
echo Please install Anaconda/Miniconda, or run this file from Anaconda Prompt.
pause
exit /b 1

:found_python
echo Found:
echo %ANACONDA_PYTHON%

if exist "%CONDA_ROOT%\Scripts\activate.bat" (
    echo.
    echo Activating Anaconda environment...
    REM Activation helps conda-managed DLL paths resolve during package installs.
    call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ROOT%"
)

echo.
echo [2/4] Upgrading pip...
call "%ANACONDA_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo.
echo [3/4] Installing the package and dependencies...
REM Editable install resolves dependencies from pyproject.toml (the single source
REM of truth) and registers the afm-analyzer / afm-analyzer-cli console commands.
call "%ANACONDA_PYTHON%" -m pip install -e .
if errorlevel 1 (
    echo Failed to install the package.
    pause
    exit /b 1
)

echo.
echo [4/4] Recording the Anaconda Python path for 92_run_from_anaconda.bat...
REM The static launcher reads this machine-local path; the file stays gitignored.
> ".afm_anaconda_python" echo %ANACONDA_PYTHON%
if errorlevel 1 (
    echo Failed to record the Anaconda Python path.
    pause
    exit /b 1
)

echo.
echo Setup completed.
echo You can now start the application with 92_run_from_anaconda.bat.
exit /b 0
