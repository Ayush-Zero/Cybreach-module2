# CyBreach Module 2 - Cross-Pod Integration Conflicts

- **Date:** 2026-09-30 (re-verified against the pod working trees, after resolving Beta, Delta and Gamma)
- **Scope:** Pod integration readiness review for Module 2 (The Validator)
- **Plan source:** `CyBreach_Module2_TheValidator_TextOnly.pdf` (authoritative spec: services, contracts, API surface, topics, security, credits)
- **Method:** Static compatibility review across all four pod repositories; each finding cites the files involved and the plan section it violates.
- **Revision note (2026-09-29):** this file now lists **open work only**. Every conflict that was previously recorded as `PATCHED` was re-checked against the pod repositories and deleted here only where the code actually satisfies it. Four previously-`PATCHED` items did not survive re-verification and have been returned to the open list with the contradicting evidence: **B13** (`POST /api/v2/validate` does not exist - the route is still `/api/v2/validator/validate`), **m8** (the 422 conversion was never implemented; `MalformedRuleQuery` is raised and never caught), **M6** (Gamma's root manifest regressed to a loose pin set, and Delta's were never bumped to match), and Delta's "one payload for all transports" (true, but `dashboard_service.py:27` still joins a string hash against an integer - now **B6/N-D18**). Claims that verification could not substantiate were downgraded rather than removed.
- **Revision note (2026-09-30):** **Beta, Delta and Gamma were resolved** and their fully-satisfied entries are deleted below: **M2**, **M11**, **m4**, **m5**, **N-G3**, **N-D18**, **N-D19**. Identifiers are unchanged, so the deleted numbers are now gaps. **Alpha was deliberately left untouched** and every Alpha-owned conflict below is still open - several of them (**B6**, **m6**, **m8**, **M6**, **B8**) were partly resolvable in the other three pods and those halves are now recorded as closed, so the remaining text is the Alpha-side remainder only. Three entries shrank rather than disappeared, because only part of each is fixable without Alpha: **B6** (Delta conforms, Alpha does not), **m7** (Beta is clean, Delta's credentials are still in git history) and **m8** (Delta now returns 422, Alpha's `clone_repo` is still unguarded). One undeclared regression was also fixed: commit `962c112` added a `DATABASE_URL` guard in Delta that raised `NameError` on every import and broke collection of all 52 of its tests.

## Pod -> Directory Mapping (from plan Section 7)

| Pod | Plan ownership | Repository directory |
| --- | --- | --- |
| Alpha | Rule Ingestion + Connector Framework | `cybreach_pod_alpha/` |
| Beta | Validation Engine + Outcome Classifier | `cybreach_pod_beta/` |
| Gamma | OCSF Normalizer + Re-Validation Service | `cybreach_pod_gamma/` |
| Delta | Verdict Publisher + Frontend Dashboard + API Gateway | `cybreach_pod_delta/` |

## Severity Legend

- **[BLOCKER]** - Integration cannot proceed (or produces wrong results) without a contract / behavior change first.
- **[MAJOR]** - Will require meaningful rework or cause runtime failure in a shared environment.
- **[MINOR]** - Cosmetic / hygiene issue that should be normalized but does not block integration.

> **Status values used below:** `STILL PRESENT` - not addressed since the original review. `PARTIAL` - some portion fixed; the open remainder is stated explicitly. There is no `PATCHED` state, because anything fully resolved has been removed from this file.

---

## Section 1 - Blockers

### B1. No shared message bus is provisioned, and nothing consumes `cybreach.evidence.v1`

- **Violates:** plan Section 5 "Message Bus Topics" (`cybreach.evidence.v1`, `cybreach.verdicts.v2`, `cybreach.gap_closed.v2`, `cybreach.revalidation.v1`, `cybreach.connector.health.v1`).
- **Where:** All five topic names are now declared in two independent manifests that were written separately and agree only by hand - Delta `cybreach_pod_delta/backend/app/kafka/config.py:16-31` and Gamma `cybreach_pod_gamma/revalidation_service/src/core/config.py:18-32` (env-overridable). Beta produces `cybreach.evidence.v1` and `cybreach.verdicts.v2` through a real lazy Kafka producer (`cybreach_pod_beta/services/verdict_publisher/vp_app/main.py:37-38,50-76,155-156`). Delta's duplicate root `verdict-publisher/` service is deleted, so `verdict-events` no longer exists in code.
- **Impact:** The topic *names* now agree but there is no single bus behind them. **No pod subscribes to `cybreach.evidence.v1`** - Beta's `services/validation_engine/ingestion.py:30-80` replays a local JSON fixture file and never opens a `KafkaConsumer`, so the plan's first data-flow step has no implementation. No root `docker-compose.yml` exists anywhere in the workspace, so the plan's "one shared bus" has nothing to boot: the only composes are pod-local (`cybreach_pod_beta/docker-compose.yml`, `cybreach_pod_gamma/docker-compose.yml`, `cybreach_pod_delta/docker-compose.yml` - Kong only). The two hand-written topic manifests are a duplication risk of exactly the kind this conflict exists to prevent, and each pod still defaults its own broker address (Delta `app/kafka/config.py:12` `KAFKA_BOOTSTRAP_SERVERS` -> `localhost:9092`). Delta's own runbooks still document the deleted service: `docs/DEPLOYMENT_GUIDE.md:429,533,953,1015,1183` and `docs/OPERATIONS_RUNBOOK.md:431,481` still say `verdict-events`, and `DEPLOYMENT_GUIDE.md:71,441,913,925,965` still points at the deleted `verdict-publisher/`.
- **Resolution:** One shared topic manifest owned by the integration environment, one root infra compose (KRaft Kafka + PostgreSQL + Redis), and a real `cybreach.evidence.v1` consumer in Beta's Validation Engine.
- **Status:** PARTIAL. Names agreed and the duplicate publisher removed; the bus, the subscriber and the shared manifest do not exist.

