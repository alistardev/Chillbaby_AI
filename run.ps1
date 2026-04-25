$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found. Running bootstrap..." -ForegroundColor Yellow
    & (Join-Path $projectRoot "bootstrap.ps1")
}

Write-Host "Starting Cammy..." -ForegroundColor Cyan
& $venvPython chillapp.py --cert-file cert.pem --key-file key.pem
