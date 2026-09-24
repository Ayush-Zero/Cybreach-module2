# CyBreach Module 2 - Cross-Pod Integration Conflicts

- **Date:** 2026-09-22 (Original review) | **Updated:** 2026-09-24 (Post-audit status appended)
- **Scope:** Pod integration readiness review for Module 2 (The Validator)
- **Plan source:** `CyBreach_Module2_TheValidator_TextOnly.pdf` (authoritative spec: services, contracts, API surface, topics, security, credits)
- **Method:** Static compatibility review across all four pod repositories; each finding cites the files involved and the plan section it violates. On 2026-09-24 every pod was re-audited against its current HEAD and every conflict annotated with a live status (`PATCHED` / `PARTIAL` / `STILL PRESENT`).

## Pod -> Directory Mapping (from plan Section 7)

| Pod | Plan ownership | Repository directory |
| --- | --- | --- |
| Alpha | Rule Ingestion + Connector Framework | `VALIDATOR/` |
| Beta | Validation Engine + Outcome Classifier | `cybreach-module2-pod-beta/` |
| Gamma | OCSF Normalizer + Re-Validation Service | `cybreach_pod_gamma/` |
| Delta | Verdict Publisher + Frontend Dashboard + API Gateway | `cybreach_pod_delta/` |

## Severity Legend

- **[BLOCKER]** - Integration cannot proceed (or produces wrong results) without a contract / behavior change first.
- **[MAJOR]** - Will require meaningful rework or cause runtime failure in a shared environment.
- **[MINOR]** - Cosmetic / hygiene issue that should be normalized but does not block integration.

> **Post-audit status legend (added 2026-09-24):** under each conflict a `**Status**` line reports the live state.
> - `PATCHED` - resolved; shown with strikethrough so teams know it is done.
> - `PARTIAL` - some pod(s)/portion(s) fixed (strikethrough marks the fixed portion); remainder open.
> - `STILL PRESENT` - not touched; same state as the original review.

---

## Section 1 - Blockers

### B1. No pod implements the plan's message-bus topics or naming

- **Violates:** plan Section 5 "Message Bus Topics" (`cybreach.evidence.v1`, `cybreach.verdicts.v2`, `cybreach.gap_closed.v2`, `cybreach.revalidation.v1`, `cybreach.connector.health.v1`).
- **Impact:** There is no single shared Kafka bus / topic contract. Beta's publisher is a mock HTTP endpoint (`cybreach-module2-pod-beta/services/verdict_publisher/vp_app/main.py`), Delta uses ad-hoc topics `verdict-events` / `evidence-events` (`cybreach_pod_delta/backend/app/kafka/config.py`). Nothing matches the plan topic names; Modules 3/4 cannot wire in.
- **Resolution:** Define one shared topic manifest per plan Section 5; all pods produce/consume only those names.
- **Status (2026-09-24):** STILL PRESENT. No `cybreach.*` topic string exists in any pod's code (only in docs/spec + two Beta docstrings in `ve_app/ingestion.py`). Delta still publishes to `verdict-events` / consumes `evidence-events` (`cybreach_pod_delta/backend/app/kafka/producer.py:20,35,51`, `config.py:3`). Beta publisher is still a mock HTTP `POST /publish` that only prints.

### B2. Three mutually incompatible "verdict" shapes, none matching the plan's v2.0 contract

- **Violates:** plan Section 9 "Verdict Event (publish, v2.0)": `action_id, verdict, confidence, causal_chain, mttd_seconds, matched_evidence_ref, regulatory_control_refs, content_hash`.
- **Shapes found:**
  1. `VALIDATOR/contracts/verdict schema/verdict_schema.json` - has `action_id, verdict, confidence, mttd_seconds, matched_evidence_ref, causal_chain, rule_id, technique_ref`; **missing** `regulatory_control_refs`, `content_hash`.
  2. Beta `cybreach-module2-pod-beta/services/validation_engine/ve_app/models.py:30-46` and `services/verdict_publisher/vp_app/models.py:6-14` - has `integrity_hash` instead of `content_hash`, **missing** `regulatory_control_refs`.
  3. Delta `cybreach_pod_delta/contracts/verdict-event/verdict.schema.json` - `rule_id, rule_name, verdict, event_data, verdict_hash, created_at`; structurally different (no `action_id`, no `confidence`, no `causal_chain`).
- **Impact:** No two pods even serialize a verdict the same way; a cross-pod verdict cannot be validated end-to-end.
- **Resolution:** One frozen `verdict.schema.json` per plan v2.0, owned by Delta (publisher); Alpha/Beta/Gamma build against it.
- **Status (2026-09-24):** STILL PRESENT. All three shapes unchanged. Grep for `content_hash` / `regulatory_control_refs` across the entire workspace: 0 matches in code/schemas.

### B3. Delta publishes to Kafka a payload that violates even its own published contract

- **Violates:** plan Section 5 topic `cybreach.verdicts.v2`; Delta contract `cybreach_pod_delta/contracts/verdict-event/verdict.schema.json`.
- **Where:** `cybreach_pod_delta/backend/app/api/validator.py:54-61` publishes `{rule_id, rule_name, status, confidence, matched_fields, event}` - key `status` instead of `verdict`, `event` instead of `event_data`, and **missing required** `verdict_hash` and `created_at`. The corrected payload in `cybreach_pod_delta/backend/app/services/verdict_service.py:116-125` is yet a third shape (`id`, `supersedes`).
- **Impact:** Any consumer validating against the published schema rejects every event.
- **Resolution:** Publish exactly the contract schema; single serialization path reused by API, WebSocket, and Kafka.
- **Status (2026-09-24):** STILL PRESENT. `validator.py:54-61` and `verdict_service.py:116-125` unchanged; a third bespoke gap-closed payload also exists in `revalidation_service.py:130-144`.

### B4. Delta hardcodes the rule identity in validate

