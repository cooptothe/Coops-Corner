<#
.SYNOPSIS
  Manually starts all three Coop's Corner services with logs in retained\service-logs.

.DESCRIPTION
  1. Refresh service  (python -m pipelines.refresh_service)  port 8766  (started first: it creates the login secret)
  2. Tools API        (python -m api.run_local)               port 8765
  3. Web app          (pnpm dev)                              port 3000

  scripts\stop-services.ps1 stops everything at once. No startup task or Windows service is registered.

.PARAMETER MaxAgeSeconds
  How old stored odds may be and still count (CORNER_TOOLS_MAX_AGE_SECONDS). Leave out to use the app's default
  (2 hours) or whatever the variable is already set to. Use a larger value (for example 259200 = 3 days) to see
  older stored odds, such as after a day with no refresh.

.PARAMETER Open
  Open http://localhost:3000 in the browser when everything is up.

.PARAMETER Fast
  Build and run the production web app locally. Manual fetching remains controlled
  by your existing configuration. Stop running services before switching modes.

.PARAMETER Ngrok
  Also start an ngrok tunnel to the web app (so you can open the app on your phone) and allow exactly that
  tunnel's https address in the app. The address is printed when everything is up. Needs ngrok installed and its
  authtoken added once:  ngrok config add-authtoken <your token>

.PARAMETER NgrokUrl
  With -Ngrok: use this fixed address instead of a random one (a free static domain from the ngrok dashboard),
  for example https://your-name.ngrok-free.app. The phone's bookmark then keeps working.

.PARAMETER BasicAuth
  With -Ngrok: ask for this 'user:password' (password at least 8 characters) before ngrok lets anyone reach the app.
  Strongly recommended: the tunnel is public, the app has open sign-up, and signed-in users can spend Odds API credits.

.EXAMPLE
  .\scripts\start-services.ps1
  .\scripts\start-services.ps1 -MaxAgeSeconds 259200 -Open
  .\scripts\start-services.ps1 -Ngrok -BasicAuth 'me:a-long-password'
#>
[CmdletBinding()]
param(
    [int]$MaxAgeSeconds = 0,
    [switch]$Fast,
    [switch]$Open,
    [switch]$Ngrok,
    [string]$NgrokUrl,
    [string]$BasicAuth
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv-api\Scripts\python.exe'
$pidFile = Join-Path $root 'retained\services.json'
$policyFile = Join-Path $root 'retained\ngrok-policy.yml'
$ports = @{ refresh = 8766; api = 8765; web = 3000 }

if (-not (Test-Path $python)) { throw "Python environment not found at $python" }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { throw 'pnpm was not found on PATH.' }
if (($NgrokUrl -or $BasicAuth) -and -not $Ngrok) { throw '-NgrokUrl and -BasicAuth need -Ngrok.' }
if ($Ngrok) {
    if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) { throw 'ngrok was not found on PATH.' }
    & cmd.exe /c 'ngrok config check >nul 2>&1'  # through cmd, so ngrok's stderr is not turned into a PowerShell error
    if ($LASTEXITCODE -ne 0) {
        throw "ngrok has no authtoken yet. Sign up at https://dashboard.ngrok.com, then run once:`n  ngrok config add-authtoken <your token>"
    }
    if ($NgrokUrl -and $NgrokUrl -notmatch '^https://[A-Za-z0-9.-]+$') { throw '-NgrokUrl must look like https://your-name.ngrok-free.app' }
    if ($BasicAuth -and $BasicAuth -notmatch '^[^:\s"]+:[^\s"]{8,}$') { throw '-BasicAuth must be user:password with a password of at least 8 characters (no spaces or quotes).' }
    if (Get-NetTCPConnection -LocalPort 4040 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Port 4040 (ngrok) is already in use. Run .\scripts\stop-services.ps1 first.'
    }
}

