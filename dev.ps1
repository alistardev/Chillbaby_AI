param(
    [string]$HostName = "0.0.0.0",
    [int]$Port = 5000,
    [string]$CertFile = "cert.pem",
    [string]$KeyFile = "key.pem",
    [switch]$KillExisting
)

$ErrorActionPreference = "Stop"

if (!(Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "venv not found. Run .\bootstrap.ps1 first." -ForegroundColor Yellow
    exit 1
}

function Test-PortBindable([string]$BindHost, [int]$BindPort) {
    $bindIp = [System.Net.IPAddress]::Any
    if ($BindHost -and $BindHost -ne "0.0.0.0") {
        try {
            $bindIp = [System.Net.IPAddress]::Parse($BindHost)
        } catch {
            $bindIp = [System.Net.IPAddress]::Any
        }
    }

    $probe = $null
    try {
        $probe = [System.Net.Sockets.TcpListener]::new($bindIp, $BindPort)
        $probe.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($probe) {
            $probe.Stop()
        }
    }
}

$connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -gt 0 } |
    Select-Object -First 1

if ($connection) {
    $ownerPid = $connection.OwningProcess
    $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    $pname = if ($proc) { $proc.ProcessName } else { "unknown" }

    if ($KillExisting) {
        Write-Host "Port $Port is in use by PID $ownerPid ($pname). Stopping it..." -ForegroundColor Yellow
        Stop-Process -Id $ownerPid -Force
        Start-Sleep -Milliseconds 400
    } else {
        Write-Host "Port $Port is already in use by PID $ownerPid ($pname)." -ForegroundColor Red
        Write-Host "Either stop it first, or rerun with -KillExisting." -ForegroundColor Yellow
        Write-Host "Example: .\dev.ps1 -KillExisting"
        exit 1
    }
}

if (!(Test-PortBindable -BindHost $HostName -BindPort $Port)) {
    Write-Host "Port $Port is not bindable yet. Waiting for release..." -ForegroundColor Yellow
    $released = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 300
        if (Test-PortBindable -BindHost $HostName -BindPort $Port) {
            $released = $true
            break
        }
    }

    if (!$released) {
        Write-Host "Port $Port is still unavailable (WinError 10048 risk)." -ForegroundColor Red
        Write-Host "Try .\dev.ps1 -KillExisting or choose a different port (e.g. -Port 5001)." -ForegroundColor Yellow
        exit 1
    }
}

$watchfilesExe = ".\venv\Scripts\watchfiles.exe"
if (!(Test-Path $watchfilesExe)) {
    Write-Host "Installing watchfiles for hot reload..." -ForegroundColor Cyan
    .\venv\Scripts\pip.exe install watchfiles
}

# Faster iteration in dev: skip heavy PANN warmup on each restart.
$env:CAMMY_SKIP_PANN_WARMUP = "1"

Write-Host "Starting Cammy dev server with hot reload..." -ForegroundColor Green
Write-Host "Host=$HostName Port=$Port Cert=$CertFile Key=$KeyFile"

$target = ".\venv\Scripts\python.exe chillapp.py --host $HostName --port $Port --cert-file $CertFile --key-file $KeyFile"

& $watchfilesExe `
    --target-type command `
    --filter default `
    --ignore-paths "venv,.git,__pycache__,static/videos,.python" `
    "$target" `
    "."
