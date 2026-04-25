$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$localPython = Join-Path $projectRoot ".python\cpython-3.10.20\python\python.exe"
$venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    if (-not (Test-Path $localPython)) {
        throw "Python 3.10.20 runtime not found at $localPython"
    }

    Write-Host "Creating virtual environment (Python 3.10.20)..." -ForegroundColor Cyan
    & $localPython -m venv venv
}

Write-Host "Upgrading pip..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip

Write-Host "Installing requirements..." -ForegroundColor Cyan
& $venvPython -m pip install -r requirements.txt

Write-Host ""
Write-Host "Bootstrap complete." -ForegroundColor Green
Write-Host "Use '.\run.ps1' to start the app."
