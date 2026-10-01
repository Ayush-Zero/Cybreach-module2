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
| `populate-delta-dashboard.ps1` | Creates a Delta rule and validates one event, so the Delta dashboard has data. |
| `normalize-event.ps1` | Feeds a raw vendor event to the Gamma normalizer and shows the OCSF result. |
| `tail-logs.ps1` | Watch any service's log live, without alt-tabbing between six windows. |

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

Each service's output is also teed to `demo\logs\<service>.log` as it runs, so
you can read a pod's log without switching windows:

```powershell
.\demo\tail-logs.ps1 gamma-normalizer          # follow it live
.\demo\tail-logs.ps1 gamma-normalizer -Dump    # print current contents
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

The dashboard will be **empty** at this point, and that is expected rather than
a bug. Delta is a Kafka *producer* only — it never consumes
`cybreach.verdicts.v2` — and its dashboard reads Delta's own Postgres. So the
Beta pipeline in step 4 cannot put a row in the Delta UI. Populate it with
Delta's own validation endpoint:

```powershell
.\demo\populate-delta-dashboard.ps1
```

It creates the rule if it is missing, validates one encoded-PowerShell event
against it, and prints the resulting `verdict` / `rule_id` / `content_hash`.
Expect `verdict = Detected`. Safe to run repeatedly — it reuses the rule rather
than creating a duplicate.

Two details that make this endpoint easy to get wrong, both handled in the
script:

- The rule must exist **before** validating. `verdict_events.rule_id` is a
  foreign key onto `rules.rule_id`, and `rule_id` is a content hash over
  `rule_name` + `query` + `rule_type` + `mitre_technique`. Validation is sent
  the same four fields, so the digests match; send fewer and the endpoint
  answers `404` naming the digest it looked for.
- Use plain field names in the rule body. Delta looks each selection key up with
  `event.get(field)`, so a Sigma modifier such as `CommandLine|contains` is
  treated as a literal field name and the rule evaluates to `NoData`.
  Substring matching is already the default.

### 6. The normalizer (Gamma, 8005)

Gamma is **not** on the evidence → verdict bus, so step 4 never reaches it and
its log stays empty. Run this when you narrate the normalizer:

```powershell
.\demo\normalize-event.ps1 -Vendor splunk
```

Feeds one raw vendor event in and prints the canonical OCSF event out:

```
  in  : _time, sourcetype, eventtype, host, action, status, ..., user, src_ip
  out : class_uid=3002 activity= severity=1 user=deepali.panchal
```

`-Vendor` accepts `splunk`, `elastic`, `sentinel`, `qradar` and `logscale`. All
five land on `class_uid 3002` (Authentication), which is the point of the pod:
the schema is detected from the payload rather than declared by the caller, so
everything downstream speaks OCSF regardless of the SIEM it came from.

### 7. Red-to-Green (Missed → Detected)

```powershell
.\demo\red-to-green.ps1
```

Proves a detection gap, fixes it, and re-verifies the **same** evidence:

```
 STEP 2   verdict  Missed    conf 0.0    "Field 'Image' is present in the event
                                         but its value does not satisfy the rule"
 STEP 3   rule tightened: Image 'cmd.exe' -> 'powershell.exe'
 STEP 4   BEFORE          AFTER
          verdict Missed   verdict Detected
          conf    0.0      conf    1.0
          id      17       id      18
          gap_closed: True   delta: 1.0   matched fields: Image
```

Step 4 is Delta's own `POST /verdicts/{id}/revalidate`. It re-reads the event
stored on the old verdict, re-runs the corrected rule against it, supersedes the
old row, and publishes a corrected verdict plus a gap-closed event on
`cybreach.gap_closed.v2`. The audit log records `REVALIDATED` with old → new.

One nuance worth narrating correctly: the gap shown is **a rule exists but does
not match**, not **no rule exists**. A verdict cannot reference a rule that was
never created — `verdict_events.rule_id` is a foreign key — so a technique with
no rule at all cannot be filed as `Missed`. That is correct behaviour, and this
demo uses the gap that is actually reachable.

### 8. Fail-closed proof (5 seconds, high value)

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