### B2. Alpha's verdict contract is not the frozen v2.0 contract

- **Violates:** plan Section 9 "Verdict Event (publish, v2.0)": `action_id, verdict, confidence, causal_chain, mttd_seconds, matched_evidence_ref, regulatory_control_refs, content_hash`.
- **Where:** Delta owns the frozen contract and enforces it at runtime - `cybreach_pod_delta/contracts/verdict-event/verdict.schema.json:7-54` (8 properties, all 8 `required`, `additionalProperties: false`, `confidence` bounded 0.0-1.0), loaded and enforced on every publish by `backend/app/contracts/verdict_event.py:33-34,98-106` via `backend/app/kafka/producer.py:67`. Beta emits the same 8 fields under the same name (`content_hash`, not the old `integrity_hash`) - `services/verdict_publisher/vp_app/main.py:96,123-128` and `services/validation_engine/ve_app/models.py:50` - and the digest agreement is proven byte-identical at `services/validation_engine/tests/test_verdict_integrity.py:163-192`. **Alpha still ships the pre-v2.0 shape**: `cybreach_pod_alpha/contracts/verdict schema/verdict_schema.json:7-63` has 8 properties but only 5 `required` and **omits `regulatory_control_refs` and `content_hash` entirely**.
- **Impact:** Two of four pods can exchange a contract-valid verdict; Alpha's schema cannot accept one and cannot produce one, so a rule ingested from Alpha cannot be traced to a verdict that satisfies the frozen contract.
- **Resolution:** Alpha adopts the frozen v2.0 field list and adds a conformance test that validates a Delta- or Beta-produced event against it.
- **Status:** PARTIAL. Delta and Beta conform; Alpha does not.

### B6. `rule_id` type and derivation still disagree - Alpha never adopted the canonical id

- **Violates:** plan Section 8 tech-stack/db schema `detection_rules (rule_id, ...)`; the cross-pod traceability guarantee.
- **Where (closed in Delta):** Delta's verdict-side surface is string-keyed on the canonical content hash: `Rule.rule_id` is `String(64) unique` (`cybreach_pod_delta/backend/app/models/rule.py:14`), `Verdict.rule_id` is `String(64)` with a foreign key onto it (`app/models/verdict.py:43`), the response type is `str` (`app/schemas/verdict.py:13`), and both dashboard services declare `rule_id: string` (`frontend-dashboard/src/services/verdictService.ts:10`, `revalidationDashboardService.ts:8`). Both joins now agree: `app/services/causal_chain_service.py:24` and `app/services/dashboard_service.py:27` both join `Rule.rule_id == Verdict.rule_id`. `Rule.id` remains Delta's local surrogate key for its own `/rules` routes, which is correct - that is Delta's rule-management surface, not a cross-pod identity.
- **Where (still open - all of it is Alpha):** Alpha never adopted the canonical id at all: `cybreach_pod_alpha/rule ingestion/app/api/rules.py:180` assigns `rule_id=parsed_dict.get("rule_id") or "UNKNOWN"`, with the content hash written to a *separate* field at `:184`. Alpha's model types `rule_id` as a free-form required `str` up to 255 chars (`app/models/rule_models.py:114-119`), so nothing forces it to be the digest Beta and Delta now key on. `rules.py:78` also leaves `INGESTED_RULES` keyed by whatever Alpha decided, so Beta's client is handed a string no other pod computes.
- **Impact:** A rule produced by Alpha is keyed by a string Beta and Delta do not compute, so a rule ingested upstream cannot be traced to the verdict that Beta and Delta publish about it.
- **Resolution:** Freeze `rule_id` as the content-hash string in the shared schema; make Alpha assign the digest.
- **Status:** PARTIAL. Delta is fully conformant on both schema and joins; Alpha is untouched and remains the whole of the open remainder.

### B7. Service ownership conflict vs plan Section 7

- **Violates:** plan Section 7 team structure (Verdict Publisher + Dashboard + Gateway = Delta; Connector Framework = Alpha).
- **Where:** Beta ships a duplicate `services/verdict_publisher/` (3 test files, `cybreach_pod_beta/services/verdict_publisher/`) - Delta's job - and still ships its own `BaseConnector` framework at `services/validation_engine/ve_app/connectors.py`, imported by `rule_execution.py:8` and used at `:117,129-130`, plus a local `DetectionRule` stand-in (`ve_app/main.py:29-42`) - Alpha's job. Delta ships `/rules`, `/connectors`, `/validator/validate` (`cybreach_pod_delta/backend/app/api/`) - Alpha's and Beta's jobs.
- **Impact:** Two implementations per responsibility with divergent behavior; ownership is ambiguous at integration time.
- **Resolution:** Enforce one owner per service per plan Section 7; retire the duplicates (contract tests on the keeper).
- **Status:** STILL PRESENT. Nothing retired.

