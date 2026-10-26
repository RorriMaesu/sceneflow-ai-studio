@echo off
setlocal
cd /d "%~dp0"
if not exist temp mkdir temp
if not exist cache mkdir cache
set "TEMP=%~dp0temp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%~dp0cache\pip"
set "npm_config_cache=%~dp0cache\npm"
if not exist .venv\Scripts\python.exe py -3.11 -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto error
pushd frontend
call npm ci
if errorlevel 1 goto frontend_error
call npm run build
if errorlevel 1 goto frontend_error
popd
echo Setup complete. Open START_STUDIO.bat.
pause
exit /b 0
:frontend_error
popd
:error
echo Setup failed. Check the message above. Python 3.11 and Node.js 22 or newer are required.
pause
exit /b 1