- **Violates:** plan Section 5 `POST /api/v2/validate`.
- **Where:** `cybreach_pod_delta/backend/app/api/validator.py:32-34` - `rule_id=1`, `rule_name="Suspicious PowerShell"` regardless of request. Also `cybreach_pod_delta/backend/app/api/validator.py:55-56` repeats the hardcode in the Kafka payload.
- **Impact:** Verdicts cannot be joined to ingested rules across pods; all activity attributed to one fake rule.
- **Resolution:** Thread real `rule_id`/`rule_name` from the rule store through validation.
- **Status (2026-09-24):** STILL PRESENT. Same hardcoded `rule_id=1` / `"Suspicious PowerShell"` at `validator.py:33-34` and `:55-56`.

### B5. Confidence scale mismatch (0.0-1.0 vs 0-100)

- **Violates:** plan Section 2 / Section 3.3 "Confidence scores (0.0 to 1.0)"; plan Verdict Schema `confidence` 0.0-1.0.
- **Where:** Beta `cybreach-module2-pod-beta/services/verdict_publisher/vp_app/models.py:9` and `ve_app/models.py:37` constrain `0.0-1.0`; Delta returns `confidence: 95` in `cybreach_pod_delta/backend/app/services/validator_service.py:67`.
- **Impact:** Feeding Delta output into Beta's `/publish` fails pydantic validation (`le=1.0`).
- **Resolution:** Centralize confidence normalization at 0.0-1.0 in the shared schema.
- **Status (2026-09-24):** STILL PRESENT. Beta still constrains `ge=0.0, le=1.0`; Delta still returns `confidence: 95` (`validator_service.py:67`).

### B6. `rule_id` type mismatch (string vs integer)

- **Violates:** plan Section 8 tech-stack/db schema `detection_rules (rule_id, ...)`; cross-pod traceability guarantee.
- **Where:** Alpha `VALIDATOR/rule ingestion/app/models/rule_models.py:114` (`ParsedRule.rule_id: str`); Beta `ve_app/models.py:41` (`rule_id: str`); Delta `cybreach_pod_delta/backend/app/models/rule.py:9`, `verdict.py:19` (`Integer`), and `/rules/{rule_id}` typed `int`.
- **Impact:** A rule produced by Alpha cannot be referenced by Delta's integer key; joins across pods break.
- **Resolution:** Freeze `rule_id` as one canonical type (string, content-hash based per plan) in the shared verdict/rule schema.
- **Status (2026-09-24):** STILL PRESENT. Alpha/Beta still `str`; Delta still `Integer` everywhere (`models/rule.py:9`, `models/verdict.py:19`, `rules.py:72,89,175,230,251`).

### B7. Service ownership conflict vs plan Section 7

- **Violates:** plan Section 7 team structure (Verdict Publisher + Dashboard + Gateway = Delta; Connector Framework = Alpha).
- **Where:** Beta ships a duplicate `services/verdict_publisher` (`cybreach-module2-pod-beta/services/verdict_publisher/`) - Delta's job; Beta also ships its own `BaseConnector`/connector framework (`cybreach-module2-pod-beta/services/validation_engine/ve_app/connectors.py`) and a local `DetectionRule` stand-in - Alpha's job. Delta ships `/rules`, `/connectors`, `/validator/validate` (`cybreach_pod_delta/backend/app/api/`) - Alpha's and Beta's jobs.
- **Impact:** Two implementations per responsibility with divergent behavior; overnight ownership ambiguity in integration.
- **Resolution:** Enforce one owner per service per plan Section 7; retire duplicate implementations (contract tests on the keeper).
- **Status (2026-09-24):** STILL PRESENT. No duplicate retired: Beta still ships `services/verdict_publisher/` (3 test files) + `ve_app/connectors.py` (imported by `rule_execution.py:8`); Delta still exposes `/rules`, `/connectors`, `/validator/validate`.

### B8. Rule ingestion -> validation engine wiring is unimplemented

- **Violates:** plan Section 5 data flow step (2) "Rule Ingestion sends parsed detection rules to the Validation Engine via internal gRPC"; plan Section 9 Rule content hashing.
- **Where:** Alpha exposes `POST /api/v2/rules/ingest` (REST) and stores rules in an **in-memory dict** `VALIDATOR/rule ingestion/app/api/rules.py:78` (its own `detection_rules` migration `VALIDATOR/rule ingestion/alembic/versions/001_create_detection_rules.py` is never used). Beta has no HTTP/gRPC client to any rules API (`cybreach-module2-pod-beta/services/validation_engine/ve_app/main.py:25-37` defines a local `DetectionRule`).
- **Impact:** No rule delivery seam exists; nothing ships "parsed rules" to the engine at integration time.
- **Resolution:** Implement the plan's gRPC rule-delivery channel (or an agreed REST `GET /api/v2/rules` + content-hash lookup) and make Beta consume Alpha, not a local stand-in.
- **Status (2026-09-24):** PARTIAL. In-memory dict + no `GET /api/v2/rules` list route + no gRPC still true. Improvement: Alpha's alembic `001_create_detection_rules.py` is now a real revision (driven by an offline-mode test in `tests/test_alembic_migrations.py`), but the service still never writes rules to the DB at runtime.

### B9. Delta's evidence consumer expects a shape that matches no producer and not the frozen EvidenceEvent contract

- **Violates:** plan Section 9 "Evidence Event (consume, v1.0)"; plan Section 2 frozen contract.
- **Where:** `cybreach_pod_delta/backend/app/consumers/consumer.py:45-46` reads `data["rule_id"]` and `data["event"]` from topic `evidence-events`. Frozen contract `cybreach-module2-pod-beta/contracts/evidence_event_schema.json` has only `action_id, correlation_key, technique_ref, target_asset_ref, expected_observable, timestamp` - no `rule_id`/`event`. No pod publishes to `evidence-events` at all.
- **Impact:** The consume path crashes with `KeyError` the moment a real Module-1 event arrives; also wrong owner (plan: Validation Engine consumes evidence, not the delta publisher).
- **Resolution:** Consume the frozen v1.0 EvidenceEvent on `cybreach.evidence.v1` in the Validation Engine; remove the mis-shaped delta consumer.
- **Status (2026-09-24):** STILL PRESENT. `consumers/consumer.py:43-47` unchanged; a second duplicate consumer `kafka/consumer.py:7-27` does the same; both read `rule_id`/`event` off `evidence-events`.

### B10. Kafka 9092 port/topology collision between Beta and Delta stacks

