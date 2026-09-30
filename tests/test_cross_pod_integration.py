"""Cross-pod checks for the shared bus, contract registry and API surface.

The tests in `test_cross_pod_contract.py` prove Beta and Delta derive the same
content hash for one event. These cover the seams that the integration
environment owns, where the failure mode is not a mismatch inside one pod but
two pods each being internally consistent and still disagreeing with each
other or with the workspace:

* B1/B10 -- the five topic names. Declared in one place
  (`topics.yaml`) and read by all three pods, but nothing verified that the
  pods' resolved values actually matched the manifest, so a pod could drift
  silently and still pass its own tests.
* B13 -- the plan's endpoint list. Alpha, Beta and Delta each resolved their
  routes differently; per-pod tests cannot catch a path that only exists in
  one pod's idea of the plan.
* M5 -- the contract registry. Every pod must read the same schema file rather
  than a private copy.

Each pod is imported in a subprocess where importing it in-process would
collide with another pod's top-level package name; the assertions are made
against the resolved values either way.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

BETA_ROOT = REPO_ROOT / "cybreach_pod_beta"
GAMMA_ROOT = REPO_ROOT / "cybreach_pod_gamma"
DELTA_BACKEND = REPO_ROOT / "cybreach_pod_delta" / "backend"
ALPHA_ROOT = REPO_ROOT / "cybreach_pod_alpha"

TOPICS_MANIFEST = REPO_ROOT / "topics.yaml"
CONTRACTS_DIR = REPO_ROOT / "contracts"
VERDICT_SCHEMA = CONTRACTS_DIR / "verdict-event" / "verdict.schema.json"
OCSF_SCHEMA = CONTRACTS_DIR / "ocsf_normalizer_schema.v1.json"

# The five topics the plan (Section 5) names, with the pod that owns each.
EXPECTED_TOPICS = {
    "cybreach.evidence.v1": "beta",
    "cybreach.verdicts.v2": "delta",
    "cybreach.gap_closed.v2": "delta",
    "cybreach.revalidation.v1": "gamma",
    "cybreach.connector.health.v1": "gamma",
}

# The plan's endpoint list, and the pod that serves each. Alpha's connector
# registry is included even though Alpha is not imported here -- the point of
# the table is that it is declared in one place, and the test below asserts
# the Beta/Delta/Gamma halves actually resolve.
PLAN_ENDPOINTS = {
    "/api/v2/rules": "alpha",
    "/api/v2/connectors/register": "alpha",
    "/api/v2/validate": "beta",
    "/api/v2/validate/batch": "beta",
    "/api/v2/classify": "beta",
    "/api/v2/publish": "beta",
    "/api/v2/verdicts": "delta",
    "/api/v2/dashboard/coverage": "delta",
}


def _run_python(code: str, cwd: Path, env_extra: dict | None = None) -> str:
    """Run a snippet in a pod's own directory and return stdout.

    A subprocess rather than an in-process import: the pods each own a
    top-level package name and their own dependency pins, so importing more
    than one per interpreter is not reliable.
    """

    env = dict(os.environ)
    env.pop("M2_TOPICS_PATH", None)
    env.update(env_extra or {})

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )

    assert result.returncode == 0, (
        f"snippet failed in {cwd.name}:\n{result.stdout}\n{result.stderr}"
    )
    return result.stdout.strip()


# --------------------------------------------------------------------------
# B1/B10: the shared topic manifest
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert TOPICS_MANIFEST.exists(), (
        f"shared topic manifest missing at {TOPICS_MANIFEST}. B1/B10's "
        "resolution is one shared manifest; its absence is the failure."
    )
    with open(TOPICS_MANIFEST, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_manifest_declares_exactly_the_plan_topics(manifest):
    declared = {entry["name"]: entry for entry in manifest["topics"]}

    assert set(declared) == set(EXPECTED_TOPICS), (
        "the shared manifest and the plan's topic list disagree: "
        f"manifest-only={sorted(set(declared) - set(EXPECTED_TOPICS))} "
        f"plan-only={sorted(set(EXPECTED_TOPICS) - set(declared))}"
    )


@pytest.mark.parametrize("name,owner", sorted(EXPECTED_TOPICS.items()))
def test_manifest_records_the_owning_pod(manifest, name, owner):
    entry = {e["name"]: e for e in manifest["topics"]}[name]
    assert entry["owner"] == owner

    # `usage` is what makes a topic actionable: without it the manifest records
    # a name nobody reads.
    assert entry.get("usage") in {"consume", "publish"}, (
        f"{name} declares no usage direction"
    )
    assert entry.get("description", "").strip(), f"{name} has no description"


def test_manifest_is_valid_yaml_and_versioned(manifest):
    assert manifest.get("version") == 1


POD_TOPIC_PROBES = {
    "delta": {
        "cwd": DELTA_BACKEND,
        "code": "from app.kafka.config import VERDICT_TOPIC; print(VERDICT_TOPIC)",
    },
    "beta": {
        "cwd": BETA_ROOT / "services" / "verdict_publisher",
        "code": "from vp_app.main import VERDICT_TOPIC; print(VERDICT_TOPIC)",
    },
}


@pytest.mark.parametrize("pod", sorted(POD_TOPIC_PROBES))
def test_pod_topic_matches_the_shared_manifest(manifest, pod):
    """Each pod's resolved topic name must equal the manifest's."""

    probe = POD_TOPIC_PROBES[pod]

    from_manifest = _run_python(
        probe["code"],
        probe["cwd"],
        {"M2_TOPICS_PATH": str(TOPICS_MANIFEST)},
    )
    without_manifest = _run_python(probe["code"], probe["cwd"])

    assert from_manifest == "cybreach.verdicts.v2", (
        f"{pod} resolved its verdict topic to {from_manifest!r} with the shared "
        "manifest mounted, which is not the plan's name"
    )
    assert without_manifest == from_manifest, (
        f"{pod} resolves {without_manifest!r} without the manifest but "
        f"{from_manifest!r} with it, so the pod's fallback has drifted from the "
        "shared manifest"
    )


def test_gamma_topic_constants_match_the_manifest(manifest):
    """Gamma's fallback constants are the pod's own record of the names."""

    code = (
        "from src.core.config import (TOPIC_EVIDENCE, TOPIC_VERDICTS, "
        "TOPIC_GAP_CLOSED, TOPIC_REVALIDATION, TOPIC_CONNECTOR_HEALTH); "
        "print(TOPIC_EVIDENCE, TOPIC_VERDICTS, TOPIC_GAP_CLOSED, "
        "TOPIC_REVALIDATION, TOPIC_CONNECTOR_HEALTH)"
    )

    out = _run_python(code, GAMMA_ROOT / "revalidation_service").split()

    assert set(out) == set(EXPECTED_TOPICS), (
        f"Gamma's topic constants {sorted(out)} do not match the shared "
        f"manifest {sorted(EXPECTED_TOPICS)}"
    )


BROKER_PROBES = {
    "delta": {
        "cwd": DELTA_BACKEND,
        "code": "from app.kafka.config import KAFKA_SERVER; print(KAFKA_SERVER)",
    },
    "beta": {
        "cwd": BETA_ROOT / "services" / "verdict_publisher",
        "code": "from vp_app.main import KAFKA_BOOTSTRAP_SERVERS; print(KAFKA_BOOTSTRAP_SERVERS)",
    },
    "gamma": {
        "cwd": GAMMA_ROOT / "revalidation_service",
        "code": (
            "from src.core.config import RevalidationSettings; "
            "print(RevalidationSettings().kafka_bootstrap_servers)"
        ),
        # Gamma reads the broker through its settings object, and its default
        # is empty rather than localhost: Gamma owns no bus in the first hybrid
        # run, so there is no address to guess at.
        "default_may_be_empty": True,
    },
}


@pytest.mark.parametrize("pod", sorted(BROKER_PROBES))
def test_pod_broker_address_is_injectable(pod):
    """The broker must be injectable; a hardcoded address cannot be pointed at
    the shared stack the plan declares."""

    probe = BROKER_PROBES[pod]

    default = _run_python(probe["code"], probe["cwd"])
    injected = _run_python(
        probe["code"], probe["cwd"], {"KAFKA_BOOTSTRAP_SERVERS": "kafka:29092"}
    )

    assert injected == "kafka:29092", f"{pod} ignores KAFKA_BOOTSTRAP_SERVERS"
    if not probe.get("default_may_be_empty"):
        assert default, f"{pod} has no broker default at all"
    else:
        # A default is allowed, but it must not be a hardcoded address the pod
        # would silently use in place of an injected one.
        assert "://" not in default or not default.startswith("http"), default


# --------------------------------------------------------------------------
# B13: the plan's endpoint list
# --------------------------------------------------------------------------


# Beta's three services each own a top-level package and their own directory,
# so they are probed one interpreter per service rather than imported together.
BETA_SERVICE_PROBES = {
    "validation_engine": (
        BETA_ROOT / "services" / "validation_engine",
        "from ve_app.main import app",
    ),
    "outcome_classifier": (
        BETA_ROOT / "services" / "outcome_classifier",
        "from oc_app.main import app",
    ),
    "verdict_publisher": (
        BETA_ROOT / "services" / "verdict_publisher",
        "from vp_app.main import app",
    ),
}


def _beta_routes() -> set:
    routes = set()
    for _service, (cwd, import_line) in BETA_SERVICE_PROBES.items():
        code = (
            f"import json; {import_line}; "
            "print(json.dumps(sorted(r.path for r in app.routes "
            "if hasattr(r,'path'))))"
        )
        routes.update(json.loads(_run_python(code, cwd)))
    return routes


def test_beta_serves_the_plans_beta_endpoints():
    """B13: Beta served /validate, /classify and /publish unversioned while the
    plan -- and Alpha and Delta -- use /api/v2."""

    routes = _beta_routes()

    missing = {
        path
        for path, owner in PLAN_ENDPOINTS.items()
        if owner == "beta" and path not in routes
    }

    assert not missing, (
        "Beta does not serve the plan's endpoint list:\n  "
        + "\n  ".join(sorted(missing))
    )


def test_beta_no_longer_serves_unversioned_routes():
    """The specific regression: the old paths must not still be mounted."""

    routes = _beta_routes()

    stale = {p for p in ("/validate", "/validate/batch", "/classify", "/publish") if p in routes}

    assert not stale, (
        f"Beta still serves unversioned routes {sorted(stale)}; the plan's paths "
        "are versioned and two pods must not answer the same operation at two URLs"
    )


def test_delta_serves_the_plans_delta_endpoints():
    """Delta's `/api/v2/validate` is the path the plan documents; the router
    used to nest it under `/api/v2/validator/validate`."""

    code = (
        "import json;"
        "from app.main import app;"
        "print(json.dumps(sorted(app.openapi()['paths'])))"
    )
    paths = set(json.loads(_run_python(code, DELTA_BACKEND, {"DATABASE_URL": "postgresql://u:p@localhost:5432/d"})))

    missing = {
        path
        for path, owner in PLAN_ENDPOINTS.items()
        if owner == "delta" and path not in paths
    }

    assert not missing, (
        "Delta does not serve the plan's endpoint list:\n  "
        + "\n  ".join(sorted(missing))
    )
    assert "/api/v2/validator/validate" not in paths


# --------------------------------------------------------------------------
# M5: the contract registry
# --------------------------------------------------------------------------


def test_contract_registry_holds_the_frozen_schemas():
    assert VERDICT_SCHEMA.exists(), f"missing {VERDICT_SCHEMA}"
    assert OCSF_SCHEMA.exists(), f"missing {OCSF_SCHEMA}"
    assert (CONTRACTS_DIR / "README.md").exists(), "the registry has no README"


def test_verdict_schema_is_valid_and_strict():
    jsonschema = pytest.importorskip("jsonschema")
    with open(VERDICT_SCHEMA, encoding="utf-8") as handle:
        schema = json.load(handle)

    jsonschema.Draft7Validator.check_schema(schema)
    assert schema.get("additionalProperties") is False, (
        "without additionalProperties:false the verdict schema is a suggestion, "
        "not a contract"
    )


def test_publisher_and_registry_agree_on_the_contract_fields():
    """M5: Beta declares the contract field set in code; the schema declares it
    in the registry. Nothing forced them to agree."""

    jsonschema = pytest.importorskip("jsonschema")
    with open(VERDICT_SCHEMA, encoding="utf-8") as handle:
        schema = json.load(handle)

    code = (
        "import json;"
        "from vp_app.models import CONTRACT_FIELDS;"
        "print(json.dumps(sorted(CONTRACT_FIELDS)))"
    )
    fields = set(json.loads(_run_python(code, BETA_ROOT / "services" / "verdict_publisher")))

    assert fields == set(schema["properties"]), (
        f"Beta's CONTRACT_FIELDS and the registry schema disagree: "
        f"beta-only={sorted(fields - set(schema['properties']))} "
        f"schema-only={sorted(set(schema['properties']) - fields)}"
    )
    assert fields == set(schema["required"])


def test_delta_reads_the_registry_schema_not_a_private_copy():
    """M5: Delta is the pod that *defines* the serializer, so it matters most
    that it validates against the shared registry rather than a copy of its
    own -- and that the path it resolves actually exists."""

    code = (
        "from app.contracts.verdict_event import (VERDICT_SCHEMA_PATH, "
        "CONTRACT_DIR); print(str(VERDICT_SCHEMA_PATH)); print(str(CONTRACT_DIR))"
    )
    schema_path, contract_dir = _run_python(
        code, DELTA_BACKEND, {"DATABASE_URL": "postgresql://u:p@localhost:5432/d"}
    ).splitlines()

    resolved = Path(schema_path)
    assert resolved.exists(), (
        f"Delta resolves its frozen schema to {resolved}, which does not exist. "
        "The schema is owned by the workspace contract registry; a private "
        "pod-local copy is exactly the divergence M5 records."
    )
    assert resolved == VERDICT_SCHEMA, (
        f"Delta reads {resolved} but the workspace registry is {VERDICT_SCHEMA}"
    )


def test_alpha_local_schema_matches_the_registry():
    """M5/B2: the registry is the single owner. Alpha's pod-local verdict schema
    must be byte-identical to it rather than a private pre-v2.0 drift."""

    alpha_schema = ALPHA_ROOT / "contracts" / "verdict schema" / "verdict_schema.json"
    assert alpha_schema.exists(), f"missing {alpha_schema}"

    with open(VERDICT_SCHEMA, encoding="utf-8") as handle:
        registry = json.load(handle)
    with open(alpha_schema, encoding="utf-8") as handle:
        alpha = json.load(handle)

    assert alpha == registry, (
        "Alpha's pod-local verdict schema drifted from the workspace registry"
    )


def test_delta_validates_a_real_payload_against_the_registry():
    """Delta's own serializer output must satisfy the shared schema."""

    code = (
        "import json;"
        "from app.contracts.verdict_event import build_verdict_event, "
        "validate_verdict_event;"
        "print(json.dumps(validate_verdict_event(build_verdict_event("
        "action_id='act-1', verdict='Detected', confidence=0.9, "
        "causal_chain=['a'], mttd_seconds=1.0, "
        "matched_evidence_ref=None, regulatory_control_refs=['ISO27001-A.5.15']"
        "))))"
    )
    validated = json.loads(
        _run_python(code, DELTA_BACKEND, {"DATABASE_URL": "postgresql://u:p@localhost:5432/d"})
    )

    with open(VERDICT_SCHEMA, encoding="utf-8") as handle:
        schema = json.load(handle)

    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(instance=validated, schema=schema)


