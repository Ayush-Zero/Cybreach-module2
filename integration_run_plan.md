# CyBreach Module 2 - Integration Run Plan

- **Date:** 2026-09-24
- **Scope:** First integrated run of all four pods (Alpha, Beta, Gamma, Delta) as one environment.
- **Run mode:** **HYBRID** - Docker Compose only for
  infrastructure (PostgreSQL 16, Redis, Kafka); pod services run individually via `uvicorn`.
  See `CyBreach_Module2_TheValidator.txt` - "Local Development Setup" (~line 862): venv ->
  `pip install -r requirements.txt` -> infra `docker compose` -> alembic migrations -> pytest ->
  `uvicorn` per service (e.g. Validation Engine on port 8002) -> verify `/health`.
- **Conflict source:** `conflict.md` (2026-09-24 post-audit statuses) + new per-pod findings (`N-A#`/`N-B#`/`N-G#`/`N-D#`).

## Goal

One infra `docker compose up` boots KRaft Kafka + PostgreSQL + Redis; pod services run via `uvicorn`,
with the flow `evidence -> normalize -> validate -> classify -> publish` working over the plan's five
topics (`cybreach.evidence.v1`, `cybreach.verdicts.v2`, `cybreach.gap_closed.v2`,
`cybreach.revalidation.v1`, `cybreach.connector.health.v1`).

## Pod -> Directory Mapping

| Pod | Plan ownership | Repository directory |
| --- | --- | --- |
| Alpha | Rule Ingestion + Connector Framework | `VALIDATOR/` |
| Beta | Validation Engine + Outcome Classifier | `cybreach-module2-pod-beta/` |
| Gamma | OCSF Normalizer + Re-Validation Service | `cybreach_pod_gamma/` |
| Delta | Verdict Publisher + Frontend Dashboard + API Gateway | `cybreach_pod_delta/` |

---

## Tier 0 - Boot blockers (must fix before anything runs via uvicorn)

| Order | Conflict | Owner | Minimal fix |
| --- | --- | --- | --- |
| P1 | **N-B1** Beta syntax error (`services/validation_engine/ve_app/main.py:150-155`) | Beta | Delete the orphaned `def validate_evidence(` stub (lines 150-153); keep the real implementation at line 155 |
| P2 | **M7** Delta backend won't boot fresh: no `.env`, missing runtime deps (`kafka`, `slowapi`, `jose`, `alembic`) | Delta | Add `.env.example` + clear DB-URL error; declare all runtime deps in `requirements.txt` |
| P3 | **M1 + N-B3 + N-G5** port collisions (`8000` claimed 5x, `8003` x2 Gamma/Beta oc, `5173` x2 frontends) | Integration env (all) | One port registry for local uvicorn runs + frontends per plan local-dev example |
| P4 | **B10** two Kafka topologies both binding `9092` (Beta KRaft vs Delta ZooKeeper) | Integration env (infra only) | Single infra `docker-compose.yml` (postgres/redis/KRaft Kafka per Beta, retire Delta ZooKeeper) |

## Tier 1 - One bus + one set of cross-pod contracts (data must flow)

| Order | Conflict | Owner | Minimal fix |
| --- | --- | --- | --- |
| P5 | **B1** No pod uses the plan topic names (Delta: `verdict-events`/`evidence-events`; Beta: mock HTTP publisher) | All | Adopt the 5 plan topic names in every producer/consumer config |
| P6 | **B9** Delta's mis-shaped evidence consumers (`consumers/consumer.py`, `kafka/consumer.py`) read `rule_id`/`event` off `evidence-events` | Delta | Remove/replace them; the Validation Engine consumes the frozen v1.0 EvidenceEvent on `cybreach.evidence.v1` |
| P7 | **B2 + B3** Three incompatible verdict shapes; Delta publishes a payload that violates even its own contract | Delta (contract owner) | Publish exactly the plan v2.0 verdict (`action_id, verdict, confidence, causal_chain, mttd_seconds, matched_evidence_ref, regulatory_control_refs, content_hash`); one serialization path used by API, WebSocket, and Kafka |
| P8 | **B8** No rule-delivery seam from Alpha to Beta (Beta runs a local `DetectionRule` stub) | Alpha + Beta | Expose rule delivery (gRPC or `GET /api/v2/rules` + content-hash lookup); Beta consumes Alpha's output |
| P9 | **B13 + N-D1** Bare routes vs `/api/v2/*`; `kong.yml` upstream `host.docker.internal:8033` contradicts backend port `8000` | Delta | Standardize routes under `/api/v2/*`; fix Kong upstream to the real backend port; resolve host-port mapping contradictions |
| P10 | **B5 + B6** Confidence `95` (0-100) in Delta vs `0.0-1.0` in Beta; `rule_id` integer (Delta) vs string (Alpha/Beta) | Delta + Beta | Normalize confidence to `0.0-1.0`; `rule_id` = content-hash string (Alpha advances, Delta adopts) -- otherwise pydantic rejects cross-pod payloads |

