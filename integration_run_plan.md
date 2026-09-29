# CyBreach Module 2 - Integration Run Plan

- **Date:** 2026-09-30
- **Scope:** First integrated run of all four pods (Alpha, Beta, Gamma, Delta) as one environment.
- **Run mode:** **HYBRID** - Docker Compose only for
  infrastructure (PostgreSQL 16, Redis, Kafka); pod services run individually via `uvicorn`.
  See `CyBreach_Module2_TheValidator.txt` - "Local Development Setup" (~line 862): venv ->
  `pip install -r requirements.txt` -> infra `docker compose` -> alembic migrations -> pytest ->
  `uvicorn` per service (e.g. Validation Engine on port 8002) -> verify `/health`.
- **Conflict source:** `conflict.md` (re-verified against the pod working trees on 2026-09-30).
- **State:** every previously `PATCHED` item was re-checked in the pod repositories and removed from both
  this plan and `conflict.md` only where the code actually satisfies it. Four `PATCHED` claims did not
  survive re-verification and are back on the open list with contradicting evidence: the plan's
  `POST /api/v2/validate` does not exist, the 422 on malformed `rule_query` was never implemented,
  Gamma's root manifest regressed to loose pins, and Delta's were never bumped to match Gamma.
- **Update (2026-09-30):** **Beta, Delta and Gamma were resolved**; Alpha was left untouched. Fully-satisfied
  items removed from this plan: **M2**, **M11**, **m4**, **m5**, **N-D18**, **N-D19** (identifiers are
  unchanged, so the numbers are now gaps). **P10** is now Alpha-only, **P3/P5/P8/P9** are unchanged because
  their blockers are all Alpha-side or architectural. Three items shrank rather than disappeared, because
  only part of each was fixable without Alpha: **B6** (Delta conforms), **m7** (Beta is clean, Delta's
  credentials are still in git history) and **m8** (Delta now returns 422). One undeclared regression was
  also fixed: commit `962c112` broke collection of all 52 Delta tests with a `NameError` on import.
- **Update (2026-09-30, second pass):** every item whose fix did not require an Alpha change is now done
  and this plan is re-pointed at what is genuinely left. **P4 (B10, the root infra compose) and P9 (B13, the
  `/api/v2` surface) are closed** and marked struck below: the root infra stack exists, `topics.yaml` is the
  single topic manifest, Beta consumes `cybreach.evidence.v1`, `contracts/` is the single registry, the API
  surface is `/api/v2` in both non-Alpha pods, and the three editable pods share one pinned core set.
  **P3, P5, P7, P8 and P10 remain, every one of them blocked on Alpha**, plus tenant scoping across all four
  pods. No Alpha file was modified in either pass.

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
| P3 | **M1 PARTIAL** - Beta, Delta and Gamma bind what the registry assigns. **Alpha binds 8000** (`rule ingestion/Dockerfile:9,11`, `app/README.md:26,39,75,105`) while the registry assigns it 8001 (`port-registery.md:13`), so Alpha collides with the canonical publisher on 8000 and is unreachable at its registry port. Beta's client default was deliberately left at the registry's 8001 rather than repointed to 8000, because 8000 is Delta's and moving Beta there would trade a documented mismatch for a real collision | Integration env (Alpha) | Move Alpha to 8001 in its Dockerfile and README. 8000 is Delta's, so the registry is right and Alpha is the thing that must move |
| ~~P4~~ | ~~**B10** - one shared bus~~ **DONE.** The root `docker-compose.yml` provisions PostgreSQL 16, Redis 7.2, KRaft Kafka and kafka-ui and declares the `m2_infra` network; Beta's duplicate pod-local infra compose is deleted and its three application services attach to that network by service name. All three pods read the broker from `KAFKA_BOOTSTRAP_SERVERS` | - | - |

## Tier 1 - One bus + one set of cross-pod contracts (data must flow)

