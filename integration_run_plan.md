# CyBreach Module 2 - Integration Run Plan


- **Scope:** First integrated run of all four pods (Alpha, Beta, Gamma, Delta) as one environment.
- **Run mode:** **HYBRID** - Docker Compose only for
  infrastructure (PostgreSQL 16, Redis, Kafka); pod services run individually via `uvicorn`.
  See `CyBreach_Module2_TheValidator.txt` - "Local Development Setup" (~line 862): venv ->
  `pip install -r requirements.txt` -> infra `docker compose` -> alembic migrations -> pytest ->
  `uvicorn` per service (e.g. Validation Engine on port 8002) -> verify `/health`.
- **Conflict source:** `conflict.md` (re-verified against the pod working trees on 2026-09-30).


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
| ~~P3~~ | ~~**M1** - Alpha bound 8000, not the registry's 8001~~ **DONE (2026-09-30, third pass).** Alpha's `rule ingestion/Dockerfile` and `app/README.md` now bind and document 8001; a scan of `cybreach_pod_alpha/rule ingestion` finds no remaining `8000` reference. 8000 remains Delta's canonical publisher port, so the registry was right and Alpha was the thing that moved | - | - |
| ~~P4~~ | ~~**B10** - one shared bus~~ **DONE.** The root `docker-compose.yml` provisions PostgreSQL 16, Redis 7.2, KRaft Kafka and kafka-ui and declares the `m2_infra` network; Beta's duplicate pod-local infra compose is deleted and its three application services attach to that network by service name. All three pods read the broker from `KAFKA_BOOTSTRAP_SERVERS` | - | - |

## Tier 1 - One bus + one set of cross-pod contracts (data must flow)

| Order | Conflict | Owner | Minimal fix |
| --- | --- | --- | --- |
| P5 | **B1 PARTIAL - Alpha is the only gap.** `topics.yaml` is the single manifest and all three editable pods read it via `M2_TOPICS_PATH` with a test holding them to it; the root stack exists; Beta's `KafkaConsumer` runs from the app lifespan; the runbooks are repointed. **Alpha publishes nothing to `cybreach.evidence.v1`**, so the first data flow still has no producer | Alpha | Alpha publishes evidence events to `cybreach.evidence.v1`. The consumer, the manifest and the bus are all in place |
| ~~P7~~ | ~~**B2** - Alpha's schema was pre-v2.0~~ **DONE (2026-09-30, third pass).** Alpha's pod schema is byte-identical to the frozen registry (`test_alpha_local_schema_matches_the_registry` in the root suite) and Alpha is gated by `rule ingestion/tests/test_verdict_contract.py` (12 conformance tests). `jsonschema==4.26.0` is pinned so the gate runs in a clean environment | - | - |
| ~~P8~~ | ~~**B8** - Alpha's store was a module-level dict and it bound 8000~~ **DONE (2026-09-30, third pass).** Alpha serves rules through `app/services/rule_store.py`: a `RuleStore` whose database backend persists into the `detection_rules` table its own migration creates when `DATABASE_URL` is set, whose in-memory backend is the same dict the offline suite seeds, and every write to the collection route goes through it. Gated by `tests/test_rule_store_persistence.py` (seam tests offline + a live-DB durability gate, skipped when PostgreSQL is unreachable). Alpha binds 8001 (P3). Beta's half (no `str()`-coercion, batch path, fetch-failure via `ALPHA_RULES_UNAVAILABLE`, env-injected `ALPHA_RULES_URL`) was already in place | - | - |
| ~~P9~~ | ~~**B13** - one `/api/v2` surface~~ **DONE for Beta and Delta.** `POST /api/v2/validate` exists and is flat, Beta serves `/api/v2/validate`, `/api/v2/validate/batch`, `/api/v2/classify` and `/api/v2/publish`, and the plan's endpoint list is asserted to resolve against both assembled apps with the old paths asserted absent. Alpha's two paths were already `/api/v2`-prefixed | - | - |
| ~~P10~~ | ~~**B6** - Alpha assigned `rule_id=... or "UNKNOWN"`~~ **DONE (2026-09-30, third pass).** Delta's verdict-side surface was already string-keyed on the content hash with both joins agreeing; Alpha now assigns the digest as `rule_id` on both the valid and invalid ingest paths, so `rule_id` and `content_hash` are the same string on every ingested rule | - | - |

### Pod ownership of the execution tasks