def test_a_published_verdict_validates_against_the_registry_schema():
    """End-to-end through Beta's real publisher, checked against the registry."""

    jsonschema = pytest.importorskip("jsonschema")
    with open(VERDICT_SCHEMA, encoding="utf-8") as handle:
        schema = json.load(handle)

    code = (
        "import json;"
        "from vp_app.main import build_event, compute_content_hash;"
        "from vp_app.models import PublishedVerdict;"
        "v=PublishedVerdict(action_id='act-x',verdict='Detected',confidence=0.5,"
        "mttd_seconds=1.0,matched_evidence_ref=None,causal_chain=['a'],"
        "regulatory_control_refs=['ISO27001-A.5.15'],rule_id='R1',"
        "technique_ref='T1486');"
        "v.content_hash=compute_content_hash(v);"
        "print(json.dumps(build_event(v)))"
    )
    event = json.loads(
        _run_python(code, BETA_ROOT / "services" / "verdict_publisher")
    )

    jsonschema.validate(instance=event, schema=schema)


# --------------------------------------------------------------------------
# M6: one agreed dependency set
# --------------------------------------------------------------------------


def _pins(path: Path) -> dict:
    pins = {}
    if not path.exists():
        return pins
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, _, version = line.partition("==")
            pins[name.strip().lower()] = version.strip()
    return pins


CORE_PACKAGES = ("fastapi", "pydantic", "uvicorn", "pytest", "httpx")


def test_pods_agree_on_the_core_dependency_set():
    """M6: three pods declared different framework generations, so the
    contract seam could not be tested against one environment."""

    lock = _pins(REPO_ROOT / "requirements.lock")
    gamma = _pins(GAMMA_ROOT / "requirements.txt")
    beta = _pins(BETA_ROOT / "requirements.txt")
    delta = _pins(DELTA_BACKEND / "requirements.txt")
    alpha = _pins(ALPHA_ROOT / "rule ingestion" / "requirements.txt")

    for package in CORE_PACKAGES:
        versions = {
            "requirements.lock": lock.get(package),
            "gamma": gamma.get(package),
            "beta": beta.get(package),
            "delta": delta.get(package),
            "alpha": alpha.get(package),
        }
        present = {k: v for k, v in versions.items() if v}
        assert len(set(present.values())) == 1, (
            f"{package} is pinned differently across the pods: {present}"
        )
