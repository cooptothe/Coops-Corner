<#
.SYNOPSIS
  Stops all Coop's Corner services (web :3000, tools API :8765, refresh service :8766).

.DESCRIPTION
  Stops the windows that start-services.ps1 opened and anything else listening on those three ports (for
  example services you started by hand), including their child processes. Then it removes the temporary
  read-only database logins that a tools API leaves behind when it is stopped without Ctrl+C.

  Nothing else is touched: your data, accounts and retained odds stay as they are.

.EXAMPLE
  .\scripts\stop-services.ps1
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv-api\Scripts\python.exe'
$pidFile = Join-Path $root 'retained\services.json'
$ports = 8765, 8766, 3000

function Stop-Tree([int]$processId, [string]$label) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process) { return }
    Write-Host "  stopping $label (pid $processId, $($process.ProcessName))"
    & taskkill.exe /PID $processId /T /F 2>&1 | Out-Null
}

Write-Host 'Stopping services...'

# 1. The windows start-services.ps1 opened (their whole process trees).
if (Test-Path $pidFile) {
    try {
        $saved = @(Get-Content $pidFile -Raw | ConvertFrom-Json | ForEach-Object { $_ })  # flattens the array (Windows PowerShell 5.1)
        foreach ($entry in $saved) { Stop-Tree ([int]$entry.pid) "$($entry.name) window" }
    } catch {
        Write-Host "  (could not use the saved process list: $($_.Exception.Message))" -ForegroundColor Yellow
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

# 2. Whatever still listens on the service ports (and ngrok's local dashboard port), however it was started.
foreach ($port in $ports) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Tree $_ "listener on :$port" }
}
Get-NetTCPConnection -LocalPort 4040 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    Where-Object { (Get-Process -Id $_ -ErrorAction SilentlyContinue).ProcessName -like 'ngrok*' } |
    ForEach-Object { Stop-Tree $_ 'ngrok tunnel' }
Remove-Item (Join-Path $root 'retained\ngrok-policy.yml') -ErrorAction SilentlyContinue  # holds the tunnel's basic-auth password

# 3. Wait for the ports to free up.
$deadline = (Get-Date).AddSeconds(10)
do {
    $left = $ports | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue }
    if (-not $left) { break }
    Start-Sleep -Milliseconds 300
} while ((Get-Date) -lt $deadline)

if ($left) {
    Write-Host "Still listening: $($left -join ', ')" -ForegroundColor Red
} else {
    Write-Host 'All service ports are free.' -ForegroundColor Green
}

# 4. A tools API that is killed (rather than stopped with Ctrl+C) leaves its temporary database login behind.
if (Test-Path $python) {
    Push-Location $root
    try { & $python (Join-Path $PSScriptRoot 'drop_session_logins.py') } finally { Pop-Location }
}