### Pod ownership of the execution tasks

Each execution task belongs to the pod(s) listed here (matches the `Owner` column above):

- **Alpha (Rule Ingestion + Connector Framework):** P8 (rule-delivery seam - expose `GET /api/v2/rules` for Beta to consume).
- **Beta (Validation Engine + Outcome Classifier):** P1 (N-B1 syntax fix), P8 (consume Alpha's rules, not a local stub), P10 (confidence scale / `rule_id` type).
- **Gamma (OCSF Normalizer + Re-Validation):** P3 (port registry - normalizer/revalidation move to 8005/8006); otherwise no boot-task ownership for the first hybrid run (deferred to Tier 3).
- **Delta (Verdict Publisher + Dashboard + Gateway):** P2 (env/deps boot), P3 (port registry), P5 (canonical topic names), P6 (evidence consumers), P7 (v2.0 verdict serialization), P9 (`/api/v2/*` routes + Kong upstream/port), P10 (confidence 0-1, `rule_id` string).
- **Integration environment (infra):** P3 (port-registry coordination across pods), P4 (single infra compose - postgres/redis/KRaft Kafka), P5 (topic manifest shared with all pods).

## Tier 2 - Data correctness (same push, required for correct verdicts)

- **M11** one `causal_chain` shape (Alpha `array of string` vs Beta `List[CausalStep]`).
- **M12** one canonical `content_hash` (SHA-256, 64 hex chars) instead of Beta `integrity_hash` / Delta `verdict_hash`.
- **M2** one verdict spelling (`NoData`, not `"No Data"`).

## Tier 3 - Defer for the first hybrid run

- **Containerization milestone (N-B2, N-D3, m4)**: Beta zero Dockerfiles, Delta empty `backend/Dockerfile`,
  Gamma `ocsf_normalizer`/`revalidation_service` `.txt` stubs. NOT required for hybrid run (services run via
  uvicorn); optional milestone for a later full-Docker deployment.
- **B11** shared JWT / tenant scoping.
- **m7** secrets hygiene (hardcoded `admin/admin123`, `SECRET_KEY`, `validator_dev_pw`, committed `connectors.db`).
- **m8** SSRF allow-list on `clone_repo` + 422 on malformed `rule_query`.
- **M6** dependency pin reconciliation.
- **M5** `shared_registry/v1/` wiring.
- **M8** wallet credit/debit hooks (file exists but never invoked).
- **B7/B12/M3/M10** ownership dedupe (Beta duplicate `verdict_publisher` + `ve_app/connectors.py`; Alpha `Rule_Dependency_Tracker/app`; Delta `/rules`/`/connectors`).
- **m2/m3** migration dedupe + Beta week snapshots.
- **N-G1** Gamma `schema_engine/` duplicate subtree.
- **N-D2/N-D6/N-D7** Delta alembic chain inconsistency, consumer import loop, committed DB creds (correctness/security; not boot-blocking).

## Suggested port registry (hybrid local run)

| Service | Pod | Port |
| --- | --- | --- |
| PostgreSQL | infra | 5432 |
| Redis | infra | 6379 |
| Kafka (KRaft) | infra | 9092 |
| Rule Ingestion API | Alpha | 8001 |
| Validation Engine (ve_app) | Beta | 8002 (plan local-dev example) |
| Outcome Classifier (oc_app) | Beta | 8003 |
| Verdict Publisher (vp_app, stand-in) / Delta backend (canonical) | Beta / Delta | 8004 / 8000 |
| OCSF Normalizer | Gamma | 8005 |
| Re-Validation | Gamma | 8006 |
| Frontend dashboard (Delta) | Delta | 5173 |
| Frontend (Gamma, optional) | Gamma | 5174 |
| Kong (optional gateway) | Delta | 8010 proxy / 8011 admin |

## Verification of "run" (hybrid)

1. `docker compose up -d` (infra) -> postgres/redis/kafka healthy.
2. `uvicorn` per pod service (port registry above); verify each `/health` returns `{"status":"ok"[, "service":...]}`.
3. Produce a v1.0 evidence event on `cybreach.evidence.v1` -> observe a verdict on `cybreach.verdicts.v2`
   with valid `content_hash` -> confirm gap-closed on revalidate.
4. Confirm Beta `ve_app` starts (post N-B1 fix) and Delta routes (`/api/v2/*` or Kong) respond without 500s.

## Notes

- If P5-P10 are not done, the stack boots but data will not pass pod boundaries (schemas reject on each seam).
- Execution starts with P1-P2 (Beta syntax + Delta env/deps), then P3-P4 (port registry + infra compose).