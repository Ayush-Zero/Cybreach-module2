# Red-to-Green: prove a detection gap, fix it, and re-verify the SAME evidence.
#
# This is the platform's re-validation path end to end. Nothing here is staged:
# the Missed verdict is really produced, the rule is really edited, and the same
# stored event is really re-evaluated.
#
# What happens:
#   1. Create a rule that does NOT match the evidence  -> the gap
#   2. Validate the evidence against it                -> Missed, confidence 0.0
#   3. Tighten the rule so it targets the real behaviour
#   4. POST /verdicts/{id}/revalidate                  -> Detected, gap_closed=true
#
# Step 4 is Delta's own re-validation endpoint. It re-reads the event stored on
# the old verdict, re-runs the (now corrected) rule against it, supersedes the
# old verdict, and publishes both a corrected verdict and a gap-closed event.
# So the comparison is over identical evidence -- not a second, easier event.
#
# One thing to be aware of when narrating: the gap is "a rule exists but does
# not match", not "no rule exists". A verdict row cannot reference a rule that
# was never created, because verdict_events.rule_id is a foreign key -- a
# brand-new technique with no rule at all cannot be filed as Missed. That is the
# correct behaviour, and this demo shows the gap that is actually reachable.

param(
    [string]$DeltaBase = 'http://127.0.0.1:8000',
    [string]$Username = 'demo',
    [string]$Password = 'demo123'
)

$DemoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $DemoDir 'demo-env.ps1') | Out-Null

try {
    $token = (Invoke-RestMethod -Uri "$DeltaBase/api/v2/auth/login" -Method Post `
        -Body @{ username = $Username; password = $Password } `
        -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 15).access_token
}
catch {
    throw "Cannot reach Delta on $DeltaBase. Start it with: .\demo\start-services.ps1"
}

$headers = @{ Authorization = "Bearer $token" }

# Unique per run so repeated takes never interfere with each other.
$run = (Get-Date).ToString('HHmmss')
$ruleName = "Red-To-Green Gap $run"

# The gap: the rule looks for cmd.exe, but the evidence is PowerShell.
# `Image` IS present in the event, so the rule is evaluable and simply does not
# fire -- that is `Missed`, not `NoData`.
$weakQuery = '{"detection":{"selection":{"Image":"cmd.exe"}}}'

# The fix: target what actually happened.
$fixedQuery = '{"detection":{"selection":{"Image":"powershell.exe"}}}'

