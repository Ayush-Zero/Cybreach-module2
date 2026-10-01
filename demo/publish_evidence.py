"""Publish one evidence event and wait for the verdict it causes.

This is the demo's end-to-end step. It puts a single event on
`cybreach.evidence.v1`, Beta's consumer picks it up, and the verdict Beta
publishes to `cybreach.verdicts.v2` is printed here. One command therefore
demonstrates the whole cross-pod chain instead of requiring a trip to Kafka UI
to confirm anything happened.

No token is required: the broker is PLAINTEXT and the evidence topic is not
JWT-gated. A Sigma rule must already be ingested into Alpha (see
`seed-rule.ps1`) or the verdict comes back `NoData` instead of `Detected`.

Re-recording is safe: nothing in the chain deduplicates. The broker is
append-only, Beta's consumer keeps no seen-set, and `vp_app` is stateless.
Republishing the same event simply writes another message. Change ACTION_ID
between takes if you want distinct content hashes on the topic.
"""

import hashlib
import json
import sys
import time

from kafka import KafkaConsumer, KafkaProducer, TopicPartition

BOOTSTRAP = "localhost:9092"
EVIDENCE_TOPIC = "cybreach.evidence.v1"
VERDICT_TOPIC = "cybreach.verdicts.v2"
WAIT_SECONDS = 30

# Bump the suffix per take so the topic shows distinct verdicts/hashes.
ACTION_ID = "act-demo-001"

# Must match a rule's mitre_techniques value EXACTLY.
#
# Alpha filters with `tech in r.mitre_techniques` and Beta compares with
# `rule.technique_ref != evidence.technique_ref`, so neither side does
# sub-technique matching: "T1059" will NOT match the fixture's "T1059.001"
# and the verdict comes back NoData. Rule 001 in the fixture directory is
# attack.t1059.001, which is what this references.
TECHNIQUE_REF = "T1059.001"

# These six fields are exactly `ve_app.models.EvidenceEvent`. Pydantic v2
# ignores unknown keys by default, but a stray field is a silent contract
# drift, so nothing extra is sent here.
EVENT = {
    "action_id": ACTION_ID,
    "correlation_key": "corr-demo-001",
    "technique_ref": TECHNIQUE_REF,
    "target_asset_ref": "web-01",
    "expected_observable": "powershell.exe spawned by services.exe",
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}

# The frozen v2.0 verdict contract, as asserted by the cross-pod contract test.
CONTRACT_FIELDS = (
    "action_id",
    "verdict",
    "confidence",
    "causal_chain",
    "mttd_seconds",
    "matched_evidence_ref",
    "regulatory_control_refs",
)


def verify_hash(payload):
    """Re-derive content_hash from the eight frozen fields, as Delta does."""
    projected = {name: payload.get(name) for name in CONTRACT_FIELDS}
    digest = hashlib.sha256(
        json.dumps(
            projected, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return digest == payload.get("content_hash")


def main():
    # Position the reader at the END of the verdict topic BEFORE publishing, so
    # only verdicts this run causes are read and no older message is reprinted.
    reader = KafkaConsumer(
        bootstrap_servers=BOOTSTRAP,
        auto_offset_reset="latest",
        consumer_timeout_ms=1000,
    )
    partition = TopicPartition(VERDICT_TOPIC, 0)
    reader.assign([partition])
    start_offset = reader.end_offsets([partition])[partition]
    print(f"Watching {VERDICT_TOPIC} from offset {start_offset}")

    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    metadata = producer.send(EVIDENCE_TOPIC, EVENT).get(timeout=30)
    producer.flush()
    producer.close()
    print(
        f"Published {ACTION_ID} to {metadata.topic} "
        f"[partition {metadata.partition}, offset {metadata.offset}]"
    )
    print(f"Waiting up to {WAIT_SECONDS}s for Beta to validate and publish...\n")

    reader.seek(partition, start_offset)
    deadline = time.time() + WAIT_SECONDS
    verdict = None

    while time.time() < deadline and verdict is None:
        for message in reader:
            try:
                payload = json.loads(message.value.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if payload.get("action_id") == ACTION_ID:
                verdict = payload
                break
        if verdict is None:
            time.sleep(0.5)

    reader.close()

    if verdict is None:
        print(f"No verdict for {ACTION_ID} within {WAIT_SECONDS}s.")
        print("Check: Beta running with VERDICT_PUBLISH_ENABLED=true, and")
        print("       B11_SERVICE_TENANT_ID set to a tenant with rules.")
        return 1

    print("=" * 62)
    print(f"VERDICT RECEIVED ON {VERDICT_TOPIC}")
    print("=" * 62)
    print(json.dumps(verdict, indent=2))

    extra = set(verdict) - set(CONTRACT_FIELDS) - {"content_hash"}
    print(f"\nfields outside the frozen contract : {extra or 'none'}")
    print(f"content_hash re-derives            : {verify_hash(verdict)}")

    if verdict.get("verdict") != "Detected":
        print(
            "\nNote: verdict is not 'Detected' -- either Alpha has no matching "
            "rule\n(run seed-rule.ps1 first) or Beta could not reach Alpha."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())