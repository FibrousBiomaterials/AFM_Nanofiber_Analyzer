@echo off
REM Create or update a dedicated conda environment for AFM Nanofiber Analyzer.
REM The environment is created in the project folder as .conda-env.
setlocal
cd /d "%~dp0"

set "ENV_DIR=%~dp0.conda-env"
set "CONDA_CMD="

echo [1/6] Searching for conda...

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
echo [2/6] Creating or reusing conda environment:
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
echo [3/6] Upgrading pip...
call "%CONDA_CMD%" run -p "%ENV_DIR%" python -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo.
echo [4/6] Generating requirements...
REM check.py regenerates requirements.txt from the project imports before install.
call "%CONDA_CMD%" run -p "%ENV_DIR%" python check.py
if errorlevel 1 (
    echo Failed to generate requirements.txt.
    pause
    exit /b 1
)

echo.
echo [5/6] Installing requirements...
echo Installing mahotas with conda-forge first to avoid pip build failures...
call "%CONDA_CMD%" install -y -p "%ENV_DIR%" -c conda-forge mahotas
if errorlevel 1 (
    echo conda-forge mahotas install failed; continuing with pip requirements.
)
call "%CONDA_CMD%" run -p "%ENV_DIR%" python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
)

echo.
echo [6/6] Writing 12_run_from_conda_env.bat...
(
    echo @echo off
    echo REM Start AFM Nanofiber Analyzer inside the dedicated conda environment.
    echo REM Run 11_setup_conda_env.bat first if the environment has not been created.
    echo setlocal
    echo cd /d "%%~dp0"
    echo.
    echo set "ENV_DIR=%%~dp0.conda-env"
    echo set "CONDA_CMD="
    echo.
    echo if defined CONDA_EXE ^(
    echo     if exist "%%CONDA_EXE%%" ^(
    echo         set "CONDA_CMD=%%CONDA_EXE%%"
    echo         goto found_conda
    echo     ^)
    echo ^)
    echo.
    echo where conda ^>nul 2^>nul
    echo if not errorlevel 1 ^(
    echo     set "CONDA_CMD=conda"
    echo     goto found_conda
    echo ^)
    echo.
    echo for %%%%C in ^(
    echo     "%%USERPROFILE%%\anaconda3\Scripts\conda.exe"
    echo     "%%USERPROFILE%%\miniconda3\Scripts\conda.exe"
    echo     "%%USERPROFILE%%\anaconda3\condabin\conda.bat"
    echo     "%%USERPROFILE%%\miniconda3\condabin\conda.bat"
    echo     "%%LOCALAPPDATA%%\anaconda3\Scripts\conda.exe"
    echo     "%%LOCALAPPDATA%%\miniconda3\Scripts\conda.exe"
    echo     "%%LOCALAPPDATA%%\anaconda3\condabin\conda.bat"
    echo     "%%LOCALAPPDATA%%\miniconda3\condabin\conda.bat"
    echo     "%%ProgramData%%\anaconda3\Scripts\conda.exe"
    echo     "%%ProgramData%%\miniconda3\Scripts\conda.exe"
    echo     "%%ProgramData%%\anaconda3\condabin\conda.bat"
    echo     "%%ProgramData%%\miniconda3\condabin\conda.bat"
    echo ^) do ^(
    echo     if exist "%%%%~C" ^(
    echo         set "CONDA_CMD=%%%%~C"
    echo         goto found_conda
    echo     ^)
    echo ^)
    echo.
    echo echo conda was not found.
    echo echo Please install Anaconda/Miniconda, or run this file from Anaconda Prompt.
    echo pause
    echo exit /b 1
    echo.
    echo :found_conda
    echo call "%%CONDA_CMD%%" run -p "%%ENV_DIR%%" python "%%~dp0Main.py"
    echo if errorlevel 1 ^(
    echo     echo.
    echo     echo Failed to start the application.
    echo     echo Please run 11_setup_conda_env.bat first.
    echo     pause
    echo     exit /b 1
    echo ^)
    echo exit /b 0
) > 12_run_from_conda_env.bat
if errorlevel 1 (
    echo Failed to write 12_run_from_conda_env.bat.
    pause
    exit /b 1
)

echo.
echo Setup completed.
echo Conda environment:
echo %ENV_DIR%
echo You can now start the application with 12_run_from_conda_env.bat.
exit /b 0