### B8. Rule ingestion -> validation engine wiring depends on Alpha process memory

- **Violates:** plan Section 5 data flow step (2) - "Rule Ingestion sends parsed detection rules to the Validation Engine via internal gRPC"; plan Section 9 rule content hashing.
- **Where:** Alpha exposes `POST /api/v2/rules/ingest` and `GET /api/v2/rules` (`cybreach_pod_alpha/rule ingestion/app/api/rules.py:21,221-224`) and Beta has a matching client and mapper (`cybreach_pod_beta/services/validation_engine/ve_app/main.py:46-73`, invoked at `:233` when a single request supplies no rules). But the store Alpha serves from is a plain module-level dict: `rule ingestion/app/api/rules.py:77-78` `INGESTED_RULES: Dict[str, ParsedRule] = {}`, mutated only at `:196`. No route in `app/api/` opens a DB session; the `detection_rules` table that Alpha's own migration creates is never read at runtime, and the same pattern holds for the versioning store (`rule_versioning.py:254`) and the dependency tracker (`rule_dependency_tracker.py:43`).
- **Impact:** Any Alpha restart silently empties the rule set and Beta degrades to `NoData` for every evidence event. Alpha's own test at `tests/test_alembic_migrations.py:55,59` proves the migration runs offline, which makes the in-memory divergence easy to miss. Two further breaks in the seam: the mapper coerces `detection_logic` with `str()` (`ve_app/main.py:60-68`) while Alpha types it `Union[Dict[str, Any], str]` (`app/models/rule_models.py:157`) - for a Sigma rule that turns a rule body into a Python-repr string, not a query; and Alpha's Dockerfile and README bind the service to **8000** (`rule ingestion/Dockerfile:9,11`, `app/README.md:26,39,75,105`) while Beta's client defaults to `http://127.0.0.1:8001/api/v2/rules` (`ve_app/main.py:47`) and the port registry assigns Alpha 8001 (`port-registery.md:13`), so the client cannot reach a default Alpha build. Batch validation still bypasses Alpha entirely (`ve_app/main.py:237-244` uses `req.rules` only, with no fetch and no fallback), the `DetectionRule` stand-in remains, fetch failures propagate with no fallback, and no gRPC seam exists.
- **Resolution:** Serve the collection route from the existing `detection_rules` table; reconcile the port; make Beta use Alpha for batch and caller-supplied flows; stop string-coercing `detection_logic`; define fetch-failure behavior; retire the stand-in or document the drift.
- **Status:** PARTIAL. The route and client exist and match on field names; persistence, the port, the coercion and the batch path do not.

### B10. No single Kafka stack is provisioned for the hybrid run

- **Violates:** plan Section 8 "Kafka/Redpanda (latest)" as a single message bus; plan Section 5.
- **Where:** Delta's ZooKeeper + Kafka services were removed from its compose, so `9092` is no longer contested and Beta's KRaft broker is the only one declared. But nothing owns the broker: there is no root `docker-compose.yml` in the workspace, and both `cybreach_pod_delta/backend/app/kafka/config.py:12` and Gamma's config default to a local address rather than an injected one for the shared environment.
- **Impact:** The port collision is gone but the plan's "one shared bus" is still unprovisioned, so B1's empty evidence seam cannot be closed by configuration alone.
- **Resolution:** One shared KRaft stack owned by the integration environment; all pods point at it by injected URL.
- **Status:** PARTIAL. Collision resolved; the stack does not exist.

### B11. Security model: Alpha/Beta/Gamma unauthenticated, and tenant scoping absent everywhere

- **Violates:** plan Section 5 "Security Model"; plan API endpoint list "all ... (JWT)"; plan code-review checklist "No hardcoded secrets".
- **Where:** Delta enforces JWT on every route outside a 3-entry public allowlist (`POST /api/v2/auth/login`, `GET /`, `GET /health`), with a 3-entry allowlist declared in `backend/tests/test_auth_coverage.py:33-38` and enforced on the assembled OpenAPI schema; secrets are env-only with no fallback (`app/api/auth.py:21-22,33-40`, `app/security/security.py:18,27-36`); the verdict WebSocket verifies its token before joining the broadcast set (`app/main.py:90-98`). **Alpha, Beta and Gamma remain fully unauthenticated** - zero `Depends(...)`, `add_middleware`, `OAuth2`, `APIKeyHeader` or `Authorization` references in any of the three. Alpha's whole surface is open (`cybreach_pod_alpha/rule ingestion/app/main.py:73-102`), as is all of Beta's (`/validate`, `/validate/batch`, `/classify`, `/publish`) and Gamma's, with one exception: Gamma's `/api/v2/webhook/ingest` is guarded by a per-connector shared secret or HMAC-SHA256 with a constant-time compare (`cybreach_pod_gamma/ocsf_normalizer/src/main.py:236-289`, `webhook/security.py:48-65`).
- **Impact (two distinct gaps):**
  1. **No tenant scoping anywhere in the workspace.** There is no `tenant_id` column on any table in any pod and no tenant filtering on any query, so the plan's tenant-scoping requirement is entirely unimplemented - including in Delta, whose authentication half is otherwise done. This is a schema migration plus per-query scoping, not a route guard.
  2. **Gamma's connector self-registration is open.** `POST /api/v2/webhook/connectors` (`ocsf_normalizer/src/main.py:393-417`) is unauthenticated, so any caller can register a connector with a self-chosen secret and then ingest through it - the HMAC guard on `ingest` is only as strong as an unauthenticated registration endpoint.
