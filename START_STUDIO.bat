@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%~dp0cache\pip"
set "STUDIO_ROOT=%~dp0"
set "PYTHONIOENCODING=utf-8"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run SETUP_STUDIO.bat first.
  pause
  exit /b 1
)
echo Your private studio opens at http://127.0.0.1:8770
echo Leave this window open while production runs. Closing your browser is fine.
"%~dp0.venv\Scripts\python.exe" "%~dp0backend\run.py"
pause
