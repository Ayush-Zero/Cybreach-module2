# CyBreach Module 2 — Demo

Everything here is **verified working end-to-end** against the live stack. The
confirmed run produced:

```
verdict     Detected
confidence  0.9
causal_chain[1] "Rule considered: 2b9a6687... (technique T1059.001)"
fields outside the frozen contract : none
content_hash re-derives            : True
```

All paths are derived from each script's own location, so the `demo/` folder
works from anywhere in the repo. Run every command below from the **repo root**.

## Files

| File | Purpose |
| --- | --- |
| `demo-env.ps1` | Single source of truth for `SECRET_KEY` and every shared setting. |
| `start-services.ps1` | Opens all six services, each in its own window with consistent env. |
| `health-check.ps1` | Read-only health probe for all six + Kafka consumer check. |
| `seed-rule.ps1` | Ingests the 10 Sigma fixtures into Alpha. **Run before publishing.** |
| `publish_evidence.py` | Publishes one evidence event and waits for the verdict it causes. |

---

## Setu

```powershell
cd G:\Cybreach-module2
docker compose up -d
```

- `http://localhost:8080` — Kafka UI
- `http://localhost:5173` — Delta dashboard
- `http://localhost:8001/docs` — Alpha Swagger

---


### 1. Start the six services

```powershell
.\demo\start-services.ps1
```

Six windows open. Wait ~20s, then:

```powershell
.\demo\health-check.ps1
```


### 2. Docker

```powershell
cd G:\Cybreach-module2
docker compose ps
```


Switch to the Kafka UI tab. `cybreach.verdicts.v2` will show verdicts from
rehearsal; that is fine, and it proves re-recording works.

### 3. Ingest rules

```powershell
.\demo\seed-rule.ps1
```

Prints 10 rules with their MITRE techniques.


### 4. The live path

```powershell
python .\demo\publish_evidence.py
```


Refresh the Kafka UI tab to show the verdict on `cybreach.verdicts.v2`.

### 5. Frontend

```powershell
cd G:\Cybreach-module2\cybreach_pod_delta\frontend-dashboard
npm run dev
```

Opens on 5173. Log in `demo` / `demo123`.

### 6. Fail-closed proof (5 seconds, high value)

```powershell
Invoke-WebRequest http://127.0.0.1:8001/api/v2/rules/search -UseBasicParsing
```
→ **401**

```powershell
. .\demo\demo-env.ps1 | Out-Null
python -c "import os,time,jose.jwt;print(jose.jwt.encode({'sub':'demo','tenant_id':'acme','exp':int(time.time())+300},os.environ['SECRET_KEY'],algorithm='HS256'))"
```
Paste the printed token into:

```powershell
Invoke-WebRequest http://127.0.0.1:8001/api/v2/rules/search -Headers @{Authorization="Bearer <token>"} -UseBasicParsing
```
→ **200**



---

## Note on `SECRET_KEY`

`demo-env.ps1` defaults to a shared demo key when `SECRET_KEY` is unset. That
key is **not a secret** and is fine for a demo on a local machine. Set your own
before any shared or deployed environment:

```powershell
$env:SECRET_KEY = '<your value>'   # then dot-source demo-env.ps1
```

`demo-env.ps1` honours a pre-existing `SECRET_KEY` rather than overwriting it.