| Order | Conflict | Owner | Minimal fix |
| --- | --- | --- | --- |
| P5 | **B1 PARTIAL - Alpha is the only gap.** `topics.yaml` is the single manifest and all three editable pods read it via `M2_TOPICS_PATH` with a test holding them to it; the root stack exists; Beta's `KafkaConsumer` runs from the app lifespan; the runbooks are repointed. **Alpha publishes nothing to `cybreach.evidence.v1`**, so the first data flow still has no producer | Alpha | Alpha publishes evidence events to `cybreach.evidence.v1`. The consumer, the manifest and the bus are all in place |
| P7 | **B2 PARTIAL - Alpha is the only gap.** The frozen schema is in the shared registry; Delta enforces it on every publish (and now resolves it from the registry rather than a path that pointed at a non-existent file); Beta's `test_frozen_schema.py` gates the real producer payload for all four verdict values and the workspace suite cross-checks both pods against the registry. **Alpha still ships the pre-v2.0 shape** - `contracts/verdict schema/verdict_schema.json:7-63` omits `regulatory_control_refs` and `content_hash` | Alpha | Alpha adopts the frozen v2.0 field list and adds a conformance test |
| P8 | **B8 PARTIAL - Alpha is the only gap.** Beta's half is done: no `str()`-coercion of `detection_logic`, batch validation resolves rules through the same path as single validation, fetch failure is caught/logged/bounded and reported via `ALPHA_RULES_UNAVAILABLE`, and `ALPHA_RULES_URL` is env-injected. **Alpha's store is still a module-level dict** that no DB session reads, so a restart empties it, and Alpha still binds 8000 rather than the 8001 Beta calls | Alpha | Persist the store behind the existing `detection_rules` table; bind 8001 |
| ~~P9~~ | ~~**B13** - one `/api/v2` surface~~ **DONE for Beta and Delta.** `POST /api/v2/validate` exists and is flat, Beta serves `/api/v2/validate`, `/api/v2/validate/batch`, `/api/v2/classify` and `/api/v2/publish`, and the plan's endpoint list is asserted to resolve against both assembled apps with the old paths asserted absent. Alpha's two paths were already `/api/v2`-prefixed | - | - |
| P10 | **B6 PARTIAL** - Delta's verdict-side surface is string-keyed on the content hash and **both** of its joins now agree. **Alpha assigns `rule_id=parsed_dict.get("rule_id") or "UNKNOWN"`** rather than the digest, so the whole remaining gap is on the Alpha side | Alpha | Alpha assigns the content-hash id |

### Pod ownership of the execution tasks

- **Alpha (Rule Ingestion + Connector Framework):** P7 (adopt the frozen v2.0 verdict contract), P8 (persist the rule store, bind the registry port), P10 (assign the canonical `rule_id`), P5 (publish `cybreach.evidence.v1`). Alpha was not modified in either 2026-09-30 pass.
- **Beta (Validation Engine + Outcome Classifier):** done as of the second 2026-09-30 pass - the `cybreach.evidence.v1` consumer, the `str()`-coercion fix, the batch path, fetch-failure handling, and the `/api/v2` routes are all in place and test-gated. Beta's contract-field gate, Dockerfiles and pin alignment are also in.
- **Gamma (OCSF Normalizer + Re-Validation):** done - the connector-registration admin token (**N-G10**) and the registry repointing. Port conformance was already correct.
- **Delta (Verdict Publisher + Dashboard + Gateway):** done - the flattening of `/api/v2/validate` and the registry-path fix. Delta's contract enforcement, single serializer, JWT route gating, env-only secrets, squashed migration chain, Dockerfile and CI were already in place; the Docker image has still never been built (no Docker engine in this environment).
- **Integration environment (infra):** done for everything not owned by Alpha - M1's registry-vs-Alpha port question is the only port item left and it is an Alpha change; the root infra compose (P4), the shared topic manifest (P5), the pin set and the contract registry (M5) are all done.

## Tier 2 - Data correctness (same push, required for correct verdicts)

- **B2's Alpha half and B6's Alpha half are the two contract items still blocking a clean cross-pod verdict**; they are tracked in Tier 1 (P7, P10) and are not repeated here.
- ~~**M11** one `causal_chain` shape~~ and ~~**M2** one verdict spelling~~ were resolved on 2026-09-30 and are removed. `/classify` now returns `causal_chain` as `List[str]` and the dashboard filter, the verdict badge and `API_REFERENCE.md` all use the canonical `NoData`.

## Tier 3 - Defer for the first hybrid run

