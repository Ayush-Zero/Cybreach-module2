# CyBreach Module 2 - Connector Framework Contract

## Overview

This directory defines the **canonical connector registry contract** for the CyBreach platform. Per plan Section 7, Pod Alpha is the sole owner of the connector framework and registry.

All pods must use the Alpha connector registry as their source of truth for:
- Connector registration and configuration
- Connector health and status
- Connector capability discovery

## Canonical Registry

**Owner:** Pod Alpha (`cybreach_pod_alpha/rule ingestion`)

**API:** `POST /api/v2/connectors/register`, `GET /api/v2/connectors/health`, and related endpoints per `rule ingestion/app/api/connector_routes.py`.

**Database:** Table `connectors` (created and owned by Alpha's migrations). Definition:

```sql
CREATE TABLE connectors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    connector_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'UNKNOWN',
    configuration JSONB,
    health_status VARCHAR(20),
    last_checked TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

## Non-Canonical Registries (Deprecated)

### Pod Delta: `platform_connector_health`

**Location:** `backend/app/models/connector.py:14` 
**Status:** Local dashboard health only; no longer acts as a registry.  
**Resolution:** Delta reads connector metadata from Alpha via HTTP or gRPC; delta's `platform_connector_health` table stores only local dashboard-specific health metrics, not the canonical connector definition.

### Pod Gamma: `/api/v2/webhook/connectors`

**Location:** `ocsf_normalizer/src/main.py:393-451` (webhook connector endpoints)  
**Status:** Webhook-specific configuration only; a *client* of Alpha's registry.  
**Resolution:** Gamma webhook connectors are registered *through* Alpha's API (`/api/v2/connectors/register`). Gamma's `/api/v2/webhook/connectors` endpoints become read-only health views that resolve `connector_id` against Alpha's registry.

## Rules

1. **Single source of truth:** All connector registrations occur via Alpha's `/api/v2/connectors/register`.
2. **Other pods are clients:** Beta, Gamma, and Delta query connector status via Alpha's `/api/v2/connectors/health` HTTP API or via gRPC.
3. **Local health tracking:** Each pod may maintain local health counters (e.g., Gamma's `webhook_health` table, Delta's `platform_connector_health`), but these are *not* the authoritative connector registry.
4. **Cross-pod contract:** The `connectors` table definition and `/api/v2/connectors/*` API contract are frozen. Changes require cross-pod consensus.

## Migration Path

### Alpha (Pod Alpha)

- Owns the `connectors` table.
- Provides HTTP API at `/api/v2/connectors/register`, `/api/v2/connectors/health`.
- Provides gRPC service `ConnectorRegistryService` (contract in `cybreach_service.proto`).

### Gamma (Pod Gamma)

- Remove the `CREATE TABLE connectors` statement from `ocsf_normalizer/migration/002_webhook_connector.sql`.
- Update webhook connector registration to call Alpha's `/api/v2/connectors/register` when a webhook connector is first created.
- Keep the `webhook_health` table for local health tracking.
- Update `/api/v2/webhook/connectors` endpoints to query Alpha's registry.

### Delta (Pod Delta)

- Keep `platform_connector_health` for dashboard-local metrics only.
- Fetch the canonical connector list from Alpha's `/api/v2/connectors/health` or gRPC on startup.
- Update dashboard and API to use Alpha's connector data as the source of truth.

## Related

- Cross-pod service contract: `cybreach_service.proto`
- Message-bus topic manifest: `../topics.yaml`