- **Violates:** plan Section 8 "Kafka/Redpanda (latest)" single message bus; plan Section 5.
- **Where:** Beta `cybreach-module2-pod-beta/docker-compose.yml:36-61` = KRaft broker+controller (no ZooKeeper); Delta `cybreach_pod_delta/docker-compose.yml:14-27` = ZooKeeper mode. **Both** bind host `9092` (`...- "9092:9092"`).
- **Impact:** The two compose stacks cannot run simultaneously; whichever starts second fails on port bind; incompatible topologies anyway.
- **Resolution:** One shared Kafka stack (recommended KRaft per beta) owned by the integration environment; all pods point at it.
- **Status (2026-09-24):** STILL PRESENT. Beta `docker-compose.yml:41` still `9092:9092` KRaft; Delta `docker-compose.yml:20-21` still ZooKeeper mode binding `9092:9092`.

### B11. Security model violated (plan mandates JWT + tenant scoping)

- **Violates:** plan Section 5 "Security Model"; plan API endpoint list "all ... (JWT)"; plan code-review checklist "No hardcoded secrets".
- **Where:** Alpha, Beta, Gamma expose **unauthenticated** APIs (no auth anywhere in `VALIDATOR/rule ingestion/app/`, `cybreach-module2-pod-beta/services/*/.../app/`, `cybreach_pod_gamma/...`). Delta has JWT but with hardcoded credentials `admin/admin123` (`cybreach_pod_delta/backend/app/api/auth.py:14-15`).
- **Impact:** Zero-trust posture (JWT everywhere, tenant-scoped) not met in 3 of 4 pods; hardcoded creds violate the review checklist.
- **Resolution:** Shared JWT middleware/issuer; enforce on every `/api/v2` route; credentials via env/vault only.
- **Status (2026-09-24):** STILL PRESENT. Alpha/Beta/Gamma remain fully unauthenticated (0 auth deps/middleware found); Delta still hardcodes `admin/admin123` (`auth.py:14-15`) and `SECRET_KEY = "cybreach_validator_secret_key"` (`security.py:9`). Gamma's only guarded route is `/api/v2/webhook/ingest` (per-connector HMAC, not shared JWT).

### B12. Incompatible `BaseConnector` implementations

- **Violates:** plan Section 3.2 Connector Framework (single pluggable framework, read-only `query()/poll()`).
- **Where:** Beta `cybreach-module2-pod-beta/services/validation_engine/ve_app/connectors.py:20` `BaseConnector.__init__(self, config: Dict[str, Any] | None)`; Alpha `VALIDATOR/rule ingestion/app/connector/base_connector.py:20,30` `BaseConnector(config: ConnectorConfig)` (pydantic) plus resilience layer (`ConnectorResilience`).
- **Impact:** Alpha's connectors (Splunk/Sentinel/Elastic/QRadar/CrowdStrike) cannot be dropped into Beta's engine; two frameworks diverge.
- **Resolution:** Alpha's connector framework is the keeper (it owns the 5 connectors); Beta's engine consumes it via the shared interface/registry - delete beta's `connectors.py`.
- **Status (2026-09-24):** STILL PRESENT. Alpha interface unchanged (pydantic `ConnectorConfig` + `ConnectorResilience`); Beta `ve_app/connectors.py` still exists and is required (`rule_execution.py:8` imports `BaseConnector` from it).

### B13. REST API surface diverges from plan's `/api/v2/*` design

- **Violates:** plan Section 5 "API Endpoints" (all `/api/v2/...` with JWT).
- **Where:** Alpha/Gamma use `/api/v2/*`; Beta uses bare `/validate`, `/classify`, `/publish`; Delta uses bare `/rules`, `/verdicts`, `/validator/validate`, `/connectors` and its gateway `cybreach_pod_delta/api-gateway/kong.yml` only routes bare paths (no `/api/v2` routes). `kong.yml:5` points upstream at `host.docker.internal:8033`, while all delta docs/frontend use port 8000 (`cybreach_pod_delta/frontend-dashboard/src/services/api.ts:4`) - internally contradictory.
- **Impact:** A unified gateway cannot front Alpha/Gamma (which use `/api/v2`) and Delta/Beta (bare) without route rework; delta's own gateway upstream contradicts its backend port.
- **Resolution:** Standardize all endpoints under `/api/v2/*`; gateway routes `/api/v2` to the relevant service; fix upstream to the real backend port.
- **Status (2026-09-24):** STILL PRESENT. Beta routes still bare (`/validate` `ve_app/main.py:188`, `/classify` `oc_app/main.py:46`, `/publish` `vp_app/main.py:43`); Delta routes still bare and `kong.yml:5` still `host.docker.internal:8033` while `frontend-dashboard/src/services/api.ts:4` uses `127.0.0.1:8000`.

---

## Section 2 - Major

### M1. Port collisions in a shared environment

- **Violates:** plan Section 7 local dev / Section 8 (one coherent environment).
- **Where:**
  - `8000` claimed by: Delta backend (docs, `cybreach_pod_delta/frontend-dashboard/src/services/api.ts:4`, `websocketService.ts:10`), Kong (`cybreach_pod_delta/docker-compose.yml:46`), Gamma normalizer + revalidation (uvicorn default), Beta `vp_app` (default), Alpha docs (`VALIDATOR/rule ingestion/app/README.md:26`).
  - `8002` claimed by: Beta Validation Engine (`cybreach-module2-pod-beta/services/validation_engine/ve_app/main.py:9`, per plan local-dev example) vs Delta Kong (`cybreach_pod_delta/api-gateway/docker-compose.yml:14`).
  - `5173` claimed by: Gamma frontend (`cybreach_pod_gamma/frontend/vite.config.js`) and Delta frontend (`cybreach_pod_delta/frontend-dashboard/vite.config.ts`).
- **Impact:** Up to 5+ services cannot run together; frontends cannot serve simultaneously.
- **Resolution:** Port registry per service (see reconciliation table); gateway internal porting.
- **Status (2026-09-24):** PARTIAL. Gamma moved its revalidation image to `8003` (`Dockerfile:10-12`, `schema_engine/Dockerfile`) but normalizer + revalidation still default to `8000` when run via uvicorn/README, and the frontend proxy still points at `8000` (`frontend/vite.config.js:10`). All other collisions unchanged. NEW: Beta Outcome Classifier also claims `8003` (`oc_app/main.py:5`) - now collides with Gamma's new 8003.