- **Alpha (Rule Ingestion + Connector Framework):** P5 (publish `cybreach.evidence.v1`) remains. P7 (frozen v2.0 verdict contract, byte-identical to the registry and test-gated), P8 (rule store persisted behind the `detection_rules` table) and P10 (canonical content-hash `rule_id`) were all closed on 2026-09-30. Alpha's hygiene items (m1 health probe, m6 vendor slugs, m8 SSRF guard, N-A1/N-A2/N-A4/N-A5) and its credential literals (m7's Alpha half) were closed in the same pass.
- **Beta (Validation Engine + Outcome Classifier):** done as of the second 2026-09-30 pass - the `cybreach.evidence.v1` consumer, the `str()`-coercion fix, the batch path, fetch-failure handling, and the `/api/v2` routes are all in place and test-gated. Beta's contract-field gate, Dockerfiles and pin alignment are also in.
- **Gamma (OCSF Normalizer + Re-Validation):** done - the connector-registration admin token (**N-G10**) and the registry repointing. Port conformance was already correct.
- **Delta (Verdict Publisher + Dashboard + Gateway):** done - the flattening of `/api/v2/validate` and the registry-path fix. Delta's contract enforcement, single serializer, JWT route gating, env-only secrets, squashed migration chain, Dockerfile and CI were already in place; the Docker image has still never been built (no Docker engine in this environment).
- **Integration environment (infra):** done - the root infra compose (P4), the shared topic manifest (P5), the pin set and the contract registry (M5) are all in place, and M1's port mismatch was closed by moving Alpha to 8001.

## Tier 2 - Data correctness (same push, required for correct verdicts)

- The two contract items that blocked a clean cross-pod verdict (**B2's Alpha half and B6's Alpha half**) were both closed on 2026-09-30 (Tier 1, P7/P10) and are not open work any more.
- ~~**M11** one `causal_chain` shape~~ and ~~**M2** one verdict spelling~~ were resolved on 2026-09-30 and are removed. `/classify` now returns `causal_chain` as `List[str]` and the dashboard filter, the verdict badge and `API_REFERENCE.md` all use the canonical `NoData`.

## Tier 3 - Defer for the first hybrid run

