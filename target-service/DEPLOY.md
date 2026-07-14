# Deploy the target service on Alibaba Cloud ECS (hackathon runbook)

This is the end-to-end path to get the instrumented Flask service **running on
Alibaba Cloud** and to **capture the deployment proof** the hackathon asks for.
Terraform provisions everything (SLS + OSS always; VPC + ECS on opt-in) and the
instance auto-deploys the app from OSS as a systemd service on port `8000`.

**Time:** ~15 min of work + ~3 min first-boot. **Cost:** one small ECS instance
(covered by the new-user free trial); `terraform destroy` when done.

---

## 0. Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.3
- An Alibaba Cloud account and a **provisioning** AccessKey (ID + Secret) with
  rights to create SLS, OSS, ECS, VPC (and RAM if you enable it). Get one at
  <https://ram.console.aliyun.com/manage/ak>.
  > This key is used by Terraform to *create* resources. By default the same key
  > is also written to the instance as the app's runtime credential. To use a
  > separate least-privilege key at runtime, set `create_ram_user = true` (below).

---

## 1. Configure

```bash
cd target-service/deploy/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
access_key = "LTAI..."        # your provisioning AccessKey ID
secret_key = "..."            # your provisioning AccessKey Secret
region     = "ap-southeast-3" # Malaysia (KL); any Alibaba region works

# Must be globally unique across ALL of Alibaba Cloud — change if apply conflicts
sls_project     = "resq-flaskapp-logs-<yourname>"
oss_bucket_name = "resq-reports-<yourname>"

create_ecs      = true        # <-- REQUIRED: provisions the VM that runs the app
auto_incident   = false       # false = you trigger the incident on camera (recommended)
create_ram_user = false       # true = separate runtime AccessKey for the app
```

> `terraform.tfvars` holds secrets and is git-ignored — never commit it.

---

## 2. Apply

```bash
terraform init
terraform plan      # sanity-check the resources
terraform apply     # type 'yes'
```

If `plan` errors on a provider attribute, run `terraform init -upgrade`
(the config pins `aliyun/alicloud >= 1.220`).

Grab the outputs:

```bash
terraform output app_url               # http://<public-ip>:8000
terraform output ecs_public_ip
terraform output ecs_instance_id       # set as ECS_INSTANCE_ID to scope CMS queries
terraform output resq_terminal_command # copy/paste to point ResQ at this box
```

---

## 3. Wait for boot, then verify (first boot ~2–3 min: apt + pip)

```bash
IP=$(terraform output -raw ecs_public_ip)

# health flips to ok once the service is up
curl -s http://$IP:8000/api/health

# THE proof endpoint: every Alibaba integration should read "true"
curl -s http://$IP:8000/api/status
```

`/api/status` returns the config summary, `config_issues` (should be empty), and
live SLS shipping stats (`shipped` climbing). A built-in load generator is already
driving traffic, so `/api/metrics` and `/api/logs` are populated immediately.

If it's not up after ~4 min, SSH in and check:

```bash
ssh root@$IP
journalctl -u flaskapp -n 100
cat /var/log/cloud-init-output.log
```

---

## 4. Capture the deployment proof (for the submission)

Collect these — they are your "backend running on Alibaba Cloud" evidence:

1. **`/api/status` output** showing `sls/oss/ecs/cms` all `true` and `shipped > 0`
   (terminal screenshot or save the JSON).
2. **SLS console** → your `sls_project` / `app-logs` logstore → run a query and
   show the app's logs arriving in real time.
3. **OSS object**: create a report and show it in the bucket:
   ```bash
   curl -X POST http://$IP:8000/api/reports -H 'content-type: application/json' \
     -d '{"id":"demo-report","summary":"deployment proof"}'
   # -> {"report_id":"demo-report","oss_key":"reports/YYYY-MM-DD/demo-report.json"}
   ```
   Then show that object in the OSS console bucket.
4. **ECS console** showing the `flaskapp` instance `Running` (matches
   `ecs_instance_id`).
5. **CMS**: `curl -s "http://$IP:8000/api/cloud-metrics?metric=CPUUtilization"`
   returns datapoints for the instance.

