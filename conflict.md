# CyBreach Module 2 - Cross-Pod Integration Conflicts

- **Date:** 2026-09-22
- **Scope:** Pod integration readiness review for Module 2 (The Validator)
- **Plan source:** `CyBreach_Module2_TheValidator_TextOnly.pdf` (authoritative spec: services, contracts, API surface, topics, security, credits)
- **Method:** Static compatibility review across all four pod repositories; each finding cites the files involved and the plan section it violates.

## Pod -> Directory Mapping (from plan Section 7)

| Pod | Plan ownership | Repository directory |
| --- | --- | --- |
| Alpha | Rule Ingestion + Connector Framework | `VALIDATOR/` |
| Beta | Validation Engine + Outcome Classifier | `cybreach-module2-pod-beta/` |
| Gamma | OCSF Normalizer + Re-Validation Service | `cybreach_pod_gamma/` |
| Delta | Verdict Publisher + Frontend Dashboard + API Gateway | `verdict-platform/` |

## Severity Legend

- **[BLOCKER]** - Integration cannot proceed (or produces wrong results) without a contract / behavior change first.
- **[MAJOR]** - Will require meaningful rework or cause runtime failure in a shared environment.
- **[MINOR]** - Cosmetic / hygiene issue that should be normalized but does not block integration.

---

## Section 1 - Blockers

### B1. No pod implements the plan's message-bus topics or naming
- **Violates:** plan Section 5 "Message Bus Topics" (`cybreach.evidence.v1`, `cybreach.verdicts.v2`, `cybreach.gap_closed.v2`, `cybreach.revalidation.v1`, `cybreach.connector.health.v1`).
- **Impact:** There is no single shared Kafka bus / topic contract. Beta's publisher is a mock HTTP endpoint (`cybreach-module2-pod-beta/services/verdict_publisher/vp_app/main.py`), Delta uses ad-hoc topics `verdict-events` / `evidence-events` (`verdict-platform/backend/app/kafka/config.py`). Nothing matches the plan topic names; Modules 3/4 cannot wire in.
- **Resolution:** Define one shared topic manifest per plan Section 5; all pods produce/consume only those names.

### B2. Three mutually incompatible "verdict" shapes, none matching the plan's v2.0 contract
- **Violates:** plan Section 9 "Verdict Event (publish, v2.0)": `action_id, verdict, confidence, causal_chain, mttd_seconds, matched_evidence_ref, regulatory_control_refs, content_hash`.
- **Shapes found:**
  1. `VALIDATOR/contracts/verdict schema/verdict_schema.json` - has `action_id, verdict, confidence, mttd_seconds, matched_evidence_ref, causal_chain, rule_id, technique_ref`; **missing** `regulatory_control_refs`, `content_hash`.
  2. Beta `cybreach-module2-pod-beta/services/validation_engine/ve_app/models.py:30-46` and `services/verdict_publisher/vp_app/models.py:6-14` - has `integrity_hash` instead of `content_hash`, **missing** `regulatory_control_refs`.
  3. Delta `verdict-platform/contracts/verdict-event/verdict.schema.json` - `rule_id, rule_name, verdict, event_data, verdict_hash, created_at`; structurally different (no `action_id`, no `confidence`, no `causal_chain`).
- **Impact:** No two pods even serialize a verdict the same way; a cross-pod verdict cannot be validated end-to-end.
- **Resolution:** One frozen `verdict.schema.json` per plan v2.0, owned by Delta (publisher); Alpha/Beta/Gamma build against it.

### B3. Delta publishes to Kafka a payload that violates even its own published contract
- **Violates:** plan Section 5 topic `cybreach.verdicts.v2`; Delta contract `verdict-platform/contracts/verdict-event/verdict.schema.json`.
- **Where:** `verdict-platform/backend/app/api/validator.py:54-61` publishes `{rule_id, rule_name, status, confidence, matched_fields, event}` - key `status` instead of `verdict`, `event` instead of `event_data`, and **missing required** `verdict_hash` and `created_at`. The corrected payload in `verdict-platform/backend/app/services/verdict_service.py:116-125` is yet a third shape (`id`, `supersedes`).
- **Impact:** Any consumer validating against the published schema rejects every event.
- **Resolution:** Publish exactly the contract schema; single serialization path reused by API, WebSocket, and Kafka.