- **Resolution:** Shared JWT middleware/issuer enforced on every `/api/v2` route in all four pods; authenticate Gamma's connector registration; add `tenant_id` and per-query scoping as a migration, not a guard.
- **Status:** PARTIAL. Delta's route-level authentication is done and test-gated; tenant scoping is untouched in every pod, and Alpha/Beta/Gamma have no authentication at all.

### B12. Incompatible `BaseConnector` implementations

- **Violates:** plan Section 3.2 Connector Framework (single pluggable framework, read-only `query()/poll()`).
- **Where:** Beta `cybreach_pod_beta/services/validation_engine/ve_app/connectors.py:23` declares `BaseConnector.__init__(self, config: Dict[str, Any] | None)`; Alpha `cybreach_pod_alpha/rule ingestion/app/connector/base_connector.py:12-20` declares a pydantic `ConnectorConfig` plus a `ConnectorResilience` layer (`app/connector/resilience.py:13`, wired at `base_connector.py:41`).
- **Impact:** Alpha's connectors (Splunk/Sentinel/Elastic/QRadar/CrowdStrike) cannot be dropped into Beta's engine; two frameworks diverge.
- **Resolution:** Alpha's framework is the keeper; Beta's engine consumes it via the shared registry - delete Beta's `connectors.py`.
- **Status:** STILL PRESENT. Alpha's interface is unchanged; Beta's `ve_app/connectors.py` still exists and is a hard import for `rule_execution.py`.

### B13. REST API surface diverges from the plan's `/api/v2/*` design

- **Violates:** plan Section 5 "API Endpoints" (all `/api/v2/...` with JWT).
- **Where:** Delta mounts every router under `/api/v2` (`cybreach_pod_delta/backend/app/main.py:66-73`) and Kong routes a single `/api/v2` path, with the upstream repointed to the backend's real port `8000` (`api-gateway/kong.yml:11`); the duplicate gateway compose is deleted, so one registry-consistent gateway on `8010`/`8011` remains. Alpha and Gamma also use `/api/v2` prefixes. **Two things are still wrong.** First, `POST /api/v2/validate` does **not** exist: `backend/app/api/validator.py:18` still sets `prefix="/validator"` and `:24` declares `@router.post("/validate")`, so the route is `POST /api/v2/validator/validate`. A previous revision of this file recorded the nesting as removed; it was not, and no `/api/v2/validate` string exists anywhere in the repository. Second, Beta's routes are unversioned - `ve_app/main.py:231,237,247`, `oc_app/main.py:50,85`, `vp_app/main.py:131,167` - with no `APIRouter` or `include_router` anywhere in Beta.
- **Impact:** A single gateway still cannot front Delta (`/api/v2`) and Beta (bare) without route rework, and the plan's documented validate endpoint is not the one implemented.
- **Resolution:** Version all of Beta's routes under `/api/v2`; flatten `validator_router` to `POST /api/v2/validate`; add a contract test asserting the plan's endpoint list resolves.
- **Status:** PARTIAL. Delta's prefixes, Kong's upstream and the single gateway are correct; the validate path is still nested and Beta is still bare.

---

## Section 2 - Major

### M1. Port assignments in the registry do not match what the pods bind

- **Violates:** plan Section 7 local dev / Section 8 (one coherent environment).
- **Where:** the registry (`port-registery.md:13-16,26-28`) assigns Alpha 8001, Beta 8002/8003/8004, Delta backend 8000 and Kong 8010/8011; Gamma binds 8005/8006 with its frontend on 5174. Beta now binds all three of its ports explicitly with env overrides (`ve_app/main.py:260` `VE_PORT`->8002, `oc_app/main.py:99` `OC_PORT`->8003, `vp_app/main.py:42,180` `VP_PORT`->8004) and only one gateway compose remains, so Beta and Delta no longer contend. **Alpha does not match:** `cybreach_pod_alpha/rule ingestion/Dockerfile:9,11` and `app/README.md:26,39,75,105` all bind **8000**, not the registry's 8001, so Alpha and the Delta backend both claim 8000 and Beta's default client URL (`ve_app/main.py:47`) cannot reach a default Alpha build. Gamma's frontend is on 5174 and Delta's on 5173, so the two dashboards no longer collide.
- **Impact:** Alpha and the Delta backend collide on 8000, and the registry - the document every pod and the gateway were corrected against - is wrong about Alpha.
- **Resolution:** Move Alpha to 8001 in its Dockerfile, README and the Beta client default, or change the registry and every reference to match; then re-check the whole set together.
- **Status:** PARTIAL. Beta, Delta and Gamma conform; Alpha's actual port contradicts the registry and collides with the canonical publisher.

### M3. Connector/registry APIs triplicated and incompatible

