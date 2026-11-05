@echo off
setlocal
cd /d "%~dp0"

echo Starting the desktop skin inference server...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-skin-server.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo The inference server stopped with exit code %EXIT_CODE%.
  echo Check .env.skin-server.local and the messages above.
)

echo.
pause
exit /b %EXIT_CODE%