- **B11** shared JWT **and tenant scoping.** Delta's authentication half is done - every route outside a 3-entry public allowlist requires a JWT, enforced by `tests/test_auth_coverage.py:33-38` walking the OpenAPI schema, with env-only secrets - and Gamma's connector-registration half (the second Gamma item under B11) is now done too: `POST /api/v2/webhook/connectors` requires an env-only `X-Admin-Token`. The two remaining halves are not: there is **no `tenant_id` column on any table in any pod and no tenant filtering on any query**, and Alpha, Beta and Gamma have no shared JWT issuer. Tenant scoping is a migration plus per-query filtering, not a route guard.
- **m7** secrets hygiene. The working trees are now clean in all four pods: Beta's compose takes `POSTGRES_USER`/`POSTGRES_PASSWORD` from the environment with no default and aborts if either is unset, and `.env` is gitignored with `.env.example` as the tracked template. What remains is both the old (`postgres:vyom`) and newer (`validator_dev_pw`) Delta credentials in **git history**, which cannot be removed without a history rewrite - or a formal rotation with the exposure documented. Two smaller Alpha literals: `tests/test_alembic_migrations.py:26` and `sqlite:///./rules.db` in the orphaned `Rule_Dependency_Tracker/app/database.py:4`.
- **m8** SSRF allow-list on `clone_repo`. Delta's half is done - `MalformedRuleQuery` is caught at `app/api/validator.py:29-38` and returned as 422, so a malformed `rule_query` no longer surfaces as a 500. Alpha's half is not: `clone_repo` (`app/api/rules.py:107-136`) has zero validation - the only check anywhere is a Pydantic validator at `app/models/rule_models.py:75-80` that accepts any `http(s)` host or local path, with no allow-list and no private-IP or loopback guard.
- ~~**M6** dependency pins~~ **done for the three editable pods** on 2026-09-30: Beta and Delta align with Gamma on `fastapi==0.141.1, pydantic==2.13.4, uvicorn==0.52.2, pytest==9.1.1, httpx==0.28.1`, `requirements.lock` pins the contract-test floor, and the workspace suite fails if the core set drifts across the pods. **Alpha remains entirely unpinned** apart from a `cryptography>=46.0.0` floor, which cannot finish without Alpha.
- ~~**M5** contract registry~~ **done** on 2026-09-30: `contracts/` at the workspace root is the single registry, Gamma publishes into it, Delta and Beta read from it, and `test_cross_pod_integration.py` asserts existence, strictness, and field-set agreement across both publishers. `shared_registry/v1/windows_auth.json` is still tracked and read by nobody; it belongs to Module 1's seam rather than this one and is left in place rather than deleted on a guess.
- **B7/B12/M10** ownership dedupe: Beta's duplicate `services/verdict_publisher/` is retained deliberately (B7 recorded it as a name conflict between the plan's "Verdict Publisher" and Delta's ownership; retirement needs a plan decision, and the service is now functionally complete). Beta's `ve_app/connectors.py` (a hard import for `rule_execution.py:8`); Alpha's orphaned `Rule_Dependency_Tracker/app/main.py` alongside the live `app/services/rule_dependency_tracker.py`; Delta's `/rules`/`/connectors`; Alpha's dead `app/services/rule_models.py` and `app/services/rule_pipeline.py`.
- **M3** three connector registries (Alpha `/api/v2/connectors/*`, Delta `/connectors`, Gamma `/api/v2/webhook/connectors`) and an unresolved `connectors` DDL owner - Gamma's `ocsf_normalizer/migration/002_webhook_connector.sql:7` creates a table named `connectors` while Delta renamed its own to `platform_connector_health` to avoid the collision. Unchanged: closing this needs a plan decision about who owns the connector registry and, in a merged database, the `connectors` table.
- ~~**m3** Beta's week snapshots and migration~~ **done** on 2026-09-30: `Week1`-`Week11` are deleted (collection unchanged at 221 tests, proving they were inert) and `0001` now creates the full frozen column set including `target_asset_ref`, `expected_observable`, `regulatory_control_refs` and `content_hash`. The migration was extended in place because it is the initial baseline with no deployed schema depending on the narrower form.
- **m6** Alpha's connector vendor enum shares no value with its runtime registry keys: `connector_specification.json:17-23` declares capitalized display names while every runtime key is a lowercase slug (`crowdstrike_logscale`, `sentinel`, `qradar`, `splunk`, `elastic`), and `tests/test_connector_contract.py:49` asserts `vendor="crowdstrike"`, which `config_validation.py:65` rejects.
- **m1** Alpha's `/health` is a hardcoded `{"status": "healthy"}` (`app/main.py:102`) that probes no dependency, plugin or database. Every other pod returns `{"status":"ok","service":...}`.
- ~~**m4/m5 (Gamma hygiene)**~~ resolved on 2026-09-30 and removed: the 0-byte root `.dockerignore` is deleted, `ocsf_normalizer/.gitignore.txt` is now a real `.gitignore` so its rules apply, all three manifests agree on `httpx >= 0.27.0`, and the README no longer claims a scheduler that does not exist or a root `pytest.ini` that targets both suites.
- ~~**N-B2** containerization~~ **done** on 2026-09-30: Beta has a `Dockerfile` per service and its compose defines the three app services attached to the root stack's `m2_infra` network; the pod's duplicate infra compose is deleted. Delta has a real `backend/Dockerfile` and `backend/.dockerignore` at the correct build context, but **it has never been built** - no Docker engine was available - so the image is verified only by the checks CI performs. In the hybrid run the services run via `uvicorn`, so the images are packaging readiness rather than a runtime dependency.
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

