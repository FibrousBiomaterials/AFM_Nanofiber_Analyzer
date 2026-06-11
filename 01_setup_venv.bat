@echo off
REM Create or update the local .venv environment for AFM Nanofiber Analyzer.
REM This path avoids conda and uses the Windows Python launcher.
setlocal
cd /d "%~dp0"

echo [1/6] Checking Python...
py -3 --version
if errorlevel 1 (
    echo.
    echo Python launcher "py" was not found.
    echo Please install Python 3.10 or later, then run this file again.
    pause
    exit /b 1
)

echo.
echo [2/6] Creating virtual environment...
py -3 -m venv .venv
if errorlevel 1 (
    echo Failed to create .venv.
    pause
    exit /b 1
)

echo.
echo [3/6] Upgrading pip...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo.
echo [4/6] Generating requirements...
REM check.py regenerates requirements.txt from the project imports before install.
call ".venv\Scripts\python.exe" check.py
if errorlevel 1 (
    echo Failed to generate requirements.txt.
    pause
    exit /b 1
)

echo.
echo [5/6] Installing requirements...
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
)

echo.
echo [6/6] Writing 02_run_from_venv.bat...
(
    echo @echo off
    echo REM Start AFM Nanofiber Analyzer from the local .venv created by 01_setup_venv.bat.
    echo setlocal
    echo cd /d "%%~dp0"
    echo.
    echo if not exist ".venv\Scripts\python.exe" ^(
    echo     echo .venv was not found.
    echo     echo Please run 01_setup_venv.bat first.
    echo     pause
    echo     exit /b 1
    echo ^)
    echo.
    echo call ".venv\Scripts\python.exe" "%%~dp0Main.py"
    echo set "EXIT_CODE=%%ERRORLEVEL%%"
    echo.
    echo if not "%%EXIT_CODE%%"=="0" ^(
    echo     echo Main.py exited with error code %%EXIT_CODE%%.
    echo     pause
    echo ^)
    echo.
    echo exit /b %%EXIT_CODE%%
) > 02_run_from_venv.bat
if errorlevel 1 (
    echo Failed to write 02_run_from_venv.bat.
    pause
    exit /b 1
)

echo.
echo Setup completed.
echo You can now start the application with 02_run_from_venv.bat.
exit /b 0
