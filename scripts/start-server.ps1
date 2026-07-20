param(
    [int]$Port = 8000,
    [string]$HostAddress = "127.0.0.1",
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$NoInstall,
    [switch]$InstallLocalModels,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
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

function Stop-IfFailed($Message) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host $Message -ForegroundColor Red
        exit $LASTEXITCODE
    }
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
        exit 2
    }

    if ($launcher.Count -eq 2) {
        & $launcher[0] $launcher[1] -m venv ".venv"
        Stop-IfFailed "Could not create the Python virtual environment."
    } else {
        & $launcher[0] -m venv ".venv"
        Stop-IfFailed "Could not create the Python virtual environment."
    }
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

    if ($InstallLocalModels) {
        Write-Step "Installing optional local model dependencies"
        & $python -m pip install -r "backend\requirements-local.txt"
        Stop-IfFailed "Could not install optional local model dependencies."
    }
}

$url = "http://$HostAddress`:$Port"
Write-Step "Starting Subtitle Studio"
Write-Host "Project: $ProjectRoot"
Write-Host "URL: $url"
Write-Host "Close this window or press Ctrl+C to stop the local server."

if (-not $NoOpen) {
    try {
        $openCommand = "Start-Sleep -Seconds 3; Start-Process '$url'"
        Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $openCommand) -WindowStyle Hidden
    } catch {
        Write-Host "Could not open the browser automatically. Open this URL manually: $url" -ForegroundColor Yellow
    }
}

& $python -m uvicorn backend.main:app --host $HostAddress --port $Port
