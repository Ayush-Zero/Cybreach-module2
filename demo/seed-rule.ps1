# Ingest Sigma rules into Alpha so the live-bus path returns 'Detected'.
#
# Run this once after Alpha starts, and again after ANY Alpha restart.
#
# Alpha's /rules/search serves from an in-memory dict (INGESTED_RULES in
# app/api/rules.py), not from Postgres. A rule row in the database is invisible
# until it is ingested through the currently running process, so restarting
# Alpha empties the store and the verdict degrades to NoData.

param(
    [string]$BearerToken = $env:B11_SERVICE_TOKEN
)

$DemoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $DemoDir
. (Join-Path $DemoDir 'demo-env.ps1') | Out-Null

$Alpha = 'http://127.0.0.1:8001'
$RulesDir = Join-Path $RepoRoot 'cybreach_pod_alpha\rule ingestion\tests\fixtures\rule_repo\sigma'

if (-not (Test-Path $RulesDir)) {
    throw "Cannot find rules directory: $RulesDir"
}

# Mint a token directly rather than using Delta's login.
#
# Delta's login token carries only `sub` (see backend/app/security/security.py),
# but Alpha's `get_current_tenant` requires a `tenant_id` claim. A Delta token
# therefore cannot call Alpha: {"detail":"tenant_id claim is required"}.
# Beta mints its own service token with both claims; this mirrors that.
$py = @'
import os, time, urllib.request, urllib.error, json, sys
import jose.jwt

tenant = os.environ.get("B11_SERVICE_TENANT_ID", "acme")
token = jose.jwt.encode(
    {
        "sub": "demo-operator",
        "tenant_id": tenant,
        "exp": int(time.time()) + 300,
    },
    os.environ["SECRET_KEY"],
    algorithm="HS256",
)

rules_dir = sys.argv[1]
body = json.dumps(
    {
        "repo_url": rules_dir,
        "branch": "main",
        "rule_types": ["sigma"],
        "include_validation": True,
    }
).encode("utf-8")

req = urllib.request.Request(
    "http://127.0.0.1:8001/api/v2/rules/ingest",
    data=body,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    },
)
try:
    with urllib.request.urlopen(req, timeout=120) as response:
        data = json.loads(response.read())
except urllib.error.URLError as exc:
    print("Cannot reach Alpha on 8001:", exc.reason)
    print("Start it with: .\\start-services.ps1")
    sys.exit(1)
except urllib.error.HTTPError as exc:
    print("HTTP", exc.code, exc.read().decode("utf-8", "replace")[:400])
    sys.exit(1)

items = data if isinstance(data, list) else data.get("rules", [])
print(f"Ingested {len(items)} rules for tenant {tenant}:")
for rule in items:
    print(f"  {rule.get('rule_id')} | {rule.get('title')} | {rule.get('mitre_techniques')}")
'@

$ingestScript = Join-Path $DemoDir '_ingest.py'
Set-Content -Path $ingestScript -Value $py -Encoding UTF8

try {
    Write-Host "Ingesting Sigma rules from $RulesDir (tenant '$($env:B11_SERVICE_TENANT_ID)')"
    python $ingestScript $RulesDir
    if ($LASTEXITCODE -ne 0) { throw "Rule ingest failed (exit $LASTEXITCODE)." }
} finally {
    Remove-Item $ingestScript -Force -ErrorAction SilentlyContinue
}
Write-Host ''