### B4. Delta hardcodes the rule identity in validate
- **Violates:** plan Section 5 `POST /api/v2/validate`. 
- **Where:** `verdict-platform/backend/app/api/validator.py:32-34` - `rule_id=1`, `rule_name="Suspicious PowerShell"` regardless of request. Also `verdict-platform/backend/app/api/validator.py:55-56` repeats the hardcode in the Kafka payload.
- **Impact:** Verdicts cannot be joined to ingested rules across pods; all activity attributed to one fake rule.
- **Resolution:** Thread real `rule_id`/`rule_name` from the rule store through validation.

### B5. Confidence scale mismatch (0.0-1.0 vs 0-100)
- **Violates:** plan Section 2 / Section 3.3 "Confidence scores (0.0 to 1.0)"; plan Verdict Schema `confidence` 0.0-1.0.
- **Where:** Beta `cybreach-module2-pod-beta/services/verdict_publisher/vp_app/models.py:9` and `ve_app/models.py:37` constrain `0.0-1.0`; Delta returns `confidence: 95` in `verdict-platform/backend/app/services/validator_service.py:67`.
- **Impact:** Feeding Delta output into Beta's `/publish` fails pydantic validation (`le=1.0`).
- **Resolution:** Centralize confidence normalization at 0.0-1.0 in the shared schema.

### B6. `rule_id` type mismatch (string vs integer)
- **Violates:** plan Section 8 tech-stack/db schema `detection_rules (rule_id, ...)`; cross-pod traceability guarantee.
- **Where:** Alpha `VALIDATOR/rule ingestion/app/models/rule_models.py:114` (`ParsedRule.rule_id: str`); Beta `ve_app/models.py:41` (`rule_id: str`); Delta `verdict-platform/backend/app/models/rule.py:9`, `verdict.py:19` (`Integer`), and `/rules/{rule_id}` typed `int`.
- **Impact:** A rule produced by Alpha cannot be referenced by Delta's integer key; joins across pods break.
- **Resolution:** Freeze `rule_id` as one canonical type (string, content-hash based per plan) in the shared verdict/rule schema.

### B7. Service ownership conflict vs plan Section 7
- **Violates:** plan Section 7 team structure (Verdict Publisher + Dashboard + Gateway = Delta; Connector Framework = Alpha).
- **Where:** Beta ships a duplicate `services/verdict_publisher` (`cybreach-module2-pod-beta/services/verdict_publisher/`) - Delta's job; Beta also ships its own `BaseConnector`/connector framework (`cybreach-module2-pod-beta/services/validation_engine/ve_app/connectors.py`) and a local `DetectionRule` stand-in - Alpha's job. Delta ships `/rules`, `/connectors`, `/validator/validate` (`verdict-platform/backend/app/api/`) - Alpha's and Beta's jobs.
- **Impact:** Two implementations per responsibility with divergent behavior; overnight ownership ambiguity in integration.
- **Resolution:** Enforce one owner per service per plan Section 7; retire duplicate implementations (contract tests on the keeper).

### B8. Rule ingestion -> validation engine wiring is unimplemented
- **Violates:** plan Section 5 data flow step (2) "Rule Ingestion sends parsed detection rules to the Validation Engine via internal gRPC"; plan Section 9 Rule content hashing.
- **Where:** Alpha exposes `POST /api/v2/rules/ingest` (REST) and stores rules in an **in-memory dict** `VALIDATOR/rule ingestion/app/api/rules.py:78` (its own `detection_rules` migration `VALIDATOR/rule ingestion/alembic/versions/001_create_detection_rules.py` is never used). Beta has no HTTP/gRPC client to any rules API (`cybreach-module2-pod-beta/services/validation_engine/ve_app/main.py:25-37` defines a local `DetectionRule`).
- **Impact:** No rule delivery seam exists; nothing ships "parsed rules" to the engine at integration time.
- **Resolution:** Implement the plan's gRPC rule-delivery channel (or an agreed REST `GET /api/v2/rules` + content-hash lookup) and make Beta consume Alpha, not a local stand-in.

