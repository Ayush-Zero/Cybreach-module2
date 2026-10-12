"""Runtime data generation for the CyBreach demo.

The demo must not read the pods' committed test fixtures. Those files belong to
the test suites (Alpha's rule_repo and Gamma's *_events.json are loaded by a
dozen test modules), so a handover demo that reads them is coupled to data that
is free to change under it -- and a recorded run that replays identical bytes
every time is not showing a live system.

Everything the demo needs is generated here, per run: the Sigma rule, the
evidence event and the vendor telemetry. Nothing is pre-baked, so no two runs
look alike and nothing in the repository exists purely for the camera.

This module is both a library (imported by full-pipeline.py and
publish_evidence.py) and a CLI (used by the PowerShell scripts so they do not
have to embed Python).

The one piece of shared state is the run tenant: a single id minted once per
demo run and stored in demo/.run/tenant so all six services agree on it. Beta's
Kafka consumer reads B11_SERVICE_TENANT_ID once at process start, so a per-run
tenant only holds if every service is started from the same run file -- which is
why start-services.ps1 is the run boundary.

CLI
---
    python demo/gendata.py tenant                  # print the run tenant
    python demo/gendata.py new-tenant              # mint + persist a fresh one
    python demo/gendata.py sigma [--technique T]   # print a generated Sigma rule
    python demo/gendata.py evidence [--technique T]
    python demo/gendata.py vendor <name> [--count N]
    python demo/gendata.py seed [--technique T] [--repo-dir DIR]
"""

import argparse
import json
import os
import random
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import yaml

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent
RUN_DIR = DEMO_DIR / ".run"
TENANT_FILE = RUN_DIR / "tenant"

ALPHA_URL = "http://127.0.0.1:8001"

# Techniques the generated rule/evidence pair can use. Every entry is a valid
# MITRE ATT&CK id (the parser's regex is ^T\d{4}(?:\.\d{3})?$). The rule and the
# evidence are always built from the same one, so the pairing is dynamic but the
# outcome is deterministic: a rule with an identical technique_ref exists.
TECHNIQUES = ["T1059.001", "T1486", "T1195", "T1053.005", "T1547.001"]

# Vendors the normalizer can detect from the payload. Keys out of this list are
# rejected -- see src/detector.py for the signature each one keys on.
VENDORS = ["splunk", "elastic", "sentinel", "qradar", "logscale"]

_USERS = [
    "admin",
    "svc_webapp",
    "john.doe",
    "mary.smith",
    "soc_analyst",
    "guest",
    "it-admin",
]
_HOSTS = ["dc01.corp.local", "web01.corp.local", "db01.corp.local"]


# --------------------------------------------------------------- environment


def load_env():
    """Load the repo-root .env into os.environ, mirroring demo-env.ps1.

    demo-env.ps1 only populates a PowerShell session, so a script launched
    without dot-sourcing it would run with no SECRET_KEY and 401 on every
    authenticated route. Reading the same file here keeps one source of truth.
    """

    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    os.environ.setdefault("SECRET_KEY", "demo-only-shared-key-not-for-production")


# ------------------------------------------------------------ run identity