### M2. Verdict enum spelling: `NoData` vs `No Data`

- **Violates:** plan ambiguity itself - glossary says `NoData`, PRD 3.4 says `No Data`; must still be reconciled once.
- **Where:** Alpha/Beta use `NoData` (`VALIDATOR/contracts/verdict schema/verdict_schema.json:17`, beta models); Delta uses `"No Data"` (`cybreach_pod_delta/backend/app/services/revalidation_service.py:106`, `cybreach_pod_delta/frontend-dashboard/src/components/VerdictFilter.tsx:25`, docs `API_REFERENCE.md`).
- **Impact:** Cross-pod verdict matching/filtering breaks silently.
- **Resolution:** Pick one canonical token (recommend `NoData`), update doc + all four pods + schema enum.
- **Status (2026-09-24):** ~~Gamma: patched~~ (Gamma source has no `NoData`/`No Data` at all; it uses `IMPROVED/DEGRADED/UNCHANGED`). Cross-pod conflict REMAINS: Alpha/Beta `NoData` vs Delta `"No Data"` (`revalidation_service.py:106`, `VerdictFilter.tsx:25`, `API_REFERENCE.md`).

### M3. Connector/registry APIs triplicated and incompatible

- **Violates:** plan Section 5 `POST /api/v2/connectors/register`, `GET /api/v2/connectors/health`.
- **Where:** Alpha `VALIDATOR/rule ingestion/app/api/connector_routes.py` (`/api/v2/connectors/*`); Delta `cybreach_pod_delta/backend/app/api/connectors*` (`/connectors`, `/connectors/{id}`); Gamma webhook connectors `cybreach_pod_gamma/ocsf_normalizer` (`/api/v2/webhook/connectors`). Alpha docs claim Gamma/Delta consume its health surface - neither does.
- **Impact:** Three registries, three health shapes; connector health cannot be aggregated.
- **Resolution:** Single registry per Alpha (owner of Connector Framework); others consume.
- **Status (2026-09-24):** PARTIAL. Gamma consolidated webhook connector routes to one file (`ocsf_normalizer/src/main.py:384,411`), but the custom OCSF class-registry API still exists 3x (`app/routes/custom_ocsf.py`, `schema_engine/app/routes/custom_ocsf.py`, `ocsf_normalizer/src/main.py:124-224`), and the whole Gamma stack is duplicated under `schema_engine/`. Alpha + Delta registries unchanged.

### M4. Rule-dependency integration is one-sided

- **Violates:** plan Week 7 Alpha "rule dependency tracker"; plan Section 5 validation_runs link.
- **Where:** Alpha exposes `POST /api/v2/rules/{rule_id}/dependencies` expecting Beta to record usage (`VALIDATOR/rule ingestion/app/api/rules.py:392`); Beta has no client that calls any rules API (local `DetectionRule` only).
- **Impact:** Dependency graph stays empty; nothing records which rule executed against which evidence.
- **Resolution:** Beta (engine) reports usage back to Alpha's dependency endpoint; covered by a contract test.
- **Status (2026-09-24):** STILL PRESENT. Endpoint still at `rules.py:392`; no pod calls Alpha's rules/dependencies endpoints (grep across other pods: 0 hits).

### M5. `shared_registry/v1/` contract registry does not exist

- **Violates:** plan Week 1 "Contracts Published: all frozen schemas and fixtures available in shared repo".
- **Where:** Gamma `cybreach_pod_gamma/publish_contract.py:7` writes to `shared_registry/v1/` - directory exists **nowhere** in the workspace; nothing reads from it.
- **Impact:** Cross-pod contract publishing mechanism is unwired; published file is an OCSF field-mapping sample, not a schema contract.
- **Resolution:** Stand up one shared registry (root `contracts/` or the `shared_registry/v1/` dir); every pod publishes frozen schemas there and contract tests load from it.
- **Status (2026-09-24):** PARTIAL. ~~`shared_registry/v1/windows_auth.json` now exists in Gamma (tracked)~~. But `publish_contract.py` now writes to `contracts/ocsf_normalizer_schema.v1.json` instead, README still claims the old path, and nothing in any pod consumes `shared_registry/v1/` today.

### M6. Mutual-exclusion dependency pins

- **Violates:** plan Section 8 (FastAPI 0.115+, Python 3.12 single env); plan Section 7 contract-test seam requires one testable environment.
- **Where:** `fastapi==0.115.6` (beta) vs `==0.141.1` (gamma) vs `==0.139.0` (delta) vs unpinned (alpha); `pydantic 2.10.3 / 2.13.4`; `uvicorn 0.32.1 / 0.52.2 / 0.49.0`; `pytest 8.3.4 / 9.1.1`.
- **Impact:** No single requirement set satisfies all pods; a shared CI/dev env is impossible.
- **Resolution:** Reconcile to one pinned set from plan Section 8 (FastAPI >=0.115.x line).
- **Status (2026-09-24):** STILL PRESENT. Gamma still `fastapi==0.141.1, pydantic==2.13.4, uvicorn==0.52.2`; Delta still `fastapi==0.139.0` plus anomalous pins (`starlette==1.3.1`); Beta `0.115.6`; Alpha unpinned. No `contracts/requirements.lock` exists.

### M7. Delta backend cannot boot in a fresh checkout

- **Violates:** plan code-review checklist "No hardcoded secrets / error handling"; plan local-dev setup.
- **Where:** `cybreach_pod_delta/backend/app/database/database.py:10-18` calls `create_engine(os.getenv("DATABASE_URL"))`; no `.env` committed anywhere -> `create_engine(None)` raises at import. `cybreach_pod_delta/backend/requirements.txt` omits runtime deps used by the code: `kafka` (`app/kafka/producer.py:2`), `slowapi` (`app/main.py:18-20`), `jose` (`app/security/security.py:3`), alembic (`alembic.ini`) -> `ImportError` after `pip install`.
- **Impact:** Delta service is not runnable -> integration blocked on Delta side regardless of others.
- **Resolution:** Commit a `.env.example`, fail fast with clear message, and declare all runtime deps.
- **Status (2026-09-24):** STILL PRESENT. No `.env.example` in repo; `requirements.txt` still omits kafka/slowapi/jose/alembic; `backend/Dockerfile` is 0 bytes (empty) so Delta cannot be containerized either.

