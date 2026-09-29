# CyBreach Module 2 - Integration Run Plan

- **Date:** 2026-09-29
- **Scope:** First integrated run of all four pods (Alpha, Beta, Gamma, Delta) as one environment.
- **Run mode:** **HYBRID** - Docker Compose only for
  infrastructure (PostgreSQL 16, Redis, Kafka); pod services run individually via `uvicorn`.
  See `CyBreach_Module2_TheValidator.txt` - "Local Development Setup" (~line 862): venv ->
  `pip install -r requirements.txt` -> infra `docker compose` -> alembic migrations -> pytest ->
  `uvicorn` per service (e.g. Validation Engine on port 8002) -> verify `/health`.
- **Conflict source:** `conflict.md` (re-verified against the pod working trees on 2026-09-29).
- **State:** every previously `PATCHED` item was re-checked in the pod repositories and removed from both
  this plan and `conflict.md` only where the code actually satisfies it. Four `PATCHED` claims did not
  survive re-verification and are back on the open list with contradicting evidence: the plan's
  `POST /api/v2/validate` does not exist, the 422 on malformed `rule_query` was never implemented,
  Gamma's root manifest regressed to loose pins, and Delta's were never bumped to match Gamma.

## Goal

One infra `docker compose up` boots KRaft Kafka + PostgreSQL + Redis; pod services run via `uvicorn`,
with the flow `evidence -> normalize -> validate -> classify -> publish` working over the plan's five
topics (`cybreach.evidence.v1`, `cybreach.verdicts.v2`, `cybreach.gap_closed.v2`,
`cybreach.revalidation.v1`, `cybreach.connector.health.v1`).

## Pod -> Directory Mapping

| Pod | Plan ownership | Repository directory |
| --- | --- | --- |
| Alpha | Rule Ingestion + Connector Framework | `cybreach_pod_alpha/` |
| Beta | Validation Engine + Outcome Classifier | `cybreach_pod_beta/` |
| Gamma | OCSF Normalizer + Re-Validation Service | `cybreach_pod_gamma/` |
| Delta | Verdict Publisher + Frontend Dashboard + API Gateway | `cybreach_pod_delta/` |

---

## Tier 0 - Boot blockers

