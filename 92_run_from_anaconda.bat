@echo off
REM Start AFM Nanofiber Analyzer with the Anaconda/Miniconda Python recorded by 91_setup_anaconda.bat.
REM Re-run 91_setup_anaconda.bat if the Anaconda installation path changes.
setlocal
cd /d "%~dp0"

set "PATH_FILE=%~dp0.afm_anaconda_python"
if not exist "%PATH_FILE%" (
    echo Anaconda Python path file was not found:
    echo %PATH_FILE%
    echo Please run 91_setup_anaconda.bat first.
    pause
    exit /b 1
)

set "ANACONDA_PYTHON="
set /p ANACONDA_PYTHON=<"%PATH_FILE%"

if not exist "%ANACONDA_PYTHON%" (
    echo Anaconda Python was not found:
    echo %ANACONDA_PYTHON%
    echo Please run 91_setup_anaconda.bat again.
    pause
    exit /b 1
)

call "%ANACONDA_PYTHON%" "%~dp0Main.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo Main.py exited with error code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
