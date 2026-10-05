# Exercise the OCSF Normalizer (Gamma, 8005) and show it in the log.
#
# This is a SEPARATE path from the Beta pipeline in publish_evidence.py. Gamma is
# not on the evidence -> verdict bus, so nothing in the main demo reaches it and
# its log stays empty. Run this when you narrate the normalizer step.
#
# It demonstrates the point of the pod: a raw vendor event goes in, and a
# canonical OCSF event comes out. The source format is detected from the payload,
# not from a caller-supplied hint -- so the same call handles Splunk, Elastic,
# Sentinel, QRadar or LogScale.
#
# Reads the pod's own test fixtures, so it cannot drift from what the normalizer
# actually supports.
#
# Usage:
#   .\demo\normalize-event.ps1 -Vendor splunk            # summary line only
#   .\demo\normalize-event.ps1 -Vendor splunk -Json      # full OCSF event body
#   .\demo\normalize-event.ps1 -Vendor elastic -Json     # same endpoint, ECS input
#   .\demo\normalize-event.ps1 -Count 0 -Json            # whole fixture at once

param(
    [string]$GammaBase = 'http://127.0.0.1:8005',
    # Which vendor format to feed in. One of: splunk, elastic, sentinel, qradar, logscale
    [ValidateSet('splunk', 'elastic', 'sentinel', 'qradar', 'logscale')]
    [string]$Vendor = 'splunk',
    # Show the live log while normalizing instead of only afterwards.
    [switch]$Follow,
    # How many fixture records to send. One is enough to demonstrate schema
    # detection; omit for all of them.
    [int]$Count = 1,
    # Print the full OCSF event body instead of the 4-field summary line.
    [switch]$Json
)

$DemoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $DemoDir
. (Join-Path $DemoDir 'demo-env.ps1') | Out-Null

$fixtureMap = @{
    splunk   = 'splunk_events.json'
    elastic  = 'ecs_events.json'
    sentinel = 'sentinel_events.json'
    qradar   = 'qradar_events.json'
    logscale = 'logscale_events.json'
}

$fixture = Join-Path $RepoRoot "cybreach_pod_gamma\ocsf_normalizer\tests\fixtures\$($fixtureMap[$Vendor])"
if (-not (Test-Path $fixture)) {
    throw "Cannot find fixture: $fixture"
}

# Gamma is tenant-scoped, so it needs the same token shape Beta mints (a Delta
# login token has no tenant_id claim and is rejected with 401).
$token = python -c "import os,time,jose.jwt;print(jose.jwt.encode({'sub':'demo-operator','tenant_id':os.environ.get('B11_SERVICE_TENANT_ID','acme'),'exp':int(time.time())+300},os.environ['SECRET_KEY'],algorithm='HS256'))"
if ($LASTEXITCODE -ne 0 -or -not $token) { throw "Could not mint a service token." }

$events = Get-Content $fixture -Raw | ConvertFrom-Json
$records = if ($events -is [array]) { $events } elseif ($events.results) { $events.results } else { @($events) }
if ($Count -gt 0 -and $records.Count -gt $Count) {
    $records = @($records | Select-Object -First $Count)
}

Write-Host "Feeding $($records.Count) raw $Vendor event(s) to the normalizer"
Write-Host "  raw format : $Vendor (detected from the payload, not declared)"
Write-Host "  OCSF class : 3002 = Authentication"
Write-Host ''

if ($Follow) {
    Write-Host 'Following gamma-normalizer.log -- run the request below, then Ctrl+C' -ForegroundColor Cyan
    Write-Host '  .\demo\normalize-event.ps1 -Vendor splunk -Follow' -ForegroundColor Cyan
    Write-Host ''
    Get-Content (Join-Path $DemoDir 'logs\gamma-normalizer.log') -Wait -Tail 5 -EA SilentlyContinue
    return
}

foreach ($record in $records) {
    # The endpoint wraps the raw vendor event in `log`.
    $body = @{ log = $record } | ConvertTo-Json -Depth 12

    try {
        $result = Invoke-RestMethod "$GammaBase/api/v2/ocsf/normalize" -Method Post `
            -Headers @{ Authorization = "Bearer $token" } `
            -ContentType 'application/json' -Body $body -TimeoutSec 30
    }
    catch {
        $detail = $null
        try { $detail = $_.ErrorDetails.Message } catch {}
        throw "Normalize failed: HTTP $([int]$_.Exception.Response.StatusCode) $detail"
    }

    Write-Host "  in  : $($record.PSObject.Properties.Name -join ', ')" -ForegroundColor DarkGray
    Write-Host "  out : class_uid=$($result.class_uid) activity_id=$($result.activity_id) severity=$($result.severity_id) user=$($result.actor.user.name)" -ForegroundColor Green

    if ($Json) {
        $result | ConvertTo-Json -Depth 15 | Write-Host
    }
}

Write-Host ''
Write-Host 'Show the request line in the log:' -ForegroundColor Cyan
Write-Host '  .\demo\tail-logs.ps1 gamma-normalizer -Dump' -ForegroundColor Cyan
Write-Host ''