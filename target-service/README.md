# flaskapp — Alibaba Cloud-Instrumented Target Service

A small Flask workload (an "items" API) that runs as a real service on
Alibaba Cloud and is instrumented against four Alibaba resources. It is
modeled on the `integrations/` layer from the ResQ project, but here the app
*produces* signal (ships logs, stores reports, exposes metrics) rather than
consuming it.

| Resource | SDK | What the app does |
|----------|-----|-------------------|
| **SLS** (Simple Log Service) | `aliyun-log-python-sdk` | Ships every request/log to a LogStore in real time; queries them back via `/api/logs` |
| **OSS** (Object Storage) | `oss2` | Stores/retrieves JSON reports via `/api/reports` |
| **ECS** (Elastic Compute) | `alibabacloud_ecs20140526` | Lists instances + status via `/api/instances` |
| **CMS** (Cloud Monitor) | `alibabacloud_cms20190101` | Reads host metrics via `/api/cloud-metrics` |

All calls are **real** Alibaba Cloud API calls — they require valid
credentials (the app still boots without them; integration endpoints return
`503` with a clear message, and logs stay local).

## Setup

```bash
python -m venv .venv
. .venv/Scripts/activate      # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

cp .env.example .env          # fill in ALIBABA_ACCESS_KEY_ID / _SECRET, SLS/OSS/etc.
python app.py                 # serves on http://localhost:8000
```

Create a RAM user with `AliyunLogFullAccess`, `AliyunOSSFullAccess`,
`AliyunECSReadOnlyAccess`, and `AliyunCloudMonitorReadOnlyAccess`, plus an SLS
project + logstore and an OSS bucket, then set the matching values in `.env`.

## Test it with the ResQ terminal (TUI)

The app doubles as a **target service** for ResQ's terminal UI, which polls a
target host (`RESQ_TARGET_URL`) and auto-detects an incident when error rate > 8%
or p99 latency > 1500ms.

- **Deploy to Alibaba Cloud ECS + capture proof** → follow **[DEPLOY.md](DEPLOY.md)**
  (the full runbook: provision, verify, drive ResQ, tear down).
- **Run locally, no cloud** → start the target with `python demo/run_target.py`
  (app on `:5000`, incident injected ~15s in), then from your ResQ checkout run
  `python demo/resq_terminal.py`. Logs still ship to SLS in the background if
  credentials are set. Knobs: `SCENARIO=1`, `FAILURE_DELAY=<seconds>`, `PORT`.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| GET | `/api/status` | Which integrations are configured + reachable |
| GET | `/api/metrics` | Local request metrics (count, error rate, p50/p95/p99) |
| GET/POST | `/api/items` | List / create items (the workload) |
| GET | `/api/items/<id>` | Fetch an item |
| GET | `/api/logs?query=*&minutes=30` | **SLS** — query shipped logs back |
| POST | `/api/reports` | **OSS** — store a JSON report |
| GET | `/api/reports` | **OSS** — list report ids for a date |
| GET | `/api/reports/<id>` | **OSS** — fetch a stored report |
| GET | `/api/instances` | **ECS** — list instances + status |
| GET | `/api/cloud-metrics?metric=CPUUtilization` | **CMS** — host metrics |

### Quick smoke test

```bash
curl localhost:8000/api/status
curl -X POST localhost:8000/api/items -H 'content-type: application/json' -d '{"name":"widget","value":42}'
curl localhost:8000/api/metrics
curl "localhost:8000/api/logs?minutes=10"          # requires SLS configured
curl localhost:8000/api/instances                  # requires ECS creds
```

## How instrumentation works

- **Logging → SLS.** `SLSLogHandler` is attached to the app logger. Records are
  enqueued and flushed to SLS by a background thread in batches (`PutLogs`), so
  request latency never depends on the network. On failure it drops records
  rather than crashing the request path (see `/api/status` → `sls.stats`).
- **Per-request access logs** are emitted in `after_request` with request id,
  method, path, status, and latency as structured SLS fields.
- **Reports → OSS** are written under `reports/YYYY-MM-DD/<id>.json`.
- **ECS/CMS** are read on demand from their endpoints.

## Layout

```
flaskapp/
├── app.py                     # Flask service + instrumentation
├── integrations/
│   ├── config.py              # env-var config for all resources
│   ├── sls_client.py          # SLS ship (PutLogs) + query (GetLogs) + log handler
│   ├── oss_client.py          # OSS report storage
│   ├── ecs_client.py          # ECS DescribeInstances / DescribeInstanceStatus
│   └── cms_client.py          # CMS DescribeMetricLast / DescribeAlertHistoryList
├── requirements.txt
└── .env.example
```
