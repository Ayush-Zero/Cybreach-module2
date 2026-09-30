# M3 & M9 Resolution Summary

## Changes Made Across All Pods

### Parent Repo (Cybreach-module2)

**Commit:** Resolve M3 — establish Alpha as canonical connector registry owner; add unified connector framework contract

- `contracts/CONNECTOR_FRAMEWORK.md` — Documents the connector registry ownership model:
  - **Alpha** owns the canonical `connectors` table and `/api/v2/connectors/*` API
  - **Gamma** owns only local `webhook_health` observability
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

**Commit:** Remove the duplicate canonical Gamma connector table so Alpha remains the only registry owner

- `ocsf_normalizer/migration/002_webhook_connector.sql`
  - **Removed** the `CREATE TABLE connectors` statement that created a duplicate registry
  - Kept only the local `webhook_health` table for local observability
  - Added clear comments that this is local state only; the canonical registry is Alpha's

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
