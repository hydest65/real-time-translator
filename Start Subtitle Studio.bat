@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-server.ps1"
echo.
echo Subtitle Studio has stopped. You can close this window.
pause