- **Violates:** plan Section 5 `POST /api/v2/connectors/register`, `GET /api/v2/connectors/health`.
- **Where:** Alpha `cybreach_pod_alpha/rule ingestion/app/api/connector_routes.py:12-15` (`/api/v2/connectors/*`); Delta `cybreach_pod_delta/backend/app/api/connectors.py` (`/connectors`, `/connectors/{id}`); Gamma webhook connectors `cybreach_pod_gamma/ocsf_normalizer/src/main.py:393-417` (`/api/v2/webhook/connectors`). Alpha's docs claim Gamma and Delta consume its health surface; neither does. Gamma's own duplication is resolved - the class registry exists once, at `ocsf_normalizer/src/main.py:133-233`, after the `schema_engine/` copy and `app/routes/custom_ocsf.py` were removed - but the two *other* registries are unchanged. The underlying DDL ownership is also unresolved: Gamma's `ocsf_normalizer/migration/002_webhook_connector.sql:7` creates a table named `connectors` (`id, name, secret, hmac_enabled, is_active, created_at`), while Delta has renamed its own to `platform_connector_health` (`app/models/connector.py:14`) precisely to avoid colliding with it.
- **Impact:** Three registries, three health shapes; connector health cannot be aggregated, and two pods define connector state in tables with the same name and different columns.
- **Resolution:** Single registry owned by Alpha; the other two consume it. Decide which pod owns the `connectors` table in a merged database.
- **Status:** PARTIAL. Gamma's internal duplication is gone; three registries and a `connectors` DDL ownership question remain.

### M4. Rule-dependency integration is one-sided

- **Violates:** plan Week 7 Alpha "rule dependency tracker"; plan Section 5 `validation_runs` link.
- **Where:** Alpha exposes `POST /api/v2/rules/{rule_id}/dependencies` with `dependent_type` validated against `{validation_run, revalidation_run, action}` (`cybreach_pod_alpha/rule ingestion/app/api/rules.py:396-428`). The only callers are Alpha's own tests (`tests/test_rule_versioning.py:275,294,303`). Beta's client for Alpha is GET-only (`cybreach_pod_beta/services/validation_engine/ve_app/main.py:46-53`) and never posts usage.
- **Impact:** The dependency graph stays empty; nothing records which rule executed against which evidence.
- **Resolution:** Beta's engine reports usage back to Alpha's dependency endpoint; covered by a contract test.
- **Status:** STILL PRESENT. No pod posts to that endpoint.

### M5. The cross-pod contract registry exists in three incompatible places and nothing reads it

- **Violates:** plan Week 1 "Contracts Published: all frozen schemas and fixtures available in shared repo".
- **Where:** Gamma's `publish_contract.py:14-15,50` writes to a **pod-local** `cybreach_pod_gamma/contracts/ocsf_normalizer_schema.v1.json`, even though its own docstring at `:5` claims the workspace root. There is no `G:\Cybreach-module2\contracts` directory. `shared_registry/v1/windows_auth.json` is still tracked and read by nobody. A workspace-wide search for consumers of either path finds only prose in this file, in `integration_run_plan.md`, and in Gamma's `README.md:25,177`.
- **Impact:** There is one registry location per the plan and three in practice, and no contract test loads frozen schemas from any of them. Delta's contract lives under its own pod (`cybreach_pod_delta/contracts/`), so the "shared repo" is three independent copies.
- **Resolution:** One registry path at the workspace root; every pod publishes and every contract test loads from it.
- **Status:** PARTIAL. Files are published somewhere; nothing is shared and nothing consumes them.

### M6. Mutual-exclusion dependency pins, and no single set is agreed across the pods

- **Violates:** plan Section 8 (FastAPI 0.115+, Python 3.12 single env); plan Section 7 contract-test seam requires one testable environment.
- **Where (Gamma is now internally consistent):** all three of Gamma's manifests - `cybreach_pod_gamma/requirements.txt`, `ocsf_normalizer/requirements.txt:1-5` and `revalidation_service/requirements.txt:1-5` - now carry the same pinned set (`fastapi==0.141.1, pydantic==2.13.4, uvicorn==0.52.2, pytest==9.1.1, httpx>=0.27.0`) byte-for-byte, so `pip install -r requirements.txt` at the pod root finally produces the environment its own CI runs. The root manifest's previous loose pins, and its four unused dependencies (`aiokafka`, `redis`, `asyncpg`, `pytest-asyncio`, none of which is imported anywhere in the pod), are gone.
- **Where (still open):** Gamma is the only pod that agrees with itself. Beta pins `fastapi==0.115.6, pydantic==2.10.3, uvicorn[standard]==0.32.1, pytest==8.3.4` and `kafka-python==3.0.11` at `:18`. Delta pins `fastapi==0.139.0, starlette==1.3.1, typing-inspection==0.4.2` (`cybreach_pod_delta/backend/requirements.txt:6,17,18`) - still not bumped to match Gamma. Alpha's `rule ingestion/requirements.txt` is entirely unpinned, its only constraint being a `cryptography>=46.0.0` floor.
- **Impact:** No single requirements set satisfies the pods that can be edited, and Alpha's unpinned manifest is still the widest gap; a shared CI/dev environment remains impossible.
- **Resolution:** One pinned set from plan Section 8 across all four pods, with a committed lockfile the contract-test seam can install.
- **Status:** PARTIAL. Gamma reconciles internally; the cross-pod set is unagreed, and closing it needs Alpha.

### M9. Internal gRPC plumbing absent