### M8. Credit / wallet logic from plan Section 9 unimplemented

- **Violates:** plan Section 9 "Credit Logic" (re-validation debits 1 credit, refund on inconclusive, mock wallet client); plan Week 9.
- **Where:** No reference to `credit`, `wallet`, or `debit` in any pod (`grep` across all Python files returns nothing).
- **Impact:** Re-validation cost accounting (a contract with Module 4) is entirely absent.
- **Resolution:** Add mock wallet client (default 100 credits) in Gamma's Re-Validation Service; debit/refund hooks per plan Section 9.
- **Status (2026-09-24):** PARTIAL. ~~Gamma added `revalidation_service/src/wallet.py` (`WalletClient(initial_balance=100)` with `debit()`/`refund()`)~~ - but it is **never imported/used**: `revalidate()` in `revalidation_service/src/main.py:65-83` performs no debit and has no refund path. No other pod has wallet code.

### M9. Internal gRPC plumbing absent

- **Violates:** plan Section 5 data flow steps (2),(5),(6),(7) (gRPC between services).
- **Where:** All inter-service channels are REST or mock HTTP; no `.proto` files or gRPC servers found in any pod.
- **Impact:** The plan's internal transport contract is unbuilt; integration will fall back to unagreed REST.
- **Resolution:** Either implement gRPC per plan or explicitly re-scope internal calls to REST with a written contract (documented drift).
- **Status (2026-09-24):** STILL PRESENT. Zero `.proto` files and zero `grpc`/`grpcio` references in any pod.

### M10. Duplicate rule-dependency tracker inside Alpha

- **Violates:** plan Week 7 single "rule dependency tracker".
- **Where:** `VALIDATOR/rule ingestion/app/services/rule_dependency_tracker.py` (in-process) vs `VALIDATOR/rule ingestion/Rule_Dependency_Tracker/app/main.py` (a **separate FastAPI app** with its own `/rules`, `/dependencies`, own DB). Two implementations, different APIs.
- **Impact:** Two dependency stores diverge; ambiguous which is canonical.
- **Resolution:** Keep one (recommend the in-process service + endpoint) and delete the duplicate app.
- **Status (2026-09-24):** STILL PRESENT. Both implementations still coexist (`app/services/rule_dependency_tracker.py` + `Rule_Dependency_Tracker/app/main.py` with own `/rules`,`/dependencies` + DB).

### M11. Causal-chain type mismatch

- **Violates:** plan Verdict Event v2.0 `causal_chain`; plan causal-chain reproducibility guarantee.
- **Where:** Beta `cybreach-module2-pod-beta/services/outcome_classifier/oc_app/models.py:19` `causal_chain: List[CausalStep]` (objects) vs Alpha schema `causal_chain: array of string` (`VALIDATOR/contracts/verdict schema/verdict_schema.json:41-47`); Beta's own cross-pod test manually flattens objects to strings (`cybreach-module2-pod-beta/services/verdict_publisher/tests/test_cross_pod_pipeline.py:72-77`).
- **Impact:** Fragile hand-rolled bridging that will break under real nested reasoning.
- **Resolution:** Define `causal_chain` shape once (recommend structured steps + serialization contract).
- **Status (2026-09-24):** STILL PRESENT. `oc_app/models.py:19` still `List[CausalStep]`; Alpha schema still `array of string`; the fragile bridge in `test_cross_pod_pipeline.py:72-77` is unchanged.

### M12. Verdict integrity hash duplicated with different names/coverage

- **Violates:** plan Section 9 `content_hash` (SHA-256); plan immutability guarantee.
- **Where:** Beta `integrity_hash` (`ve_app/models.py:43`, covers action_id/verdict/confidence/...); Delta `verdict_hash` (`cybreach_pod_delta/backend/app/models/verdict.py:27`, covers rule_id/rule_name/verdict/event_data); plan says `content_hash`. Verification endpoints disagree.
- **Impact:** Tamper-evidence schemes are incompatible; a consumer cannot verify a producer's hash.
- **Resolution:** One canonical `content_hash` field (SHA-256 hex, 64 chars) computed over the full plan v2.0 verdict payload.
- **Status (2026-09-24):** STILL PRESENT. Beta still `integrity_hash` (`ve_app/models.py:43`, `vp_app/models.py:15`, `verdict_integrity.py:45`); Delta still `verdict_hash` (`verdict.py:27`); `content_hash` appears nowhere in any pod.

---

## Section 3 - Minor

### m1. Health-check response shapes differ

- **Violates:** plan Section 7 local-dev "verify health via /health"; plan Section 5 connector health aggregation.
- **Where:** `{"status":"ok"}` (beta, delta) vs `{"status":"healthy"}` (alpha, gamma revalidation) vs `{"status":"ok","service":...}` (beta services).
- **Resolution:** Normalize to `{"status": "ok"}` + optional `service` field.
- **Status (2026-09-24):** PARTIAL. ~~Beta patched internally: all three Beta services now return the uniform `{"status":"ok","service":...}` (`ve_app/main.py:205`, `oc_app/main.py:83`, `vp_app/main.py:64-66`)~~. Cross-pod still divergent: Alpha `{"status":"healthy"}` (`app/main.py:102`), Gamma `{"status":"healthy"}` (`src/main.py:11`) / `{"status":"online"}` (`app/main.py:19-25`).

### m2. Duplicate `connectors` table + no-op migrations in Delta

