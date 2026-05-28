param(
    [int]$Port = 8000,
    [string]$HostAddress = "127.0.0.1",
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Stop-IfFailed($Message) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host $Message -ForegroundColor Red
        pause
        exit $LASTEXITCODE
    }
}

function Get-PythonLauncher {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3.11")
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    return $null
}

Set-Location $ProjectRoot
$runtimeDir = Join-Path $ProjectRoot ".runtime"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Step "Creating Python environment"
    $launcher = Get-PythonLauncher
    if (-not $launcher) {
        Write-Host "Python 3.11 was not found. Install Python 3.11, then run this again." -ForegroundColor Red
        pause
        exit 2
    }

    if ($launcher.Count -eq 2) {
        & $launcher[0] $launcher[1] -m venv ".venv"
    } else {
        & $launcher[0] -m venv ".venv"
    }
    Stop-IfFailed "Could not create the Python virtual environment."
}

if (-not $NoInstall) {
    Write-Step "Checking dependencies"
    $dependencyCheck = Start-Process -FilePath $python `
        -ArgumentList @("-c", "import fastapi, uvicorn, numpy, sounddevice, azure.cognitiveservices.speech") `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeDir "dependency-check.out.log") `
        -RedirectStandardError (Join-Path $runtimeDir "dependency-check.err.log")
    if ($dependencyCheck.ExitCode -ne 0) {
        Write-Host "Installing dependencies. First run can take a while." -ForegroundColor Yellow
        & $python -m pip install --upgrade pip
        Stop-IfFailed "Could not upgrade pip."
        & $python -m pip install -r "backend\requirements.txt"
        Stop-IfFailed "Could not install project dependencies."
    } else {
        Write-Host "Dependencies look ready."
    }
}

$url = "http://$HostAddress`:$Port"
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    Write-Step "Subtitle Studio is already running"
    Write-Host "Opening $url"
    Start-Process $url
    Write-Host "A server is already listening on port $Port."
    Write-Host "Use Stop Subtitle Studio.bat if you want to stop it."
    pause
    exit 0
}

Write-Step "Starting Subtitle Studio"
Write-Host "URL: $url"
Write-Host "This window is the local app server."
Write-Host "Close this window or press Ctrl+C to stop Subtitle Studio."

$openScript = @"
for (`$i = 0; `$i -lt 30; `$i++) {
    try {
        `$result = Invoke-RestMethod -Uri '$url/api/health' -TimeoutSec 2
        if (`$result.ok) {
            Start-Process '$url'
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 700
}
Start-Process '$url'
"@

Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $openScript) -WindowStyle Hidden

& $python -m uvicorn backend.main:app --host $HostAddress --port $Port