def new_tenant(prefix="demo"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def write_tenant(tenant):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    TENANT_FILE.write_text(tenant + "\n", encoding="utf-8")
    return tenant


def run_tenant():
    """Return the tenant for this demo run, creating the run file if needed.

    Precedence: the run file first (start-services.ps1 owns the run boundary),
    then B11_SERVICE_TENANT_ID from the environment, then a fresh id. Whichever
    value wins is persisted so every process that calls this agrees on it.
    """

    if TENANT_FILE.exists():
        # utf-8-sig tolerates a BOM that Windows PowerShell's Set-Content may
        # have written before the writer was switched to -Encoding Ascii.
        value = TENANT_FILE.read_text(encoding="utf-8-sig").strip()
        if value:
            return value

    value = os.environ.get("B11_SERVICE_TENANT_ID", "").strip() or new_tenant()
    return write_tenant(value)


# ------------------------------------------------------------- generators


def _ip():
    return (
        f"10.{random.randint(0, 255)}.{random.randint(0, 255)}"
        f".{random.randint(1, 254)}"
    )


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def make_sigma_rule(technique=None):
    """Return (rule_dict, technique) for a Sigma rule generated in memory.

    The shape matches what parse_sigma_rule expects (title + detection
    required; tags carry the MITRE technique). The detection block does not have
    to match Beta's bus path -- that path compares technique_ref only -- but it
    is a real selection so Alpha's parser and validation treat it as a rule.
    """

    technique = technique or random.choice(TECHNIQUES)
    rule_id = str(uuid.uuid4())
    rule = {
        "title": f"Auto-Generated Demo Rule {rule_id[:8]}",
        "id": rule_id,
        "status": "experimental",
        "description": (
            "Generated in memory during the CyBreach demo; never read from a "
            "committed fixture."
        ),
        "author": "cybreach-demo",
        "tags": ["attack.execution", f"attack.{technique.lower()}"],
        "logsource": {"category": "process_creation", "product": "windows"},
        "detection": {
            "selection": {
                "Image|endswith": "\\powershell.exe",
                "CommandLine|contains": ["-enc ", "-EncodedCommand"],
            },
            "condition": "selection",
        },
        "falsepositives": ["Legitimate administrative scripting"],
        "level": "high",
    }
    return rule, technique


def sigma_yaml(rule):
    return yaml.safe_dump(rule, sort_keys=False)


def write_rule_repo(directory, rule):
    """Write one generated rule as a .yml into `directory` (Alpha discovers only
    .yml/.yaml). Returns the file path."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"auto_{uuid.uuid4().hex[:8]}.yml"
    path.write_text(sigma_yaml(rule), encoding="utf-8")
    return path


def make_evidence(technique=None, run=None):
    """Return (evidence_event_dict, technique) matching ve_app.models.EvidenceEvent."""

    technique = technique or random.choice(TECHNIQUES)
    run = run or uuid.uuid4().hex[:12]
    event = {
        "action_id": f"act-{run}",
        "correlation_key": f"corr-{run}",
        "technique_ref": technique,
        "target_asset_ref": f"host-{random.randint(1, 99):02d}",
        "expected_observable": (
            f"{random.choice(['powershell.exe', 'vssadmin.exe', 'rundll32.exe'])} "
            f"spawned by services.exe (generated {_iso()})"
        ),
        "timestamp": _iso(),
    }
    return event, technique


def make_vendor_event(vendor, technique=None):
    """Return a raw vendor event whose signature makes the detector pick `vendor`.

    Field names mirror the shapes in Gamma's adapters so the normalizer produces
    a real OCSF event. `technique` is accepted for symmetry with the other
    generators; the normalizer does not use it.
    """

    if vendor not in VENDORS:
        raise ValueError(f"unknown vendor {vendor!r}; expected one of {VENDORS}")

    user = random.choice(_USERS)
    host = random.choice(_HOSTS)
    src = _ip()
    dst = _ip()

    if vendor == "splunk":
        action = random.choice(["success", "failure"])
        return {
            "_time": str(int(time.time()) - random.randint(0, 3600)),
            "sourcetype": "WinEventLog:Security",
            "eventtype": random.choice(["auth_event", "failed_auth"]),
            "host": host,
            "action": action,
            "status": action,
            "vendor_severity": random.choice(["informational", "low", "high"]),
            "src_ip": src,
            "dest_ip": dst,
            "user": user,
        }

    if vendor == "elastic":
        # ECS: nested source/destination/event/host/user plus @timestamp. The
        # detector keys on the nested objects, not on dotted fields.
        outcome = random.choice(["success", "failure"])
        return {
            "@timestamp": _iso(),
            "event": {"category": "authentication", "outcome": outcome},
            "source": {"ip": src, "port": random.randint(1024, 65535)},
            "destination": {"ip": dst, "port": random.choice([22, 443, 3389])},
            "host": {"name": host},
            "user": {"name": user, "id": f"uid-{random.randint(0, 999)}"},
        }

    if vendor == "sentinel":
        return {
            "TimeGenerated": _iso(),
            "EventType": random.choice(["Logon", "Logoff"]),
            "TargetUsername": user,
            "SrcIpAddr": src,
            "DstIpAddr": dst,
            "DstHostname": host,
            "EventResult": random.choice(["Success", "Failure"]),
            "SeverityLevel": random.choice(["Low", "Medium", "High"]),
        }

    if vendor == "qradar":
        return {
            "starttime": int(time.time() * 1000),
            "sourceip": src,
            "sourceport": random.randint(1024, 65535),
            "destinationip": dst,
            "destinationport": random.choice([22, 443]),
            "username": user,
            "action": random.choice(["login", "logout"]),
            "status": random.choice(["success", "failure"]),
            "magnitude": random.randint(1, 10),
        }

    # logscale
    return {
        "@timestamp": _iso(),
        "aip": src,
        "endpoint_ip": dst,
        "user": user,
        "event_type": random.choice(["user_login", "user_logout"]),
        "status": random.choice(["success", "failure"]),
        "loglevel": random.choice(["info", "warn", "error", "critical"]),
    }


# ------------------------------------------------------------------ ingest


def mint_service_token(tenant, secret, ttl=900, subject="demo-operator"):
    """Mint the HS256 token Alpha and Gamma expect (sub + tenant_id claims)."""

    import jose.jwt

    return jose.jwt.encode(
        {"sub": subject, "tenant_id": tenant, "exp": int(time.time()) + ttl},
        secret,
        algorithm="HS256",
    )


def ingest_rule_repo(repo_dir, tenant, secret, alpha_url=ALPHA_URL, branch="main"):
    """POST a local directory of .yml rules to Alpha, as the running process.

    Alpha's only write route takes a repo_url pointing at a directory (or git
    URL) and walks it for .yml/.yaml; there is no inline-rule endpoint. A
    generated rule therefore round-trips through a temp directory.
    """

    token = mint_service_token(tenant, secret)
    body = json.dumps(
        {
            "repo_url": str(repo_dir),
            "branch": branch,
            "rule_types": ["sigma"],
            "include_validation": True,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{alpha_url}/api/v2/rules/ingest",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Alpha ingest failed: HTTP {exc.code} {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"cannot reach Alpha on {alpha_url} ({exc.reason}). "
            "Start it with demo/start-services.ps1."
        ) from None


def seed_rule(repo_dir=None, tenant=None, secret=None, technique=None,
              alpha_url=ALPHA_URL):
    """Ingest a generated rule (or an explicit directory) into Alpha.

    Returns a summary dict. When repo_dir is omitted, a Sigma rule is generated
    in memory, written to a temp directory, ingested, and the directory removed.
    """

    tenant = tenant or run_tenant()
    secret = secret or os.environ.get("SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY is not set. Dot-source demo/demo-env.ps1 or populate .env."
        )

    cleanup = None
    if repo_dir:
        path = Path(repo_dir)
        if not path.is_dir():
            raise RuntimeError(f"rules directory does not exist: {path}")
    else:
        rule, technique = make_sigma_rule(technique)
        cleanup = tempfile.TemporaryDirectory(prefix="cybreach-demo-rule-")
        path = Path(cleanup.name)
        write_rule_repo(path, rule)

    try:
        response = ingest_rule_repo(path, tenant, secret, alpha_url=alpha_url)
    finally:
        if cleanup is not None:
            cleanup.cleanup()

    items = response if isinstance(response, list) else response.get("rules", [])
    return {
        "tenant": tenant,
        "technique": technique,
        "generated": repo_dir is None,
        "rules": items,
    }


# --------------------------------------------------------------------- CLI


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate CyBreach demo data at runtime.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("tenant", help="print the run tenant (read-or-create)")
    sub.add_parser("new-tenant", help="mint and persist a fresh run tenant")

    p_sigma = sub.add_parser("sigma", help="print a generated Sigma rule as YAML")
    p_sigma.add_argument("--technique")

    p_ev = sub.add_parser("evidence", help="print a generated evidence event as JSON")
    p_ev.add_argument("--technique")

    p_vendor = sub.add_parser("vendor", help="print generated vendor telemetry as JSON")
    p_vendor.add_argument("name", choices=VENDORS)
    p_vendor.add_argument("--count", type=int, default=1)
    p_vendor.add_argument("--technique")

    p_seed = sub.add_parser("seed", help="generate + ingest a rule into Alpha")
    p_seed.add_argument("--technique")
    p_seed.add_argument("--repo-dir")

    args = parser.parse_args(argv)

    if args.command == "tenant":
        print(run_tenant())
        return 0

    if args.command == "new-tenant":
        print(write_tenant(new_tenant()))
        return 0

    if args.command == "sigma":
        rule, _ = make_sigma_rule(args.technique)
        print(sigma_yaml(rule), end="")
        return 0

    if args.command == "evidence":
        event, _ = make_evidence(args.technique)
        print(json.dumps(event, indent=2))
        return 0

    if args.command == "vendor":
        events = [make_vendor_event(args.name, args.technique) for _ in range(args.count)]
        print(json.dumps(events, indent=2))
        return 0

    if args.command == "seed":
        load_env()
        result = seed_rule(repo_dir=args.repo_dir, technique=args.technique)
        print(json.dumps(result, indent=2))
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