- **B11** shared JWT **and tenant scoping.** Delta's authentication half is done - every route outside a 3-entry public allowlist requires a JWT, enforced by `tests/test_auth_coverage.py:33-38` walking the OpenAPI schema, with env-only secrets - and Gamma's connector-registration half (the second Gamma item under B11) is now done too: `POST /api/v2/webhook/connectors` requires an env-only `X-Admin-Token`. The two remaining halves are not: there is **no `tenant_id` column on any table in any pod and no tenant filtering on any query**, and Alpha, Beta and Gamma have no shared JWT issuer. Tenant scoping is a migration plus per-query filtering, not a route guard.
- **m7** secrets hygiene. The working trees are now clean in all four pods: Beta's compose takes `POSTGRES_USER`/`POSTGRES_PASSWORD` from the environment with no default and aborts if either is unset, and `.env` is gitignored with `.env.example` as the tracked template. Alpha's two literals (`tests/test_alembic_migrations.py` now reads `DATABASE_URL`, and the `sqlite:///./rules.db` was deleted with the orphaned `Rule_Dependency_Tracker/app`, see M10) are gone. What remains is both the old (`postgres:vyom`) and newer (`validator_dev_pw`) Delta credentials in **git history**, which cannot be removed without a history rewrite - or a formal rotation with the exposure documented.
- ~~**m8** Alpha's `clone_repo` SSRF surface~~ **DONE (2026-09-30, third pass).** Delta's half (the 422 conversion, `app/api/validator.py:29-38`) was already in; Alpha's half added `assert_safe_repo_url` to `clone_repo`, rejecting `http(s)` hosts that resolve to loopback, link-local, private, reserved or multicast addresses while allowing local directory paths and git/ssh URLs, gated by `tests/test_rule_ssrf_guard.py` (12 cases including an ingest-endpoint 400).
- ~~**M6** dependency pins~~ **DONE.** Beta, Delta and Gamma align on `fastapi==0.141.1, pydantic==2.13.4, uvicorn==0.52.2, pytest==9.1.1, httpx==0.28.1`; Alpha's `rule ingestion/requirements.txt` is now pinned to the same core plus its pod-specific runtime deps, with `jsonschema==4.26.0` declared for the B2 gate. `requirements.lock` pins the contract-test floor, and the workspace suite fails if the core set drifts across all four pods.
- ~~**M5** contract registry~~ ** `contracts/` at the workspace root is the single registry, Gamma publishes into it, Delta and Beta read from it, Alpha's pod schema is byte-identical to it (B2), and `test_cross_pod_integration.py` asserts existence, strictness, and field-set agreement across both publishers. `shared_registry/v1/windows_auth.json` is still tracked and read by nobody; it belongs to Module 1's seam rather than this one and is left in place rather than deleted on a guess.
- **B7/B12/M10** ownership dedupe: Beta's duplicate `services/verdict_publisher/` is retained deliberately (B7 recorded it as a name conflict between the plan's "Verdict Publisher" and Delta's ownership; retirement needs a plan decision, and the service is now functionally complete). Beta's `ve_app/connectors.py` (a hard import for `rule_execution.py:8`); Delta's `/rules`/`/connectors`. M10's Alpha side is done: the orphaned `Rule_Dependency_Tracker/app` and the dead `app/services/rule_models.py` + `app/services/rule_pipeline.py` are deleted, and the keeper dependency tracker persists via `DEPENDENCY_TRACKER_PATH`.
- **M3** three connector registries (Alpha `/api/v2/connectors/*`, Delta `/connectors`, Gamma `/api/v2/webhook/connectors`) and an unresolved `connectors` DDL owner - Gamma's `ocsf_normalizer/migration/002_webhook_connector.sql:7` creates a table named `connectors` while Delta renamed its own to `platform_connector_health` to avoid the collision. Unchanged: closing this needs a plan decision about who owns the connector registry and, in a merged database, the `connectors` table.
- ~~**m3** Beta's week snapshots and migration~~ ** `Week1`-`Week11` are deleted (collection unchanged at 221 tests, proving they were inert) and `0001` now creates the full frozen column set including `target_asset_ref`, `expected_observable`, `regulatory_control_refs` and `content_hash`. The migration was extended in place because it is the initial baseline with no deployed schema depending on the narrower form.
- ~~**m6** connector vendor enum casing~~ **DONE (2026-09-30, third pass).** `connector_specification.json` now declares the lowercase slugs (`splunk`, `sentinel`, `elastic`, `qradar`, `crowdstrike_logscale`) that every runtime registration key uses, `tests/test_connector_contract.py` passes the slug form, and the spec, registry, validator and tests all use one identifier form.
- ~~**m1** Alpha's `/health`~~ **DONE (2026-09-30, third pass).** Alpha's `/health` now returns the cross-pod `{"status":"ok","service":"rule-ingestion"}` and actually probes the rule store on every call (a failing store returns `{"status":"degraded",...}`), gated by `tests/test_health_endpoint.py`.
- ~~**m4/m5 (Gamma hygiene)**~~ resolved on 2026-09-30 and removed: the 0-byte root `.dockerignore` is deleted, `ocsf_normalizer/.gitignore.txt` is now a real `.gitignore` so its rules apply, all three manifests agree on `httpx >= 0.27.0`, and the README no longer claims a scheduler that does not exist or a root `pytest.ini` that targets both suites.
- ~~**N-B2** containerization~~ ** Beta has a `Dockerfile` per service and its compose defines the three app services attached to the root stack's `m2_infra` network; the pod's duplicate infra compose is deleted. Delta has a real `backend/Dockerfile` and `backend/.dockerignore` at the correct build context, but **it has never been built** - no Docker engine was available - so the image is verified only by the checks CI performs. In the hybrid run the services run via `uvicorn`, so the images are packaging readiness rather than a runtime dependency.
- **M8 test coverage:** Gamma's `WalletClient` is wired into `revalidate()` (`revalidation_service/src/main.py:85-86,96-97,102-105` - debit 1, HTTP 402 when exhausted, refund on `UNCHANGED`, balance endpoint) but `revalidation_service/tests/` contains **no** wallet, 402 or credit test. The behaviour is unexercised.

## Suggested port registry (hybrid local run)

