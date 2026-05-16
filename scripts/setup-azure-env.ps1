param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function Read-Required($Prompt) {
    while ($true) {
        $value = Read-Host $Prompt
        if ($value.Trim()) {
            return $value.Trim()
        }
        Write-Host "This value is required." -ForegroundColor Yellow
    }
}

function Escape-EnvValue($Value) {
    return $Value.Replace("`r", "").Replace("`n", "").Trim()
}

Set-Location $ProjectRoot
$envPath = Join-Path $ProjectRoot ".env"

Write-Host ""
Write-Host "Azure Speech permanent local setup" -ForegroundColor Cyan
Write-Host "This writes credentials to: $envPath"
Write-Host "The .env file is ignored by git and should not be shared."
Write-Host ""

$speechKey = Read-Required "Azure Speech key"
$speechRegion = Read-Required "Azure Speech region, for example eastus"
$defaultPhraseList = "Teams,Codex,faster-whisper,MarianMT,Azure Speech,UPW,CDA,PCW,FFU,MAU,HEPA,VHP,P&ID,HAZOP"
$phraseList = Read-Host "Phrase list, optional comma-separated terms [$defaultPhraseList]"
if (-not $phraseList.Trim()) {
    $phraseList = $defaultPhraseList
}

$content = @(
    "# Local Azure Speech configuration for Subtitle Studio.",
    "# This file is ignored by git. Do not share it.",
    "AZURE_SPEECH_KEY=$(Escape-EnvValue $speechKey)",
    "AZURE_SPEECH_REGION=$(Escape-EnvValue $speechRegion)",
    "AZURE_PHRASE_LIST=$(Escape-EnvValue $phraseList)"
)

Set-Content -Path $envPath -Value $content -Encoding UTF8

Write-Host ""
Write-Host "Saved Azure credentials to .env." -ForegroundColor Green
Write-Host "Restart Subtitle Studio, then choose Engine: Azure Cloud."