- **Violates:** plan Section 8 DB schema single `connectors` table.
- **Where:** Delta alembic `cbf3cdf06b8f_add_connectors_table.py` and `dc17eb937333_add_connectors_table.py` are duplicate empty revisions; Gamma `cybreach_pod_gamma/ocsf_normalizer/migration/002_webhook_connector.sql:7` also creates `connectors` (different schema). Safe today (separate DBs) but a landmine if merged into one Postgres.
- **Resolution:** Deduplicate migrations; decide a single `connectors` DDL owner for merged DB.
- **Status (2026-09-24):** STILL PRESENT. Both empty pass-through revisions still present and chained (`cbf3cdf06b8f` -> `dc17eb937333` -> `cde517e5b5d6` -> `fa0be04e9958`); no DDL added. Gamma `002_webhook_connector.sql` unchanged.

### m3. Beta repo drift: Week1-Week11 snapshots

- **Violates:** plan Section 11 file structure (`services/` canonical).
- **Where:** `cybreach-module2-pod-beta/Week1/...` through `Week11/` duplicate `services/` content (`Week2/migrations` duplicates `migrations/`); `evidence_events` table (`cybreach-module2-pod-beta/migrations/versions/0001_create_validation_runs_and_evidence_events.py`) omits `target_asset_ref` and `expected_observable` from the frozen contract it claims to consume.
- **Resolution:** Delete week snapshots; fix evidence_events columns to match the frozen schema.
- **Status (2026-09-24):** STILL PRESENT. `Week1`-`Week11` dirs all still at top level; migration `0001_...:21-28` still omits `target_asset_ref`/`expected_observable` (model + frozen contract require them).

### m4. Gamma Docker/CI artifacts disabled

- **Violates:** plan Week 1 CI/CD + Docker configuration.
- **Where:** `cybreach_pod_gamma/Dockerfile.txt`, `.dockerignore.txt`, `.github/workflows/ci.yml.txt` (renamed `.txt`) - no buildable images or CI.
- **Resolution:** Restore extensions and wire a working pipeline.
- **Status (2026-09-24):** PARTIAL. ~~Root `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, and `schema_engine/` equivalents restored (tracked)~~. Still `.txt`/empty stubs in `ocsf_normalizer/` and `revalidation_service/` (`Dockerfile.txt`, `.dockerignore.txt`, `.github/workflows/ci.yml.txt` all 0 bytes).

### m5. Gamma test/requirement inconsistency

- **Where:** Gamma tests use `fastapi.testclient.TestClient` (needs `httpx`), but root `requirements.txt` pins `httpx2==2.10.0` (nonstandard pkg name); `revalidation_service/requirements.txt` lists both `httpx2` and `httpx`. README's root `pytest` flow will likely fail.
- **Resolution:** Pin the real `httpx` package consistently across gamma manifests.
- **Status (2026-09-24):** PARTIAL. ~~`revalidation_service/requirements.txt` fixed to only `httpx>=0.27.0`~~. Root `requirements.txt:5` and `ocsf_normalizer/requirements.txt:5` still pin `httpx2 == 2.10.0`; root CI installs `httpx2` then runs `pytest` against `ocsf_normalizer/tests` which need real `httpx` - CI would fail.

### m6. Connector vendor enum casing inconsistency

- **Where:** `VALIDATOR/contracts/connector specification/connector_specification.json` has lowercase `"crowdstrike"` amid capitalized vendor values; delta connector docs use "Microsoft Sentinel"/"QRadar".
- **Resolution:** Normalize vendor identifiers (lowercase kebab) in the connector spec.
- **Status (2026-09-24):** STILL PRESENT - and WORSE. Spec still `"crowdstrike"` lowercase amid capitalized values (`connector_specification.json:15-24`); runtime registration keys diverge again (`crowdstrike_logscale_connector.py:388` -> `crowdstrike_logscale`, `sentinel_connector.py:226` -> `sentinel`, `qradar_connector.py:415` -> `qradar`).

### m7. Credentials/secrets hygiene

- **Violates:** plan review checklist "No hardcoded secrets".
- **Where:** Hardcoded `admin/admin123` (`cybreach_pod_delta/backend/app/api/auth.py:14-15`, `docs/API_REFERENCE.md`); plaintext Postgres password `validator_dev_pw` (`cybreach-module2-pod-beta/docker-compose.yml:10`); `cybreach_pod_gamma/connectors.db` (SQLite) committed.
- **Resolution:** Env/vault for all secrets; gitignore runtime artifacts.
- **Status (2026-09-24):** ~~Alpha side clean~~ (Alpha added `app/connector/credential_manager.py` - env-driven Fernet encryption, no hardcoded secrets, `alembic.ini` leaves DB URL blank). REMAINS: Delta `admin/admin123` + hardcoded `SECRET_KEY` (`security.py:9`) + committed DB creds `postgres:vyom` (`backend/alembic.ini:89`); Beta `POSTGRES_PASSWORD: validator_dev_pw` (`docker-compose.yml:10`); Gamma `connectors.db` still committed and tracked.

### m8. SSRF-adjacent ingest by design

- **Where:** `VALIDATOR/rule ingestion/app/api/rules.py` `clone_repo` clones arbitrary user-supplied URLs without allow-listing; also `cybreach_pod_delta/backend/app/api/validator.py:23-27` does `json.loads(rule_query)` with no error handling (500 on malformed input).
- **Resolution:** URL allow-list / domain policy; validate + 422 on bad input.
- **Status (2026-09-24):** STILL PRESENT. Alpha `clone_repo` (`rules.py:107-136`) still clones any `http(s)` URL or local path with no allow-list; Delta `validator_service.py:10-12` still runs `json.loads(rule_query)` without try/except (duplicate call, produces HTTP 500 not 422).

---

## Section 4 - Per-Pod Conflict Status (Post-Audit, 2026-09-24)

Re-audit of each repository at its current HEAD. `PATCHED` = resolved; `PARTIAL` = partially addressed; `STILL PRESENT` = untouched. Newly discovered integration risks are listed per pod as `N-A#`/`N-B#`/`N-G#`/`N-D#`.