### B9. Delta's evidence consumer expects a shape that matches no producer and not the frozen EvidenceEvent contract
- **Violates:** plan Section 9 "Evidence Event (consume, v1.0)"; plan Section 2 frozen contract.
- **Where:** `verdict-platform/backend/app/consumers/consumer.py:45-46` reads `data["rule_id"]` and `data["event"]` from topic `evidence-events`. Frozen contract `cybreach-module2-pod-beta/contracts/evidence_event_schema.json` has only `action_id, correlation_key, technique_ref, target_asset_ref, expected_observable, timestamp` - no `rule_id`/`event`. No pod publishes to `evidence-events` at all.
- **Impact:** The consume path crashes with `KeyError` the moment a real Module-1 event arrives; also wrong owner (plan: Validation Engine consumes evidence, not the delta publisher).
- **Resolution:** Consume the frozen v1.0 EvidenceEvent on `cybreach.evidence.v1` in the Validation Engine; remove the mis-shaped delta consumer.

### B10. Kafka 9092 port/topology collision between Beta and Delta stacks
- **Violates:** plan Section 8 "Kafka/Redpanda (latest)" single message bus; plan Section 5.
- **Where:** Beta `cybreach-module2-pod-beta/docker-compose.yml:36-61` = KRaft broker+controller (no ZooKeeper); Delta `verdict-platform/docker-compose.yml:14-27` = ZooKeeper mode. **Both** bind host `9092` (`...- "9092:9092"`).
- **Impact:** The two compose stacks cannot run simultaneously; whichever starts second fails on port bind; incompatible topologies anyway.
- **Resolution:** One shared Kafka stack (recommended KRaft per beta) owned by the integration environment; all pods point at it.

### B11. Security model violated (plan mandates JWT + tenant scoping)
- **Violates:** plan Section 5 "Security Model"; plan API endpoint list "all ... (JWT)"; plan code-review checklist "No hardcoded secrets".
- **Where:** Alpha, Beta, Gamma expose **unauthenticated** APIs (no auth anywhere in `VALIDATOR/rule ingestion/app/`, `cybreach-module2-pod-beta/services/*/…/app/`, `cybreach_pod_gamma/...`). Delta has JWT but with hardcoded credentials `admin/admin123` (`verdict-platform/backend/app/api/auth.py:14-15`).
- **Impact:** Zero-trust posture (JWT everywhere, tenant-scoped) not met in 3 of 4 pods; hardcoded creds violate the review checklist.
- **Resolution:** Shared JWT middleware/issuer; enforce on every `/api/v2` route; credentials via env/vault only.

### B12. Incompatible `BaseConnector` implementations
- **Violates:** plan Section 3.2 Connector Framework (single pluggable framework, read-only `query()/poll()`).
- **Where:** Beta `cybreach-module2-pod-beta/services/validation_engine/ve_app/connectors.py:20` `BaseConnector.__init__(self, config: Dict[str, Any] | None)`; Alpha `VALIDATOR/rule ingestion/app/connector/base_connector.py:20,30` `BaseConnector(config: ConnectorConfig)` (pydantic) plus resilience layer (`ConnectorResilience`).
- **Impact:** Alpha's connectors (Splunk/Sentinel/Elastic/QRadar/CrowdStrike) cannot be dropped into Beta's engine; two frameworks diverge.
- **Resolution:** Alpha's connector framework is the keeper (it owns the 5 connectors); Beta's engine consumes it via the shared interface/registry - delete beta's `connectors.py`.

### B13. REST API surface diverges from plan's `/api/v2/*` design
- **Violates:** plan Section 5 "API Endpoints" (all `/api/v2/...` with JWT).
- **Where:** Alpha/Gamma use `/api/v2/*`; Beta uses bare `/validate`, `/classify`, `/publish`; Delta uses bare `/rules`, `/verdicts`, `/validator/validate`, `/connectors` and its gateway `verdict-platform/api-gateway/kong.yml` only routes bare paths (no `/api/v2` routes). `kong.yml:5` points upstream at `host.docker.internal:8033`, while all delta docs/frontend use port 8000 (`verdict-platform/frontend-dashboard/src/services/api.ts:4`) - internally contradictory.
- **Impact:** A unified gateway cannot front Alpha/Gamma (which use `/api/v2`) and Delta/Beta (bare) without route rework; delta's own gateway upstream contradicts its backend port.
- **Resolution:** Standardize all endpoints under `/api/v2/*`; gateway routes `/api/v2` to the relevant service; fix upstream to the real backend port.

