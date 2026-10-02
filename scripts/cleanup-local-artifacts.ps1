[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$All,
    [switch]$IncludeVenv,
    [switch]$IncludeRecordings,
    [switch]$IncludeDesignPreviews
)

$ErrorActionPreference = "Stop"

function Get-PathSizeMB($Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return 0
    }

    $total = (Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if (-not $total) {
        $total = 0
    }
    return [math]::Round($total / 1MB, 1)
}

function Resolve-ChildPath($Root, $RelativePath) {
    $candidate = Join-Path $Root $RelativePath
    if (Test-Path -LiteralPath $candidate) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    return $null
}

$root = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd("\")
$targets = @(
    ".model-cache",
    ".cache",
    ".runtime",
    ".pip-cache",
    "logs"
)

if ($All -or $IncludeVenv) {
    $targets += ".venv"
}
if ($All -or $IncludeRecordings) {
    $targets += "recordings"
}
if ($All -or $IncludeDesignPreviews) {
    $targets += "design-previews"
}

Write-Host "Project root: $root"
Write-Host "Cleanup targets: $($targets -join ', ')"

foreach ($relative in $targets) {
    $target = Resolve-ChildPath -Root $root -RelativePath $relative
    if (-not $target) {
        Write-Host "Skip missing: $relative"
        continue
    }

    $normalized = $target.TrimEnd("\")
    if ($normalized -ne $root -and -not $normalized.StartsWith("$root\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside project root: $target"
    }

    $sizeMB = Get-PathSizeMB $target
    $label = "$relative ($sizeMB MB)"
    if ($PSCmdlet.ShouldProcess($target, "Remove $label")) {
        try {
            Remove-Item -LiteralPath $target -Recurse -Force
            Write-Host "Removed: $label"
        } catch {
            Write-Host "Could not fully remove $label. A running app may still be using one of its files." -ForegroundColor Yellow
            Write-Host $_.Exception.Message -ForegroundColor DarkYellow
        }
    }
}

Write-Host "Cleanup complete."
