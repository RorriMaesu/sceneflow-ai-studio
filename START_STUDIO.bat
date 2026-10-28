@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%~dp0cache\pip"
set "STUDIO_ROOT=%~dp0"
set "PYTHONIOENCODING=utf-8"
call "%~dp0SETUP_STUDIO.bat"
if errorlevel 1 exit /b 1
if exist "%~dp0local\app-update.json" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0backend\apply_update.py" --root "%~dp0." --recover
  if errorlevel 1 exit /b 1
)
echo Your private studio opens at http://127.0.0.1:8770
"%~dp0.venv\Scripts\python.exe" "%~dp0backend\launch.py"
if errorlevel 1 pause
