# Start all six services in separate PowerShell windows with consistent env.
#
# This fixes the "SECRET_KEY differs between windows" problem by dot-sourcing
# demo/demo-env.ps1 in each window first. Everything is defined once.
# Also ensures DATABASE_URL is set correctly (Alpha gets its own DB).
#
# Each service's output is teed to demo\logs\<service>.log so a demo can be
# narrated without alt-tabbing to six windows. Nothing is lost -- the same lines
# still print in the window.

param(
    # Where to write the per-service logs. Created if missing.
    [string]$LogDir,
    # Append to existing logs instead of truncating them. Useful when a service
    # is restarted mid-demo and you want the earlier output kept.
    [switch]$AppendLog,
    # Reuse the tenant from the previous run instead of minting a fresh one.
    [switch]$KeepTenant
)

$DemoDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $DemoDir
$EnvScript = Join-Path $DemoDir 'demo-env.ps1'
$HealthScript = Join-Path $DemoDir 'health-check.ps1'

if (-not $LogDir) { $LogDir = Join-Path $DemoDir 'logs' }

# Verify the target exists before we launch anything.
if (-not (Test-Path $EnvScript)) {
    throw "Cannot find $EnvScript"
}

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# --- One tenant for this run ----------------------------------------------
# start-services.ps1 is the run boundary: it mints the tenant every window will
# share and writes it to demo\.run\tenant, which demo-env.ps1 reads. A new
# invocation is therefore a new run with a new tenant, unless -KeepTenant is
# passed. Beta's Kafka consumer reads B11_SERVICE_TENANT_ID once at process
# start, so rotating the tenant without restarting Beta would break the bus.
$RunDir     = Join-Path $DemoDir '.run'
$TenantFile = Join-Path $RunDir 'tenant'
if (-not (Test-Path $RunDir)) { New-Item -ItemType Directory -Path $RunDir -Force | Out-Null }
if ($KeepTenant -and (Test-Path $TenantFile)) {
    $RunTenant = (Get-Content $TenantFile -Raw -EA SilentlyContinue) -replace [char]0xFEFF, ''
    $RunTenant = $RunTenant.Trim()
} else {
    $RunTenant = "demo-$([guid]::NewGuid().ToString('N').Substring(0,8))"
}
Set-Content -Path $TenantFile -Value $RunTenant -Encoding Ascii
Write-Host "[run] tenant $RunTenant (demo\.run\tenant)" -ForegroundColor Green

# Each service must exist before we open a window for it, otherwise uvicorn
# fails with a confusing "module not found" instead of a clear message here.
$windows = @(
    @{
        Title   = 'CyBreach - Alpha (8001)'
        Log     = 'alpha'
        Path    = Join-Path $RepoRoot 'cybreach_pod_alpha\rule ingestion'
        Command = 'uvicorn app.main:app --port 8001'
        ExtraEnv = @{ DATABASE_URL = '$env:ALPHA_DATABASE_URL' }
    },
    @{
        Title   = 'CyBreach - Beta Validation (8002)'
        Log     = 'beta-validation'
        Path    = Join-Path $RepoRoot 'cybreach_pod_beta\services\validation_engine'
        Command = 'uvicorn ve_app.main:app --port 8002'
    },
    @{
        Title   = 'CyBreach - Beta Publisher (8004)'
        Log     = 'beta-publisher'
        Path    = Join-Path $RepoRoot 'cybreach_pod_beta\services\verdict_publisher'
        Command = 'uvicorn vp_app.main:app --port 8004'
    },
    @{
        Title   = 'CyBreach - Delta (8000)'
        Log     = 'delta'
        Path    = Join-Path $RepoRoot 'cybreach_pod_delta\backend'
        Command = 'uvicorn app.main:app --port 8000'
        ExtraEnv = @{ DATABASE_URL = '$env:DELTA_DATABASE_URL' }
    },
    @{
        Title   = 'CyBreach - Gamma Normalizer (8005)'
        Log     = 'gamma-normalizer'
        Path    = Join-Path $RepoRoot 'cybreach_pod_gamma\ocsf_normalizer'
        Command = 'uvicorn src.main:app --port 8005'
    },
    @{
        Title   = 'CyBreach - Gamma Revalidation (8006)'
        Log     = 'gamma-revalidation'
        Path    = Join-Path $RepoRoot 'cybreach_pod_gamma\revalidation_service'
        Command = 'uvicorn src.main:app --port 8006'
    }
)

foreach ($w in $windows) {
    if (-not (Test-Path $w.Path)) {
        throw "Service directory not found for $($w.Title): $($w.Path)"
    }

    # Launch each service in its own PowerShell window. The leading dot
    # dot-sources demo-env.ps1 into THAT window, so SECRET_KEY is identical
    # everywhere. Without the dot the variables would land in a child scope and
    # the service would start with no SECRET_KEY at all.
    $lines = @()
    $lines += "Set-Location -LiteralPath '$($w.Path)'"
    $lines += ". '$EnvScript'"
    if ($w.ExtraEnv) {
        foreach ($k in $w.ExtraEnv.Keys) {
            $lines += "`$env:$k = $($w.ExtraEnv[$k])"
        }
    }

    # Tee the service's output to a log file as it runs. uvicorn writes its
    # access log to stderr, so 2>&1 is needed to capture the request lines --
    # those are the ones worth reading during a demo.
    #
    # $ErrorActionPreference must be SilentlyContinue: in Windows PowerShell
    # 5.1 a native command writing to stderr inside a pipeline is wrapped in a
    # NativeCommandError, which would put "At line:1 char:172" noise and a
    # FullyQualifiedErrorId into the log ahead of every real uvicorn line.
    $logPath = Join-Path $LogDir "$($w.Log).log"
    $append = if ($AppendLog) { '-Append' } else { '' }
    $lines += "`$ErrorActionPreference = 'SilentlyContinue'"
    $lines += "$($w.Command) 2>&1 | Tee-Object -FilePath '$logPath' $append"

    $scriptBlock = ($lines -join '; ')

    Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $scriptBlock -WindowStyle Normal
    Write-Host "Launched: $($w.Title)" -ForegroundColor Green
}

Write-Host ''
Write-Host 'All six windows launched. Wait ~20s, then run:' -ForegroundColor Cyan
Write-Host "  . '$HealthScript'" -ForegroundColor Cyan
Write-Host ''
Write-Host "Logs are also being written to: $LogDir" -ForegroundColor Cyan
Write-Host '  Get-Content .\demo\logs\gamma-normalizer.log -Wait -Tail 20' -ForegroundColor Cyan
Write-Host ''