---

## Section 2 - Major

### M1. Port collisions in a shared environment
- **Violates:** plan Section 7 local dev / Section 8 (one coherent environment).
- **Where:** 
  - `8000` claimed by: Delta backend (docs, `verdict-platform/frontend-dashboard/src/services/api.ts:4`, `websocketService.ts:10`), Kong (`verdict-platform/docker-compose.yml:46`), Gamma normalizer + revalidation (uvicorn default), Beta `vp_app` (default), Alpha docs (`VALIDATOR/rule ingestion/app/README.md:26`).
  - `8002` claimed by: Beta Validation Engine (`cybreach-module2-pod-beta/services/validation_engine/ve_app/main.py:9`, per plan local-dev example) vs Delta Kong (`verdict-platform/api-gateway/docker-compose.yml:14`).
  - `5173` claimed by: Gamma frontend (`cybreach_pod_gamma/frontend/vite.config.js`) and Delta frontend (`verdict-platform/frontend-dashboard/vite.config.ts`).
- **Impact:** Up to 5+ services cannot run together; frontends cannot serve simultaneously.
- **Resolution:** Port registry per service (see reconciliation table); gateway internal porting.

### M2. Verdict enum spelling: `NoData` vs `No Data`
- **Violates:** plan ambiguity itself - glossary says `NoData`, PRD 3.4 says `No Data`; must still be reconciled once.
- **Where:** Alpha/Beta use `NoData` (`VALIDATOR/contracts/verdict schema/verdict_schema.json:17`, beta models); Delta uses `"No Data"` (`verdict-platform/backend/app/services/revalidation_service.py:106`, `verdict-platform/frontend-dashboard/src/components/VerdictFilter.tsx:25`, docs `API_REFERENCE.md`).
- **Impact:** Cross-pod verdict matching/filtering breaks silently.
- **Resolution:** Pick one canonical token (recommend `NoData`), update doc + all four pods + schema enum.

### M3. Connector/registry APIs triplicated and incompatible
- **Violates:** plan Section 5 `POST /api/v2/connectors/register`, `GET /api/v2/connectors/health`.
- **Where:** Alpha `VALIDATOR/rule ingestion/app/api/connector_routes.py` (`/api/v2/connectors/*`); Delta `verdict-platform/backend/app/api/connectors*` (`/connectors`, `/connectors/{id}`); Gamma webhook connectors `cybreach_pod_gamma/ocsf_normalizer` (`/api/v2/webhook/connectors`). Alpha docs claim Gamma/Delta consume its health surface - neither does.
- **Impact:** Three registries, three health shapes; connector health cannot be aggregated.
- **Resolution:** Single registry per Alpha (owner of Connector Framework); others consume.

### M4. Rule-dependency integration is one-sided
- **Violates:** plan Week 7 Alpha "rule dependency tracker"; plan Section 5 validation_runs link.
- **Where:** Alpha exposes `POST /api/v2/rules/{rule_id}/dependencies` expecting Beta to record usage (`VALIDATOR/rule ingestion/app/api/rules.py:392`); Beta has no client that calls any rules API (local `DetectionRule` only).
- **Impact:** Dependency graph stays empty; nothing records which rule executed against which evidence.
- **Resolution:** Beta (engine) reports usage back to Alpha's dependency endpoint; covered by a contract test.

### M5. `shared_registry/v1/` contract registry does not exist
- **Violates:** plan Week 1 "Contracts Published: all frozen schemas and fixtures available in shared repo".
- **Where:** Gamma `cybreach_pod_gamma/publish_contract.py:7` writes to `shared_registry/v1/` - directory exists **nowhere** in the workspace; nothing reads from it.
- **Impact:** Cross-pod contract publishing mechanism is unwired; published file is an OCSF field-mapping sample, not a schema contract.
- **Resolution:** Stand up one shared registry (root `contracts/` or the `shared_registry/v1/` dir); every pod publishes frozen schemas there and contract tests load from it.

