# CyBreach Module 2 - Cross-Pod Contract Registry

This is the single registry of frozen cross-pod contracts, per plan Week 1
("Contracts Published: all frozen schemas and fixtures available in shared
repo"). Before this directory every pod kept its own copy of the schemas and
nothing read them cross-pod, so the copies could drift without any signal.

- `verdict-event/verdict.schema.json` - the frozen v2.0 Verdict Event
  (plan Section 9). Publisher of record: Delta. Beta emits the same eight
  fields. This is the file Beta's acceptance test and Delta's runtime
  validation both resolve.
- `ocsf_normalizer_schema.v1.json` - Gamma's OCSF Normalized Event output
  schema. Publisher: Gamma (`cybreach_pod_gamma/publish_contract.py`).
- `cybreach_service.proto` - the internal gRPC contract for Alpha/Beta/Gamma/
  Delta service-to-service calls. This file is the source of truth for the
  inter-pod RPC surface introduced to close M9.

## Rules

1. A pod publishes its schema here. Pod-local copies are not the source of
   truth.
2. Every contract test loads schemas from this directory.
3. `tests/test_cross_pod_contract.py` (workspace root) asserts that the pods'
   resolved contract field set and topic names match this registry, so drift
   between a pod and the registry fails CI rather than surfacing at integration
   time.
4. Any inter-pod service call must resolve to a contract in this registry.
   gRPC definitions live here alongside JSON schemas so there is a single
   contract source for both message-bus and RPC plumbing.

## Related

- The message-bus topic manifest is a sibling of this directory:
  `../topics.yaml`. It is not a JSON Schema, so it lives at the root where the
  pods resolve it by relative path.
- gRPC contracts are generated from `cybreach_service.proto` using
  `python -m grpc_tools.protoc -I./contracts --python_out=. --grpc_python_out=. ./contracts/cybreach_service.proto`.
