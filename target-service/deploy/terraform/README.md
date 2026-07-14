# Terraform — Alibaba Cloud resources for flaskapp

Provisions the Alibaba Cloud resources the instrumented Flask app uses, in
**Malaysia / Kuala Lumpur (`ap-southeast-3`)** by default.

| Resource | Always | What it's for |
|----------|:------:|---------------|
| SLS log project + logstore | ✅ | App ships its logs here (`/api/logs`) |
| OSS bucket (private) | ✅ | Report/artifact storage (`/api/reports`) |
| VPC + ECS instance (runs flaskapp) | opt-in (`create_ecs`) | A VM that auto-deploys and runs flaskapp on `:8000` |
| RAM user + AccessKey | opt-in (`create_ram_user`) | Least-privilege runtime identity for the app |

## Running flaskapp on ECS + connecting the ResQ terminal

Set `create_ecs = true` (already the default in `terraform.tfvars`). On `apply`,
Terraform will:

1. Zip the app (`app.py` + `integrations/`) and upload it to the OSS bucket.
2. Boot an Ubuntu ECS instance whose `user_data` downloads the zip from OSS,
   writes `.env` (with your credentials + SLS/OSS settings), installs
   dependencies in a venv, and runs the app as a **systemd service** on `:8000`.
3. Open port `8000` (and `22`) in the security group.

The app starts with `SCENARIO=1`, so it injects an incident ~30s after boot and
also ships its logs to **SLS** the whole time. Point ResQ's terminal at it:

```bash
terraform output app_url                 # http://<public-ip>:8000
terraform output resq_terminal_command   # copy/paste this into the ResQ repo
```

`resq_terminal_command` looks like:

```bash
RESQ_TARGET_URL=http://<public-ip>:8000 python demo/resq_terminal.py
```

Run it from your ResQ checkout and the TUI will poll the remote instance,
detect the incident, and investigate. Trigger/clear incidents on demand:

```bash
curl -X POST http://<public-ip>:8000/api/scenario -H 'content-type: application/json' -d '{"action":"start"}'
curl -X POST http://<public-ip>:8000/api/scenario -H 'content-type: application/json' -d '{"action":"stop"}'
```

> First boot takes ~2–3 min (apt + pip). Check readiness with
> `curl http://<public-ip>:8000/api/health`. If it never comes up, SSH in and
> run `journalctl -u flaskapp -n 100` / `cat /var/log/cloud-init-output.log`.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.3
- An Alibaba Cloud AccessKey with **provisioning** rights (create SLS/OSS, and
  ECS/RAM if you enable those). This is separate from the app's *runtime* key.

## Usage

```bash
cd deploy/terraform
cp terraform.tfvars.example terraform.tfvars   # then edit: access_key, secret_key, names

terraform init
terraform plan
terraform apply
```

After apply, wire the app's `.env` from the outputs:

```bash
terraform output env_block          # non-secret .env lines to paste

# If you set create_ram_user = true, also grab the runtime credentials:
terraform output -raw app_access_key_id
terraform output -raw app_access_key_secret
```

Paste those into `../../.env` (the values from `env_block`, plus
`ALIBABA_ACCESS_KEY_ID` / `ALIBABA_ACCESS_KEY_SECRET`), then run the app.

## Notes

- **Globally-unique names:** `sls_project` and `oss_bucket_name` must be unique
  across all of Alibaba Cloud. If `apply` reports a conflict, change them in
  `terraform.tfvars`.
- **State contains secrets:** `terraform.tfvars` and `*.tfstate` are git-ignored.
  The state file holds the RAM AccessKey secret in plaintext — keep it private
  (consider an OSS remote backend for team use).
- **Provider version:** pinned to `aliyun/alicloud >= 1.220`. If `plan` errors on
  an attribute name (e.g. `alicloud_oss_bucket_acl` or `project_name`), your
  provider is older — run `terraform init -upgrade`.
- **Teardown:** `terraform destroy`. Note OSS buckets must be empty to delete;
  remove stored reports first if `destroy` complains.
```
