@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0SceneFlowSetup.exe" (
  "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:exe /r:System.Windows.Forms.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll /out:"%~dp0SceneFlowSetup.exe" "%~dp0scripts\SceneFlowSetup.cs"
  if errorlevel 1 goto error
)
"%~dp0SceneFlowSetup.exe"
if errorlevel 1 goto error
exit /b 0
:error
echo Setup needs attention. Read the message above, then open SETUP_STUDIO again.
pause
exit /b 1