### M6. Mutual-exclusion dependency pins
- **Violates:** plan Section 8 (FastAPI 0.115+, Python 3.12 single env); plan Section 7 contract-test seam requires one testable environment.
- **Where:** `fastapi==0.115.6` (beta) vs `==0.141.1` (gamma) vs `==0.139.0` (delta) vs unpinned (alpha); `pydantic 2.10.3 / 2.13.4`; `uvicorn 0.32.1 / 0.52.2 / 0.49.0`; `pytest 8.3.4 / 9.1.1`.
- **Impact:** No single requirement set satisfies all pods; a shared CI/dev env is impossible.
- **Resolution:** Reconcile to one pinned set from plan Section 8 (FastAPI >=0.115.x line).

### M7. Delta backend cannot boot in a fresh checkout
- **Violates:** plan code-review checklist "No hardcoded secrets / error handling"; plan local-dev setup.
- **Where:** `verdict-platform/backend/app/database/database.py:10-18` calls `create_engine(os.getenv("DATABASE_URL"))`; no `.env` committed anywhere -> `create_engine(None)` raises at import. `verdict-platform/backend/requirements.txt` omits runtime deps used by the code: `kafka` (`app/kafka/producer.py:2`), `slowapi` (`app/main.py:18-20`), `jose` (`app/security/security.py:3`), alembic (`alembic.ini`) -> `ImportError` after `pip install`.
- **Impact:** Delta service is not runnable -> integration blocked on Delta side regardless of others.
- **Resolution:** Commit a `.env.example`, fail fast with clear message, and declare all runtime deps.

### M8. Credit / wallet logic from plan Section 9 unimplemented
- **Violates:** plan Section 9 "Credit Logic" (re-validation debits 1 credit, refund on inconclusive, mock wallet client); plan Week 9.
- **Where:** No reference to `credit`, `wallet`, or `debit` in any pod (`grep` across all Python files returns nothing).
- **Impact:** Re-validation cost accounting (a contract with Module 4) is entirely absent.
- **Resolution:** Add mock wallet client (default 100 credits) in Gamma's Re-Validation Service; debit/refund hooks per plan Section 9.

### M9. Internal gRPC plumbing absent
- **Violates:** plan Section 5 data flow steps (2),(5),(6),(7) (gRPC between services).
- **Where:** All inter-service channels are REST or mock HTTP; no `.proto` files or gRPC servers found in any pod.
- **Impact:** The plan's internal transport contract is unbuilt; integration will fall back to unagreed REST.
- **Resolution:** Either implement gRPC per plan or explicitly re-scope internal calls to REST with a written contract (documented drift).

### M10. Duplicate rule-dependency tracker inside Alpha
- **Violates:** plan Week 7 single "rule dependency tracker".
- **Where:** `VALIDATOR/rule ingestion/app/services/rule_dependency_tracker.py` (in-process) vs `VALIDATOR/rule ingestion/Rule_Dependency_Tracker/app/main.py` (a **separate FastAPI app** with its own `/rules`, `/dependencies`, own DB). Two implementations, different APIs.
- **Impact:** Two dependency stores diverge; ambiguous which is canonical.
- **Resolution:** Keep one (recommend the in-process service + endpoint) and delete the duplicate app.

### M11. Causal-chain type mismatch
- **Violates:** plan Verdict Event v2.0 `causal_chain`; plan causal-chain reproducibility guarantee.
- **Where:** Beta `cybreach-module2-pod-beta/services/outcome_classifier/oc_app/models.py:19` `causal_chain: List[CausalStep]` (objects) vs Alpha schema `causal_chain: array of string` (`VALIDATOR/contracts/verdict schema/verdict_schema.json:41-47`); Beta's own cross-pod test manually flattens objects to strings (`cybreach-module2-pod-beta/services/verdict_publisher/tests/test_cross_pod_pipeline.py:72-77`).
- **Impact:** Fragile hand-rolled bridging that will break under real nested reasoning.
- **Resolution:** Define `causal_chain` shape once (recommend structured steps + serialization contract).

### M12. Verdict integrity hash duplicated with different names/coverage
- **Violates:** plan Section 9 `content_hash` (SHA-256); plan immutability guarantee.
- **Where:** Beta `integrity_hash` (`ve_app/models.py:43`, covers action_id/verdict/confidence/...); Delta `verdict_hash` (`verdict-platform/backend/app/models/verdict.py:27`, covers rule_id/rule_name/verdict/event_data); plan says `content_hash`. Verification endpoints disagree.
- **Impact:** Tamper-evidence schemes are incompatible; a consumer cannot verify a producer's hash.
- **Resolution:** One canonical `content_hash` field (SHA-256 hex, 64 chars) computed over the full plan v2.0 verdict payload.

