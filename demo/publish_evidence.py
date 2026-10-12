"""Publish one freshly generated evidence event and wait for the verdict it causes.

This is the demo's end-to-end step. A unique evidence event is generated at
runtime, a Sigma rule covering the same MITRE technique is generated and
ingested into Alpha, the event is put on `cybreach.evidence.v1`, Beta's consumer
picks it up, and the verdict Beta publishes to `cybreach.verdicts.v2` is printed
here. One command therefore demonstrates the whole cross-pod chain instead of
requiring a trip to Kafka UI to confirm anything happened.

Nothing is committed and nothing is static. The technique is chosen per run, the
rule and the evidence are built from it in the same run (Beta compares
technique_ref by exact equality, so they must agree), and the action_id is a
fresh UUID -- so repeated takes produce distinct content hashes on the topic.

The tenant is the shared run tenant (demo/.run/tenant), minted by
start-services.ps1 and read by every service. Run start-services.ps1 first, or
this will seed a rule and publish evidence under a tenant Beta is not serving.

No token is required to publish: the broker is PLAINTEXT and the evidence topic
is not JWT-gated. A service token is required to seed the rule into Alpha.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from kafka import KafkaConsumer, KafkaProducer, TopicPartition

DEMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_DIR))

import gendata  # noqa: E402  (path set above)

BOOTSTRAP = "localhost:9092"
EVIDENCE_TOPIC = "cybreach.evidence.v1"
VERDICT_TOPIC = "cybreach.verdicts.v2"
WAIT_SECONDS = 30

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
    """Re-derive content_hash from the seven frozen fields, as Delta does."""

    projected = {name: payload.get(name) for name in CONTRACT_FIELDS}
    digest = hashlib.sha256(
        json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest == payload.get("content_hash")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="do not ingest a matching rule first (expect NoData unless one exists)",
    )
    parser.add_argument("--technique", help="pin the MITRE technique for this run")
    args = parser.parse_args()

    gendata.load_env()
    tenant = gendata.run_tenant()
    secret = os.environ.get("SECRET_KEY", "")

    technique = args.technique
    if not args.no_seed:
        print(f"Seeding a generated rule for tenant {tenant}...")
        seeded = gendata.seed_rule(tenant=tenant, secret=secret, technique=technique)
        technique = seeded["technique"]
        for rule in seeded["rules"]:
            print(
                f"  rule {str(rule.get('rule_id'))[:16]}..  {rule.get('title')}  "
                f"{rule.get('mitre_techniques')}"
            )

    event, technique = gendata.make_evidence(technique)
    action_id = event["action_id"]
    print(f"\nGenerated evidence {action_id} (technique {technique}):")
    print(json.dumps(event, indent=2))

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
    print(f"\nWatching {VERDICT_TOPIC} from offset {start_offset}")

    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    metadata = producer.send(EVIDENCE_TOPIC, event).get(timeout=30)
    producer.flush()
    producer.close()
    print(
        f"Published {action_id} to {metadata.topic} "
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
            if payload.get("action_id") == action_id:
                verdict = payload
                break
        if verdict is None:
            time.sleep(0.5)

    reader.close()

    if verdict is None:
        print(f"No verdict for {action_id} within {WAIT_SECONDS}s.")
        print("Check: Beta running with VERDICT_PUBLISH_ENABLED=true, and")
        print("       B11_SERVICE_TENANT_ID set to this run's tenant (see demo-env.ps1).")
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
            "\nNote: verdict is not 'Detected' -- Beta did not find a rule with "
            f"technique {technique}\nfor tenant {tenant} (or could not reach Alpha)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