The code behind these calls (your gradeable proof link) lives in
[`target-service/integrations/`](integrations/).

---

## 5. Drive it with ResQ (for the 3-min video)

From your ResQ checkout, point the terminal UI at the remote instance:

```bash
RESQ_TARGET_URL=http://<public-ip>:8000 python demo/resq_terminal.py
```

Trigger and clear an incident on demand (do this on camera). There are **two
incident types**:

```bash
# (a) DB pool exhaustion — unambiguous: the agents AGREE (no negotiation needed)
curl -X POST http://$IP:8000/api/scenario -H 'content-type: application/json' \
  -d '{"action":"start","type":"db_pool"}'

# (b) Cache failure disguised as a memory leak — AMBIGUOUS: logs point at memory,
#     metrics point at the cache, so the agents DISAGREE and the negotiation round
#     resolves the conflict on-screen. Use this to showcase Track 3 live.
curl -X POST http://$IP:8000/api/scenario -H 'content-type: application/json' \
  -d '{"action":"start","type":"cache"}'

# recover
curl -X POST http://$IP:8000/api/scenario -H 'content-type: application/json' -d '{"action":"stop"}'
```

PowerShell (Windows):

```powershell
$env:RESQ_TARGET_URL="http://<public-ip>:8000"; python demo/resq_terminal.py
Invoke-RestMethod -Method Post "http://<public-ip>:8000/api/scenario" -ContentType application/json -Body '{"action":"start","type":"cache"}'
```

> **For the video:** trigger `type:"cache"` — the TUI's Negotiation panel shows the
> Log Analyzer ("memory leak") and Metric Monitor ("cache failure") disagree, then
> reconcile to the correct cache root cause. (`type:"db_pool"` is the simpler
> "agents agree" case.) The first `start` call blocks 2–5s (it hits the degraded
> path); ResQ polls independently and picks up the spike right after.

Metrics/logs come from the real Alibaba-hosted service the whole time, so the
cloud integration is exercised live while ResQ investigates.

---

## 6. Teardown

```bash
terraform destroy   # type 'yes'
```

> OSS buckets must be empty to delete. If `destroy` complains, remove stored
> objects (the `reports/` and `deploy/` keys) from the bucket first, then re-run.

---

## Quick reference

| Action | Command |
|--------|---------|
| App base URL | `terraform output app_url` |
| Public IP | `terraform output -raw ecs_public_ip` |
| ResQ launch command | `terraform output resq_terminal_command` |
| Health check | `curl http://<ip>:8000/api/health` |
| Integration status (proof) | `curl http://<ip>:8000/api/status` |
| Trigger incident | `POST /api/scenario {"action":"start"}` |
| Recover | `POST /api/scenario {"action":"stop"}` |
| Query logs from SLS | `curl "http://<ip>:8000/api/logs?source=sls&minutes=10"` |

## Troubleshooting

- **`/api/health` never responds:** SSH in and check
  `journalctl -u flaskapp -n 100` and `cat /var/log/cloud-init-output.log`.
- **App up but ResQ shows no incident:** confirm the load generator is running
  (`systemctl status flaskapp-load`) — without traffic the flag flips but metrics stay flat.
- **`/api/status` shows sls/oss = false:** credentials or SLS/OSS names in the
  instance `.env` are wrong; re-check `terraform.tfvars` and re-apply.
- **ResQ agents say "Analysis unavailable":** set `QWEN_API_KEY` in ResQ's `.env`.
- **Port unreachable from your laptop:** the security group opens `8000` to
  `ssh_cidr` (default `0.0.0.0/0`); if you narrowed it, include your IP.

## Notes & gotchas

- **Globally-unique names:** if `apply` fails on `sls_project` or
  `oss_bucket_name`, pick different values.
- **State holds secrets:** `*.tfstate` is git-ignored and contains credentials in
  plaintext — keep it private (use an OSS remote backend for team use).
- **Region:** everything defaults to `ap-southeast-3`; change `region` to deploy
  elsewhere (endpoints are derived automatically).
