@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto setup_missing
if not exist .venv\Scripts\pythonw.exe goto setup_missing
if not exist app\check_environment.py goto files_missing
if not exist app\track_splitter.py goto files_missing
echo Checking Track Splitter installation...
.venv\Scripts\python.exe app/check_environment.py --startup
if errorlevel 1 goto fail
if not exist library\logs mkdir library\logs
start "" /b ".venv\Scripts\pythonw.exe" "app\track_splitter.py" %* 1>>library\logs\desktop.log 2>&1
if errorlevel 1 goto fail
exit /b 0

:setup_missing
echo Track Splitter setup has not completed.
echo Run Setup_Track_Splitter.bat first. It requires 64-bit Python 3.12.
goto fail

:files_missing
echo Track Splitter application files are missing.
echo Extract or download the complete project folder, then run Setup_Track_Splitter.bat.

:fail
echo Track Splitter could not start. See the error above.
pause
exit /b 1
