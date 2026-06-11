@echo off
REM Set up this project against an existing Anaconda or Miniconda installation.
REM Run from Anaconda Prompt if automatic conda detection fails.
setlocal
cd /d "%~dp0"

echo [1/5] Searching for Anaconda or Miniconda Python...
set "ANACONDA_PYTHON="
set "CONDA_ROOT="
set "CONDA_CMD="

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

if exist "%CONDA_ROOT%\Scripts\conda.exe" (
    set "CONDA_CMD=%CONDA_ROOT%\Scripts\conda.exe"
) else if exist "%CONDA_ROOT%\condabin\conda.bat" (
    set "CONDA_CMD=%CONDA_ROOT%\condabin\conda.bat"
)
if not defined CONDA_CMD (
    where conda >nul 2>nul
    if not errorlevel 1 (
        set "CONDA_CMD=conda"
    )
)

echo.
echo [2/5] Upgrading pip...
call "%ANACONDA_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo.
echo [3/5] Generating requirements...
REM check.py regenerates requirements.txt from the project imports before install.
call "%ANACONDA_PYTHON%" check.py
if errorlevel 1 (
    echo Failed to generate requirements.txt.
    pause
    exit /b 1
)

echo.
echo [4/5] Installing requirements...
if defined CONDA_CMD (
    echo Installing mahotas with conda-forge first to avoid pip build failures...
    REM mahotas can require native builds on Windows; conda-forge usually provides a wheel-equivalent package.
    call "%CONDA_CMD%" install -y -c conda-forge mahotas
    if errorlevel 1 (
        echo conda-forge mahotas install failed; continuing with pip requirements.
    )
)
call "%ANACONDA_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
)

echo.
echo [5/5] Writing 92_run_from_anaconda.bat...
(
    echo @echo off
    echo REM Start AFM Nanofiber Analyzer with the Anaconda/Miniconda Python detected by setup.
    echo REM Re-run 91_setup_anaconda.bat if this Python path changes.
    echo setlocal
    echo cd /d "%%~dp0"
    echo.
    echo set "ANACONDA_PYTHON=%ANACONDA_PYTHON%"
    echo.
    echo if not exist "%%ANACONDA_PYTHON%%" ^(
    echo     echo Anaconda Python was not found:
    echo     echo %%ANACONDA_PYTHON%%
    echo     echo Please run 91_setup_anaconda.bat again.
    echo     pause
    echo     exit /b 1
    echo ^)
    echo.
    echo call "%%ANACONDA_PYTHON%%" "%%~dp0Main.py"
    echo set "EXIT_CODE=%%ERRORLEVEL%%"
    echo.
    echo if not "%%EXIT_CODE%%"=="0" ^(
    echo     echo Main.py exited with error code %%EXIT_CODE%%.
    echo     pause
    echo ^)
    echo.
    echo exit /b %%EXIT_CODE%%
) > 92_run_from_anaconda.bat
if errorlevel 1 (
    echo Failed to write 92_run_from_anaconda.bat.
    pause
    exit /b 1
)

echo.
echo Setup completed.
echo You can now start the application with 92_run_from_anaconda.bat.
exit /b 0