| Pod | Directory | B1-B13 | M1-M12 | m1-m8 | New conflicts |
| --- | --- | --- | --- | --- | --- |
| Alpha | `VALIDATOR/` | 12 STILL PRESENT (B3/B4/B9 = Delta-only) | 11 STILL PRESENT + 1 PARTIAL (B8) | 5 STILL PRESENT, 2 PATCHED | 5 (N-A1..N-A5) |
| Beta | `cybreach-module2-pod-beta/` | 13 STILL PRESENT | 11 STILL PRESENT + 1 PARTIAL (M1) | 6 STILL PRESENT, 1 PARTIAL (m1) | 4 (N-B1..N-B4) |
| Gamma | `cybreach_pod_gamma/` | B11 STILL PRESENT | 5 PARTIAL (M1,M3,M5,M8) | 3 STILL PRESENT, 3 PARTIAL (m1,m4,m5) | 8 (N-G1..N-G8) |
| Delta | `cybreach_pod_delta/` | 13 STILL PRESENT | 12 STILL PRESENT | 8 STILL PRESENT | 8 (N-D1..N-D8) |

### Pod Alpha - `VALIDATOR/`

**Patched / resolved:**

- ~~m7 (Alpha side): no hardcoded secrets; connector credentials encrypted with env-driven Fernet key~~ (`app/connector/credential_manager.py`); `alembic.ini` deliberately leaves DB URL blank.
- ~~B8 (Alembic half): `alembic/versions/001_create_detection_rules.py` is now a real revision~~ with an offline migration test, though the running service still uses the in-memory store.

**Still present from `conflict.md`:** B1, B2, B5, B6, B7, B8 (store part), B10, B11, B12, B13; M1, M2, M4, M5, M6, M9, M10, M11, M12; m1, m6, m8. (B3, B4, B9, M3, M7, m2, m3, m4, m5, m7-others are owned by other pods.)

**New conflicts (Alpha):**

- **N-A1 (MAJOR):** Vendor identifier triple-divergence. Spec enum `connector_specification.json:15-24` (`Splunk`, `Microsoft Sentinel`, `IBM QRadar`, `Elastic`, `crowdstrike`) vs runtime registration keys (`crowdstrike_logscale_connector.py:388`, `sentinel_connector.py:226`, `qradar_connector.py:415`) vs `config_validation.py:17`. A contract-validated connector would not match real registry keys.
- **N-A2 (MINOR):** Dead/duplicate model set `app/services/rule_models.py` (60 lines) defines `ParsedRule`/`RuleIngestRequest`/`SyntaxValidationReport` that nothing imports; `rule_id: Optional[str]` contradicts the canonical `app/models/rule_models.py`.
- **N-A3 (BLOCKER):** Zero cross-pod wiring effective. No pod calls Alpha's `POST /api/v2/rules/ingest`, `GET /api/v2/rules`, or `/{rule_id}/dependencies`; no `GET /api/v2/rules` list route exists (only `/search`).
- **N-A4 (MINOR):** Health shape still `{"status": "healthy"}` (`app/main.py:102`) instead of the normalized `{"status":"ok"}`.
- **N-A5 (BLOCKER):** `rule_id` still assigned as `parsed_dict.get("rule_id") or "UNKNOWN"` (`rules.py:180`) - not the plan's content-hash canonical id; `clone_repo` (m8) remains an unguarded SSRF surface (`rules.py:107-136`).

### Pod Beta - `cybreach-module2-pod-beta/`

**Patched / resolved:**

- ~~m1 (Beta side): all three services now return the uniform `{"status":"ok","service":...}`~~ (`ve_app/main.py:205`, `oc_app/main.py:83`, `vp_app/main.py:64-66`).

**Still present from `conflict.md`:** B1, B2, B5, B6, B7, B8, B10, B11, B12, B13; M1 (port 8002/8000), M2, M4, M6, M9, M11, M12; m3, m6(NA), m7. No verdict schema exists in `contracts/` (only `evidence_event_schema.json` + `CONSUMED_CONTRACTS.md`).

**New conflicts (Beta):**

- **N-B1 (BLOCKER - regression):** `services/validation_engine/ve_app/main.py:150-155` has a Python syntax error - an orphaned `def validate_evidence(` with no body followed by a redefinition. `ast.parse` fails; `ve_app.main` cannot be imported, breaking `ingestion.py:24`, `incremental_validation.py:11`, `tests/test_cross_pod_pipeline.py:3`, and the `/validate` endpoint.
- **N-B2 (MAJOR):** No deployable packaging. `docker-compose.yml` defines only infra (postgres/redis/kafka/kafka-ui); there are **zero** `Dockerfile`s in Beta and no app services defined.
- **N-B3 (MINOR):** Outcome Classifier claims port `8003` (`oc_app/main.py:5`) - not in the port registry and now collides with Gamma's revalidation image (`cybreach_pod_gamma/Dockerfile:10-12`).
- **N-B4 (MAJOR):** DB schema drift beyond the two evidence columns - `validation_runs` has no `regulatory_control_refs`/content-hash column, and `target_asset_ref`/`expected_observable` exist only in the Pydantic model + frozen JSON schema, not in the migration.

### Pod Gamma - `cybreach_pod_gamma/`

**Patched / resolved:**

- ~~M2 (Gamma side): no `NoData`/`No Data` anywhere in source; revalidation verdict enum is `IMPROVED`/`DEGRADED`/`UNCHANGED`~~ (`revalidation_service/src/core/contracts.py:52`).
- ~~M5: `shared_registry/v1/windows_auth.json` now exists and is tracked~~ (still unwired - see below).
- ~~M8: `revalidation_service/src/wallet.py` added with default 100 credits + debit/refund~~ (still not invoked - see below).
- ~~m4: root `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml` and `schema_engine/` equivalents restored~~ (sub-service dirs still `.txt` stubs).
- ~~m5: `revalidation_service/requirements.txt` fixed to real `httpx`~~ (root + `ocsf_normalizer` still `httpx2`).

**Still present / partially open from `conflict.md`:** B11 (all APIs unauth except webhook HMAC); M1 (default 8000 collision remains), M3 (class-registry triplicated + `schema_engine/` duplicate), M6, M9, M12; m1, m4 (sub-dirs), m5 (root+ocsf_normalizer), m7 (`connectors.db` committed, 32 KB, in git index).

**New conflicts (Gamma):**