---

## Section 3 - Minor

### m1. Health-check response shapes differ
- **Violates:** plan Section 7 local-dev "verify health via /health"; plan Section 5 connector health aggregation.
- **Where:** `{"status":"ok"}` (beta, delta) vs `{"status":"healthy"}` (alpha, gamma revalidation) vs `{"status":"ok","service":...}` (beta services).
- **Resolution:** Normalize to `{"status": "ok"}` + optional `service` field.

### m2. Duplicate `connectors` table + no-op migrations in Delta
- **Violates:** plan Section 8 DB schema single `connectors` table.
- **Where:** Delta alembic `cbf3cdf06b8f_add_connectors_table.py` and `dc17eb937333_add_connectors_table.py` are duplicate empty revisions; Gamma `cybreach_pod_gamma/ocsf_normalizer/migration/002_webhook_connector.sql:7` also creates `connectors` (different schema). Safe today (separate DBs) but a landmine if merged into one Postgres.
- **Resolution:** Deduplicate migrations; decide a single `connectors` DDL owner for merged DB.

### m3. Beta repo drift: Week1-Week11 snapshots
- **Violates:** plan Section 11 file structure (`services/` canonical).
- **Where:** `cybreach-module2-pod-beta/Week1/...` through `Week11/` duplicate `services/` content (`Week2/migrations` duplicates `migrations/`); `evidence_events` table (`cybreach-module2-pod-beta/migrations/versions/0001_create_validation_runs_and_evidence_events.py`) omits `target_asset_ref` and `expected_observable` from the frozen contract it claims to consume.
- **Resolution:** Delete week snapshots; fix evidence_events columns to match the frozen schema.

### m4. Gamma Docker/CI artifacts disabled
- **Violates:** plan Week 1 CI/CD + Docker configuration.
- **Where:** `cybreach_pod_gamma/Dockerfile.txt`, `.dockerignore.txt`, `.github/workflows/ci.yml.txt` (renamed `.txt`) - no buildable images or CI.
- **Resolution:** Restore extensions and wire a working pipeline.

### m5. Gamma test/requirement inconsistency
- **Where:** Gamma tests use `fastapi.testclient.TestClient` (needs `httpx`), but root `requirements.txt` pins `httpx2==2.10.0` (nonstandard pkg name); `revalidation_service/requirements.txt` lists both `httpx2` and `httpx`. README's root `pytest` flow will likely fail.
- **Resolution:** Pin the real `httpx` package consistently across gamma manifests.

### m6. Connector vendor enum casing inconsistency
- **Where:** `VALIDATOR/contracts/connector specification/connector_specification.json` has lowercase `"crowdstrike"` amid capitalized vendor values; delta connector docs use "Microsoft Sentinel"/"QRadar".
- **Resolution:** Normalize vendor identifiers (lowercase kebab) in the connector spec.

### m7. Credentials/secrets hygiene
- **Violates:** plan review checklist "No hardcoded secrets".
- **Where:** Hardcoded `admin/admin123` (`verdict-platform/backend/app/api/auth.py:14-15`, `docs/API_REFERENCE.md`); plaintext Postgres password `validator_dev_pw` (`cybreach-module2-pod-beta/docker-compose.yml:10`); `cybreach_pod_gamma/connectors.db` (SQLite) committed.
- **Resolution:** Env/vault for all secrets; gitignore runtime artifacts.

### m8. SSRF-adjacent ingest by design
- **Where:** `VALIDATOR/rule ingestion/app/api/rules.py` `clone_repo` clones arbitrary user-supplied URLs without allow-listing; also `verdict-platform/backend/app/api/validator.py:23-27` does `json.loads(rule_query)` with no error handling (500 on malformed input).
- **Resolution:** URL allow-list / domain policy; validate + 422 on bad input.

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
| Re-validation credits (M8) | Gamma | Mock wallet + debit/refund per plan Section 9 |
| Dependency pins (M6) | Integration env | Single reconciled requirements set |
| Ports (M1) | Integration env | Port registry; gateway internal ports |