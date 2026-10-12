# Ingest a detection rule into Alpha so the live-bus path returns 'Detected'.
#
# Run this once after Alpha starts, and again after ANY Alpha restart.
#
# Alpha's /rules/search serves from an in-memory dict (INGESTED_RULES in
# app/api/rules.py), not from Postgres. A rule row in the database is invisible
# until it is ingested through the currently running process, so restarting
# Alpha empties the store and the verdict degrades to NoData.
#
# By default the rule is GENERATED at runtime by demo/gendata.py and ingested
# from a temporary directory, so the demo reads nothing committed to the repo.
# Pass -RulesDir (or set RULES_DIR) to ingest real rules from disk instead.

param(
    # Optional: a real directory of .yml/.yaml rules. Omit to generate one.
    [string]$RulesDir = $env:RULES_DIR,
    # Optional: pin the MITRE technique of the generated rule.
    [string]$Technique = $env:RULE_TECHNIQUE
)

$DemoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $DemoDir 'demo-env.ps1') | Out-Null

$generator = Join-Path $DemoDir 'gendata.py'
if (-not (Test-Path $generator)) { throw "Cannot find $generator" }

$genArgs = @($generator, 'seed')
if ($RulesDir) { $genArgs += @('--repo-dir', $RulesDir) }
if ($Technique) { $genArgs += @('--technique', $Technique) }

Write-Host "Seeding rules for tenant '$($env:B11_SERVICE_TENANT_ID)'" -ForegroundColor Cyan
if ($RulesDir) {
    Write-Host "  source : $RulesDir (explicit)"
} else {
    Write-Host '  source : generated at runtime (no committed fixtures)'
}

python @genArgs
if ($LASTEXITCODE -ne 0) { throw "Rule ingest failed (exit $LASTEXITCODE)." }

Write-Host ''
