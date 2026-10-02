param(
    [int]$Port = 8000,
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "start-server.ps1") `
    -Port $Port `
    -HostAddress "0.0.0.0" `
    -ProjectRoot $ProjectRoot `
    -NoOpen `
    -NoInstall:$NoInstall
