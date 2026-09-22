param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python virtual environment not found at $python"
}

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    throw "Ollama was not found on PATH. Install Ollama for Windows first."
}

$env:APP_HOST = "0.0.0.0"
$env:APP_PORT = "$Port"

$ollamaReady = $false
try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
    $ollamaReady = $response.StatusCode -eq 200
} catch {
    $ollamaReady = $false
}

if (-not $ollamaReady) {
    Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WorkingDirectory $Root
    Start-Sleep -Seconds 2
}

try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    if ($response.StatusCode -ne 200) { throw "Ollama did not become ready." }
} catch {
    throw "Ollama is not reachable at http://127.0.0.1:11434. Start it manually and retry."
}

Write-Host "Starting SenaSaarthi AI at http://SERVER_LAN_IP:$Port"
& $python -m scripts.start_server
