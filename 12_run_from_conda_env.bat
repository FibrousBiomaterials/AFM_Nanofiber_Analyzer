@echo off
REM Start AFM Nanofiber Analyzer inside the dedicated conda environment.
REM Run 11_setup_conda_env.bat first if the environment has not been created.
setlocal
cd /d "%~dp0"

set "ENV_DIR=%~dp0.conda-env"
set "CONDA_CMD="

if defined CONDA_EXE (
    if exist "%CONDA_EXE%" (
        set "CONDA_CMD=%CONDA_EXE%"
        goto found_conda
    )
)

where conda >nul 2>nul
if not errorlevel 1 (
    set "CONDA_CMD=conda"
    goto found_conda
)

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
call "%CONDA_CMD%" run -p "%ENV_DIR%" python "%~dp0Main.py"
if errorlevel 1 (
    echo.
    echo Failed to start the application.
    echo Please run 11_setup_conda_env.bat first.
    pause
    exit /b 1
)
exit /b 0
