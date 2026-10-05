# Cybreach-module2

Cybreach main integration repo — aggregates all pod work as git submodules.

## Pod directory mapping

| Pod | Responsibility | Repository directory |
| --- | --- | --- |
| Alpha | Rule Ingestion + Connector Framework | `cybreach_pod_alpha/` |
| Beta | Validation Engine + Outcome Classifier | `cybreach_pod_beta/` |
| Gamma | OCSF Normalizer + Re-Validation Service | `cybreach_pod_gamma/` |
| Delta | Verdict Publisher + Frontend Dashboard + API Gateway | `cybreach_pod_delta/` |

## Demo

`demo/` drives the running stack: it starts the services, probes their health,
exercises each pod's real endpoints, and tails their logs. Every path is derived
from each script's own location, so the folder works from anywhere in the repo.
Run all commands from the **repo root**.

### Ports

| Port | Service | Pod |
| --- | --- | --- |
| 8000 | Verdict platform, REST + WebSocket | Delta |
| 8001 | Rule ingestion | Alpha |
| 8002 | Validation engine | Beta |
| 8004 | Verdict publisher | Beta |
| 8005 | OCSF normalizer | Gamma |
| 8006 | Revalidation service | Gamma |
| 8010 / 8011 | Kong gateway proxy / admin | Delta |
| 5173 | Dashboard (Vite dev server) | Delta |
| 5174 | Connector console (Vite dev server) | Gamma |
| 5432 / 6379 / 9092 / 8080 | Postgres / Redis / Kafka / Kafka UI | shared infra |

### Prerequisites

Infrastructure runs in Docker, services run on the host:

```powershell
Copy-Item .env.example .env      # then set POSTGRES_USER and POSTGRES_PASSWORD
docker compose up -d             # Postgres, Redis, Kafka (KRaft), Kafka UI
```

`.env` is required — `demo-env.ps1` fails loudly rather than defaulting the
database credentials, because guessing `postgres` fails with
`role "postgres" does not exist`.

### Environment

`demo/demo-env.ps1` is the single source of truth for the shared environment.
All six services share one HS256 `SECRET_KEY`, and each pod needs its own
`DATABASE_URL`, so two windows with different values produce 401s with no
obvious culprit. Dot-source it into any shell you intend to run from:

```powershell
. .\demo\demo-env.ps1
```

The leading dot matters — without it the variables land in a child scope and
vanish. It sets `SECRET_KEY`, the per-pod `DATABASE_URL`, the Kafka bootstrap,
`M2_TOPICS_PATH`, the Delta admin credentials, and the Beta live-bus flags
(`KAFKA_EVIDENCE_ENABLED`, `VERDICT_PUBLISH_ENABLED`, `ALPHA_RULES_URL`).

### Scripts

| File | Purpose |
| --- | --- |
| `demo-env.ps1` | Shared environment. Dot-source it; never run it standalone. |
| `start-services.ps1` | Launches the six services in separate windows, each dot-sourcing `demo-env.ps1`, teeing output to `demo/logs/<service>.log`. |
| `health-check.ps1` | Read-only probe of all six services plus the Beta Kafka consumer group and its lag. |
| `tail-logs.ps1` | Follow one service's log, or all six. |
| `seed-rule.ps1` | Ingests the fixture Sigma rules into Alpha so validation can return `Detected`. |
| `publish_evidence.py` | Publishes one evidence event to `cybreach.evidence.v1`, waits for Beta's verdict on `cybreach.verdicts.v2`, and re-derives its `content_hash`. |
| `normalize-event.ps1` | Feeds a raw vendor event to Gamma's normalizer and prints the canonical OCSF result. |
| `populate-delta-dashboard.ps1` | Exercises Delta's own `POST /api/v2/validate` so a verdict is persisted and appears in the dashboard. |
| `red-to-green.ps1` | Proves a detection gap, fixes the rule, and re-validates the same stored evidence. |
| `full-pipeline.py` | Runs every cross-pod seam that exists, as six independently runnable takes. |

#### Starting and checking services

```powershell
.\demo\start-services.ps1        # add -AppendLog to keep earlier output
.\demo\health-check.ps1
```

`health-check.ps1` reports Beta's consumer group separately because a healthy
`/health` on 8002 does **not** prove the consumer is running: without
`KAFKA_EVIDENCE_ENABLED=true` the thread never launches and no verdict is ever
produced while `/health` still returns ok.

Logs:

```powershell
.\demo\tail-logs.ps1                          # follow all six
.\demo\tail-logs.ps1 gamma-normalizer         # follow one
.\demo\tail-logs.ps1 gamma-normalizer -Dump   # print and exit
```

#### Seeding rules and publishing evidence

```powershell
.\demo\seed-rule.ps1
python .\demo\publish_evidence.py
```

`seed-rule.ps1` must be re-run after **every** Alpha restart. Alpha's
`/rules/search` serves from an in-memory dict, not from Postgres, so a rule row
is invisible to validation until the currently running process has ingested it.
Restarting Alpha empties the store and verdicts degrade to `NoData`.

`publish_evidence.py` needs no token — the broker is PLAINTEXT and the evidence
topic is not JWT-gated. It positions a reader at the end of the verdict topic
before publishing, so it prints only the verdict its own event causes, then
re-derives `content_hash` from the eight frozen contract fields to prove the
digest matches.