| Order | Conflict | Owner | Minimal fix |
| --- | --- | --- | --- |
| P3 | **M1 PARTIAL** - the port registry does not match what the pods bind. Beta binds 8002/8003/8004 with env overrides and one gateway compose remains, so Beta and Delta no longer contend, and Gamma is on 8005/8006 with its frontend on 5174. **Alpha binds 8000** (`rule ingestion/Dockerfile:9,11`, `app/README.md:26,39,75,105`) while the registry assigns it 8001 (`port-registery.md:13`) and Beta's client defaults to `http://127.0.0.1:8001/api/v2/rules` (`ve_app/main.py:47`), so Alpha collides with the canonical publisher on 8000 and is unreachable at its registry port | Integration env (all) | Move Alpha to 8001 in its Dockerfile, README and Beta's client default, or change the registry and every reference to match; re-check the whole set together |
| P4 | **B10 PARTIAL** - the `9092` collision is gone (Delta's ZooKeeper broker was retired) but no single Kafka stack owns the bus: there is no root `docker-compose.yml` in the workspace, and Delta's `app/kafka/config.py:12` still defaults `KAFKA_BOOTSTRAP_SERVERS` to `localhost:9092` rather than an injected shared address | Integration env (infra only) | Add a root `docker-compose.yml` (postgres/redis/KRaft Kafka) and inject the broker URL into every pod |

## Tier 1 - One bus + one set of cross-pod contracts (data must flow)

| Order | Conflict | Owner | Minimal fix |
| --- | --- | --- | --- |
| P5 | **B1 PARTIAL** - all five topic names are declared in two hand-written manifests that agree only by hand (Delta `backend/app/kafka/config.py:16-31`, Gamma `revalidation_service/src/core/config.py:18-32`), and Beta produces on `cybreach.evidence.v1` and `cybreach.verdicts.v2` through a real lazy producer (`vp_app/main.py:50-76,155-156`). **No pod subscribes to `cybreach.evidence.v1`** - Beta's `ve_app/ingestion.py:30-80` replays a local JSON fixture and never opens a `KafkaConsumer` - and there is no root infra compose to boot the bus. Delta's runbooks still document the deleted publisher: `docs/DEPLOYMENT_GUIDE.md:429,533,953,1015,1183` and `docs/OPERATIONS_RUNBOOK.md:431,481` say `verdict-events`, and `DEPLOYMENT_GUIDE.md:71,441,913,925,965` point at the deleted `verdict-publisher/` | Integration env + Beta | One root infra compose, one shared `topics.yaml` replacing the two copies, a real `cybreach.evidence.v1` consumer in Beta, and repointed runbooks |
| P7 | **B2 PARTIAL** - Delta owns the frozen v2.0 schema and validates every publish against it (`app/contracts/verdict_event.py:33-34,98-106` via `app/kafka/producer.py:67`); Beta emits the same 8 fields with a byte-identical digest (`test_verdict_integrity.py:163-192`). **Alpha still ships the pre-v2.0 shape** - `contracts/verdict schema/verdict_schema.json:7-63` omits `regulatory_control_refs` and `content_hash`. Beta has no `verdict.schema.json` and never runs `jsonschema.validate` against a verdict | Alpha (contract owner: Delta) | Alpha adopts the frozen v2.0 field list; Beta adds a frozen-schema acceptance test |
| P8 | **B8 PARTIAL** - Alpha serves `GET /api/v2/rules` (`app/api/rules.py:21,221-224`) and Beta's client/mapper match `ParsedRule` on field names (`ve_app/main.py:46-73`). But the store is a module-level dict (`app/api/rules.py:77-78`) that no DB session ever reads, so a restart empties it; Alpha binds 8000, not the 8001 Beta calls; the mapper `str()`-coerces `detection_logic`, which is a dict for Sigma rules; and batch validation bypasses Alpha entirely (`ve_app/main.py:237-244`) with no fallback | Alpha + Beta | Persist the store behind the existing `detection_rules` table; reconcile the port; stop coercing `detection_logic`; route batch and caller-supplied flows through Alpha |
| P9 | **B13 PARTIAL** - Delta mounts all routers under `/api/v2` and Kong routes a single `/api/v2` path at the backend's real port (`api-gateway/kong.yml:11`), with one registry-consistent gateway on `8010`/`8011`. **But `POST /api/v2/validate` does not exist**: `app/api/validator.py:18` still sets `prefix="/validator"` and `:24` declares `@router.post("/validate")`, so the route is `/api/v2/validator/validate`. Beta's routes are also bare - `ve_app/main.py:231,237,247`, `oc_app/main.py:50,85`, `vp_app/main.py:131,167`, with no `APIRouter` in Beta at all | Delta + Beta | Flatten `validator_router` to `POST /api/v2/validate`; version all of Beta's routes under `/api/v2` |
| P10 | **B6 PARTIAL** - Delta's verdict-side surface is string-keyed on the content hash (`app/models/rule.py:14`, `app/models/verdict.py:43`, `app/schemas/verdict.py:13`, and `rule_id: string` in both dashboard services) and `causal_chain_service.py:24` joins correctly. **But `app/services/dashboard_service.py:27` still joins `Verdict.rule_id == Rule.id`** - a hash against an integer, so `/dashboard/coverage` cannot join - and Alpha assigns `rule_id=parsed_dict.get("rule_id") or "UNKNOWN"` (`app/api/rules.py:180`) rather than the digest | Alpha + Delta | Alpha assigns the content-hash id; Delta fixes `dashboard_service.py:27` |

### Pod ownership of the execution tasks

- **Alpha (Rule Ingestion + Connector Framework):** P7 (adopt the frozen v2.0 verdict contract), P8 (persist the rule store, bind the registry port), P10 (assign the canonical `rule_id`). Alpha is otherwise read-only this round.
- **Beta (Validation Engine + Outcome Classifier):** P5 (the missing `cybreach.evidence.v1` consumer), P8 (use Alpha for batch and caller-supplied flows; stop the `str()` coercion), P9 (version the routes). Beta's confidence bounds, string `rule_id`, canonical `NoData` spelling, health shape, real Kafka publisher and explicit port binds are all in place and are not listed as open.
- **Gamma (OCSF Normalizer + Re-Validation):** P3 (port registry conformance - normalizer 8005, revalidation 8006, frontend 5174 -> 8005 are already correct). Gamma's two service manifests agree with each other, but Gamma's **root** `requirements.txt:1-9` is a different unpinned set (see Tier 3, M6) and two README scheduler references survive.
- **Delta (Verdict Publisher + Dashboard + Gateway):** P9 (flatten the validate route), P10 (the `dashboard_service.py:27` join). Delta's contract enforcement, single serializer, runtime schema validation, content-hash derivation, JWT route gating, env-only secrets, squashed migration chain, Dockerfile and CI are all in place; the Docker image has never been built (no Docker engine in this environment).
- **Integration environment (infra):** P3 (port-registry coordination), P4 (single root infra compose), P5 (one shared topic manifest).

## Tier 2 - Data correctness (same push, required for correct verdicts)

- **M11** one `causal_chain` shape. Delta emits `List[str]` reasoning steps through the shared serializer and Alpha's contract declares `array of string`, but Beta's `/classify` still returns objects - `oc_app/models.py:39` is `List[CausalStep]` and `oc_app/main.py:79` passes the raw list into `OutcomeVerdict`. The string projection that fixes it exists and is tested (`causal_chain_strings` at `oc_app/models.py:43-47`, `CausalStep.as_contract_entry` at `:14-26`, exercised at `oc_app/tests/test_contract_conformance.py:82,97`) and is simply not applied at the boundary. Apply it, then validate the result against the frozen schema.
- **M2** one verdict spelling (`NoData`, not `"No Data"`). Both publishers agree and Beta and Delta normalize legacy input at the edge, so identical bytes are hashed (`vp_app/models.py:51-60,88-111`; Delta `app/contracts/verdict_event.py:73-79`). Two user-facing surfaces still carry the old token: the dashboard's filter option (`frontend-dashboard/src/components/VerdictFilter.tsx:25`) and `docs/API_REFERENCE.md`. Drop the legacy alias from Delta's normalizer only if the compatibility path is deliberately retired - it is a feature, not a conflict.
- **B2's Alpha half and B6's Alpha half are the two contract items still blocking a clean cross-pod verdict**; they are tracked in Tier 1 (P7, P10) and are not repeated here.

## Tier 3 - Defer for the first hybrid run

- **B11** shared JWT **and tenant scoping.** Delta's authentication half is done - every route outside a 3-entry public allowlist requires a JWT, enforced by `tests/test_auth_coverage.py:33-38` walking the OpenAPI schema, with env-only secrets - but the two remaining halves are not: there is **no `tenant_id` column on any table in any pod and no tenant filtering on any query**, so the plan's tenant-scoping requirement is entirely unimplemented; Alpha, Beta and Gamma have no authentication at all; and Gamma's `POST /api/v2/webhook/connectors` (`ocsf_normalizer/src/main.py:393-417`) is unauthenticated, so the HMAC guard on `ingest` is only as strong as an open registration endpoint. Tenant scoping is a migration plus per-query filtering, not a route guard.
- **m7** secrets hygiene. The working trees are clean in all four pods, but `cybreach_pod_beta/docker-compose.yml:10` hardcodes `POSTGRES_PASSWORD: validator_dev_pw`, and both the old (`postgres:vyom`) and newer (`validator_dev_pw`) Delta credentials remain in **git history**, which cannot be removed without a history rewrite. Two smaller Alpha literals: `tests/test_alembic_migrations.py:26` and `sqlite:///./rules.db` in the orphaned `Rule_Dependency_Tracker/app/database.py:4`.
- **m8** SSRF allow-list on `clone_repo` + 422 on malformed `rule_query`. Neither half is done. `clone_repo` (`app/api/rules.py:107-136`) has zero validation - the only check anywhere is a Pydantic validator at `app/models/rule_models.py:75-80` that accepts any `http(s)` host or local path, with no allow-list or private-IP guard. Delta raises `MalformedRuleQuery` at `app/services/validator_service.py:144,149` but nothing catches it: `app/api/validator.py:29-32` calls `validate_rule(...)` bare, so a malformed `rule_query` still returns 500. The docstring at `validator_service.py:36` claims the API layer converts it to a 422; that layer does not exist.
- **M6** dependency pin reconciliation. No pod is aligned with any other: Beta pins `fastapi==0.115.6`/`pydantic==2.10.3`/`pytest==8.3.4`, Gamma's two service manifests pin `fastapi==0.141.1`/`pydantic==2.13.4`/`pytest==9.1.1`, Delta pins `fastapi==0.139.0`/`starlette==1.3.1`, and Alpha is entirely unpinned. Gamma's **root** `requirements.txt:1-9` additionally contradicts Gamma's own services - it is the loose set (`fastapi>=0.100.0`, `httpx>=0.24.0`, no `alembic`/`sqlalchemy`), having been reconciled once and then regressed by two later commits. Restore it, align all four, and commit a lockfile.
- **M5** `shared_registry/v1/` wiring. Gamma's `publish_contract.py:14-15` writes to a **pod-local** `cybreach_pod_gamma/contracts/`, not the workspace root its own docstring (`:5`) claims - there is no `G:\Cybreach-module2\contracts` directory. `shared_registry/v1/windows_auth.json` is tracked and read by nobody. Nothing in any pod consumes either path; a search finds only prose in this plan, in `conflict.md` and in Gamma's `README.md:25,177`. Stand up one root registry and have every contract test load from it.
- **B7/B12/M10** ownership dedupe: Beta's duplicate `services/verdict_publisher/` and `ve_app/connectors.py` (the latter a hard import for `rule_execution.py:8`); Alpha's orphaned `Rule_Dependency_Tracker/app/main.py` alongside the live `app/services/rule_dependency_tracker.py`; Delta's `/rules`/`/connectors`; Alpha's dead `app/services/rule_models.py` and `app/services/rule_pipeline.py`.
- **M3** three connector registries (Alpha `/api/v2/connectors/*`, Delta `/connectors`, Gamma `/api/v2/webhook/connectors`) and an unresolved `connectors` DDL owner - Gamma's `ocsf_normalizer/migration/002_webhook_connector.sql:7` creates a table named `connectors` while Delta renamed its own to `platform_connector_health` to avoid the collision.
- **m3** Beta's `Week1`-`Week11` snapshots are still tracked, and `migrations/versions/0001_create_validation_runs_and_evidence_events.py:21-28` still omits `target_asset_ref` and `expected_observable` from `evidence_events` while `:32-41` gives `validation_runs` no `regulatory_control_refs` and no `content_hash`. `pytest.ini:3-10` scopes collection to `services/*/tests`, so the snapshots are inert but not gone.
- **m6** Alpha's connector vendor enum shares no value with its runtime registry keys: `connector_specification.json:17-23` declares capitalized display names while every runtime key is a lowercase slug (`crowdstrike_logscale`, `sentinel`, `qradar`, `splunk`, `elastic`), and `tests/test_connector_contract.py:49` asserts `vendor="crowdstrike"`, which `config_validation.py:65` rejects.
- **m1** Alpha's `/health` is a hardcoded `{"status": "healthy"}` (`app/main.py:102`) that probes no dependency, plugin or database. Every other pod returns `{"status":"ok","service":...}`.
- **m4/m5 (Gamma hygiene)** a tracked 0-byte root `.dockerignore`, a tracked `ocsf_normalizer/.gitignore.txt` with a `.txt` suffix, and two surviving scheduler references in `README.md:100,161`; plus `README.md:182-183` misstating `pytest.ini:21`, which runs only the normalizer suite. Gamma's substantive Docker/CI work is done and its 4452 tests pass.
- **N-B2** containerization: Beta has **zero** `Dockerfile`s and no app services in its compose. Delta has a real `backend/Dockerfile` and `backend/.dockerignore` at the correct build context, but **it has never been built** - no Docker engine was available - so the image is verified only by the checks CI performs. Not required for the hybrid run either way (services run via `uvicorn`).
- **M8 test coverage:** Gamma's `WalletClient` is wired into `revalidate()` (`revalidation_service/src/main.py:85-86,96-97,102-105` - debit 1, HTTP 402 when exhausted, refund on `UNCHANGED`, balance endpoint) but `revalidation_service/tests/` contains **no** wallet, 402 or credit test. The behaviour is unexercised.

## Suggested port registry (hybrid local run)

| Service | Pod | Port |
| --- | --- | --- |
| PostgreSQL | infra | 5432 |
| Redis | infra | 6379 |
| Kafka (KRaft) | infra | 9092 |
| Rule Ingestion API | Alpha | 8001 **in the registry, but Alpha's Dockerfile and README bind 8000 (P3)** |
| Validation Engine (ve_app) | Beta | 8002 (plan local-dev example) |
| Outcome Classifier (oc_app) | Beta | 8003 |
| Verdict Publisher (vp_app, stand-in) / Delta backend (canonical) | Beta / Delta | 8004 / 8000 |
| OCSF Normalizer | Gamma | 8005 |
| Re-Validation | Gamma | 8006 |
| Frontend dashboard (Delta) | Delta | 5173 |
| Frontend (Gamma, optional) | Gamma | 5174 |
| Kong (optional gateway) | Delta | 8010 proxy / 8011 admin |

## Verification of "run" (hybrid)

1. `docker compose up -d` (infra) -> postgres/redis/kafka healthy. **Currently impossible: there is no root `docker-compose.yml` in the workspace (P4).**
2. `uvicorn` per pod service (port registry above); verify each `/health` returns `{"status":"ok"[, "service":...]}`. **Alpha returns `{"status": "healthy"}` and probes nothing.**
3. Produce a v1.0 evidence event on `cybreach.evidence.v1` -> observe a verdict on `cybreach.verdicts.v2` with a valid `content_hash` -> confirm gap-closed on revalidate.
   **This step cannot currently run.** No pod subscribes to `cybreach.evidence.v1`; Beta's `ve_app/ingestion.py:30-80` replays local fixtures only, so the plan's evidence seam is empty in both directions. Delta's own consumers were removed, which is correct - the plan assigns evidence consumption to the Validation Engine - so Beta has to take the seam over.
   The payload side is not the blocker: Delta validates every publish against the frozen schema through one serializer carrying real values, and Beta's digest is proven byte-identical to Delta's. The empty seam is.
4. Confirm Beta `ve_app` starts and Delta's routes (`/api/v2/*` or via Kong) respond without 500s. **A malformed `rule_query` still returns 500, not 422 (m8).**

## Notes

- If the Tier 0/1 items are not done, the stack boots but data will not pass pod boundaries: there is no bus to carry it and no subscriber to receive it.
- The evidence seam is empty in both directions and is the single blocker to demonstrating the flow end to end.
- Alpha's `GET /api/v2/rules` resolves the B8 blocker in shape only: it serves an in-memory dict, so an Alpha restart makes Beta silently validate everything as `NoData`. It also binds 8000 while Beta calls 8001. Persist the store and reconcile the port before treating the seam as reliable.
- Delta's contract work is not the risk it was. One serializer feeds the WebSocket broadcast, the Kafka publish and the REST response from the same dict, every publish is schema-validated, and `content_hash` covers the published payload and is re-derived on demand at `GET /api/v2/audit-logs/verify/{verdict_id}`. What is still unproven cross-pod is Alpha's adoption of the contract, Beta's missing frozen-schema acceptance test, and Beta's `/classify` still emitting `CausalStep` objects.
- Tier 0 is now a port-registry reconciliation plus a root infra compose. Beta's syntax error, Delta's boot chain, its missing dependencies, its Alembic chain, its Dockerfile and its duplicate gateway compose are all resolved and are no longer gating.

## Verification status (2026-09-29)

| Suite | Command | Result |
| --- | --- | --- |
| Beta | `python -m pytest --collect-only -q` | **220 tests collected** (validation_engine 142, outcome_classifier 41, verdict_publisher 37), 29 files under `services/*/tests` |
| Delta | `pytest` (52 collected) | 5 files / 40 test functions, 52 after `parametrize`; CI runs `compileall`, `pytest`, an import-with-only-`DATABASE_URL` check, offline `alembic upgrade head --sql` + downgrade reversibility, and `tsc -b --force` |
| Gamma | `python run_tests.py -q` | **4409 + 43 passed** |
| Cross-pod | - | Beta/Delta digest agreement at `services/validation_engine/tests/test_verdict_integrity.py:163-192`. **No frozen-schema acceptance test exists in Beta** (no `verdict.schema.json`, no `jsonschema.validate` on a verdict) |

Not verified: no live PostgreSQL/Kafka/Redis (Docker unavailable), Alpha was not modified this round, Delta's
Docker image has never been built, Delta's frontend has no `node_modules` so its TypeScript build could not
be run, and Gamma's `WalletClient` has no test coverage.