function Get-Listener([int]$port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

$busy = $ports.GetEnumerator() | Where-Object { Get-Listener $_.Value }
if ($busy) {
    Write-Host 'These ports are already in use:' -ForegroundColor Yellow
    $busy | ForEach-Object { Write-Host "  $($_.Name): $($_.Value)" }
    Write-Host 'Run .\scripts\stop-services.ps1 first.' -ForegroundColor Yellow
    exit 1
}

if ($MaxAgeSeconds -gt 0) { $env:CORNER_TOOLS_MAX_AGE_SECONDS = "$MaxAgeSeconds" }

if ($Fast) {
    Push-Location (Join-Path $root 'web')
    try {
        & pnpm build
        if ($LASTEXITCODE -ne 0) { throw 'Production web build failed; services were not started.' }
    } finally { Pop-Location }
}

function Start-Window([string]$title, [string]$workdir, [string]$command) {
    $logDirectory = Join-Path $root 'retained\service-logs'
    New-Item -ItemType Directory -Force $logDirectory | Out-Null
    $logFile = Join-Path $logDirectory (($title -replace '[^a-zA-Z0-9-]', '_') + '.log')
    $inner = "Set-Location '$workdir'; $command *>> '$logFile'; exit `$LASTEXITCODE"
    Start-Process -FilePath powershell -WindowStyle Hidden -ArgumentList '-NoLogo', '-NoProfile', '-Command', $inner -PassThru
}

function Wait-Port([string]$name, [int]$port, [int]$seconds, $window) {
    Write-Host "Waiting for $name on :$port " -NoNewline
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-Listener $port) { Write-Host ' up' -ForegroundColor Green; return }
        if ($window.HasExited) { throw "$name exited before startup. Check retained\service-logs." }
        Write-Host '.' -NoNewline
        Start-Sleep -Milliseconds 700
    }
    throw "$name did not start listening on :$port within $seconds seconds. Check retained\service-logs."
}

$windows = [ordered]@{}
$publicUrl = $null

if ($Ngrok) {
    # The tunnel goes first: its address has to be known to the services so they accept requests from it.
    $arguments = "http 127.0.0.1:3000"
    if ($NgrokUrl) { $arguments += " --url $NgrokUrl" }
    if ($BasicAuth) {
        New-Item -ItemType Directory -Force (Split-Path $policyFile) | Out-Null
        @"
on_http_request:
  - actions:
      - type: basic-auth
        config:
          credentials:
            - "$BasicAuth"
"@ | Set-Content -Path $policyFile -Encoding ascii
        $arguments += " --traffic-policy-file '$policyFile'"
    }
    $windows.ngrok = Start-Window 'Corner: ngrok tunnel' $root "ngrok $arguments"
    Write-Host 'Waiting for the ngrok tunnel ' -NoNewline
    $deadline = (Get-Date).AddSeconds(40)
    while (-not $publicUrl -and (Get-Date) -lt $deadline) {
        if ($windows.ngrok.HasExited) { throw 'The ngrok window closed. Run ngrok by hand to see the error.' }
        try {
            $publicUrl = (Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2).tunnels |
                Where-Object { $_.public_url -like 'https://*' } | Select-Object -First 1 -ExpandProperty public_url
        } catch { }
        if (-not $publicUrl) { Write-Host '.' -NoNewline; Start-Sleep -Milliseconds 700 }
    }
    if (-not $publicUrl) { throw 'ngrok did not report a public address. Check its window.' }
    Write-Host " $publicUrl" -ForegroundColor Green
    $env:CORNER_PUBLIC_ORIGINS = $publicUrl
}

# The refresh service creates retained\auth_secret, which the tools API reads, so it goes first.
$windows.refresh = Start-Window 'Corner: refresh service :8766' $root "& '$python' -m pipelines.refresh_service"
Wait-Port 'Refresh service' $ports.refresh 60 $windows.refresh

# The tools API builds its catalog from the database before it listens (about 10 to 30 seconds).
$windows.api = Start-Window 'Corner: tools API :8765' $root "& '$python' -m api.run_local --port 8765"
Wait-Port 'Tools API' $ports.api 180 $windows.api

$webCommand = if ($Fast) { 'pnpm start' } else { 'pnpm dev' }
$windows.web = Start-Window 'Corner: web :3000' (Join-Path $root 'web') $webCommand
Wait-Port 'Web app' $ports.web 120 $windows.web

New-Item -ItemType Directory -Force (Split-Path $pidFile) | Out-Null
($windows.GetEnumerator() | ForEach-Object { [pscustomobject]@{ name = $_.Name; pid = $_.Value.Id } }) |
    ConvertTo-Json | Set-Content -Path $pidFile -Encoding utf8

Write-Host ''
Write-Host 'All services are running:' -ForegroundColor Green
Write-Host '  Web app          http://localhost:3000'
Write-Host '  Tools API        http://127.0.0.1:8765'
Write-Host '  Refresh service  http://127.0.0.1:8766'
if ($publicUrl) {
    Write-Host ''
    Write-Host "  On your phone    $publicUrl" -ForegroundColor Cyan
    Write-Host '  ngrok shows a "Visit Site" page the first time: tap it.'
    if ($BasicAuth) { Write-Host '  Then sign in to the ngrok prompt with the -BasicAuth user and password.' }
    else { Write-Host '  Anyone with this address can reach the app and create accounts. Use -BasicAuth, and stop it when done.' -ForegroundColor Yellow }
}
Write-Host 'Stop them all with .\scripts\stop-services.ps1'
if ($Open) { Start-Process 'http://localhost:3000' }
