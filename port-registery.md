# CyBreach Module 2 - Port Registry (Hybrid Local Run)

- **Date:** 2026-09-24
- **Run mode:** hybrid - infra in Docker Compose, services via `uvicorn` on the host.
- **Policy:** one unique host port per service; infra ports fixed (5432/6379/9092).
- **Supersedes:** pod-local compose port maps (`M1`, N-B3, N-G5).

| Service | Pod | Port |
| --- | --- | --- |
| PostgreSQL 16 | infra | 5432 |
| Redis 7 | infra | 6379 |
| Kafka (KRaft, single broker) | infra | 9092 |
| Rule Ingestion API | Alpha | 8001 |
| Validation Engine (`ve_app`) | Beta | 8002 |
| Outcome Classifier (`oc_app`) | Beta | 8003 |
| Verdict Publisher (`vp_app`) | Beta | 8004 |
| OCSF Normalizer | Gamma | 8005 |
| Re-Validation Service | Gamma | 8006 |
| Kong API Gateway (optional) | Delta | 8010 (proxy) / 8011 (admin) |
| Delta backend (canonical publisher) | Delta | 8000 |
| Delta frontend dashboard | Delta | 5173 |
| Gamma frontend (optional) | Gamma | 5174 |

## Notes

- `ve_app` on `8002` follows the txt plan local-dev example.
- Beta `oc_app` kept on `8003`; Gamma revalidation moved to host `8006` (no `8003` collision - N-B3/N-G5).
- Beta `vp_app` on `8004` is the duplicate publisher (B7; retained only as stand-in); Delta backend on `8000` is canonical per B13/frontend (`api.ts:4`).
- Kong, when enabled, proxies `8010` -> Delta backend; admin on `8011`.
- Gamma frontend uses `5174` to avoid the `5173` collision with Delta (M1).
- Infra ports match the single root `docker-compose.yml` (P4).