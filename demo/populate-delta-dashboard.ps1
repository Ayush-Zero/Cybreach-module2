# Populate the Delta dashboard with a real verdict.
#
# Run this after start-services.ps1. Safe to run repeatedly.
#
# Delta is a Kafka *producer* only -- it never consumes cybreach.verdicts.v2 --
# and its dashboard reads Delta's own Postgres. So the bus-driven Beta pipeline
# will never put a row in the Delta UI. This script exercises Delta's own
# POST /api/v2/validate, which persists the verdict and publishes it to Kafka.
#
# The verdict_events.rule_id column is a foreign key onto rules.rule_id, and
# rule_id is a *content hash* over rule_name + query + rule_type +
# mitre_technique (see backend/app/utils/rule_hash_utils.py). The rule must
# therefore exist first, and validation must be sent with the identical four
# fields, or the endpoint rejects the digest with HTTP 404.

param(
    [string]$DeltaBase = 'http://127.0.0.1:8000',
    [string]$Username = 'demo',
    [string]$Password = 'demo123'
)

$DemoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $DemoDir 'demo-env.ps1') | Out-Null

# The rule body and the event are kept here, once, so the create step and the
# validate step cannot drift apart -- a mismatch is only visible as a 404.
$RuleName  = 'Suspicious PowerShell Encoded Command'
$RuleType  = 'sigma'
$Technique = 'T1059.001'

# Plain field names only. validator_service looks each selection key up with
# event.get(field) (app/services/validator_service.py:177), so a Sigma modifier
# like 'CommandLine|contains' is treated as a literal field name and the rule
# evaluates to NoData. Substring matching is already the default: _field_matches
# lowercases and does `needle in actual`, so 'CommandLine': '-enc' is enough.
$RuleQuery = '{"detection":{"selection":{"Image":"powershell.exe","CommandLine":"-enc"}}}'

$Event = @{
    event_id    = 'evt-delta-demo-001'
    Image       = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    CommandLine = 'powershell.exe -enc SQBFAFgA'
    parent_image = 'C:\Windows\System32\services.exe'
    timestamp   = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

try {
    $token = (Invoke-RestMethod -Uri "$DeltaBase/api/v2/auth/login" -Method Post `
        -Body @{ username = $Username; password = $Password } `
        -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 15).access_token
}
catch {
    throw "Cannot reach Delta on $DeltaBase. Start it with: .\start-services.ps1"
}

$headers = @{ Authorization = "Bearer $token" }

Write-Host "[1/3] Ensuring the Delta rule exists"

# Windows PowerShell 5.1's Invoke-RestMethod returns a top-level JSON array as
# ONE object rather than enumerating it, so piping it straight into Where-Object
# filters the array as a single item ($_.query then yields every query at once).
# Enumerate explicitly instead.
$allRules = Invoke-RestMethod -Uri "$DeltaBase/api/v2/rules" -Headers $headers -TimeoutSec 30
$rule = $null
foreach ($candidate in $allRules) {
    if ($candidate.rule_name -ne $RuleName) { continue }
    # Compare compacted JSON so whitespace/escaping differences don't create a
    # duplicate rule that differs only cosmetically (and hash differently).
    if (($candidate.query -replace '\s', '') -eq ($RuleQuery -replace '\s', '')) {
        $rule = $candidate
        break
    }
}

if ($rule) {
    Write-Host "      already present, reusing"
}
else {
    $rule = Invoke-RestMethod -Uri "$DeltaBase/api/v2/rules" -Method Post -Headers $headers `
        -ContentType 'application/json' -TimeoutSec 30 -Body (@{
            rule_name       = $RuleName
            rule_type       = $RuleType
            severity        = 'high'
            description     = 'Detects base64-encoded PowerShell command lines'
            query           = $RuleQuery
            status          = 'active'
            mitre_technique = $Technique
        } | ConvertTo-Json)
    Write-Host "      created"
}

# Older Delta builds omit rule_id from the response; fall back to deriving it
# the same way the backend does so this script keeps working on either.
$ruleId = $rule.rule_id
if (-not $ruleId) {
    Write-Warning "Rule response had no rule_id; deriving it locally (update Delta if this persists)."
    $canonical = [ordered]@{
        rule_name       = $RuleName
        query           = ($RuleQuery | ConvertFrom-Json)
        rule_type       = $RuleType
        mitre_technique = $Technique
    }
    $json = $canonical | ConvertTo-Json -Depth 10 -Compress
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hash = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($json)) | ForEach-Object { $_.ToString('x2') })
    $ruleId = $hash
}
Write-Host "      rule_id = $ruleId"

Write-Host "[2/3] Validating one event against it"
try {
    $verdict = Invoke-RestMethod -Uri "$DeltaBase/api/v2/validate" -Method Post -Headers $headers `
        -ContentType 'application/json' -TimeoutSec 30 -Body (@{
            action_id        = 'act-delta-demo-003'
            rule_query       = $RuleQuery
            event            = $Event
            rule_name        = $RuleName
            rule_type        = $RuleType
            mitre_technique  = $Technique
        } | ConvertTo-Json -Depth 10)
}
catch {
    $detail = $null
    try { $detail = $_.ErrorDetails.Message } catch {}
    throw "Validation failed: HTTP $([int]$_.Exception.Response.StatusCode) $detail"
}

if ($verdict.rule_id -ne $ruleId) {
    throw "rule_id mismatch: rule is $ruleId but the verdict was filed under $($verdict.rule_id)."
}

Write-Host "[3/3] Done"
Write-Host ''
Write-Host "  verdict                : $($verdict.verdict)"
Write-Host "  confidence             : $($verdict.confidence)"
Write-Host "  verdict_id             : $($verdict.verdict_id)"
Write-Host "  rule_id                : $($verdict.rule_id)"
Write-Host "  matched_evidence_ref   : $($verdict.matched_evidence_ref)"
Write-Host "  content_hash           : $($verdict.content_hash)"
Write-Host ''
if ($verdict.verdict -eq 'NoData') {
    Write-Warning 'NoData means the rule could not be evaluated -- check the rule body.'
    Write-Warning 'Missed means it was evaluated and did not fire.'
    Write-Warning 'Detected means it fired. Only Detected is expected for the event above.'
}
Write-Host 'Open the Delta dashboard:'
Write-Host '  cd cybreach_pod_delta\frontend-dashboard'
Write-Host '  npm run dev          # then http://127.0.0.1:5173  (demo / demo123)'
Write-Host ''