#### Normalizing vendor telemetry

```powershell
.\demo\normalize-event.ps1 -Vendor splunk            # summary line only
.\demo\normalize-event.ps1 -Vendor splunk -Json      # full OCSF event body
.\demo\normalize-event.ps1 -Vendor elastic -Json     # same endpoint, ECS input
.\demo\normalize-event.ps1 -Count 0 -Json            # whole fixture at once
```

`-Vendor` accepts `splunk`, `elastic`, `sentinel`, `qradar`, `logscale`. The
source format is detected from the payload rather than declared by the caller,
so one endpoint handles all five. OCSF class 3002 is Authentication.

`-Json` and `-Follow` are mutually exclusive: `-Follow` returns before the
request is sent, so it only tails the log.

#### Getting a verdict into the dashboard

```powershell
.\demo\populate-delta-dashboard.ps1
cd cybreach_pod_delta\frontend-dashboard; npm run dev    # http://127.0.0.1:5173
```

Sign in with the `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `demo-env.ps1`
(`demo` / `demo123` by default). Delta has no default credentials on purpose,
so login returns 401 until they are set.

#### Proving and closing a detection gap

```powershell
.\demo\red-to-green.ps1
```

Four steps: create a rule that looks for `cmd.exe` while the evidence contains
`powershell.exe` → validate → expect `Missed`; tighten the rule; then
`POST /verdicts/{id}/revalidate` → expect `Detected` with `gap_closed=true`.
Step 4 re-reads the event stored on the old verdict and re-runs it against the
rule's current query, so the comparison is over identical evidence rather than a
second, easier event. The script aborts if the verdict is not `Missed`, so a
gap is never faked. Superseded verdicts are retired, not deleted, and the audit
log records `REVALIDATED`.

### full-pipeline.py

Runs the whole set as six takes and prints the four cross-pod hops that do not
exist, rather than papering over them.

```powershell
python demo\full-pipeline.py -Preflight     # check services and Kafka, mutate nothing
python demo\full-pipeline.py -All          # every take, in order
python demo\full-pipeline.py -Take 5       # one take
python demo\full-pipeline.py -Take 1 -Json # full response bodies
```

| Take | Pod | What it exercises |
| --- | --- | --- |
| 1 | Gamma | Five vendor formats normalised to OCSF; format auto-detected |
| 2 | Alpha | Sigma fixture rules ingested; rule ids are content hashes |
| 3 | Beta | Evidence published to the bus, validated, verdict on `cybreach.verdicts.v2` |
| 4 | Delta | `POST /api/v2/validate` persisted to Postgres and pushed over the WebSocket |
| 5 | Delta | Red-to-green: `Missed` → rule tightened → `Detected`, `gap_closed=true` |
| 6 | Gamma | Normalisation drift: `IMPROVED` → `UNCHANGED` (refunded) → `DEGRADED` |

Takes 2, 3 and 6 depend on state produced by an earlier take and run it
automatically, so any single take is runnable on its own. Options: `-Count`
(fixture records per vendor, `0` for all), `-Json` (full bodies), `-Wait`
(seconds to wait for a verdict), `-Force` (run despite a failed preflight).

Read the output before trusting it:

- **Take 3's confidence is a flat `0.9`.** Alpha-sourced rules always arrive
  with `keywords=[]` (`ve_app/main.py:222`), so `compute_confidence` returns
  early. `Detected` means a rule with an identical MITRE technique existed —
  `expected_observable` is never compared to anything on that path.
- **Take 3's verdict does not reach the dashboard.** Delta is a producer on
  `cybreach.verdicts.v2` and never consumes it; its dashboard reads Delta's own
  Postgres. That is what take 4's `POST /api/v2/validate` is for.
- **Take 5's gap is "a rule exists but does not match", not "no rule exists."**
  `verdict_events.rule_id` is a foreign key, so a technique with zero rules
  cannot be filed as `Missed` at all.
- **Take 6 is not take 5.** Gamma's revalidation service diffs two OCSF
  snapshots and returns `UNCHANGED` / `IMPROVED` / `DEGRADED`. It has no
  `Detected` / `Missed` verdict and never calls Beta's publisher.


## Adding your pod as a submodule

If you are a pod in-charge, add your repository here as a submodule using the `cybreach_pod_<pod>` naming convention:

```powershell
git submodule add <your-git-repo-url> cybreach_pod_<pod>
```

Example (Gamma):

```powershell
git submodule add https://github.com/Ayush-Sonwane/cybreach_pod_gamma cybreach_pod_gamma
```

This:

- clones your repo into the mapped directory,
- records the remote URL in `.gitmodules`,
- sets the working tree to your repo's default branch `HEAD`.

Commit the resulting `.gitmodules` and submodule entry, then push:

```powershell
git add .gitmodules <directory-name>
git commit -m "Add <pod> submodule"
git push
```

## Cloning this repo with submodules

```powershell
git clone --recurse-submodules <this-repo-url>
```

Already cloned? Run:

```powershell
git submodule update --init --recursive
```

## Updating a pod submodule

From the repo root, pull the latest of every pod and record the new pointers:

```powershell
git submodule update --remote
git add .
git commit -m "Update pod submodules"
git push
```