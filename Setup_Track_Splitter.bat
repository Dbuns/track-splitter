@echo off
setlocal
cd /d "%~dp0"
set "PYTHON312="
call py -3.12 -c "import struct,sys; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 (
 set "PYTHON312=py -3.12"
 goto python_found
)
call python -c "import struct,sys; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 (
 set "PYTHON312=python"
 goto python_found
)
echo Track Splitter requires 64-bit Python 3.12.
echo Python 3.13 and later are not supported by the pinned PyTorch version.
echo Install Python 3.12 for Windows from https://www.python.org/downloads/windows/
echo Select the Python launcher option during installation, then run this setup again.
echo Python 3.12 can be installed alongside other Python versions.
pause
exit /b 1

:python_found
echo Using 64-bit Python 3.12.
if not exist .tmp mkdir .tmp
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"
if not exist .venv\pyvenv.cfg goto create_environment
if not exist .venv\Scripts\python.exe goto recreate_environment
.venv\Scripts\python.exe -c "import struct,sys; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto recreate_environment
goto create_environment

:recreate_environment
echo Recreating the incompatible local Python environment. Close Track Splitter first.
echo Songs, stems and saved settings are kept.
call %PYTHON312% -m venv --clear .venv
if errorlevel 1 goto fail
goto install_dependencies

:create_environment
call %PYTHON312% -m venv .venv
if errorlevel 1 goto fail

:install_dependencies
.venv\Scripts\python.exe -m pip install --cache-dir .cache/pip torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --cache-dir .cache/pip -r app/requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe app/check_environment.py
if errorlevel 1 goto fail
echo Setup complete. Open Start_Track_Splitter.bat.
pause
exit /b 0

:fail
echo Setup did not complete. Track Splitter is not ready to launch.
echo Check the error above, then run Setup_Track_Splitter.bat again.
pause
exit /b 1
