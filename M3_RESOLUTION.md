# M3 & M9 Resolution Summary

## Changes Made Across All Pods

### Parent Repo (Cybreach-module2)

**Commit:** Resolve M3 — establish Alpha as canonical connector registry owner; add unified connector framework contract

- `contracts/CONNECTOR_FRAMEWORK.md` — Documents the connector registry ownership model:
  - **Alpha** owns the canonical `connectors` table and `/api/v2/connectors/*` API
  - **Gamma** owns only local `webhook_connector_credentials` (its per-connector ingest secret + HMAC flag) and `webhook_health` observability
  - **Delta** owns only local `platform_connector_health` dashboard metadata
  - All pods must treat Alpha as the source of truth

- `contracts/cybreach_service.proto` — Unified gRPC service contract for all inter-pod communication
  - `ConnectorRegistryService` (Alpha)
  - `NormalizationService` (Gamma)
  - `RevalidationService` (Gamma)
  - `VerdictPublisherService` (Delta)

- `contracts/README.md` — Updated to reference the new connector framework and gRPC contracts

---

### Pod Alpha (alvinalobo/VALIDATOR)

**Commit:** Declare Alpha as canonical connector registry owner in the actual Alpha submodule

- `rule ingestion/app/api/connector_routes.py`
  - Added `/api/v2/connectors/ownership` endpoint that declares Alpha as the canonical owner
  - Documents that this is the single authoritative registry for all pods

---

### Pod Gamma (Ayush-Sonwane/cybreach_pod_gamma)

**Commit:** `4c41838` remove the duplicate canonical Gamma connector table so Alpha remains the only registry owner

- `ocsf_normalizer/migration/002_webhook_connector.sql`
  - **Removed** the `CREATE TABLE connectors` statement that created a duplicate registry
  - Kept only local tables for observability; the canonical registry is Alpha's

**Follow-up commit:** `26bae99` close the migration/code disagreement

The commit above only edited the migration. `webhook/repository.py` still ran
`CREATE TABLE IF NOT EXISTS connectors (...)` on open and `create_connector()`
still wrote to it, so the running service recreated the very table the migration
had stopped declaring - the stated architecture and the actual schema diverged,
and a merged database could still collide. No test caught it, because each test
builds its own schema on an isolated `tmp_path` SQLite file, so a green suite was
not evidence either way.

Gamma's local table is now **`webhook_connector_credentials`**, renamed rather
than deleted, because `/api/v2/webhook/ingest` authenticates against a
per-connector shared secret and HMAC flag that Alpha's registry does not model;
"delete the table" would have broken ingest. Existing databases are migrated in
place on open via `ALTER TABLE ... RENAME TO` (SQLite also propagates this into
`webhook_health`'s foreign key), so connectors and their counters survive, the
stale `idx_connectors_tenant` index is dropped, and the B11 `tenant_id` column is
added. A fresh database never creates a table named `connectors` at all. Gated by
`ocsf_normalizer/tests/test_m3_table_rename.py` (5 cases, built against a real
pre-rename database).

---

### Pod Delta (CyBreach-Validator/verdict-platform)

**Commit:** Update Delta's connector reads to prefer the Alpha canonical registry and mark the local table as dashboard-only

- `backend/app/services/connector_service.py`
  - Updated `get_all_connectors()` to call Alpha's `/api/v2/connectors/health` as the authoritative source
  - Falls back to local `platform_connector_health` table only if Alpha is unavailable
  - Added comment documenting that Delta's table is dashboard-only metadata, not the canonical registry

---

## Architecture After Resolution

```
┌─────────────────────────────────────────────────────┐
│         Pod Alpha (VALIDATOR)                       │
│  ┌─────────────────────────────────────────────┐   │
│  │ Canonical Connector Registry                │   │
│  │ • Table: connectors                         │   │
│  │ • API:   /api/v2/connectors/register        │   │
│  │ • API:   /api/v2/connectors/health          │   │
│  │ • gRPC:  ConnectorRegistryService           │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
         ↑                   ↑                   ↑
         │ (reads only)      │ (reads only)     │ (reads only)
         │                   │                  │
┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐
│   Pod Beta      │  │ Pod Gamma    │  │   Pod Delta      │
│ (Validation     │  │ (Normalizer) │  │  (Verdict        │
│  Engine)        │  │              │  │   Publisher)     │
│ • Queries rules │  │ • webhook_   │  │ • platform_      │
│   via Alpha     │  │   health     │  │   connector_     │
│                 │  │   (local)    │  │   health (local) │
└─────────────────┘  └──────────────┘  └──────────────────┘
```

## Status

✅ **M3 Closed**: Single connector registry owned by Alpha. Gamma and Delta no longer maintain duplicate canonical registries.

✅ **M9 Status**: gRPC contracts are now defined and unified across all pods in `cybreach_service.proto`.

## How to Apply

Run this in the parent repo to pull the latest submodule commits:

```bash
git submodule update --init --recursive
```

This will fetch:
- `alvinalobo/VALIDATOR` @ latest (Alpha owns the canonical registry)
- `Ayush-Sonwane/cybreach_pod_gamma` @ latest (Gamma removed duplicate table)
- `CyBreach-Validator/verdict-platform` @ latest (Delta reads from Alpha)
