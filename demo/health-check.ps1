# Health check for all six services.
#
# Usage (from the repo root):
#   .\demo\health-check.ps1
#
# Non-destructive read-only health probe. Safe to run on camera -- it does not
# mutate anything. It also reports whether Beta's Kafka consumer actually
# started, because that is the one failure mode where the HTTP service looks
# healthy while the live path is silently dead.

. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'demo-env.ps1') | Out-Null

# Gamma's normalizer has no /health route -- its only unauthenticated endpoint
# is GET / (see ocsf_normalizer/src/main.py). Probing /health reports a
# perfectly healthy service as DOWN, so it gets its own probe path.
$ports = @{
    8000 = @{ Path = '/health';                  Name = 'Delta (dashboard+API)' }
    8001 = @{ Path = '/health';                  Name = 'Alpha (rule ingestion)' }
    8002 = @{ Path = '/health';                  Name = 'Beta Validation Engine' }
    8004 = @{ Path = '/health';                  Name = 'Beta Verdict Publisher' }
    8005 = @{ Path = '/';                       Name = 'Gamma Normalizer' }
    8006 = @{ Path = '/health';                  Name = 'Gamma Revalidation' }
}

Write-Host ''
Write-Host ('{0,-6} {1,-10} {2,-30} {3}' -f 'PORT', 'STATUS', 'SERVICE', 'NAME')
Write-Host ('-' * 78)

$allUp = $true
foreach ($p in ($ports.Keys | Sort-Object)) {
    $cfg = $ports[$p]
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$p$($cfg.Path)" -TimeoutSec 8
        # /health returns {status, service}; Gamma's / returns only {message}.
        $status = if ($r.status) { $r.status } else { 'ok' }
        $svc    = if ($r.service) { $r.service } else { 'ocsf-normalizer' }
        Write-Host ('{0,-6} {1,-10} {2,-30} {3}' -f $p, $status, $svc, $cfg.Name) -ForegroundColor Green
    } catch {
        $allUp = $false
        Write-Host ('{0,-6} {1,-10} {2,-30} {3}' -f $p, 'DOWN', '-', $cfg.Name) -ForegroundColor Red
    }
}

Write-Host ''
if (-not $allUp) {
    Write-Host 'Some services are down. Check the individual windows for tracebacks.' -ForegroundColor Red
}

# -- Beta Kafka consumer check ---------------------------------------------
# A healthy 8002 does NOT prove the consumer is running. If KAFKA_EVIDENCE_ENABLED
# was not set when Beta started, the consumer thread never launched and no
# verdict is ever produced, even though /health returns ok. This is the exact
# state the demo silently failed in during verification.
# Docker ships its CLI under the per-user Programs dir but does not always put
# it on PATH in a plain PowerShell session. Add it if `docker` is unresolvable.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerBin = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'
    if (Test-Path $dockerBin) {
        $env:Path = "$dockerBin;$env:Path"
    } else {
        Write-Host '  docker CLI not found -- skipping consumer check.' -ForegroundColor Yellow
    }
}

Write-Host 'Checking Beta Kafka consumer group...' -ForegroundColor Cyan
try {
    $members = docker exec m2_kafka kafka-consumer-groups `
        --bootstrap-server localhost:9092 `
        --describe --group validation-engine-evidence 2>&1 | Out-String

    if ($members -match 'no active members') {
        Write-Host '  WARNING: consumer group has NO active members.' -ForegroundColor Yellow
        Write-Host '  Beta is up but its Kafka consumer is NOT consuming.' -ForegroundColor Yellow
        Write-Host '  Fix: restart Beta with KAFKA_EVIDENCE_ENABLED=true (demo-env.ps1 does this).' -ForegroundColor Yellow
    } elseif ($members -match 'CURRENT-OFFSET') {
        # The describe output is tab-separated with blank lines, so parse the
        # header line then read the row beneath it rather than regex-ing the
        # whole blob (a naive 'LAG\s+(\d+)' can match across a newline).
        $header = ($members -split "`n" | Where-Object { $_ -match 'CURRENT-OFFSET' } | Select-Object -First 1)
        $row    = ($members -split "`n" | Where-Object { $_ -match '^\s*validation-engine-evidence' } | Select-Object -First 1)

        if ($header -and $row) {
            $cols = ($header -replace '\s+', ' ').Trim() -split ' '
            $vals = ($row   -replace '\s+', ' ').Trim() -split ' '
            $lag  = $vals[$cols.IndexOf('LAG')]
            if ($lag -eq '0') {
                Write-Host "  Consumer active and caught up (lag 0)." -ForegroundColor Green
            } else {
                Write-Host "  Consumer active. Lag = $lag (unprocessed evidence messages)." -ForegroundColor Yellow
            }
        } else {
            Write-Host '  Consumer active (could not parse lag).' -ForegroundColor Green
        }
    } else {
        Write-Host '  Could not parse consumer group output.' -ForegroundColor Yellow
        Write-Host $members
    }
} catch {
    Write-Host '  Could not reach Kafka (is the broker running?).' -ForegroundColor Yellow
}

Write-Host ''