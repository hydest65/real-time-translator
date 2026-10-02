$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$packages = foreach ($folder in (Get-ChildItem -LiteralPath (Join-Path $projectRoot 'outputs') -Directory -Filter 'Subtitle-Studio-Desktop-*')) {
    $manifest = Join-Path $folder.FullName 'resources\app\package.json'
    if (-not (Test-Path -LiteralPath $manifest) -or
        -not (Test-Path -LiteralPath (Join-Path $folder.FullName 'Subtitle Studio.exe'))) { continue }
    try {
        $version = [version](Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json).version
        [PSCustomObject]@{ FullName = $folder.FullName; Version = $version; Name = $folder.Name }
    } catch { continue }
}
$package = $packages | Sort-Object Version,Name -Descending | Select-Object -First 1
if (-not $package) { throw 'Desktop app package not found. Run scripts/build-desktop.ps1 first.' }
Start-Process -FilePath (Join-Path $package.FullName 'Subtitle Studio.exe') -WindowStyle Hidden
