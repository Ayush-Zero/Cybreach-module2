"""Cross-pod contract check: Beta and Delta must derive the same content hash
for the same verdict event.

B2/B3: Beta and Delta each had their own serializer with different field
coverage and different field *names* (`integrity_hash` vs `content_hash`), so a
consumer could not verify a Beta-produced event using Delta's code -- and a
Beta event carrying `integrity_hash` would be rejected outright by Delta's
frozen schema (`additionalProperties: false`, `regulatory_control_refs`
required).

This module builds one event, hashes it with Beta's publisher, hashes it with
Delta's serializer, and asserts the two digests are identical.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Both pods' service roots, so their `app` / `ve_app` / `vp_app` packages
# resolve. Each pod keeps its own top-level package name, so both roots have to
# be importable at once.
BETA_ROOT = REPO_ROOT / "cybreach_pod_beta"
DELTA_BACKEND = REPO_ROOT / "cybreach_pod_delta" / "backend"

for path in (
    DELTA_BACKEND,
    BETA_ROOT / "services" / "verdict_publisher",
    BETA_ROOT / "services" / "validation_engine",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


CONTRACT_FIELDS = {
    "action_id",
    "verdict",
    "confidence",
    "causal_chain",
    "mttd_seconds",
    "matched_evidence_ref",
    "regulatory_control_refs",
    "content_hash",
}


@pytest.fixture(scope="module")
def event() -> dict:
    """One verdict event, expressed in the plan's v2.0 contract."""

    return {
        "action_id": "act-cross-pod-1",
        "verdict": "Detected",
        "confidence": 0.87,
        "causal_chain": [
            "Evidence event received: act-cross-pod-1",
            "Rule considered: DET-001",
        ],
        "mttd_seconds": 4.25,
        "matched_evidence_ref": "ev-1",
        "regulatory_control_refs": ["ISO27001-A.5.15", "NIST-800-53-AC-2"],
    }


class TestHashesAgree:
    def test_beta_and_delta_derive_the_same_digest(self, event):
        from vp_app.main import PublishedVerdict, build_event

        beta_event = build_event(
            PublishedVerdict(
                action_id=event["action_id"],
                verdict=event["verdict"],
                confidence=event["confidence"],
                causal_chain=event["causal_chain"],
                mttd_seconds=event["mttd_seconds"],
                matched_evidence_ref=event["matched_evidence_ref"],
                regulatory_control_refs=event["regulatory_control_refs"],
            )
        )

        expected = hashlib.sha256(
            json.dumps(
                event, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

        assert beta_event["content_hash"] == expected

    def test_delta_recomputes_the_beta_digest(self, event):
        from app.contracts.verdict_event import (
            compute_content_hash,
            validate_verdict_event,
        )
        from vp_app.main import PublishedVerdict, build_event

        beta_event = build_event(
            PublishedVerdict(
                action_id=event["action_id"],
                verdict=event["verdict"],
                confidence=event["confidence"],
                causal_chain=event["causal_chain"],
                mttd_seconds=event["mttd_seconds"],
                matched_evidence_ref=event["matched_evidence_ref"],
                regulatory_control_refs=event["regulatory_control_refs"],
            )
        )

        # Delta's own re-derivation, and its frozen-schema validation.
        assert compute_content_hash(beta_event) == beta_event["content_hash"]
        assert validate_verdict_event(beta_event) == beta_event

    def test_delta_verifies_a_beta_digest(self, event):
        from app.contracts.verdict_event import verify_content_hash
        from vp_app.main import PublishedVerdict, build_event

        beta_event = build_event(
            PublishedVerdict(
                action_id=event["action_id"],
                verdict=event["verdict"],
                confidence=event["confidence"],
                causal_chain=event["causal_chain"],
                mttd_seconds=event["mttd_seconds"],
                matched_evidence_ref=event["matched_evidence_ref"],
                regulatory_control_refs=event["regulatory_control_refs"],
            )
        )

        assert verify_content_hash(beta_event) is True


class TestEventShape:
    def test_beta_event_has_exactly_the_contract_fields(self, event):
        from vp_app.main import PublishedVerdict, build_event

        beta_event = build_event(
            PublishedVerdict(
                action_id=event["action_id"],
                verdict=event["verdict"],
                confidence=event["confidence"],
                causal_chain=event["causal_chain"],
                mttd_seconds=event["mttd_seconds"],
                matched_evidence_ref=event["matched_evidence_ref"],
                regulatory_control_refs=event["regulatory_control_refs"],
            )
        )

        assert set(beta_event) == CONTRACT_FIELDS

    def test_beta_event_passes_the_frozen_schema(self, event):
        """Delta's schema is strict; a Beta event must satisfy it unchanged."""

        from app.contracts.verdict_event import validate_verdict_event
        from vp_app.main import PublishedVerdict, build_event

        beta_event = build_event(
            PublishedVerdict(
                action_id=event["action_id"],
                verdict=event["verdict"],
                confidence=event["confidence"],
                causal_chain=event["causal_chain"],
                mttd_seconds=event["mttd_seconds"],
                matched_evidence_ref=event["matched_evidence_ref"],
                regulatory_control_refs=event["regulatory_control_refs"],
            )
        )

        validate_verdict_event(beta_event)

    def test_both_sides_agree_on_the_legacy_verdict_token(self):
        """M2: one spelling -- `NoData`."""

        from app.contracts.verdict_event import VERDICT_NODATA
        from ve_app.models import Verdict

        assert VERDICT_NODATA == "NoData"

        verdict = Verdict(
            action_id="a",
            verdict="NoData",
            confidence=0.0,
            rule_id="NONE",
            technique_ref="T1047",
        )

        assert verdict.verdict == VERDICT_NODATA

    def test_both_sides_normalise_legacy_spellings(self):
        """A legacy spelling must hash identically on both sides.

        Delta normalises aliases before hashing; if Beta did not, the same
        logical verdict would produce two different digests and Delta's
        `verify_content_hash` would reject Beta's event.
        """

        from app.contracts.verdict_event import (
            compute_content_hash as delta_hash,
            validate_verdict_event as delta_validate,
        )
        from vp_app.main import build_event
        from vp_app.models import PublishedVerdict

        for alias in ("No Data", "no data", "NODATA", "no_data"):
            beta_event = build_event(
                PublishedVerdict(
                    action_id="act-alias",
                    verdict=alias,
                    confidence=0.0,
                )
            )

            assert beta_event["verdict"] == "NoData", alias
            assert delta_hash(beta_event) == beta_event["content_hash"], alias
            delta_validate(beta_event)

    def test_an_unnormalised_alias_would_have_diverged(self):
        """Guards the regression this normalisation exists to prevent.

        Hashes the raw alias form directly; the result must differ from what
        either pod actually publishes, proving the normalisation is load-bearing
        rather than cosmetic.
        """

        from app.contracts.verdict_event import (
            compute_content_hash as delta_hash,
        )
        from vp_app.main import build_event
        from vp_app.models import PublishedVerdict

        published = build_event(
            PublishedVerdict(
                action_id="act-alias",
                verdict="No Data",
                confidence=0.0,
            )
        )

        raw_alias_hash = delta_hash(
            dict(published, verdict="No Data")
        )

        assert raw_alias_hash != published["content_hash"]
