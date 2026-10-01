# CyBreach Module 2 -- demo environment (single source of truth)
#
# WHY THIS FILE EXISTS
# --------------------
# All six services share ONE HS256 SECRET_KEY: Alpha verifies Beta's service
# token, Delta verifies the dashboard token, and Beta mints both. If two
# windows disagree on the value you get 401s with no obvious culprit.
#
# The fix is to stop setting the key by hand in six windows. It is defined
# exactly once here, and every script dot-sources this file, so a window
# cannot drift from another.
#
# HOW TO USE (from any PowerShell window):
#     . .\demo\demo-env.ps1
#
# That dot-sources into the CURRENT window. Note the leading dot -- without
# it the variables would live in a child scope and vanish.

# --- Paths ----------------------------------------------------------------
# Derived from this script's own location, so the demo folder works from
# anywhere in the tree and needs no editing when the repo moves.
$DemoDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $DemoDir
$RepoEnv   = Join-Path $RepoRoot '.env'

if (-not (Test-Path $RepoEnv)) {
    Write-Warning "No .env at $RepoEnv. Set POSTGRES_USER and POSTGRES_PASSWORD in this shell first."
}

if (Test-Path $RepoEnv) {
    foreach ($line in Get-Content $RepoEnv) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $key, $value = $line -split '=', 2
        Set-Item -Path "env:$($key.Trim())" -Value $value.Trim()
    }
}

# There is deliberately NO fallback for the credentials. The compose file
# requires POSTGRES_USER/PASSWORD to be set (`:?`), and guessing 'postgres'
# fails with `role "postgres" does not exist` because the real role is
# `module2`. Fail loudly here instead of half-starting a service.
foreach ($required in 'POSTGRES_USER', 'POSTGRES_PASSWORD') {
    if (-not (Get-Item "env:$required" -ErrorAction SilentlyContinue)) {
        throw "demo-env.ps1: $required is not set and $RepoEnv was not readable."
    }
}
if (-not $env:POSTGRES_DB) { $env:POSTGRES_DB = 'module2_validator' }

# --- The shared signing key ----------------------------------------------
# ONE value, read by every service. Override by setting $env:SECRET_KEY in
# your shell BEFORE dot-sourcing this file; otherwise you get the demo value.
if ($env:SECRET_KEY) {
    Write-Host "[demo-env] using pre-existing SECRET_KEY from this session" -ForegroundColor DarkGray
} else {
    $env:SECRET_KEY = 'demo-only-shared-key-not-for-production'
    Write-Host "[demo-env] SECRET_KEY set to the demo default" -ForegroundColor DarkGray
}

# --- Infra ---------------------------------------------------------------
$env:KAFKA_BOOTSTRAP_SERVERS = 'localhost:9092'
$env:REDIS_HOST              = 'localhost'
$env:REDIS_PORT              = '6379'
$env:M2_TOPICS_PATH          = Join-Path $RepoRoot 'topics.yaml'

# --- Per-service database URLs ------------------------------------------
# Alpha MUST NOT use $env:POSTGRES_DB. Delta owns
# `alembic_version = 0001_initial_verdict_platform` in the shared database, so
# pointing Alpha's migrations there makes them fail on a revision mismatch.
# Per-pod databases are not architecturally resolved yet (see conflict.md);
# this local split is what keeps the demo working.
$env:ALPHA_DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@localhost:5432/alpha_rule_ingestion"
$env:DELTA_DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@localhost:5432/$($env:POSTGRES_DB)"

# --- Delta dashboard login ------------------------------------------------
# m7 removed the hardcoded admin/admin123 fallback and deliberately left no
# default, so Delta starts healthy but returns 401 on login until these are
# set. That is the intended fail-closed behaviour.
$env:ADMIN_USERNAME = 'demo'
$env:ADMIN_PASSWORD = 'demo123'

# --- Beta live-bus wiring -------------------------------------------------
$env:KAFKA_EVIDENCE_ENABLED = 'true'
$env:B11_SERVICE_TENANT_ID = 'acme'
$env:VERDICT_PUBLISH_ENABLED = 'true'
$env:ALPHA_RULES_URL = 'http://127.0.0.1:8001/api/v2/rules/search'
# The publisher's route is /api/v2/publish -- NOT /api/v2/verdicts/publish.
# Setting a wrong URL here overrides vp_app's correct built-in default and
# fails with a 404 that looks like the publisher being down.
$env:VERDICT_PUBLISH_URL = 'http://127.0.0.1:8004/api/v2/publish'
$env:VE_PORT = '8002'
$env:VP_PORT = '8004'

# --- Frontend -------------------------------------------------------------
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000/api/v2'
$env:VITE_WS_URL       = 'ws://127.0.0.1:8000/ws/verdicts'

Write-Host ''
Write-Host '[demo-env] loaded. Database split:' -ForegroundColor Green
Write-Host "  Alpha -> alpha_rule_ingestion (own alembic chain)" -ForegroundColor Green
Write-Host "  Delta -> $($env:POSTGRES_DB) (owns 0001_initial_verdict_platform)" -ForegroundColor Green
Write-Host '[demo-env] one SECRET_KEY shared by all six services.' -ForegroundColor Green
Write-Host ''