# One event, used for both runs.
$event = @{
    event_id     = "evt-red-to-green-$run"
    Image        = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    CommandLine  = 'powershell.exe -enc SQBFAFgA'
    timestamp    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

Write-Host '=========================================================' -ForegroundColor DarkGray
Write-Host ' STEP 1 - a rule that does not cover this behaviour' -ForegroundColor Cyan
Write-Host '=========================================================' -ForegroundColor DarkGray
$rule = Invoke-RestMethod -Uri "$DeltaBase/api/v2/rules" -Method Post -Headers $headers `
    -ContentType 'application/json' -TimeoutSec 30 -Body (@{
        rule_name       = $ruleName
        rule_type       = 'sigma'
        severity        = 'medium'
        description     = 'Looks for the wrong binary (the detection gap)'
        query           = $weakQuery
        status          = 'active'
        mitre_technique = 'T1059.001'
    } | ConvertTo-Json)

Write-Host "  rule name      : $ruleName"
Write-Host "  rule looks for : Image contains 'cmd.exe'"
Write-Host "  evidence is    : Image contains 'powershell.exe'  (T1059.001)"
Write-Host "  rule_id        : $($rule.rule_id)"
Write-Host ''

Write-Host '=========================================================' -ForegroundColor DarkGray
Write-Host ' STEP 2 - evaluate the evidence -> expect Missed' -ForegroundColor Cyan
Write-Host '=========================================================' -ForegroundColor DarkGray
$missed = Invoke-RestMethod -Uri "$DeltaBase/api/v2/validate" -Method Post -Headers $headers `
    -ContentType 'application/json' -TimeoutSec 30 -Body (@{
        action_id        = "act-red-to-green-$run"
        rule_query       = $weakQuery
        event            = $event
        rule_name        = $ruleName
        rule_type        = 'sigma'
        mitre_technique  = 'T1059.001'
    } | ConvertTo-Json -Depth 10)

Write-Host "  verdict        : $($missed.verdict)" -ForegroundColor $(if ($missed.verdict -eq 'Missed') { 'Yellow' } else { 'Red' })
Write-Host "  confidence     : $($missed.confidence)"
Write-Host "  verdict_id     : $($missed.verdict_id)"
Write-Host "  content_hash   : $($missed.content_hash)"
Write-Host '  causal chain   :'
foreach ($line in $missed.causal_chain) {
    Write-Host "      - $line"
}

if ($missed.verdict -ne 'Missed') {
    throw "Expected Missed for the gap but got $($missed.verdict). Aborting before the fix."
}
Write-Host ''

Write-Host '=========================================================' -ForegroundColor DarkGray
Write-Host ' STEP 3 - tighten the rule to cover the behaviour' -ForegroundColor Cyan
Write-Host '=========================================================' -ForegroundColor DarkGray
$updated = Invoke-RestMethod -Uri "$DeltaBase/api/v2/rules/$($rule.id)" -Method Put -Headers $headers `
    -ContentType 'application/json' -TimeoutSec 30 -Body (@{
        rule_name       = $ruleName
        rule_type       = 'sigma'
        severity        = 'high'
        description     = 'Now targets the binary that actually ran'
        query           = $fixedQuery
        status          = 'active'
        mitre_technique = 'T1059.001'
    } | ConvertTo-Json)

Write-Host "  rule now looks for : Image contains 'powershell.exe'"
Write-Host "  rule_id            : $($updated.rule_id)  (unchanged, so the old verdict still resolves)"
Write-Host ''

Write-Host '=========================================================' -ForegroundColor DarkGray
Write-Host ' STEP 4 - re-validate the SAME evidence -> expect Detected' -ForegroundColor Cyan
Write-Host '=========================================================' -ForegroundColor DarkGray
$result = Invoke-RestMethod -Uri "$DeltaBase/api/v2/verdicts/$($missed.verdict_id)/revalidate" `
    -Method Post -Headers $headers -TimeoutSec 30

Write-Host ''
Write-Host '  BEFORE                       AFTER' -ForegroundColor DarkGray
Write-Host '  -------------------------    -------------------------' -ForegroundColor DarkGray
Write-Host ("  {0,-25}    {1,-25}" -f "verdict  $($result.old_verdict.verdict)", "verdict  $($result.new_verdict.verdict)")
Write-Host ("  {0,-25}    {1,-25}" -f "conf     $($result.old_verdict.confidence)", "conf     $($result.new_verdict.confidence)")
Write-Host ("  {0,-25}    {1,-25}" -f "id       $($result.old_verdict.id)", "id       $($result.new_verdict.id)")
Write-Host ("  {0,-25}    {1,-25}" -f "hash     $($result.old_verdict.content_hash.Substring(0, 20))..", "hash     $($result.new_verdict.content_hash.Substring(0, 20))..")
Write-Host ''
Write-Host "  gap_closed      : $($result.gap_closed)" -ForegroundColor $(if ($result.gap_closed) { 'Green' } else { 'Red' })
Write-Host "  confidence delta: $($result.comparison.delta)"
Write-Host "  validation      : $($result.validation.status)"
Write-Host "  matched fields  : $($result.validation.matched_fields -join ', ')"
Write-Host "  superseded      : verdict #$($result.previous_verdict_id) -> #$($result.verdict_id)"
Write-Host ''

if (-not $result.gap_closed) {
    throw "Re-validation did not close the gap (still $($result.new_verdict.verdict))."
}

Write-Host 'Same evidence, re-played and verified: Missed -> Detected.' -ForegroundColor Green
Write-Host ''
Write-Host 'Two more things are now true, both worth pointing at:' -ForegroundColor Cyan
Write-Host '  * Kafka topic cybreach.gap_closed.v2 now carries this verdict.' -ForegroundColor Cyan
Write-Host '    Switch to the Kafka UI tab (http://localhost:8080) and open it -- the'
Write-Host '    action_id matches act-red-to-green-<run>, so it is findable.'
Write-Host '  * The superseded verdict is retired, not deleted, and the audit log'
Write-Host '    records REVALIDATED with old -> new.'
Write-Host ''
Write-Host 'Show it in the UI:' -ForegroundColor Cyan
Write-Host '  cd cybreach_pod_delta\frontend-dashboard' -ForegroundColor Cyan
Write-Host '  npm run dev            # http://127.0.0.1:5173  (demo / demo123)' -ForegroundColor Cyan
Write-Host '  the Re-validation view pairs the superseded verdict with its replacement' -ForegroundColor Cyan
Write-Host ''