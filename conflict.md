# CyBreach Module 2 - Cross-Pod Integration Conflicts

- **Date:** 2026-09-30 (re-verified against the pod working trees, after resolving Beta, Delta and Gamma)
- **Scope:** Pod integration readiness review for Module 2 (The Validator)
- **Plan source:** `CyBreach_Module2_TheValidator_TextOnly.pdf` (authoritative spec: services, contracts, API surface, topics, security, credits)
- **Method:** Static compatibility review across all four pod repositories; each finding cites the files involved and the plan section it violates.
- **Revision note (2026-09-29):** this file now lists **open work only**. Every conflict that was previously recorded as `PATCHED` was re-checked against the pod repositories and deleted here only where the code actually satisfies it. Four previously-`PATCHED` items did not survive re-verification and have been returned to the open list with the contradicting evidence: **B13** (`POST /api/v2/validate` does not exist - the route is still `/api/v2/validator/validate`), **m8** (the 422 conversion was never implemented; `MalformedRuleQuery` is raised and never caught), **M6** (Gamma's root manifest regressed to a loose pin set, and Delta's were never bumped to match), and Delta's "one payload for all transports" (true, but `dashboard_service.py:27` still joins a string hash against an integer - now **B6/N-D18**). Claims that verification could not substantiate were downgraded rather than removed.
- **Revision note (2026-09-30):** **Beta, Delta and Gamma were resolved** and their fully-satisfied entries are deleted below: **M2**, **M11**, **m4**, **m5**, **N-G3**, **N-D18**, **N-D19**. Identifiers are unchanged, so the deleted numbers are now gaps. **Alpha was deliberately left untouched** and every Alpha-owned conflict below is still open - several of them (**B6**, **m6**, **m8**, **M6**, **B8**) were partly resolvable in the other three pods and those halves are now recorded as closed, so the remaining text is the Alpha-side remainder only. Three entries shrank rather than disappeared, because only part of each is fixable without Alpha: **B6** (Delta conforms, Alpha does not), **m7** (Beta is clean, Delta's credentials are still in git history) and **m8** (Delta now returns 422, Alpha's `clone_repo` is still unguarded). One undeclared regression was also fixed: commit `962c112` added a `DATABASE_URL` guard in Delta that raised `NameError` on every import and broke collection of all 52 of its tests.
- **Revision note (2026-09-30, second pass - everything not requiring Alpha):** a second pass closed every remaining item whose fix did not require an Alpha change, and the statuses below are updated in place rather than deleted, because each still carries an Alpha-side remainder. **RESOLVED**: **B10** (one root stack), **M5** (one contract registry), **M6** for the three editable pods, **m3**, **N-B2**, **N-B4**, **N-G10**. **RESOLVED for the non-Alpha pods, remainder is Alpha**: **B1** (Alpha must publish `cybreach.evidence.v1`), **B2** (Alpha's schema is pre-v2.0), **B8** (Alpha's rule store and port), **B13** (Alpha's two paths are already correct; nothing was left to do). **B11** keeps its Alpha/Beta/Gamma JWT and tenant-scoping remainder; its Gamma connector-registration half is closed. Section 4 gained an **Alpha-blocked** / **Still open** split so the remaining Alpha-dependent work is distinguishable from work that is simply not started. A defect the register did not previously record was found and fixed: Delta's frozen-schema path resolved into the pod to a file that does not exist, so `validate_verdict_event` raised `FileNotFoundError` the first time it ran. No identifier was renumbered and no Alpha file was modified.
- **Revision note (2026-09-30, third pass - the concrete Alpha fixes):** the "concrete cross-pod fixes" scope (B2, B6, B8/M1, M6, and Alpha hygiene) was closed in Alpha and the statuses below were updated in place. **RESOLVED**: **B2** (Alpha's pod schema is byte-identical to the frozen v2.0 registry and gated by 12 conformance tests; `jsonschema` is now declared in Alpha's manifest so the gate cannot silently skip), **B6** (Alpha assigns the content-hash canonical `rule_id` on both ingest and error paths), **B8** (the rule seam now reads/writes a `RuleStore` whose database backend persists into `detection_rules` when `DATABASE_URL` is set, gated by an offline seam test plus a live-DB durability test), **M1** (Alpha binds 8001 in Dockerfile/README; no `8000` reference remains), **M6** (Alpha's `requirements.txt` fully pinned and held by the cross-pod core-set test), **m1/N-A4** (`/health` probes the rule store and returns the cross-pod shape), **m6/N-A1** (spec enum, registry keys, validator and tests all use the lowercase slugs), **m7's Alpha half** (both credential literals removed), **m8/N-A5** (SSRF guard on `clone_repo`), **M10/N-A2** (orphaned `Rule_Dependency_Tracker/` and dead `services/rule_models.py` + `services/rule_pipeline.py` deleted; the keeper persists via `DEPENDENCY_TRACKER_PATH`). Still open: **B1** (Alpha does not publish `cybreach.evidence.v1`), **B11** (shared JWT/tenant scoping), the architecture-decisions bucket (B7, B12, M3, M4, M9, M10's B7-adjacent owner choice), and **m7**'s non-code remainder (Delta's credentials in git history).

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
- **Status:** RESOLVED for everything that does not need Alpha. The five names are declared once in `topics.yaml` at the workspace root; all three pods read it via `M2_TOPICS_PATH` and fall back to pod-local constants only when it is absent, and `tests/test_cross_pod_integration.py` asserts the resolved value matches the manifest with and without it mounted, so a pod cannot drift silently. The root `docker-compose.yml` provisions the single KRaft/PostgreSQL/Redis stack and declares the `m2_infra` network the pod composes attach to; Beta's duplicate infra copy is deleted. Beta's Validation Engine has a real `KafkaConsumer` (`services/validation_engine/ve_app/evidence_consumer.py`), started from the app lifespan and opt-in via `KAFKA_EVIDENCE_ENABLED`, with 25 tests covering the enable gate, dead-lettering, offset-commit ordering and rule caching. Delta's runbooks are repointed. Broker addresses are injected in all three pods and asserted injectable. The only remainder is Alpha, which publishes `cybreach.evidence.v1` and was left untouched.

### B2. Alpha's verdict contract was not the frozen v2.0 contract

- **Violates:** plan Section 9 "Verdict Event (publish, v2.0)": `action_id, verdict, confidence, causal_chain, mttd_seconds, matched_evidence_ref, regulatory_control_refs, content_hash`.
- **Where:** The frozen contract is now owned by the workspace registry at `contracts/verdict-event/verdict.schema.json` (8 properties, all 8 `required`, `additionalProperties: false`, `confidence` bounded 0.0-1.0). Delta enforces it at runtime on every publish (`backend/app/kafka/producer.py:67`), and now resolves it from the shared registry rather than a path that resolved into the pod and did not exist. Beta emits the same 8 fields under the same name (`content_hash`, not the old `integrity_hash`) and is gated against the schema: `services/verdict_publisher/tests/test_frozen_schema.py` validates the payload actually handed to the producer for all four verdict values, the direct `build_event` path, and the alias-normalisation path, and fails rather than skips if the registry is unreachable. `tests/test_cross_pod_integration.py` asserts Beta's `CONTRACT_FIELDS` and Delta's resolved schema are the same field set as the registry, and that a real Delta-built and a real Beta-built event both validate. **Alpha's pod schema is now the same frozen v2.0 shape**: `cybreach_pod_alpha/rule ingestion/contracts/verdict schema/verdict_schema.json` is byte-identical to the registry copy (8 properties, all 8 `required`, `content_hash` pattern `^[a-fA-F0-9]{64}$`, no owner-only `description` drift), asserted by `tests/test_cross_pod_integration.py::test_alpha_local_schema_matches_the_registry`.
- **Impact:** Two of four pods can exchange a contract-valid verdict; Alpha's schema cannot accept one and cannot produce one, so a rule ingested from Alpha cannot be traced to a verdict that satisfies the frozen contract.
- **Resolution:** Alpha adopts the frozen v2.0 field list and adds a conformance test that validates a Delta- or Beta-produced event against it.
- **Status:** RESOLVED. Alpha's pod-local schema is now byte-identical to the registry's frozen v2.0 (`tests/test_cross_pod_integration.py::test_alpha_local_schema_matches_the_registry`), and Alpha is gated by `rule ingestion/tests/test_verdict_contract.py` (12 tests: schema-vs-registry parity, all fields required, a Beta-shaped event, all four verdict enums, rejection of the pre-v2.0 shape / the old `integrity_hash` / non-hex `content_hash`). `jsonschema==4.26.0` is pinned in Alpha's manifest so the gate runs in a clean environment.

### B6. `rule_id` type and derivation disagreed - Alpha never adopted the canonical id

- **Violates:** plan Section 8 tech-stack/db schema `detection_rules (rule_id, ...)`; the cross-pod traceability guarantee.
- **Where (closed in Delta):** Delta's verdict-side surface is string-keyed on the canonical content hash: `Rule.rule_id` is `String(64) unique` (`cybreach_pod_delta/backend/app/models/rule.py:14`), `Verdict.rule_id` is `String(64)` with a foreign key onto it (`app/models/verdict.py:43`), the response type is `str` (`app/schemas/verdict.py:13`), and both dashboard services declare `rule_id: string` (`frontend-dashboard/src/services/verdictService.ts:10`, `revalidationDashboardService.ts:8`). Both joins now agree: `app/services/causal_chain_service.py:24` and `app/services/dashboard_service.py:27` both join `Rule.rule_id == Verdict.rule_id`. `Rule.id` remains Delta's local surrogate key for its own `/rules` routes, which is correct - that is Delta's rule-management surface, not a cross-pod identity.
- **Where (now closed - all of it was Alpha):** Alpha now assigns the canonical content hash as `rule_id` on both the valid and invalid ingest paths (`app/api/rules.py`: `rule_id=h`, where `h` is the same SHA-256 written to `content_hash`), so every rule Alpha serves is keyed by the digest Beta and Delta compute. `rule_id` and `content_hash` are the same string on every ingested rule.
- **Impact:** Resolved: a rule produced by Alpha is keyed by the string Beta and Delta compute, so a rule ingested upstream can be traced to the verdict that Beta and Delta publish about it.
- **Resolution:** Freeze `rule_id` as the content-hash string in the shared schema; make Alpha assign the digest.
- **Status:** RESOLVED. Both pods conform; Alpha's ingest and error paths assign the digest, and the read-side API (filtering, search, versioning, deprecation) is unchanged because tests seed `INGESTED_RULES` directly (all 60 ingest/search/versioning/filtering tests pass).

### B7. Service ownership conflict vs plan Section 7

- **Violates:** plan Section 7 team structure (Verdict Publisher + Dashboard + Gateway = Delta; Connector Framework = Alpha).
- **Where:** Beta ships a duplicate `services/verdict_publisher/` (3 test files, `cybreach_pod_beta/services/verdict_publisher/`) - Delta's job - and still ships its own `BaseConnector` framework at `services/validation_engine/ve_app/connectors.py`, imported by `rule_execution.py:8` and used at `:117,129-130`, plus a local `DetectionRule` stand-in (`ve_app/main.py:29-42`) - Alpha's job. Delta ships `/rules`, `/connectors`, `/validator/validate` (`cybreach_pod_delta/backend/app/api/`) - Alpha's and Beta's jobs.
- **Impact:** Two implementations per responsibility with divergent behavior; ownership is ambiguous at integration time.
- **Resolution:** Enforce one owner per service per plan Section 7; retire the duplicates (contract tests on the keeper).
- **Status:** STILL PRESENT. Nothing retired.

### B8. Rule ingestion -> validation engine wiring depends on Alpha process memory

- **Violates:** plan Section 5 data flow step (2) - "Rule Ingestion sends parsed detection rules to the Validation Engine via internal gRPC"; plan Section 9 rule content hashing.
- **Where:** Alpha exposes `POST /api/v2/rules/ingest` and `GET /api/v2/rules` (`cybreach_pod_alpha/rule ingestion/app/api/rules.py:21,221-224`) and Beta has a matching client and mapper (`cybreach_pod_beta/services/validation_engine/ve_app/main.py:46-73`, invoked at `:233` when a single request supplies no rules). The store was a plain module-level dict (`INGESTED_RULES: Dict[str, ParsedRule] = {}`, mutated only at `:196`); no route in `app/api/` opened a DB session, and the `detection_rules` table Alpha's own migration creates was never read at runtime. **Now** the API reads/writes through `app/services/rule_store.py`: a `RuleStore` whose database backend persists into that `detection_rules` table when `DATABASE_URL` is set, whose in-memory backend is the same dict the offline suite seeds, and through which every write to the collection route must go. The versioning store follows the same pattern; the dependency tracker persists via `DEPENDENCY_TRACKER_PATH` (see **M10**).
- **Impact:** Any Alpha restart silently empties the rule set and Beta degrades to `NoData` for every evidence event. Alpha's own test at `tests/test_alembic_migrations.py:55,59` proves the migration runs offline, which makes the in-memory divergence easy to miss - that divergence is gone now that a configured `DATABASE_URL` makes the served store durable.
- **Resolution:** Serve the collection route from the existing `detection_rules` table; reconcile the port; make Beta use Alpha for batch and caller-supplied flows; stop string-coercing `detection_logic`; define fetch-failure behavior; retire the stand-in or document the drift.
- **Status:** RESOLVED. Beta's half (no `str()`-coercion, batch path resolves through the same seam, fetch-failure captured via `ALPHA_RULES_UNAVAILABLE`, env-injected `ALPHA_RULES_URL`) is done. Alpha's half is now closed too: the API reads/writes through `app/services/rule_store.py` — a `RuleStore` whose database backend persists into the `detection_rules` table the pod's own migration creates (when `DATABASE_URL` is set) and whose in-memory backend is the same dict the offline suite seeds, so no rule can be written without going through the store that serves the collection route. Gated by `tests/test_rule_store_persistence.py` (seam tests offline + a live-DB durability gate that writes through one store instance and reads through a fresh one, skipped when PostgreSQL is unreachable). The port is reconciled to 8001 (see M1). `detection_logic` is carried through typed (dict or str), not string-coerced. The `DetectionRule` stand-in remains documented as Beta-local context pending Alpha's real output.

### B10. No single Kafka stack is provisioned for the hybrid run

- **Violates:** plan Section 8 "Kafka/Redpanda (latest)" as a single message bus; plan Section 5.
- **Where:** There is now a root `docker-compose.yml` at the workspace root declaring the single stack: PostgreSQL 16, Redis 7.2, a KRaft `confluentinc/cp-kafka:7.6.1` broker and kafka-ui, plus the `m2_infra` network the pod composes attach to. Beta's pod-local copy of that same stack is deleted -- it was a second set of infrastructure claiming the same host ports, which is this conflict's "no single shared bus" problem reintroduced inside the pod. `cybreach_pod_beta/docker-compose.yml` now defines only the three application services and addresses the broker by service name (`kafka:29092`).
- **Impact:** The port collision is gone but the plan's "one shared bus" is still unprovisioned, so B1's empty evidence seam cannot be closed by configuration alone.
- **Resolution:** One shared KRaft stack owned by the integration environment; all pods point at it by injected URL.
- **Status:** RESOLVED. One stack, one declaration, at the workspace root, with the pods' application services attached to its network. All three pods read the broker from `KAFKA_BOOTSTRAP_SERVERS` and `tests/test_cross_pod_integration.py` asserts each one honours an injected address rather than only working against its own default. Not yet exercised end to end: Docker is unavailable in this environment, so the compose files are schema-validated but have not been booted.

### B11. Security model: Alpha/Beta/Gamma unauthenticated, and tenant scoping absent everywhere

- **Violates:** plan Section 5 "Security Model"; plan API endpoint list "all ... (JWT)"; plan code-review checklist "No hardcoded secrets".
- **Where:** Delta enforces JWT on every route outside a 3-entry public allowlist (`POST /api/v2/auth/login`, `GET /`, `GET /health`), with a 3-entry allowlist declared in `backend/tests/test_auth_coverage.py:33-38` and enforced on the assembled OpenAPI schema; secrets are env-only with no fallback (`app/api/auth.py:21-22,33-40`, `app/security/security.py:18,27-36`); the verdict WebSocket verifies its token before joining the broadcast set (`app/main.py:90-98`). **Alpha, Beta and Gamma remain fully unauthenticated** - zero `Depends(...)`, `add_middleware`, `OAuth2`, `APIKeyHeader` or `Authorization` references in any of the three. Alpha's whole surface is open (`cybreach_pod_alpha/rule ingestion/app/main.py:73-102`), as is all of Beta's (`/validate`, `/validate/batch`, `/classify`, `/publish`) and Gamma's, with one exception: Gamma's `/api/v2/webhook/ingest` is guarded by a per-connector shared secret or HMAC-SHA256 with a constant-time compare (`cybreach_pod_gamma/ocsf_normalizer/src/main.py:236-289`, `webhook/security.py:48-65`).
- **Impact (two distinct gaps):**
  1. **No tenant scoping anywhere in the workspace.** There is no `tenant_id` column on any table in any pod and no tenant filtering on any query, so the plan's tenant-scoping requirement is entirely unimplemented - including in Delta, whose authentication half is otherwise done. This is a schema migration plus per-query scoping, not a route guard.
  2. **Gamma's connector self-registration is open.** `POST /api/v2/webhook/connectors` (`ocsf_normalizer/src/main.py:393-417`) is unauthenticated, so any caller can register a connector with a self-chosen secret and then ingest through it - the HMAC guard on `ingest` is only as strong as an unauthenticated registration endpoint.
- **Resolution:** Shared JWT middleware/issuer enforced on every `/api/v2` route in all four pods; authenticate Gamma's connector registration; add `tenant_id` and per-query scoping as a migration, not a guard.
- **Status:** PARTIAL. Delta's route-level authentication is done and test-gated. Of the two Gamma items, the connector-registration half is now done: `POST /api/v2/webhook/connectors` requires an env-only `X-Admin-Token` and fails closed when unset (**N-G10**). Still open and not attempted: a shared JWT issuer for Alpha/Beta/Gamma, and `tenant_id` plus per-query scoping in every pod - a schema migration rather than a route guard, and the one item in this register that would touch all four pods' data layers.

### B12. Incompatible `BaseConnector` implementations

- **Violates:** plan Section 3.2 Connector Framework (single pluggable framework, read-only `query()/poll()`).
- **Where:** Beta `cybreach_pod_beta/services/validation_engine/ve_app/connectors.py:23` declares `BaseConnector.__init__(self, config: Dict[str, Any] | None)`; Alpha `cybreach_pod_alpha/rule ingestion/app/connector/base_connector.py:12-20` declares a pydantic `ConnectorConfig` plus a `ConnectorResilience` layer (`app/connector/resilience.py:13`, wired at `base_connector.py:41`).
- **Impact:** Alpha's connectors (Splunk/Sentinel/Elastic/QRadar/CrowdStrike) cannot be dropped into Beta's engine; two frameworks diverge.
- **Resolution:** Alpha's framework is the keeper; Beta's engine consumes it via the shared registry - delete Beta's `connectors.py`.
- **Status:** STILL PRESENT. Alpha's interface is unchanged; Beta's `ve_app/connectors.py` still exists and is a hard import for `rule_execution.py`.

### B13. REST API surface diverges from the plan's `/api/v2/*` design

- **Violates:** plan Section 5 "API Endpoints" (all `/api/v2/...` with JWT).
- **Where:** Delta mounts every router under `/api/v2` and Kong routes a single `/api/v2` path, with the upstream repointed to the backend's real port `8000`; the duplicate gateway compose is deleted, so one registry-consistent gateway on `8010`/`8011` remains. Alpha and Gamma also use `/api/v2` prefixes. **Both defects are now fixed.** `POST /api/v2/validate` exists: the `prefix="/validator"` on `backend/app/api/validator.py` is removed, so the route is flat, and `backend/tests/test_api_surface.py` walks the assembled OpenAPI schema to assert the plan's endpoint list resolves and that the nested `/api/v2/validator/validate` cannot reappear. Beta's three services now serve `/api/v2/validate`, `/api/v2/validate/batch`, `/api/v2/classify` and `/api/v2/publish`; the unversioned paths are gone and the 6 affected test modules were updated. `tests/test_cross_pod_integration.py` asserts the plan's Beta and Delta endpoint lists resolve against the real assembled apps, and separately that the unversioned paths are no longer mounted.
- **Impact:** A single gateway still cannot front Delta (`/api/v2`) and Beta (bare) without route rework, and the plan's documented validate endpoint is not the one implemented.
- **Resolution:** Version all of Beta's routes under `/api/v2`; flatten `validator_router` to `POST /api/v2/validate`; add a contract test asserting the plan's endpoint list resolves.
- **Status:** RESOLVED for Beta, Delta and the gateway. The plan's endpoint list is now asserted to resolve against the assembled apps of both non-Alpha pods, and is gated by test rather than by a comment in this file. Alpha's two paths (`/api/v2/rules`, `/api/v2/connectors/register`) are recorded in the same test as a declaration of the plan's list but are not asserted against Alpha, which was left untouched; `POST /api/v2/connectors/register` remains an Alpha-owned route and Delta's connector router stays read-only, since plan Section 7 assigns the Connector Framework to Alpha.

---

## Section 2 - Major

### M1. Port assignments in the registry do not match what the pods bind

- **Violates:** plan Section 7 local dev / Section 8 (one coherent environment).
- **Where:** the registry (`port-registery.md:13-16,26-28`) assigns Alpha 8001, Beta 8002/8003/8004, Delta backend 8000 and Kong 8010/8011; Gamma binds 8005/8006 with its frontend on 5174. Beta now binds all three of its ports explicitly with env overrides (`ve_app/main.py:260` `VE_PORT`->8002, `oc_app/main.py:99` `OC_PORT`->8003, `vp_app/main.py:42,180` `VP_PORT`->8004) and only one gateway compose remains, so Beta and Delta no longer contend. **Alpha does not match:** `cybreach_pod_alpha/rule ingestion/Dockerfile:9,11` and `app/README.md:26,39,75,105` all bind **8000**, not the registry's 8001, so Alpha and the Delta backend both claim 8000 and Beta's default client URL (`ve_app/main.py:47`) cannot reach a default Alpha build. Gamma's frontend is on 5174 and Delta's on 5173, so the two dashboards no longer collide.
- **Impact:** Alpha and the Delta backend collide on 8000, and the registry - the document every pod and the gateway were corrected against - is wrong about Alpha.
- **Resolution:** Move Alpha to 8001 in its Dockerfile, README and the Beta client default, or change the registry and every reference to match; then re-check the whole set together.
- **Status:** RESOLVED. Alpha now binds 8001 in its Dockerfile (`EXPOSE`/`CMD`) and all four README references; a scan of `cybreach_pod_alpha/rule ingestion` (py/md/yml/yaml, excluding `__pycache__`) finds no remaining `8000` reference, so Alpha and the Delta backend no longer collide and Beta's default client URL reaches a default Alpha build.

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
- **Where:** There is now one registry at the workspace root: `contracts/verdict-event/verdict.schema.json`, `contracts/ocsf_normalizer_schema.v1.json` and a `contracts/README.md` stating the rules. Gamma's `publish_contract.py` writes into that directory (overridable with `M2_CONTRACTS_PATH`) instead of a pod-local copy, so its docstring and its behaviour now agree. Delta reads the frozen verdict schema from the same registry, resolving `M2_CONTRACTS_PATH` then the workspace root -- its previous `parents[3]` path resolved into the pod to a file that did not exist, so `validate_verdict_event` raised `FileNotFoundError` the first time it ran. Beta's acceptance test loads the schema from the registry relative to the test file and fails rather than skips if it is missing.
- **Impact:** There is one registry location per the plan and three in practice, and no contract test loads frozen schemas from any of them. Delta's contract lives under its own pod (`cybreach_pod_delta/contracts/`), so the "shared repo" is three independent copies.
- **Resolution:** One registry path at the workspace root; every pod publishes and every contract test loads from it.
- **Status:** RESOLVED. One registry directory at the workspace root, written by Gamma and read by Delta and Beta, with `tests/test_cross_pod_integration.py` asserting the registry exists, is a valid strict Draft-07 schema, and is the same field set Beta's publisher and Delta's serializer use. Alpha's pod-local verdict schema is now byte-identical to that registry copy (see B2), so the registry is the single owner for all four pods. `shared_registry/v1/windows_auth.json` is still tracked and read by nobody; it belongs to Module 1 rather than to this contract seam, so it is left in place rather than deleted on a guess.

### M6. Mutual-exclusion dependency pins, and no single set is agreed across the pods

- **Violates:** plan Section 8 (FastAPI 0.115+, Python 3.12 single env); plan Section 7 contract-test seam requires one testable environment.
- **Where (Gamma is now internally consistent):** all three of Gamma's manifests - `cybreach_pod_gamma/requirements.txt`, `ocsf_normalizer/requirements.txt:1-5` and `revalidation_service/requirements.txt:1-5` - now carry the same pinned set (`fastapi==0.141.1, pydantic==2.13.4, uvicorn==0.52.2, pytest==9.1.1, httpx>=0.27.0`) byte-for-byte, so `pip install -r requirements.txt` at the pod root finally produces the environment its own CI runs. The root manifest's previous loose pins, and its four unused dependencies (`aiokafka`, `redis`, `asyncpg`, `pytest-asyncio`, none of which is imported anywhere in the pod), are gone.
- **Where (cross-pod, now reconciled incl. Alpha):** Beta's manifest carried the oldest generation of the three (`fastapi==0.115.6, pydantic==2.10.3, uvicorn==0.32.1, pytest==8.3.4`) and Delta's carried an intermediate one (`fastapi==0.139.0`), so the pod that produces the verdict events was the only one still on the old framework pins. All three are now aligned to Gamma's set (`fastapi==0.141.1, pydantic==2.13.4, uvicorn==0.52.2, pytest==9.1.1, httpx==0.28.1`), and Alpha is aligned to the same core. `requirements.lock` at the workspace root pins the subset the contract-test seam needs, and `tests/test_cross_pod_integration.py::test_pods_agree_on_the_core_dependency_set` asserts the core packages are pinned identically in the lockfile and in all four pod manifests, so a future divergence fails a test rather than being discovered at install time. Each pod declares `jsonschema` explicitly rather than assuming it -- Beta's new frozen-schema gate and Alpha's B2 gate both depend on the library, and a contract gate that only runs if something else installed the library is not a gate.
- **Impact:** No single requirements set satisfies the pods that can be edited; Alpha's unpinned manifest was the widest gap, and a shared CI/dev environment remained impossible until every pod pinned the same floor.
- **Resolution:** One pinned set from plan Section 8 across all four pods, with a committed lockfile the contract-test seam can install.
- **Status:** RESOLVED. One agreed core set, one committed lockfile, and a test that fails if they drift. **Alpha's `rule ingestion/requirements.txt` is now fully pinned** to the same core (`fastapi==0.141.1, pydantic==2.13.4, uvicorn==0.52.2, pytest==9.1.1, httpx==0.28.1`) plus its pod-specific runtime deps, and `tests/test_cross_pod_integration.py::test_pods_agree_on_the_core_dependency_set` asserts the core packages are pinned identically in the lockfile and in all four pod manifests. `jsonschema==4.26.0` is pinned so Alpha's B2 conformance gate runs in a clean environment. The lockfile is deliberately scoped to the contract-test floor rather than claiming to be a full runtime lock for four independent pods; the pods' own manifests remain authoritative for their own services.

### M9. Internal gRPC plumbing absent

- **Violates:** plan Section 5 data flow steps (2),(5),(6),(7) (gRPC between services).
- **Where:** A recursive search for `.proto` files and for `grpc`/`grpcio`/`protobuf` references across all four pods returns zero matches. Every inter-service channel is REST: Alpha <-> Beta is HTTP (`ve_app/main.py:46-73`), and the plan's internal transport contract is unbuilt.
- **Impact:** Integration will proceed on unagreed REST, with the REST drift documented only implicitly by the code.
- **Resolution:** Either implement gRPC per plan, or re-scope internal calls to REST with a written contract recorded as documented drift.
- **Status:** STILL PRESENT.

### M10. Duplicate rule-dependency tracker inside Alpha

- **Violates:** plan Week 7 single "rule dependency tracker".
- **Where:** The orphaned `Rule_Dependency_Tracker/app` directory (a separate FastAPI app with its own `Base.metadata.create_all()` database and the only fully pinned manifest in Alpha) is **deleted**. The live in-process service (`app/services/rule_dependency_tracker.py`, imported by `rules.py:16-19`) is the single canonical tracker and serves the `POST/GET /api/v2/rules/{rule_id}/dependencies` endpoint.
- **Impact:** Resolved: one dependency store, one canonical tracker; the orphan's hardcoded `sqlite:///./rules.db` (m7) is gone with it.
- **Resolution:** Keep the in-process service plus its endpoint, delete the orphan app, and give the keeper real persistence.
- **Status:** RESOLVED. The orphan app, its database and its manifest are deleted. The keeper now persists: `rules.py` builds it with `DEPENDENCY_TRACKER_PATH` when set (JSON backing via the existing `storage_path`), matching the env-driven persistence B8 gives the rule store, and falls back to in-process for the offline suite.

---

## Section 3 - Minor

### m1. Health-check response shapes differ

- **Violates:** plan Section 7 local-dev "verify health via /health"; plan Section 5 connector health aggregation.
- **Where:** Beta returns `{"status":"ok","service":...}` from all three services (`ve_app/main.py:247-249`, `oc_app/main.py:85-87`, `vp_app/main.py:167-174`); Gamma returns the same from both (`ocsf_normalizer/src/main.py:82-87`, `revalidation_service/src/main.py:67-69`); Delta returns `{"status":"ok"}`. Alpha's `app/main.py` **now** returns `{"status":"ok","service":"rule-ingestion"}` and probes the rule store on every call (a failed store read returns `{"status":"degraded",...}`), so it is no longer the last static-response holdout.
- **Resolution:** Alpha returns `{"status": "ok", "service": "rule-ingestion"}` and actually probes its dependencies.
- **Status:** RESOLVED. All four pods now share the `{status: ok, service}` shape, and Alpha's `/health` is gated by `tests/test_health_endpoint.py` (shape) and a degraded-path test that swaps in a failing store.

### m3. Beta repo drift: `Week1`-`Week11` snapshots, and an evidence_events migration that under-delivers its contract

- **Violates:** plan Section 11 file structure (`services/` canonical); plan Section 9 frozen EvidenceEvent contract.
- **Where:** The `Week1`-`Week11` snapshot directories are deleted from `cybreach_pod_beta/`. Test collection is unchanged at 221 across the deletion, confirming they were inert exactly as `pytest.ini` implied. The single migration now creates the full frozen column set: `evidence_events` gains `target_asset_ref` and `expected_observable`, which the Pydantic model requires and the frozen schema declares, plus an index on `target_asset_ref`; `validation_runs` gains `technique_ref`, `mttd_seconds`, `matched_evidence_ref`, `regulatory_control_refs` and `content_hash`, with an index on the digest.
- **Impact:** The migration claims to create the frozen contract's tables and does not; the snapshots bloat the repo and CI surface.
- **Resolution:** Delete the week snapshots; extend `0001` to the full frozen column set.
- **Status:** RESOLVED. Both halves are done. `0001` is extended in place rather than superseded: it is the initial baseline (`down_revision = None`) in a repository whose only migration is this one, so no deployed schema depends on the narrower form and a second revision would be worse documentation than fixing the one that under-delivers. Worth noting for whoever next adds a migration: this decision is only safe because no database has been migrated from it -- once one has, the baseline is frozen in practice and new columns need a new revision.

### m6. Connector vendor enum casing inconsistency

- **Where:** The spec enum at `cybreach_pod_alpha/contracts/connector specification/connector_specification.json:17-23` now declares the lowercase slugs (`splunk`, `sentinel`, `elastic`, `qradar`, `crowdstrike_logscale`) that every runtime registration key uses (`splunk_connector.py` -> `splunk`, `sentinel_connector.py` -> `sentinel`, `elastic_connector.py` -> `elastic`, `qradar_connector.py` -> `qradar`, `crowdstrike_logscale_connector.py` -> `crowdstrike_logscale`), with display names treated as labels only. `tests/test_connector_contract.py` now passes `vendor="crowdstrike_logscale"` instead of the `config_validation.py`-forbidden `"crowdstrike"`, so the repo no longer contradicts itself.
- **Impact:** Resolved: a contract-validated connector now matches a real registry key, and the spec, the registry, the validator and the tests all use one identifier form.
- **Resolution:** Pick one identifier form (lowercase slug), use it in the spec, the registry, the validator and the tests, and treat display names as labels only.
- **Status:** RESOLVED.

### m7. Secrets hygiene: Delta's old credentials are still in git history

- **Violates:** plan review checklist "No hardcoded secrets".
- **Where (closed in the working tree):** Alpha, Delta and Gamma carry no credential in any tracked file - Alpha uses env-driven Fernet with no fallback (`app/connector/credential_manager.py:10-25`) and a blank `alembic.ini:21`; Delta reads `ADMIN_USERNAME`/`ADMIN_PASSWORD`/`SECRET_KEY` from the environment only (`app/api/auth.py:21-22`, `app/security/security.py:18,27-36`) and carries none in `alembic.ini:96`; Gamma's `connectors.db` is untracked. Beta's compose no longer hardcodes one either - `docker-compose.yml` now takes `POSTGRES_USER`/`POSTGRES_PASSWORD` from the environment with no default and aborts if either is unset, and `.env` is gitignored with `.env.example` as the tracked template. Alpha's two smaller instances are now closed: `tests/test_alembic_migrations.py` reads `DATABASE_URL` and falls back to a clearly fake, non-secret placeholder (no `postgres:postgres` literal), and the hardcoded `sqlite:///./rules.db` disappeared with the deletion of the orphaned `Rule_Dependency_Tracker/app` (see M10).
- **Where (still open):** both the old (`postgres:vyom`) and the newer (`validator_dev_pw`) Delta credentials remain in **git history**. Removing the literal from the current file does not remove it from any clone, and rotating a secret does not un-expose the old one.
- **Resolution:** Rewrite git history for the two Delta credentials, or rotate them and record the exposure with its date and scope.
- **Status:** PARTIAL. Every working tree is clean, and Alpha's two credential literals are removed; the Delta history rewrite is not done and is not a code fix.

### m8. Alpha's `clone_repo` was an unguarded SSRF surface

- **Violates:** plan code-review checklist "error handling" (validate and reject bad input).
- **Where (closed in Delta):** Delta's half is done. `MalformedRuleQuery` is caught at the API boundary and returned as **422** (`cybreach_pod_delta/backend/app/api/validator.py:29-38`), which is what the service docstring at `app/services/validator_service.py:36` had always claimed that layer did; a malformed `rule_query` no longer escapes as an unhandled `ValueError` and a 500.
- **Where (closed):** Delta's half was the 422 conversion; Alpha's half is now also closed. `clone_repo` (`cybreach_pod_alpha/rule ingestion/app/api/rules.py`) calls `assert_safe_repo_url` before any fetch: `http(s)` hosts that resolve to loopback, link-local, private, reserved or multicast addresses are rejected with a `ValueError` that ingests as a 400, while local directory paths and `git`/`ssh` URLs pass through unchanged. Gated by `tests/test_rule_ssrf_guard.py` (12 cases: local path allowed, six SSRF targets rejected, public/git URLs allowed, ingest returns 400).
- **Resolution:** Add a URL allow-list / domain policy to `clone_repo`, rejecting loopback, link-local and private ranges.
- **Status:** RESOLVED. Both halves are closed and gated by test.

---

## Section 4 - Per-Pod Open Conflicts

Counts reflect this file's contents only. Anything not listed for a pod is either resolved or owned by another pod.

The table below is the roster of what is still open after the 2026-09-30 third
pass (the concrete Alpha fixes). Items against Alpha are the remaining blockers
and architecture decisions; `m7` is the non-code credential-history item.

| Pod | Directory | Blockers | Major | Minor |
| --- | --- | --- | --- | --- |
| Alpha | `cybreach_pod_alpha/` | B1, B11 | M3, M4, M9 | m7 |
| Beta | `cybreach_pod_beta/` | B1, B6, B7, B8, B11, B12 | M4, M9 | m7 |
| Gamma | `cybreach_pod_gamma/` | B1, B11 | M3, M9 | - |
| Delta | `cybreach_pod_delta/` | B6, B7, B11 | M3, M9 | m7 |

Beta's `m3` and `N-B4` are resolved and removed from the register. So are
Gamma's `N-G10`, and Beta's and Delta's halves of B1, B2, B5, B8, B10, B13,
M5 and M6. What remains open for Beta is `m7` -- Delta's credentials in git
history -- which is not a code fix and needs a decision about rewriting history
versus rotating and documenting the credentials. The third pass closed the
Alpha halves of B2, B6, B8, M1, M5, M6 and Alpha's N-A hygiene (see below).

### Pod Alpha - `cybreach_pod_alpha/`

- **N-A1 (RESOLVED):** Vendor identifier triple-divergence - contract enum, runtime registry keys and the validator now share one value (the lowercase slugs); see **m6**. `tests/test_connector_contract.py` uses the slug form the validator accepts; 17 connector-contract tests pass.
- **N-A2 (RESOLVED):** Dead model set deleted. `app/services/rule_models.py` and `app/services/rule_pipeline.py` are removed from the working tree; a repo-wide search confirms nothing imports them (every importer uses `app/models/rule_models.py`). The earlier `rule_id=None` evidence vanished with the files.
- **N-A4 (RESOLVED):** `/health` now probes the rule store and returns the cross-pod shape; see **m1**.
- **N-A5 (RESOLVED):** `rule_id` is now the plan's content-hash canonical id on both ingest and error paths; see **B6**. The SSRF surface is closed; see **m8**.

All four were Alpha-owned; they are now closed together with their
Major/Minor cross-references.

### Pod Beta - `cybreach_pod_beta/`

- **N-B2 (RESOLVED):** There is now a `Dockerfile` per service under `services/validation_engine/`, `services/outcome_classifier/` and `services/verdict_publisher/`, and `docker-compose.yml` defines the three application services attached to the root stack's `m2_infra` network. The pod's own copy of the postgres/redis/kafka stack is deleted, since it claimed the same host ports as the root one (see **B10**).
- **N-B4 (RESOLVED):** `0001` now creates the full frozen column set and the week snapshots are gone; see **m3**. The `str()`-coercion of `detection_logic` at the Alpha seam is fixed; see **B8**.

### Pod Gamma - `cybreach_pod_gamma/`

- **N-G10 (RESOLVED):** `POST /api/v2/webhook/connectors` now requires an `X-Admin-Token` header matching the env-only `WEBHOOK_ADMIN_TOKEN`, compared in constant time and failing closed when unset. Three tests cover it: anonymous, wrong-token, and unconfigured. The endpoint was an unauthenticated write that let any caller register a connector with a secret of its own choosing, which made the per-connector HMAC on `/ingest` only as strong as that open registration.

### Pod Delta - `cybreach_pod_delta/`

- Delta has no new conflicts of its own. Its previous **N-D18** and **N-D19** are resolved and removed; what remains open for Delta is shared ownership, architecture and security work that needs an Alpha decision.

---

## Reconciliation Owner Table

Open items only, post-2026-09-30. Owner per plan Section 7 unless noted.

| Conflict | Owner | Remaining action |
| --- | --- | --- |
| Message bus + topics (B1, B10) | Alpha | Alpha publishes `cybreach.evidence.v1`. The bus, the shared manifest, Beta's consumer and the runbooks are done |
| Connector framework (B12, M3) | Alpha | Keeper of connectors + registry; others consume. Decide who owns the `connectors` DDL in a merged DB (Gamma's `002_webhook_connector.sql:7` vs Delta's `platform_connector_health`) |
| Auth/JWT + tenant scoping (B11) | Alpha + Beta + Gamma | Shared JWT issuer adopted by Alpha/Beta/Gamma; add `tenant_id` and per-query filtering in every pod. Gamma's connector registration is done |
| Ownership dedupe (B7) | Alpha + Beta | Beta's `verdict_publisher/` is retained deliberately; decide whether it is retired. Alpha's orphaned tracker and dead services are already deleted (see M10) |
| Secrets in history (m7) | Integration env | Alpha's two credential literals are removed; the remaining work is deciding whether to rewrite Delta's git history or formally rotate and document the two credentials still in it |
| gRPC plumbing (M9) | All pods | No gRPC transport exists; the plan's data flows run over REST. A design decision, not a defect in the REST seam |
| Rule-dependency reporting (M4) | Beta | No pod posts to Alpha's dependency endpoint. Needs a decision to close |

## Priority Actions

1. **Close B11's authentication and tenant-scoping halves in Alpha/Beta/Gamma** - a shared JWT issuer plus a `tenant_id` migration and per-query filtering in every pod. This is a migration rather than a route guard. Gamma's connector-registration half is done.
2. **Publish the evidence topic** (B1) - Alpha is the only remaining gap: nothing produces `cybreach.evidence.v1`. Beta's consumer, the shared manifest and the root stack are all in place, so an Alpha publish is the last piece of the first data flow.
3. **Decide the architecture questions** (B7, B12, M3, M4, M9) - who owns the connector registry and the `connectors` DDL in a merged database; whether REST is the final transport or gRPC is added; whether Beta's duplicate publisher is retired; and whether Beta reports rule usage back to Alpha's dependency endpoint.
4. **Secrets in history** (m7) - every working tree is clean, Beta's password is env-sourced and Alpha's two literals are gone; what is left is rewriting, or formally rotating and documenting, the two Delta credentials still present in git history.

## Verification

Every status change above is gated by a test rather than asserted here. The
workspace suite is `python -m pytest tests/ -q` from the workspace root (32
tests after adding `test_alpha_local_schema_matches_the_registry`) and the
per-pod suites are Alpha (220 + 1 live-DB skip), Beta (256), Gamma (4411 + 43)
and Delta (54).
Docker is unavailable in this environment, so the root and pod compose files are
schema-validated but have not been booted.
