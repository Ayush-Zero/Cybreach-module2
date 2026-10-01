# Watch one service's log while it runs.
#
# start-services.ps1 tees every service's output to demo\logs\<name>.log, so a
# demo can be narrated from this window instead of alt-tabbing to six
# consoles.
#
#   .\demo\tail-logs.ps1                          # live view of all six
#   .\demo\tail-logs.ps1 gamma-normalizer         # just the normalizer
#   .\demo\tail-logs.ps1 gamma-normalizer -Dump   # print current contents, don't follow
#
# Ctrl+C stops following. The services keep running.

param(
    # Which service to watch. Omit to watch all of them.
    [string[]]$Service,
    # Print what is there now and exit instead of following.
    [switch]$Dump,
    # Lines to show on start when following.
    [int]$Tail = 20
)

$DemoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir  = Join-Path $DemoDir 'logs'

if (-not (Test-Path $LogDir)) {
    throw "No log directory at $LogDir. Start the services first: .\demo\start-services.ps1"
}

$known = @{
    'alpha'              = 'alpha.log'
    'beta-validation'    = 'beta-validation.log'
    'beta-publisher'     = 'beta-publisher.log'
    'delta'              = 'delta.log'
    'gamma-normalizer'   = 'gamma-normalizer.log'
    'gamma-revalidation' = 'gamma-revalidation.log'
}

if (-not $Service -or $Service.Count -eq 0) {
    $targets = $known.Keys | Sort-Object
}
else {
    $targets = foreach ($s in $Service) {
        if (-not $known.ContainsKey($s)) {
            throw "Unknown service '$s'. Known: $($known.Keys -join ', ')"
        }
        $s
    }
}

if ($Dump) {
    foreach ($t in $targets) {
        $path = Join-Path $LogDir $known[$t]
        Write-Host "=== $t ($path) ===" -ForegroundColor Cyan
        if (Test-Path $path) {
            Get-Content $path -Tail $Tail
        }
        else {
            Write-Host '(no log yet -- service may not have started)'
        }
        Write-Host ''
    }
    return
}

# Follow all requested logs. Get-Content -Wait on one file at a time keeps the
# output readable; for a single service that is exactly what you want during a
# narration, so only the first is followed and the rest are tailed once.
$first = $targets[0]
foreach ($t in $targets) {
    $path = Join-Path $LogDir $known[$t]
    if (-not (Test-Path $path)) {
        Write-Host "$t : no log yet (service may still be starting)" -ForegroundColor Yellow
        continue
    }

    if ($t -eq $first) {
        Write-Host "=== following $t ($path) -- Ctrl+C to stop ===" -ForegroundColor Cyan
        Get-Content $path -Wait -Tail $Tail
    }
    else {
        Write-Host "=== $t (last $Tail lines) ===" -ForegroundColor Cyan
        Get-Content $path -Tail $Tail
        Write-Host ''
    }
}