@echo off
REM Idempotent launcher for AFM Nanofiber Analyzer using a dedicated conda env.
REM First run creates the .conda-env prefix and installs the package; later runs just start the app.
REM If .conda-env is later damaged, the launcher repairs it automatically (see below).
setlocal
cd /d "%~dp0"

set "ENV_DIR=%~dp0.conda-env"
set "CONDA_CMD="

REM ---- Locate conda (needed both to create the env and to run from it) ----
REM Prefer CONDA_EXE when running from Anaconda Prompt because it points to the active installation.
if defined CONDA_EXE (
    if exist "%CONDA_EXE%" (
        set "CONDA_CMD=%CONDA_EXE%"
        goto found_conda
    )
)

REM Then try PATH for terminals where conda has already been initialized.
where conda >nul 2>nul
if not errorlevel 1 (
    set "CONDA_CMD=conda"
    goto found_conda
)

REM Finally check common Windows install locations.
for %%C in (
    "%USERPROFILE%\anaconda3\Scripts\conda.exe"
    "%USERPROFILE%\miniconda3\Scripts\conda.exe"
    "%USERPROFILE%\anaconda3\condabin\conda.bat"
    "%USERPROFILE%\miniconda3\condabin\conda.bat"
    "%LOCALAPPDATA%\anaconda3\Scripts\conda.exe"
    "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe"
    "%LOCALAPPDATA%\anaconda3\condabin\conda.bat"
    "%LOCALAPPDATA%\miniconda3\condabin\conda.bat"
    "%ProgramData%\anaconda3\Scripts\conda.exe"
    "%ProgramData%\miniconda3\Scripts\conda.exe"
    "%ProgramData%\anaconda3\condabin\conda.bat"
    "%ProgramData%\miniconda3\condabin\conda.bat"
) do (
    if exist "%%~C" (
        set "CONDA_CMD=%%~C"
        goto found_conda
    )
)

echo conda was not found.
echo Please install Anaconda/Miniconda, or run this file from Anaconda Prompt.
pause
exit /b 1

:found_conda
echo Found:
echo %CONDA_CMD%

REM Health check (cheap file-existence tests only):
REM   - env interpreter missing -> clean rebuild of the prefix
REM   - setup marker missing     -> reinstall into the existing env
REM   - both present             -> run straight away
REM The marker lives inside the env, so deleting the whole folder forces a rebuild.
if not exist "%ENV_DIR%\python.exe" goto rebuild
if not exist "%ENV_DIR%\.afm_setup_done" goto reinstall
goto run

:rebuild
REM The env interpreter is missing, so remove any leftover prefix and recreate it.
REM A fresh prefix avoids the case where a deleted package still has surviving
REM dist-info metadata, which would make pip skip reinstalling it.
if exist "%ENV_DIR%" (
    echo Removing the incomplete conda environment for a clean rebuild...
    rmdir /s /q "%ENV_DIR%"
)

echo.
echo Creating conda environment:
echo %ENV_DIR%
call "%CONDA_CMD%" create -y -p "%ENV_DIR%" python=3.11 pip
if errorlevel 1 (
    echo Failed to create conda environment.
    pause
    exit /b 1
)

echo.
echo Upgrading pip...
call "%CONDA_CMD%" run -p "%ENV_DIR%" python -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)
goto install

:reinstall
echo The setup marker is missing; reinstalling into the existing conda environment...
goto install

:install
echo.
echo Installing the package and dependencies...
REM Editable install resolves dependencies from pyproject.toml (the single source
REM of truth) and registers the afm-analyzer / afm-analyzer-cli console commands.
call "%CONDA_CMD%" run -p "%ENV_DIR%" python -m pip install -e .
if errorlevel 1 (
    echo Failed to install the package.
    pause
    exit /b 1
)

REM Record a successful setup so later launches skip straight to running.
> "%ENV_DIR%\.afm_setup_done" echo ok
echo.
echo Setup completed.
echo Conda environment:
echo %ENV_DIR%

:run
call "%CONDA_CMD%" run -p "%ENV_DIR%" python "%~dp0Main.py"
if errorlevel 1 (
    echo.
    echo Failed to start the application.
    echo If the environment is broken, delete the .conda-env folder and run this file again.
    pause
    exit /b 1
)
exit /b 0
