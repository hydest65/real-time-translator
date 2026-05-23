@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=@(8000,8001); $stopped=$false; foreach($port in $ports){ Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $stopped=$true; Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('Stopped local server on port ' + $port) } }; if(-not $stopped){ Write-Host 'No Subtitle Studio backend was listening on ports 8000 or 8001.' }"
echo.
pause
