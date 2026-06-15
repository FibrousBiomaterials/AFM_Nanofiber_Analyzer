@echo off
REM Create or update a dedicated conda environment for AFM Nanofiber Analyzer.
REM The environment is created in the project folder as .conda-env.
setlocal
cd /d "%~dp0"

set "ENV_DIR=%~dp0.conda-env"
set "CONDA_CMD="

echo [1/4] Searching for conda...

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

echo.
echo [2/4] Creating or reusing conda environment:
echo %ENV_DIR%
REM conda run is used instead of activation so this script works from plain cmd.exe.
call "%CONDA_CMD%" run -p "%ENV_DIR%" python --version >nul 2>nul
if errorlevel 1 (
    call "%CONDA_CMD%" create -y -p "%ENV_DIR%" python=3.11 pip
    if errorlevel 1 (
        echo Failed to create conda environment.
        pause
        exit /b 1
    )
) else (
    echo Environment already exists.
)

echo.
echo [3/4] Upgrading pip...
call "%CONDA_CMD%" run -p "%ENV_DIR%" python -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo.
echo [4/4] Installing the package and dependencies...
REM Editable install resolves dependencies from pyproject.toml (the single source
REM of truth) and registers the afm-analyzer / afm-analyzer-cli console commands.
call "%CONDA_CMD%" run -p "%ENV_DIR%" python -m pip install -e .
if errorlevel 1 (
    echo Failed to install the package.
    pause
    exit /b 1
)

echo.
echo Setup completed.
echo Conda environment:
echo %ENV_DIR%
echo You can now start the application with 12_run_from_conda_env.bat.
exit /b 0