- **Violates:** plan Section 5 data flow steps (2),(5),(6),(7) (gRPC between services).
- **Where:** A recursive search for `.proto` files and for `grpc`/`grpcio`/`protobuf` references across all four pods returns zero matches. Every inter-service channel is REST: Alpha <-> Beta is HTTP (`ve_app/main.py:46-73`), and the plan's internal transport contract is unbuilt.
- **Impact:** Integration will proceed on unagreed REST, with the REST drift documented only implicitly by the code.
- **Resolution:** Either implement gRPC per plan, or re-scope internal calls to REST with a written contract recorded as documented drift.
- **Status:** STILL PRESENT.

### M10. Duplicate rule-dependency tracker inside Alpha

- **Violates:** plan Week 7 single "rule dependency tracker".
- **Where:** `cybreach_pod_alpha/rule ingestion/app/services/rule_dependency_tracker.py` (127 lines, in-process dict at `:43`, with JSON backing only if a `storage_path` is passed - and `rules.py:25` constructs it without one) coexists with `cybreach_pod_alpha/rule ingestion/Rule_Dependency_Tracker/app/main.py` (a separate FastAPI app at `:10` with its own DB via `Depends(get_db)` at `:23` and `Base.metadata.create_all()` at `:8`). Only the first is imported (`rules.py:16-19`); the standalone service is orphaned, and its `requirements.txt` is the only fully pinned manifest in Alpha, so it advertises a version set nothing else uses.
- **Impact:** Two dependency stores, different APIs, both in-process and neither durable; ambiguous which is canonical.
- **Resolution:** Keep the in-process service plus its endpoint, delete the orphan app, and give the keeper real persistence.
- **Status:** STILL PRESENT.

---

## Section 3 - Minor

### m1. Health-check response shapes differ

- **Violates:** plan Section 7 local-dev "verify health via /health"; plan Section 5 connector health aggregation.
- **Where:** Beta returns `{"status":"ok","service":...}` from all three services (`ve_app/main.py:247-249`, `oc_app/main.py:85-87`, `vp_app/main.py:167-174`); Gamma returns the same from both (`ocsf_normalizer/src/main.py:82-87`, `revalidation_service/src/main.py:67-69`); Delta returns `{"status":"ok"}`. **Alpha is the last holdout**: `cybreach_pod_alpha/rule ingestion/app/main.py:102` returns a hardcoded `{"status": "healthy"}` and, despite the docstring at `:101`, evaluates no dependency, plugin or database health at all.
- **Resolution:** Alpha returns `{"status": "ok", "service": "rule-ingestion"}` and actually probes its dependencies.
- **Status:** PARTIAL. One pod and one static response remain.

### m3. Beta repo drift: `Week1`-`Week11` snapshots, and an evidence_events migration that under-delivers its contract

- **Violates:** plan Section 11 file structure (`services/` canonical); plan Section 9 frozen EvidenceEvent contract.
- **Where:** `cybreach_pod_beta/Week1` through `Week11` all still exist at the top level and duplicate `services/` content (`Week2/migrations` duplicates `migrations/`); `pytest.ini:3-10` scopes collection to the three `services/*/tests` directories, so the snapshots are inert but still tracked. The single migration `cybreach_pod_beta/migrations/versions/0001_create_validation_runs_and_evidence_events.py:21-28` creates `evidence_events` with only `event_id, action_id, correlation_key, technique_ref, timestamp, created_at` - **omitting `target_asset_ref` and `expected_observable`**, which the Pydantic model requires (`services/validation_engine/ve_app/models.py:25-26`) and the frozen schema declares. `validation_runs` (`:32-41`) likewise has no `regulatory_control_refs` and no `content_hash` column, and no follow-up revision exists.
- **Impact:** The migration claims to create the frozen contract's tables and does not; the snapshots bloat the repo and CI surface.
- **Resolution:** Delete the week snapshots; extend `0001` to the full frozen column set.
- **Status:** STILL PRESENT.

### m6. Connector vendor enum casing inconsistency

- **Where:** `cybreach_pod_alpha/contracts/connector specification/connector_specification.json:17-23` declares `["Splunk","Microsoft Sentinel","IBM QRadar","Elastic","crowdstrike"]` - capitalized display names, with `crowdstrike` lowercase - while every runtime registration key is a lowercase slug: `crowdstrike_logscale_connector.py:387-390` -> `crowdstrike_logscale`, `sentinel_connector.py:226` -> `sentinel`, `qradar_connector.py:414-417` -> `qradar`, `splunk_connector.py:447-450` -> `splunk`, `elastic_connector.py:339-342` -> `elastic`. `config_validation.py:12-18` keys on that same slug set. **No runtime key matches any contract enum value verbatim**, and the repo contradicts itself: `tests/test_connector_contract.py:49` passes `vendor="crowdstrike"`, which `config_validation.py:65` rejects.
- **Impact:** A contract-validated connector can never match a real registry key, and the repo's own test suite asserts a value the validator forbids.
- **Resolution:** Pick one identifier form (lowercase slug), use it in the spec, the registry, the validator and the tests, and treat display names as labels only.
- **Status:** STILL PRESENT.

### m7. Secrets hygiene: Delta's old credentials are still in git history