1. `docker compose up -d` (infra) -> postgres/redis/kafka healthy. The root `docker-compose.yml` now exists (P4 done) but was **not booted**: no Docker engine was available, so the file is YAML-validated only. Beta's duplicate pod-local infra compose is deleted as of the second pass; the root stack is the single source.
2. `uvicorn` per pod service (port registry above); verify each `/health` returns `{"status":"ok"[, "service":...]}`. **Alpha returns `{"status": "healthy"}` and probes nothing.** Beta, Delta and now Gamma all return the canonical shape.
3. Produce a v1.0 evidence event on `cybreach.evidence.v1` -> observe a verdict on `cybreach.verdicts.v2` with a valid `content_hash` -> confirm gap-closed on revalidate.
   **This step still cannot run end to end, but the seam is now one-sided.** Beta subscribes to `cybreach.evidence.v1` (opt-in via `KAFKA_EVIDENCE_ENABLED`, dead-letter topic, commit-after-verdict, rule cache) and Delta publishes into `cybreach.verdicts.v2`. The producer is missing: **Alpha publishes nothing to `cybreach.evidence.v1`** (P5). The payload side stays proven: Delta validates every publish against the frozen schema through one serializer, and Beta's digest is byte-identical to Delta's.
4. Confirm Beta `ve_app` starts and Delta's routes (`/api/v2/*` or via Kong) respond without 500s. The 422 conversion is in (m8's Delta half), so a malformed `rule_query` returns 422 rather than 500; `POST /api/v2/validate` now exists at the flat path (P9). A runtime check of the full chain was not performed because Docker is unavailable.

## Notes

- If the Tier 0/1 items are not done, the stack boots but data will not pass pod boundaries: there is no bus to carry it and no subscriber to receive it.
- With the second pass, the remaining blockers to demonstrating the flow end to end are all Alpha-side or architectural: Alpha must publish `cybreach.evidence.v1` (P5), adopt the frozen v2.0 verdict contract (P7), assign the content-hash `rule_id` (P10), persist its rule store and bind 8001 (P8), and, when it does so, the seam is complete.
- Alpha's `GET /api/v2/rules` resolves the B8 blocker in shape only: it serves an in-memory dict, so an Alpha restart makes Beta silently validate everything as `NoData`. It also binds 8000 while Beta calls the registry's 8001. Persist the store and move Alpha onto 8001 before treating the seam as reliable.
- Delta's contract work is not the risk it was. One serializer feeds the WebSocket broadcast, the Kafka publish and the REST response from the same dict, every publish is schema-validated against the registry copy of the frozen schema, and `content_hash` covers the published payload and is re-derived on demand at `GET /api/v2/audit-logs/verify/{verdict_id}`. What is still unproven cross-pod is Alpha's adoption of the contract.
- Tier 0 is now a single port question and nothing else: Alpha owns it. Beta, Delta and Gamma bind what the registry assigns.

## Verification status (2026-09-30, second pass)

| Suite | Command | Result |
| --- | --- | --- |
| Root (cross-pod) | `python -m pytest tests/ -q` | **31 passed** (8 contract + 23 integration, 0 skipped) - topic manifest ownership/usage, pod topic/broker resolution with and without `M2_TOPICS_PATH`/`M2_CONTRACTS_PATH`, Beta+Delta plan endpoint lists, registry consistency, M6 pin agreement; real Beta/Delta payloads validate against the registry schema |
| Beta | `python -m pytest -q` (three services) | **256 passed**, 2 pre-existing Redis-dependent failures in `test_cache.py` |
| Delta | `pytest` | **54 passed** (was 52: `test_api_surface.py` added to guard the plan endpoint list) |
| Gamma | `python run_tests.py -q` | **4411 + 43 passed** (normalizer + revalidation) |
| Cross-pod | - | Beta/Delta digest agreement at `services/validation_engine/tests/test_verdict_integrity.py:163-192`; Beta's `test_frozen_schema.py` gates the real producer payload against the registry schema for all four verdict values |

Not verified: no live PostgreSQL/Kafka/Redis (Docker unavailable, compose YAML-validated only); Alpha was not
modified this round; Delta's Docker image has never been built; Delta's frontend has no `node_modules` so its
TypeScript build could not be run; Gamma's `WalletClient` has no test coverage.