| Service | Pod | Port |
| --- | --- | --- |
| PostgreSQL | infra | 5432 |
| Redis | infra | 6379 |
| Kafka (KRaft) | infra | 9092 |
| Rule Ingestion API | Alpha | 8001 (registry; Alpha's Dockerfile and README now bind it after P3) |
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
2. `uvicorn` per pod service (port registry above); verify each `/health` returns `{"status":"ok"[, "service":...]}`. All four pods return the canonical shape now, and Alpha's probes its rule store (degraded on store failure).
3. Produce a v1.0 evidence event on `cybreach.evidence.v1` -> observe a verdict on `cybreach.verdicts.v2` with a valid `content_hash` -> confirm gap-closed on revalidate.
   **This step still cannot run end to end, but the seam is now one-sided.** Beta subscribes to `cybreach.evidence.v1` (opt-in via `KAFKA_EVIDENCE_ENABLED`, dead-letter topic, commit-after-verdict, rule cache) and Delta publishes into `cybreach.verdicts.v2`. The producer is missing: **Alpha publishes nothing to `cybreach.evidence.v1`** (P5). The payload side stays proven: Delta validates every publish against the frozen schema through one serializer, and Beta's digest is byte-identical to Delta's.
4. Confirm Beta `ve_app` starts and Delta's routes (`/api/v2/*` or via Kong) respond without 500s. The 422 conversion is in (m8's Delta half), so a malformed `rule_query` returns 422 rather than 500; `POST /api/v2/validate` now exists at the flat path (P9). A runtime check of the full chain was not performed because Docker is unavailable.

## Notes

- If the Tier 0/1 items are not done, the stack boots but data will not pass pod boundaries: there is no bus to carry it and no subscriber to receive it.
- With the third pass, the only remaining blocker to demonstrating the flow end to end is Alpha's evidence **producer**: Alpha must publish `cybreach.evidence.v1` (P5). The verdict contract (P7), the canonical `rule_id` (P10), the persisted rule store and port 8001 (P8) are all closed, so the seam is complete on every side except that one topic.
- Alpha's `GET /api/v2/rules` now serves the persisted store when `DATABASE_URL` is set (P8), so an Alpha restart no longer empties the rule set; Beta's client reaches a default Alpha build on the registry's 8001 (P3).
- Delta's contract work is not the risk it was. One serializer feeds the WebSocket broadcast, the Kafka publish and the REST response from the same dict, every publish is schema-validated against the registry copy of the frozen schema, and `content_hash` covers the published payload and is re-derived on demand at `GET /api/v2/audit-logs/verify/{verdict_id}`. Alpha's pod schema is byte-identical to the registry copy (B2), so there is no longer a pre-v2.0 contract to catch out a publisher.
- Tier 0 is now empty. Beta, Delta, Gamma and Alpha all bind what the registry assigns; the only parts of the run still open are the evidence producer (P5) and the deferred architecture decisions.

## Verification status (2026-09-30, third pass)

| Suite | Command | Result |
| --- | --- | --- |
| Root (cross-pod) | `python -m pytest tests/ -q` | **32 passed** - topic manifest ownership/usage, pod topic/broker resolution with and without `M2_TOPICS_PATH`/`M2_CONTRACTS_PATH`, Beta+Delta plan endpoint lists, registry consistency, M6 pin agreement, `test_alpha_local_schema_matches_the_registry` (Alpha's pod schema is byte-identical to the registry) |
| Alpha | `python -m pytest -q` (`rule ingestion/tests/`) | **220 passed, 1 skipped** (the live-DB gate pre-skip); B8 store seam tests run offline, and `test_rule_store_persistence.py` passes fully wired against live PostgreSQL when `DATABASE_URL` is set |
| Beta | `python -m pytest -q` (three services) | **256 passed**, 2 pre-existing Redis-dependent failures in `test_cache.py` |
| Delta | `pytest` | **54 passed** (was 52: `test_api_surface.py` added to guard the plan endpoint list) |
| Gamma | `python run_tests.py -q` | **4411 + 43 passed** (normalizer + revalidation) |
| Cross-pod | - | Beta/Delta digest agreement at `services/validation_engine/tests/test_verdict_integrity.py:163-192`; Beta's `test_frozen_schema.py` gates the real producer payload against the registry schema for all four verdict values |

Not verified: no live Kafka/Redis booted (Docker unavailable, compose YAML-validated only); the Alpha B8 live-DB
gate skipped unless `DATABASE_URL` is set (it passes when run against the local PostgreSQL); Delta's Docker
image has never been built; Delta's frontend has no `node_modules` so its TypeScript build could not be run;
Gamma's `WalletClient` has no test coverage.