- **Violates:** plan review checklist "No hardcoded secrets".
- **Where (closed in the working tree):** Alpha, Delta and Gamma carry no credential in any tracked file - Alpha uses env-driven Fernet with no fallback (`app/connector/credential_manager.py:10-25`) and a blank `alembic.ini:21`; Delta reads `ADMIN_USERNAME`/`ADMIN_PASSWORD`/`SECRET_KEY` from the environment only (`app/api/auth.py:21-22`, `app/security/security.py:18,27-36`) and carries none in `alembic.ini:96`; Gamma's `connectors.db` is untracked. Beta's compose no longer hardcodes one either - `docker-compose.yml` now takes `POSTGRES_USER`/`POSTGRES_PASSWORD` from the environment with no default and aborts if either is unset, and `.env` is gitignored with `.env.example` as the tracked template. Two smaller Alpha instances also remain: a test-only literal at `tests/test_alembic_migrations.py:26` and a hardcoded `sqlite:///./rules.db` in the orphaned `Rule_Dependency_Tracker/app/database.py:4`.
- **Where (still open):** both the old (`postgres:vyom`) and the newer (`validator_dev_pw`) Delta credentials remain in **git history**. Removing the literal from the current file does not remove it from any clone, and rotating a secret does not un-expose the old one.
- **Resolution:** Rewrite git history for the two Delta credentials, or rotate them and record the exposure with its date and scope.
- **Status:** PARTIAL. Every working tree is clean; the Delta history rewrite is not done and is not a code fix.

### m8. Alpha's `clone_repo` is still an unguarded SSRF surface

- **Violates:** plan code-review checklist "error handling" (validate and reject bad input).
- **Where (closed in Delta):** Delta's half is done. `MalformedRuleQuery` is caught at the API boundary and returned as **422** (`cybreach_pod_delta/backend/app/api/validator.py:29-38`), which is what the service docstring at `app/services/validator_service.py:36` had always claimed that layer did; a malformed `rule_query` no longer escapes as an unhandled `ValueError` and a 500.
- **Where (still open - all of it is Alpha):** `clone_repo` (`cybreach_pod_alpha/rule ingestion/app/api/rules.py:107-136`) clones any user-supplied target with **zero validation** - the only check anywhere is a Pydantic field validator at `app/models/rule_models.py:75-80` that accepts any `http(s)` host or any local path. There is no allow-list, no private-IP or loopback guard, so a caller can name `169.254.169.254` or `file:///etc/passwd` and the pod will fetch it on their behalf.
- **Resolution:** Add a URL allow-list / domain policy to `clone_repo`, rejecting loopback, link-local and private ranges.
- **Status:** PARTIAL. Delta is clean; Alpha's clone path is unguarded and Alpha was left untouched.

---

## Section 4 - Per-Pod Open Conflicts

Counts reflect this file's contents only. Anything not listed for a pod is either resolved or owned by another pod.

| Pod | Directory | Blockers | Major | Minor | New conflicts |
| --- | --- | --- | --- | --- | --- |
| Alpha | `cybreach_pod_alpha/` | B1, B2, B6, B8, B11 | M1, M3, M4, M6, M9, M10 | m1, m6, m7, m8 | N-A1, N-A2, N-A4, N-A5 |
| Beta | `cybreach_pod_beta/` | B1, B6, B7, B8, B11, B12, B13 | M4, M5, M6, M9 | m3, m7 | N-B2, N-B4 |
| Gamma | `cybreach_pod_gamma/` | B1, B10, B11 | M3, M5, M6, M9 | - | N-G10 |
| Delta | `cybreach_pod_delta/` | B1, B6, B7, B11 | M3, M5, M6, M9 | m7, m8 | - |

### Pod Alpha - `cybreach_pod_alpha/`

- **N-A1 (MAJOR):** Vendor identifier triple-divergence - contract enum, runtime registry keys and the validator share no value; see **m6**. A contract-validated connector would not match a real registry key.
- **N-A2 (MINOR):** Dead model set. `rule ingestion/app/services/rule_models.py` (60 lines) defines `ParsedRule`/`RuleIngestRequest`/`SyntaxValidationReport` that nothing imports - every importer uses `app/models/rule_models.py`. Its shapes differ from the live models (`rule_id: Optional[str]=None` at `:26` against the live required `str`). `app/services/rule_pipeline.py` is dead on the same pattern: imported by nothing, and it passes `rule_id=None` at `:46,102`, which the live model's required `str` would reject - direct evidence it has never been executed.
- **N-A4 (MINOR):** `/health` is a static `{"status": "healthy"}` that probes nothing; see **m1**.
- **N-A5 (BLOCKER):** `rule_id` is assigned `parsed_dict.get("rule_id") or "UNKNOWN"` (`app/api/rules.py:180`) rather than the plan's content-hash canonical id, with the hash written to a separate field at `:184`; see **B6**. `clone_repo` remains an unguarded SSRF surface (`app/api/rules.py:107-136`); see **m8**.

### Pod Beta - `cybreach_pod_beta/`

- **N-B2 (MAJOR):** No deployable packaging. `docker-compose.yml` defines only infrastructure (postgres/redis/kafka/kafka-ui); there are **zero** `Dockerfile`s anywhere in Beta and no app services are defined.
- **N-B4 (MAJOR):** DB schema drift beyond the two evidence columns - `migrations/versions/0001_create_validation_runs_and_evidence_events.py:32-41` gives `validation_runs` no `regulatory_control_refs` and no `content_hash`, and the two evidence columns the frozen contract requires are missing too; see **m3**. `detection_logic` is string-coerced at the Alpha seam; see **B8**.

### Pod Gamma - `cybreach_pod_gamma/`

