# CyBreach Module 2 - Cross-Pod Contract Registry

This is the **single registry** of frozen cross-pod contracts, per plan Week 1
("Contracts Published: all frozen schemas and fixtures available in shared
repo"). Before this directory every pod kept its own copy of the schemas and
nothing read them cross-pod, so the copies could drift without any signal.

- `verdict-event/verdict.schema.json` - the frozen **v2.0 Verdict Event**
  (plan Section 9). Publisher of record: Delta. Beta emits the same eight
  fields. This is the file Beta's acceptance test and Delta's runtime
  validation both resolve.
- `ocsf_normalizer_schema.v1.json` - Gamma's OCSF Normalized Event output
  schema. Publisher: Gamma (`cybreach_pod_gamma/publish_contract.py`).

## Rules

1. A pod publishes its schema here. Pod-local copies are not the source of
   truth.
2. Every contract test loads schemas from **this** directory.
3. `tests/test_cross_pod_contract.py` (workspace root) asserts that the pods'
   resolved contract field set and topic names match this registry, so drift
   between a pod and the registry fails CI rather than surfacing at integration
   time.

## Related

- The message-bus topic manifest is a sibling of this directory:
  `../topics.yaml`. It is not a JSON Schema, so it lives at the root where the
  pods resolve it by relative path.