- **N-G1 (BLOCKER):** Nested `schema_engine/` is a full duplicate pod (141 tracked files mirroring root `app/`/`src/`/`ocsf_normalizer/`/`revalidation_service/`/`contracts/`/`shared_registry/`). Same routes exist 2-3x; any fix must land in both or they drift.
- **N-G2 (MAJOR):** `frontend/node_modules/` is committed (2,267 tracked files) - massively bloats repo/CI.
- **N-G3 (MINOR):** README drift - still claims `publish_contract.py` writes to `shared_registry/v1/` and documents a removed scheduler (script now writes `contracts/`).
- **N-G4 (BLOCKER):** CI cannot pass - root installs `httpx2==2.10.0` then `pytest` runs `ocsf_normalizer/tests` needing real `httpx`; test paths duplicated across copies.
- **N-G5 (MAJOR):** Port plan inconsistent - Dockerfile runs revalidation on `8003` only, frontend proxies to `8000` (`frontend/vite.config.js:10`), README uses default 8000.
- **N-G6 (MINOR):** Empty `.dockerignore` files (0 B) at root and `schema_engine/` - image builds would copy `.git/` and `node_modules/`.
- **N-G7 (MINOR):** Odd artifacts: `app/__init__.py.py`, `app/models/__init__.py.py`, `alembic/versions/0001_create_custom_ocsf_classes_table.py.py`, `schema_engine/requirements.txt.txt` (0 B).
- **N-G8 (MINOR):** `.coverage` binaries committed at root and inside `schema_engine/`.

### Pod Delta - `cybreach_pod_delta/`

**Patched / resolved:** none. All 13 blockers, all 12 majors, and all 8 minors from `conflict.md` remain in the working tree (HEAD `c6e7d23`; only cosmetic commit `Fix PDF export layout` since the review).

**New conflicts (Delta):**

- **N-D1 (BLOCKER):** Kong topology broken end-to-end - upstream `host.docker.internal:8033` is bound by nothing (`kong.yml:5`); root compose maps Kong to host `8000` (collides with backend `8000`); `api-gateway/docker-compose.yml` maps host `8002`; frontend `api.ts:4` uses `127.0.0.1:8000`.
- **N-D2 (BLOCKER):** Alembic chain inconsistent - `963dcd789856_add_verdict_hash.py:25` operates on table `"verdicts"` while model `__tablename__` is `"verdict_events"`; initial `0cb22bf6e0a0` never creates `verdict_events` cleanly.
- **N-D3 (BLOCKER):** `backend/Dockerfile` is 0 bytes (empty) - backend cannot be containerized, compounding M7 boot + the 8033 gap.
- **N-D4 (MINOR):** `compare_rule` route (`rules.py:250-251`) has no auth dependency while every other `/rules` handler does.
- **N-D5 (MINOR):** Dead/duplicate code - unreachable duplicate 404 in `api/verdicts.py:62-68`; duplicate `json.loads` at `validator_service.py:10` and `:12`.
- **N-D6 (BLOCKER):** `backend/app/kafka/consumer.py:20` runs `for message in consumer:` at module import time (infinite loop that would hang any worker that imports it).
- **N-D7 (BLOCKER):** Committed DB credentials - `backend/alembic.ini:89` = `postgresql://postgres:vyom@localhost:5432/verdict_db`.
- **N-D8 (MINOR):** Anomalous pins (`fastapi==0.139.0`, `starlette==1.3.1`, `typing-inspection==0.4.2`) that may not resolve cleanly, on top of the missing runtime deps in M7.

---

## Reconciliation Owner Table (suggested)

| Conflict | Suggested owner | Action |
| --- | --- | --- |
| Verdict contract (B2, B3) | Delta (publisher) | Publish frozen v2.0 schema; all pods consume |
| Rule_id type (B6) | Alpha | Content-hash `rule_id` string; Delta adopts |
| Confidence scale (B5) | Delta + Beta | Normalize 0.0-1.0 in shared schema |
| Kafka bus + topics (B1, B10) | Integration env (Delta) | Single KRaft stack, plan topic names |
| gRPC rule delivery (B8) | Alpha + Beta | Shared contract + client |
| Connector framework (B12, M3) | Alpha | Keeper of connectors + registry; others consume |
| `/api/v2` surface + gateway (B13) | Delta + all | Standardize prefix; fix kong upstream/port |
| Auth/JWT (B11) | Delta | Provide shared JWT middleware; all pods adopt |
| Re-validation credits (M8) | Gamma | Wire the existing `WalletClient` into revalidate; add refund on inconclusive |
| Dependency pins (M6) | Integration env | Single reconciled requirements set |
| Ports (M1) | Integration env | Port registry; gateway internal ports |

## Priority Actions (from 2026-09-24 audit)

1. **Fix Beta N-B1 first** - `ve_app/main.py:150-155` syntax error blocks import of the whole Validation Engine.
2. **Stand up root `contracts/`** per plan Phase B - `verdict.v2.schema.json`, `evidence.v1.schema.json`, `topics.yaml`, `port-registry.md`; all pods consume root contracts, not pod-local copies.
3. **Shared JWT + env secrets** (B11, m7) - remove `admin/admin123`, hardcoded `SECRET_KEY`, `postgres:vyom` DB creds, Beta plaintext password; untrack Gamma `connectors.db`.
4. **Unify Kafka bus** (B1, B10, B9) - single KRaft stack + plan topic names; delete Delta's mis-shaped `evidence-events` consumers.
5. **Canonicalize verdict shape** (B2, B3, B5, B6, M11, M12) - Delta owns frozen v2.0; adopt content-hash `rule_id`, 0.0-1.0 confidence, single `content_hash`, one `causal_chain` shape, one `NoData` spelling.
6. **Ownership dedupe** (B7, B12, M3, M10, m2, m3, N-G1) - retire Beta duplicates, Alpha `Rule_Dependency_Tracker/app`, Gamma `schema_engine/` subtree (or pick canonical), Beta week snapshots, Delta no-op migrations.
7. **Wire seams** (B8, M4, M9) - rule-delivery channel Alpha->Beta; dependency reporting; gRPC or documented REST drift.
8. **Delta blocking fixes** - Kong topology (N-D1), Alembic `verdicts`/`verdict_events` (N-D2), empty Dockerfile (N-D3), consumer import loop (N-D6), env-based boot (M7), 422 on malformed input (m8).

