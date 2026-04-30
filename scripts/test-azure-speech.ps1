param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    if (-not (Test-Path $Path)) {
        return $values
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $name, $value = $line.Split("=", 2)
        $values[$name.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    return $values
}

$envPath = Join-Path $ProjectRoot ".env"
$values = Read-DotEnv -Path $envPath
$key = $values["AZURE_SPEECH_KEY"]
$region = $values["AZURE_SPEECH_REGION"]

Write-Host "Azure Speech config check"
Write-Host "Project: $ProjectRoot"
Write-Host ".env present: $([bool](Test-Path $envPath))"
Write-Host "Key present: $([bool]$key)"
Write-Host "Key length: $(if ($key) { $key.Length } else { 0 })"
Write-Host "Region: $(if ($region) { $region } else { '<missing>' })"

if (-not $key -or -not $region) {
    Write-Host "Result: missing AZURE_SPEECH_KEY or AZURE_SPEECH_REGION." -ForegroundColor Red
    exit 2
}

$oldHttpProxy = $env:HTTP_PROXY
$oldHttpsProxy = $env:HTTPS_PROXY
$oldAllProxy = $env:ALL_PROXY
$oldLowerHttpProxy = $env:http_proxy
$oldLowerHttpsProxy = $env:https_proxy
$oldLowerAllProxy = $env:all_proxy

try {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:ALL_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:all_proxy = ""

    $hostName = "$region.api.cognitive.microsoft.com"
    $portCheck = Test-NetConnection $hostName -Port 443 -WarningAction SilentlyContinue
    Write-Host "Port 443 reachable: $($portCheck.TcpTestSucceeded)"
    if (-not $portCheck.TcpTestSucceeded) {
        Write-Host "Result: network cannot reach Azure Cognitive Services for this region." -ForegroundColor Red
        exit 3
    }

    $body = @"
from pathlib import Path
import os
import urllib.error
import urllib.request

key = os.environ["AZURE_SPEECH_KEY_FOR_TEST"]
region = os.environ["AZURE_SPEECH_REGION_FOR_TEST"]
url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
request = urllib.request.Request(
    url,
    data=b"",
    method="POST",
    headers={"Ocp-Apim-Subscription-Key": key},
)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(request, timeout=12) as response:
        token = response.read()
        print(f"TOKEN_OK status={response.status} token_received={bool(token)}")
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="ignore").replace("\n", " ")[:300]
    print(f"TOKEN_HTTP_ERROR status={exc.code} reason={exc.reason} detail={detail}")
except Exception as exc:
    print(f"TOKEN_ERROR type={type(exc).__name__} detail={str(exc)[:300]}")
"@

    $env:AZURE_SPEECH_KEY_FOR_TEST = $key
    $env:AZURE_SPEECH_REGION_FOR_TEST = $region
    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        $python = "python"
    }
    $result = $body | & $python -
    Write-Host $result

    if ($result -like "TOKEN_OK*") {
        Write-Host "Result: Azure Speech key and region are usable." -ForegroundColor Green
        exit 0
    }
    if ($result -like "TOKEN_HTTP_ERROR status=401*") {
        Write-Host "Result: invalid subscription key or wrong region for this Speech resource." -ForegroundColor Red
        exit 4
    }

    Write-Host "Result: Azure token request failed. Check network, proxy, or Azure service availability." -ForegroundColor Red
    exit 5
}
finally {
    $env:HTTP_PROXY = $oldHttpProxy
    $env:HTTPS_PROXY = $oldHttpsProxy
    $env:ALL_PROXY = $oldAllProxy
    $env:http_proxy = $oldLowerHttpProxy
    $env:https_proxy = $oldLowerHttpsProxy
    $env:all_proxy = $oldLowerAllProxy
    Remove-Item Env:AZURE_SPEECH_KEY_FOR_TEST -ErrorAction SilentlyContinue
    Remove-Item Env:AZURE_SPEECH_REGION_FOR_TEST -ErrorAction SilentlyContinue
}
