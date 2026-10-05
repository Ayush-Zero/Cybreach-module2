"""Drive every real cross-pod seam in CyBreach Module 2, one narrated take at a time.

WHY THIS IS SEVEN TAKES AND NOT ONE PIPELINE
--------------------------------------------
The four pods are deployed and individually working, but they are NOT wired
end to end. Four hops in the "obvious" pipeline do not exist:

  1. OCSF-normalised event -> Beta's validation engine.
     Beta has no OCSF awareness at all (no `class_uid` anywhere in
     cybreach_pod_beta). `ve_app.models.EvidenceEvent` requires exactly
     action_id, correlation_key, technique_ref, target_asset_ref,
     expected_observable and timestamp. An OCSF event has none of those, so
     Pydantic rejects it and EvidenceConsumer dead-letters it to
     cybreach.evidence.v1.dlq. No mapper was ever written.

  2. "Missed because no rule exists".
     No matching rule yields NoData, not Missed. `ve_app.main.build_verdict`
     returns verdict="NoData" when rule is None. `Missed` requires a rule that
     exists and does not fire -- see app/services/validator_service.py:3-12 for
     why conflating the two matters.

  3. Alpha creating a rule from a detected gap.
     Alpha's only write route is POST /api/v2/rules/ingest, which takes a
     `repo_url` pointing at a directory of .yml files. There is no
     "synthesise a rule from a missed verdict" endpoint.

  4. Gamma's re-validation service producing a detection verdict.
     Gamma :8006 POST /api/v2/revalidate takes {event_id, vendor, normalized}
     and diffs two OCSF *normalisation* snapshots, returning a drift verdict
     (UNCHANGED / IMPROVED / DEGRADED). It has no notion of
     Detected/Missed, never calls Beta's publisher, and debits wallet credits.

So this script demonstrates every seam that genuinely exists and prints the
missing ones at the end, rather than papering over them in glue code. Each take
is independent and re-recordable.

USAGE
-----
    python demo/full-pipeline.py -All
    python demo/full-pipeline.py -Take 3
    python demo/full-pipeline.py -Take 1 -Count 0 -Json
    python demo/full-pipeline.py -Preflight

Requires the six services up (demo/start-services.ps1) and Kafka on :9092.
Reads .env from the repo root using the same keys as demo/demo-env.ps1.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

import jose.jwt

# kafka-python warns that value_serializer is not a Serializer subclass. It is
# only a DeprecationWarning and the callback works, but on a recorded demo it
# prints to stderr mid-take and looks like a failure.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="kafka.*")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = Path(__file__).resolve().parent

ALPHA = "http://127.0.0.1:8001"
BETA_VALIDATE = "http://127.0.0.1:8002"
BETA_PUBLISH = "http://127.0.0.1:8004"
DELTA = "http://127.0.0.1:8000"
GAMMA_NORMALIZE = "http://127.0.0.1:8005"
GAMMA_REVALIDATE = "http://127.0.0.1:8006"

BOOTSTRAP = "localhost:9092"
EVIDENCE_TOPIC = "cybreach.evidence.v1"
VERDICT_TOPIC = "cybreach.verdicts.v2"
GAP_CLOSED_TOPIC = "cybreach.gap_closed.v2"

CONTRACT_FIELDS = (
    "action_id",
    "verdict",
    "confidence",
    "causal_chain",
    "mttd_seconds",
    "matched_evidence_ref",
    "regulatory_control_refs",
)

VENDOR_FIXTURES = {
    "splunk": "splunk_events.json",
    "elastic": "ecs_events.json",
    "sentinel": "sentinel_events.json",
    "qradar": "qradar_events.json",
    "logscale": "logscale_events.json",
}

WIDTH = 78


# ---------------------------------------------------------------- environment


def load_env():
    """Load .env into os.environ, mirroring demo/demo-env.ps1.

    demo-env.ps1 only populates a PowerShell session, so a script launched
    without dot-sourcing it first would run with no SECRET_KEY and 401 on every
    authenticated route. Reading the same file here keeps one source of truth.
    """

    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        print(f"! no .env at {env_file}", file=sys.stderr)
        return

    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

    os.environ.setdefault("SECRET_KEY", "demo-only-shared-key-not-for-production")
    os.environ.setdefault("B11_SERVICE_TENANT_ID", "acme")


def mint_service_token():
    """Mint the HS256 token Alpha and Gamma expect.

    Delta's own login token carries only `sub` (backend/app/security/security.py),
    but Alpha's get_current_tenant and Gamma's get_current_tenant both require a
    `tenant_id` claim and reject a Delta token with 401. Beta mints its own
    service token with both claims; this mirrors that.
    """

    secret = os.environ["SECRET_KEY"]
    return jose.jwt.encode(
        {
            "sub": "demo-operator",
            "tenant_id": os.environ.get("B11_SERVICE_TENANT_ID", "acme"),
            "exp": int(time.time()) + 900,
        },
        secret,
        algorithm="HS256",
    )


def delta_login(username="demo", password="demo123"):
    body = urllib.parse.urlencode({"username": username, "password": password})
    request = urllib.request.Request(
        f"{DELTA}/api/v2/auth/login",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())["access_token"]


# ------------------------------------------------------------------ plumbing


def http(method, url, token=None, payload=None, timeout=30):
    """One JSON request. Raises RuntimeError with the body on any non-2xx."""

    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"HTTP {exc.code} {url}\n    {body}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"cannot reach {url} ({exc.reason}). Start the services first."
        ) from None


def banner(take, title, pod, port):
    print()
    print("=" * WIDTH)
    print(f" TAKE {take}  {title}")
    print(f" pod {pod}  port {port}")
    print("=" * WIDTH)


def say(text):
    print(f"  SAY > {text}")


def gap(text):
    print(f"  NOT CONNECTED > {text}")


def field(label, value):
    print(f"  {label:<22}: {value}")


def verify_hash(payload):
    """Re-derive content_hash from the seven frozen fields, as Delta does."""

    projected = {name: payload.get(name) for name in CONTRACT_FIELDS}
    digest = hashlib.sha256(
        json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest == payload.get("content_hash")


def read_fixture(relative):
    path = REPO_ROOT / relative
    if not path.exists():
        raise RuntimeError(f"missing fixture: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]
    return [payload]


def run_id():
    return time.strftime("%H%M%S")


def kafka_ready():
    from kafka.admin import KafkaAdminClient

    try:
        admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP, request_timeout_ms=5000)
        admin.close()
        return True
    except Exception:
        return False


# ----------------------------------------------------------------- preflight


def preflight():
    banner(0, "PREFLIGHT", "all", "-")
    probes = [
        (DELTA, "/health", "Delta"),
        (ALPHA, "/health", "Alpha"),
        (BETA_VALIDATE, "/health", "Beta validate"),
        (BETA_PUBLISH, "/health", "Beta publisher"),
        (GAMMA_NORMALIZE, "/", "Gamma normalizer"),
        (GAMMA_REVALIDATE, "/health", "Gamma revalidate"),
    ]
    ok = True
    for base, path, name in probes:
        try:
            http("GET", f"{base}{path}", timeout=8)
            field(name, "up")
        except RuntimeError as exc:
            ok = False
            field(name, f"DOWN  {exc}")

    if kafka_ready():
        field("Kafka", f"up on {BOOTSTRAP}")
    else:
        ok = False
        field("Kafka", f"DOWN on {BOOTSTRAP}")

    print()
    if ok:
        say("Six services and the broker are up. Every take below is runnable.")
    else:
        say("Something is down. Run demo/start-services.ps1 and demo/health-check.ps1.")
    return ok


# --------------------------------------------------------------- take 1: OCSF


def take_1_ocsf(args, state):
    banner(1, "Gamma: vendor telemetry -> canonical OCSF", "Gamma", 8005)
    say("Five vendors, five schemas, one canonical event. The format is detected")
    say("from the payload -- the caller never declares it.")

    token = mint_service_token()
    normalized = None

    for vendor in VENDOR_FIXTURES:
        relative = f"cybreach_pod_gamma/ocsf_normalizer/tests/fixtures/{VENDOR_FIXTURES[vendor]}"
        records = read_fixture(relative)
        if args.Count > 0:
            records = records[: args.Count]

        print()
        print(f"  -- {vendor} ({len(records)} record(s))")
        for record in records:
            result = http(
                "POST",
                f"{GAMMA_NORMALIZE}/api/v2/ocsf/normalize",
                token=token,
                payload={"log": record},
            )
            actor = (result.get("actor") or {}).get("user") or {}
            field("in", ", ".join(list(record)[:6]))
            field(
                "out",
                f"class_uid={result.get('class_uid')} "
                f"activity_id={result.get('activity_id')} "
                f"category_uid={result.get('category_uid')} "
                f"severity_id={result.get('severity_id')} "
                f"user={actor.get('name')}",
            )
            if args.Json:
                print(json.dumps(result, indent=2))
            normalized = normalized or result

    print()
    metrics = http(
        "GET", f"{GAMMA_NORMALIZE}/api/v2/ocsf/normalize/metrics", token=token
    )
    field("metrics", json.dumps(metrics)[:200])

    print()
    gap("This OCSF event does NOT reach Beta. No OCSF->EvidenceEvent mapper exists.")
    return {"normalized": normalized, "token": token}


# --------------------------------------------------------------- take 2: alpha


def take_2_alpha(args, state):
    banner(2, "Alpha: Sigma rule ingestion", "Alpha", 8001)
    say("A rule's identity is a content hash, not an integer -- so the same rule")
    say("resolves to the same id on every pod and verdicts stay joinable.")

    token = state.get("service_token") or mint_service_token()
    state["service_token"] = token

    rules_dir = REPO_ROOT / "cybreach_pod_alpha/rule ingestion/tests/fixtures/rule_repo/sigma"
    if not rules_dir.exists():
        raise RuntimeError(f"missing Sigma repo: {rules_dir}")

    ingested = http(
        "POST",
        f"{ALPHA}/api/v2/rules/ingest",
        token=token,
        payload={
            "repo_url": str(rules_dir),
            "branch": "main",
            "rule_types": ["sigma"],
            "include_validation": True,
        },
        timeout=120,
    )
    items = ingested if isinstance(ingested, list) else ingested.get("rules", [])
    field("ingested", f"{len(items)} rules for tenant {os.environ.get('B11_SERVICE_TENANT_ID')}")

    for rule in items[:5]:
        print(
            f"    {str(rule.get('rule_id'))[:16]}..  "
            f"{rule.get('title')}  "
            f"{rule.get('mitre_techniques')}"
        )
    if len(items) > 5:
        print(f"    ... and {len(items) - 5} more")

    print()
    gap("Alpha cannot synthesise a rule from a missed verdict. /ingest needs a")
    gap("directory of .yml files on disk -- there is no gap-driven rule creation.")
    state["alpha_rules"] = items


# --------------------------------------------------------------- take 3: beta


def take_3_beta(args, state):
    banner(3, "Beta: evidence -> verdict -> published on the bus", "Beta", "8002 / 8004")
    say("This is the genuine cross-pod chain: Alpha's rules, Beta's validation,")
    say("and a canonical v2.0 verdict landing on a shared Kafka topic.")

    from kafka import KafkaConsumer, KafkaProducer, TopicPartition

    run = run_id()
    action_id = f"act-pipeline-{run}"

    # The demo evidence is T1059.001 because rule_matching.matches_technique is
    # exact string equality (rule_matching.py:53) -- "T1059" will NOT match
    # "T1059.001", and neither side does sub-technique matching.
    event = {
        "action_id": action_id,
        "correlation_key": f"corr-pipeline-{run}",
        "technique_ref": "T1059.001",
        "target_asset_ref": "host-web-01",
        "expected_observable": "powershell.exe spawned by services.exe",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Sit at the END of the verdict topic before publishing, so only verdicts
    # this run causes are read and no older message is reprinted.
    reader = KafkaConsumer(
        bootstrap_servers=BOOTSTRAP,
        auto_offset_reset="latest",
        consumer_timeout_ms=1000,
    )
    partition = TopicPartition(VERDICT_TOPIC, 0)
    reader.assign([partition])
    start = reader.end_offsets([partition])[partition]

    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    metadata = producer.send(EVIDENCE_TOPIC, event).get(timeout=30)
    producer.flush()
    producer.close()
    field("published", f"{action_id} -> {metadata.topic} p{metadata.partition} @{metadata.offset}")

    print()
    print(f"  waiting up to {args.Wait}s for Beta to validate and publish...")
    reader.seek(partition, start)
    deadline = time.time() + args.Wait
    verdict = None
    while time.time() < deadline and verdict is None:
        for message in reader:
            try:
                payload = json.loads(message.value.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if payload.get("action_id") == action_id:
                verdict = payload
                break
        if verdict is None:
            time.sleep(0.5)
    reader.close()

    if verdict is None:
        gap("No verdict. Check Beta has KAFKA_EVIDENCE_ENABLED=true AND")
        gap("VERDICT_PUBLISH_ENABLED=true, and Alpha was seeded in take 2.")
        return

    field("verdict", verdict.get("verdict"))
    field("confidence", verdict.get("confidence"))
    field("content_hash", verdict.get("content_hash"))
    field("hash re-derives", verify_hash(verdict))
    extra = set(verdict) - set(CONTRACT_FIELDS) - {"content_hash"}
    field("fields off-contract", extra or "none")

    print()
    print("  causal_chain:")
    for line in verdict.get("causal_chain") or []:
        print(f"      - {line}")

    print()
    if verdict.get("verdict") == "NoData":
        say("NoData, not Missed. No Alpha rule carries technique_ref T1059.001")
        say("for this tenant, so there was nothing to evaluate.")
    elif verdict.get("verdict") == "Detected":
        say("Confidence is a flat 0.9 here, not a match score. Alpha-sourced rules")
        say("always arrive with keywords=[] (ve_app/main.py:222), so")
        say("compute_confidence takes its early return. Detected means a rule with")
        say("an identical MITRE technique existed -- expected_observable is never")
        say("compared to anything on this path.")

    print()
    gap("Delta never consumes cybreach.verdicts.v2. This verdict is on the topic")
    gap("and nowhere else -- it will NOT appear in the Delta dashboard.")
    state["bus_verdict"] = verdict


# --------------------------------------------------------------- take 4: delta


def take_4_delta(args, state):
    banner(4, "Delta: rule storage, evaluation, persistence, dashboard", "Delta", 8000)
    say("A separate path from take 3. Delta evaluates in-process, persists to")
    say("Postgres, broadcasts on the WebSocket, and publishes to the same topic.")

    token = delta_login()
    field("logged in", "demo / demo123 -> JWT (sub only, no tenant_id)")

    run = run_id()
    rule_name = f"Pipeline Demo Encoded PowerShell {run}"
    query = '{"detection":{"selection":{"Image":"powershell.exe","CommandLine":"-enc"}}}'
    event = {
        "event_id": f"evt-pipeline-{run}",
        "Image": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        "CommandLine": "powershell.exe -enc SQBFAFgA",
        "parent_image": "C:\\Windows\\System32\\services.exe",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # The rule must exist first. verdict_events.rule_id is a foreign key and the
    # id is a content hash over exactly rule_name + query + rule_type +
    # mitre_technique, so validation must repeat all four or it 404s
    # (api/validator.py:90-100).
    rule = http(
        "POST",
        f"{DELTA}/api/v2/rules",
        token=token,
        payload={
            "rule_name": rule_name,
            "rule_type": "sigma",
            "severity": "high",
            "description": "Detects base64-encoded PowerShell command lines",
            "query": query,
            "status": "active",
            "mitre_technique": "T1059.001",
        },
    )
    field("rule_id", rule.get("rule_id"))

    verdict = http(
        "POST",
        f"{DELTA}/api/v2/validate",
        token=token,
        payload={
            "action_id": f"act-delta-{run}",
            "rule_query": query,
            "event": event,
            "rule_name": rule_name,
            "rule_type": "sigma",
            "mitre_technique": "T1059.001",
        },
    )
    field("verdict", verdict.get("verdict"))
    field("confidence", verdict.get("confidence"))
    field("verdict_id", verdict.get("verdict_id"))
    field("matched fields", ", ".join(verdict.get("matched_fields") or []) or "none")
    field("mttd_seconds", verdict.get("mttd_seconds"))

    listed = http("GET", f"{DELTA}/api/v2/verdicts", token=token)
    field("persisted verdicts", len(listed) if isinstance(listed, list) else "?")

    stats = http("GET", f"{DELTA}/api/v2/dashboard/stats", token=token)
    field("dashboard stats", json.dumps(stats)[:180])

    print()
    say("That row is in Postgres now. Open http://127.0.0.1:5173 -- the verdict")
    say("table updates over the WebSocket with no refresh.")
    gap("This verdict reached the dashboard via Delta's own /validate. Take 3's")
    gap("bus verdict did not, and never will in this hybrid run.")
    state["delta_token"] = token


# ---------------------------------------------------------- take 5: red/green


def take_5_red_to_green(args, state):
    banner(5, "Delta: prove a gap, fix it, re-verify the SAME evidence", "Delta", 8000)
    say("The strongest clip in the demo. Nothing is staged: the Missed verdict is")
    say("really produced, the rule is really edited, the stored event is really")
    say("re-evaluated. The evidence never changes -- only the rule does.")

    token = state.get("delta_token") or delta_login()
    state["delta_token"] = token

    run = run_id()
    rule_name = f"Red-To-Green Gap {run}"
    weak = '{"detection":{"selection":{"Image":"cmd.exe"}}}'
    fixed = '{"detection":{"selection":{"Image":"powershell.exe"}}}'
    event = {
        "event_id": f"evt-red-to-green-{run}",
        "Image": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        "CommandLine": "powershell.exe -enc SQBFAFgA",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    print()
    print("  STEP 1  a rule that does not cover this behaviour")
    rule = http(
        "POST",
        f"{DELTA}/api/v2/rules",
        token=token,
        payload={
            "rule_name": rule_name,
            "rule_type": "sigma",
            "severity": "medium",
            "description": "Looks for the wrong binary (the detection gap)",
            "query": weak,
            "status": "active",
            "mitre_technique": "T1059.001",
        },
    )
    field("rule looks for", "Image contains 'cmd.exe'")
    field("evidence is", "Image contains 'powershell.exe'  (T1059.001)")

    print()
    print("  STEP 2  evaluate -> expect Missed")
    missed = http(
        "POST",
        f"{DELTA}/api/v2/validate",
        token=token,
        payload={
            "action_id": f"act-red-to-green-{run}",
            "rule_query": weak,
            "event": event,
            "rule_name": rule_name,
            "rule_type": "sigma",
            "mitre_technique": "T1059.001",
        },
    )
    field("verdict", missed.get("verdict"))
    field("confidence", missed.get("confidence"))
    field("verdict_id", missed.get("verdict_id"))
    for line in missed.get("causal_chain") or []:
        print(f"      - {line}")

    if missed.get("verdict") != "Missed":
        gap(f"Expected Missed but got {missed.get('verdict')}. Aborting before the fix.")
        return

    print()
    print("  STEP 3  tighten the rule to cover the behaviour")
    updated = http(
        "PUT",
        f"{DELTA}/api/v2/rules/{rule['id']}",
        token=token,
        payload={
            "rule_name": rule_name,
            "rule_type": "sigma",
            "severity": "high",
            "description": "Now targets the binary that actually ran",
            "query": fixed,
            "status": "active",
            "mitre_technique": "T1059.001",
        },
    )
    field("rule now looks for", "Image contains 'powershell.exe'")
    field("rule_id", f"{str(updated.get('rule_id'))[:20]}.. (unchanged, old verdict resolves)")

    print()
    print("  STEP 4  re-validate the SAME stored evidence -> expect Detected")
    result = http(
        "POST",
        f"{DELTA}/api/v2/verdicts/{missed['verdict_id']}/revalidate",
        token=token,
    )
    old = result.get("old_verdict") or {}
    new = result.get("new_verdict") or {}
    field("BEFORE", f"{old.get('verdict')} conf={old.get('confidence')}")
    field("AFTER", f"{new.get('verdict')} conf={new.get('confidence')}")
    field("gap_closed", result.get("gap_closed"))
    field("confidence delta", (result.get("comparison") or {}).get("delta"))
    field("matched fields", ", ".join((result.get("validation") or {}).get("matched_fields") or []) or "none")
    field("superseded", f"#{result.get('previous_verdict_id')} -> #{result.get('verdict_id')}")

    audit = http("GET", f"{DELTA}/api/v2/audit-logs", token=token)
    if isinstance(audit, list) and audit:
        latest = audit[-1]
        field("audit action", latest.get("action"))

    print()
    say(f"Kafka topic {GAP_CLOSED_TOPIC} now carries this verdict -- find it in the")
    say(f"Kafka UI by action_id act-red-to-green-{run}.")
    say("The superseded verdict is retired, not deleted.")
    gap("This is Delta's own in-process re-validation, not Gamma :8006.")
    gap("The gap is 'a rule exists but does not match', never 'no rule exists' --")
    gap("verdict_events.rule_id is a foreign key, so a technique with zero rules")
    gap("cannot be filed as Missed at all.")


# --------------------------------------------------------------- take 6: gamma


def take_6_gamma_revalidate(args, state):
    banner(6, "Gamma: normalisation drift re-validation", "Gamma", 8006)
    say("Be precise about this one. Gamma re-validates NORMALISATION quality,")
    say("not detection. It diffs two OCSF snapshots for one event_id.")

    token = state.get("service_token") or mint_service_token()
    state["service_token"] = token

    normalized = (state.get("normalized") or {})
    if not normalized:
        records = read_fixture(
            "cybreach_pod_gamma/ocsf_normalizer/tests/fixtures/splunk_events.json"
        )
        normalized = http(
            "POST",
            f"{GAMMA_NORMALIZE}/api/v2/ocsf/normalize",
            token=token,
            payload={"log": records[0]},
        )

    run = run_id()
    event_id = f"evt-ocsf-{run}"

    before = http("GET", f"{GAMMA_REVALIDATE}/api/v2/revalidate/wallet", token=token)
    field("wallet before", (before or {}).get("balance"))

    print()
    print("  RUN 1  first submission -> compared against an empty baseline")
    first = http(
        "POST",
        f"{GAMMA_REVALIDATE}/api/v2/revalidate",
        token=token,
        payload={"event_id": event_id, "vendor": "splunk", "normalized": normalized},
    )
    field("verdict", first.get("verdict"))
    field("confidence", f"{first.get('confidence_before')} -> {first.get('confidence_after')}")
    field("delta", first.get("confidence_delta"))
    field("improved by", ", ".join(first.get("improved_by") or []) or "none")

    print()
    print("  RUN 2  identical payload -> UNCHANGED, and the credit is refunded")
    second = http(
        "POST",
        f"{GAMMA_REVALIDATE}/api/v2/revalidate",
        token=token,
        payload={"event_id": event_id, "vendor": "splunk", "normalized": normalized},
    )
    field("verdict", second.get("verdict"))
    field("confidence delta", second.get("confidence_delta"))

    after_unchanged = http("GET", f"{GAMMA_REVALIDATE}/api/v2/revalidate/wallet", token=token)
    field("wallet after", (after_unchanged or {}).get("balance"))

    print()
    print("  RUN 3  degrade the payload -> confidence drops")
    degraded = json.loads(json.dumps(normalized))
    degraded.pop("actor", None)
    degraded["severity_id"] = 99
    third = http(
        "POST",
        f"{GAMMA_REVALIDATE}/api/v2/revalidate",
        token=token,
        payload={"event_id": event_id, "vendor": "splunk", "normalized": degraded},
    )
    field("verdict", third.get("verdict"))
    field("confidence", f"{third.get('confidence_before')} -> {third.get('confidence_after')}")
    field("delta", third.get("confidence_delta"))
    field("degraded by", ", ".join(third.get("degraded_by") or []) or "none")
    for entry in (third.get("deltas") or [])[:5]:
        field(
            f"  {entry.get('ocsf_field')}",
            f"{entry.get('old_value')} -> {entry.get('new_value')} ({entry.get('change_type')})",
        )

    runs = http("GET", f"{GAMMA_REVALIDATE}/api/v2/revalidate/runs", token=token)
    if isinstance(runs, list):
        field("stored runs", len(runs))
    elif isinstance(runs, dict):
        field("stored runs", len(runs.get("runs", [])))
    else:
        field("stored runs", "?")

    print()
    gap("Gamma never returns Detected/Missed/Partial -- its vocabulary is")
    gap("UNCHANGED / IMPROVED / DEGRADED. It never calls Beta's verdict publisher.")
    gap("This is NOT the re-validation shown in take 5.")


# --------------------------------------------------------------------- gaps


def print_gaps():
    print()
    print("=" * WIDTH)
    print(" HONEST STATE OF INTEGRATION -- four hops that do not exist")
    print("=" * WIDTH)
    rows = [
        ("OCSF event -> Beta validation", "MISSING", "no mapper; Pydantic rejects it -> DLQ"),
        ("'Missed because no rule'", "WRONG VERDICT", "no rule yields NoData, not Missed"),
        ("Alpha: rule from a gap", "MISSING", "/ingest needs a directory of .yml"),
        ("Gamma -> detection verdict", "MISMATCH", "compares OCSF snapshots, not verdicts"),
    ]
    print(f"  {'HOP':<34} {'STATE':<15} WHY")
    print("  " + "-" * (WIDTH - 4))
    for hop, state, why in rows:
        print(f"  {hop:<34} {state:<15} {why}")

    print()
    say("Every service works. The contracts are frozen and the cross-pod tests")
    say("pass. What is missing is the wiring between them -- and naming those")
    say("seams precisely is the integration work, not hiding them in glue.")


# --------------------------------------------------------------------- main


TAKES = {
    1: ("Gamma OCSF normalisation", take_1_ocsf),
    2: ("Alpha rule ingestion", take_2_alpha),
    3: ("Beta evidence -> verdict -> bus", take_3_beta),
    4: ("Delta validate -> dashboard", take_4_delta),
    5: ("Delta red-to-green re-validation", take_5_red_to_green),
    6: ("Gamma normalisation re-validation", take_6_gamma_revalidate),
}

# Take N needs the state take N-1 produced, so they run in order.
NEEDS_STATE = {2: 1, 3: 2, 6: 1}


def main():
    parser = argparse.ArgumentParser(
        description="Drive every real CyBreach cross-pod seam, one take at a time."
    )
    parser.add_argument("-Take", type=int, choices=[0, 1, 2, 3, 4, 5, 6], help="run one take")
    parser.add_argument("-All", action="store_true", help="run every take in order")
    parser.add_argument("-Preflight", action="store_true", help="check services and Kafka")
    parser.add_argument("-Count", type=int, default=1, help="fixture records per vendor (0 = all)")
    parser.add_argument("-Json", action="store_true", help="print full response bodies")
    parser.add_argument("-Wait", type=int, default=30, help="seconds to wait for a verdict")
    parser.add_argument(
        "-Force", action="store_true", help="run even if preflight fails"
    )
    args = parser.parse_args()

    if not (args.All or args.Take or args.Preflight):
        parser.print_help()
        return 0

    load_env()

    if args.Preflight and not args.Take and not args.All:
        return 0 if preflight() else 1

    if not args.Force and not preflight():
        print()
        print("Aborting. Re-run with -Force if you want to try anyway.")
        return 1

    order = sorted(TAKES) if args.All else [args.Take]
    state = {}

    if args.Take:
        prerequisite = NEEDS_STATE.get(args.Take)
        if prerequisite:
            print()
            print(f"  Take {args.Take} reads state from take {prerequisite}; running it first.")
            TAKES[prerequisite][1](args, state)

    failures = []
    for number in order:
        title, handler = TAKES[number]
        try:
            handler(args, state)
        except RuntimeError as exc:
            failures.append((number, title, str(exc)))
            print()
            print(f"  TAKE {number} FAILED: {exc}")

    if args.All or args.Take == 6:
        print_gaps()

    print()
    if failures:
        print(f"{len(failures)} take(s) failed:")
        for number, title, message in failures:
            print(f"  take {number} ({title}): {message.splitlines()[0]}")
        return 1
    print("All requested takes completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())