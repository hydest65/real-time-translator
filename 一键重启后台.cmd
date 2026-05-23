@echo off
setlocal
cd /d "%~dp0"
echo Stopping existing Subtitle Studio backend on ports 8000 and 8001...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=@(8000,8001); foreach($port in $ports){ Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('Stopped local server on port ' + $port) } }"
echo.
echo Starting Subtitle Studio backend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-server.ps1"
echo.
echo Subtitle Studio backend has stopped. You can close this window.
pause