- **N-G10 (MINOR):** `POST /api/v2/webhook/connectors` is unauthenticated (`ocsf_normalizer/src/main.py:393-417`), so the HMAC guard on `ingest` is only as strong as an open registration endpoint; folded into **B11**.

### Pod Delta - `cybreach_pod_delta/`

- Delta has no new conflicts of its own. Its previous **N-D18** and **N-D19** are resolved and removed; what remains open for Delta is the shared ownership, bus, registry and security work listed against it above.

---

## Reconciliation Owner Table

Open items only. Owner per plan Section 7 unless noted.

| Conflict | Owner | Remaining action |
| --- | --- | --- |
| Verdict contract (B2) | Delta (publisher) | Alpha adopts the frozen v2.0 field list; Beta adds a frozen-schema acceptance test (its digest test exists at `test_verdict_integrity.py:163-192`, but Beta has no `verdict.schema.json` and never runs `jsonschema.validate` on a verdict) |
| Rule_id type (B6) | Alpha | Assign the content-hash canonical id. Delta's schema and both of its joins conform; the whole open remainder is Alpha's |
| Message bus + topics (B1, B10) | Integration env (Delta) | One root infra compose; one shared topic manifest replacing the two hand-written copies; a real `cybreach.evidence.v1` consumer in Beta; repoint the runbooks that still document the deleted `verdict-publisher/` and `verdict-events` |
| gRPC rule delivery (B8) | Alpha (Beta REST client partial) | Alpha persists `INGESTED_RULES`; Alpha binds the registry port 8001; Beta uses Alpha for batch and caller-supplied flows; stop `str()`-coercing `detection_logic` |
| Connector framework (B12, M3) | Alpha | Keeper of connectors + registry; others consume. Decide who owns the `connectors` DDL in a merged DB (Gamma's `002_webhook_connector.sql:7` vs Delta's `platform_connector_health`) |
| `/api/v2` surface (B13) | Delta + Beta | Flatten `validator_router` so `POST /api/v2/validate` exists; version all of Beta's routes |
| Auth/JWT + tenant scoping (B11) | Delta + Alpha + Beta + Gamma | Shared JWT issuer adopted by Alpha/Beta/Gamma; authenticate Gamma's connector registration; add `tenant_id` and per-query filtering in every pod |
| Contract registry (M5) | Integration env | One root `contracts/` path; every pod publishes there and every contract test loads from it |
| Dependency pins (M6) | Integration env | One pinned set across all four pods, plus a committed lockfile. Gamma is internally consistent; Beta, Delta and the unpinned Alpha still differ |
| Ports (M1) | Integration env | Reconcile Alpha's actual 8000 against the registry's 8001, in the Dockerfile, the README and Beta's client default |
| Ownership dedupe (B7, M10) | Alpha + Beta | Retire Beta's `verdict_publisher/` and `ve_app/connectors.py`; delete Alpha's orphaned `Rule_Dependency_Tracker/app` |

## Priority Actions

1. **Stand up the bus and close the evidence seam** (B1, B10) - a root `docker-compose.yml` with KRaft Kafka, PostgreSQL and Redis, one shared `topics.yaml` replacing Delta's and Gamma's independent copies, and a real `cybreach.evidence.v1` consumer in Beta's Validation Engine. Nothing downstream is demonstrable until an evidence event reaches a verdict.
2. **Close B11's tenant-scoping half and Alpha/Beta/Gamma's authentication** - a schema migration plus per-query filtering in every pod, a shared JWT issuer, and an authenticated connector-registration route in Gamma. The Delta route guards are done; this is the part that is not, and it is a migration rather than a guard.
3. **Persist Alpha's rule store and reconcile its port** (B8, M1, N-A5) - move `INGESTED_RULES` behind the `detection_rules` table Alpha already migrates, and settle 8000 vs 8001 across the Dockerfile, the README, the registry and Beta's client default. Until then the rule seam silently depends on Alpha never restarting.
4. **Get Alpha onto the frozen verdict contract** (B2) - add `regulatory_control_refs` and `content_hash`, make all 8 fields required, and add a test that validates a Delta- or Beta-produced event.
5. **Standardize the API surface** (B13) - flatten `POST /api/v2/validator/validate` to `POST /api/v2/validate` and put Beta's `/validate`, `/validate/batch`, `/classify` and `/publish` under `/api/v2`, so one gateway can front all four pods.
6. ~~Switch Beta's `/classify` to the string causal chain (M11)~~ - **done**, removed above.
7. ~~Fix the remaining int-vs-hash join and the unhandled exception (B6/N-D18, m8)~~ - **done in Delta**, removed above; the two Alpha-side remainders survive under **B6** and **m8**.
8. **Reconcile dependency pins and delete Beta's week snapshots** (M6, m3) - one pinned set across four pods, and `Week1`-`Week11` removed with `0001` extended to the full frozen column set. Gamma's root manifest is already reconciled; the remaining pin gap is Beta, Delta and the unpinned Alpha.
9. **Retire the duplicate implementations** (B7, B12, M10) - Beta's `verdict_publisher/` and `ve_app/connectors.py`, Alpha's orphaned `Rule_Dependency_Tracker/app` and its dead `services/rule_models.py` + `services/rule_pipeline.py`.
10. **Secrets and history** (m7) - Beta's `POSTGRES_PASSWORD` is now an env var and every working tree is clean; what is left is rewriting, or formally rotating and documenting, the two Delta credentials still present in git history.
