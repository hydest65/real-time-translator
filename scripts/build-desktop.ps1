param(
    [string]$ElectronZip = (Join-Path $PSScriptRoot '..\.cache\desktop-build\downloads\electron-v44.5.1-win32-x64.zip'),
    [switch]$SkipBackendBuild
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $projectRoot
if (-not (Test-Path -LiteralPath $ElectronZip)) { throw 'Download the Electron runtime first. Choose VPS/proxy or direct routing; Motrix is the default downloader.' }
$expectedHash = '9b382492dcfee91f8f9e92c91f7972550a1b95d2299cac72279dab33a600d7db'
if ((Get-FileHash -LiteralPath $ElectronZip -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Electron archive checksum mismatch.' }
if ($SkipBackendBuild) {
    foreach ($frontendFile in (Get-ChildItem -LiteralPath frontend -File)) {
        $bundledFile = Join-Path $projectRoot ('desktop\dist\subtitle-backend\_internal\frontend\' + $frontendFile.Name)
        if (-not (Test-Path -LiteralPath $bundledFile) -or
            (Get-FileHash -LiteralPath $frontendFile.FullName).Hash -ne (Get-FileHash -LiteralPath $bundledFile).Hash) {
            Write-Output 'Refreshing the backend bundle to include the current UI.'
            $SkipBackendBuild = $false
            break
        }
    }
}
if (-not $SkipBackendBuild) {
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath desktop/dist --workpath desktop/build desktop/backend.spec
    if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
}
$backendBuild = Join-Path $projectRoot 'desktop\dist\subtitle-backend'
if (-not (Test-Path (Join-Path $backendBuild 'subtitle-backend.exe'))) { throw 'Backend executable missing.' }
$desktopVersion = (Get-Content -LiteralPath (Join-Path $projectRoot 'desktop\package.json') -Raw | ConvertFrom-Json).version
if ($desktopVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid desktop version.' }
$releaseFolder = Join-Path $projectRoot ('outputs\Subtitle-Studio-Desktop-' + $desktopVersion + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $releaseFolder -Force | Out-Null
Expand-Archive -LiteralPath $ElectronZip -DestinationPath $releaseFolder
Rename-Item -LiteralPath (Join-Path $releaseFolder 'electron.exe') -NewName 'Subtitle Studio.exe'
$appFolder = Join-Path $releaseFolder 'resources\app'
New-Item -ItemType Directory -Path $appFolder -Force | Out-Null
foreach ($filename in @('package.json', 'main.cjs', 'preload.cjs', 'geometry.cjs', 'cloud-config.cjs', 'smoke.cjs')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "desktop\$filename") -Destination $appFolder
}
Copy-Item -LiteralPath $backendBuild -Destination (Join-Path $releaseFolder 'resources\backend') -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\DESKTOP_APP.md') -Destination (Join-Path $releaseFolder '使用说明.md')
foreach ($releaseFile in (Get-ChildItem -LiteralPath $releaseFolder -Force -Recurse -File)) {
    $relative = $releaseFile.FullName.Substring($releaseFolder.Length + 1).Replace('\', '/')
    if ($releaseFile.Name -eq '.env' -or $releaseFile.Extension -in @('.wav', '.mp3', '.key')) {
        throw "Unexpected private configuration or media: $relative"
    }
    if ($releaseFile.Extension -eq '.pem') {
        if ($relative -notin @('resources/backend/_internal/certifi/cacert.pem', 'resources/backend/_internal/grpc/_cython/_credentials/roots.pem') -or
            [IO.File]::ReadAllText($releaseFile.FullName) -match 'PRIVATE KEY') {
            throw "Unexpected certificate or private key: $relative"
        }
    }
}
$releaseZip = "$releaseFolder.zip"
Compress-Archive -Path (Join-Path $releaseFolder '*') -DestinationPath $releaseZip
Write-Output "Application: $(Join-Path $releaseFolder 'Subtitle Studio.exe')"
Write-Output "Package: $releaseZip"
exit 0
