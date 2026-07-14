# ── Values to copy into the app's .env ────────────────────────────────────
output "alibaba_region_id" {
  value = var.region
}

output "sls_project" {
  value = alicloud_log_project.app.project_name
}

output "sls_logstore" {
  value = alicloud_log_store.app.logstore_name
}

output "sls_endpoint" {
  description = "Leave SLS_ENDPOINT blank in .env to auto-derive; shown here for reference"
  value       = "${var.region}.log.aliyuncs.com"
}

output "oss_bucket_name" {
  value = alicloud_oss_bucket.reports.bucket
}

output "oss_endpoint" {
  value = "https://oss-${var.region}.aliyuncs.com"
}

output "ecs_instance_id" {
  description = "Set as ECS_INSTANCE_ID in .env to scope CMS metric queries"
  value       = var.create_ecs ? alicloud_instance.app[0].id : null
}

output "ecs_public_ip" {
  value = var.create_ecs ? alicloud_instance.app[0].public_ip : null
}

output "app_url" {
  description = "Base URL of flaskapp on the instance"
  value       = var.create_ecs ? "http://${alicloud_instance.app[0].public_ip}:${var.app_port}" : null
}

output "resq_terminal_command" {
  description = "Run this from the ResQ repo to point its terminal UI at the remote instance"
  value = var.create_ecs ? join(" ", [
    "RESQ_TARGET_URL=http://${alicloud_instance.app[0].public_ip}:${var.app_port}",
    "python demo/resq_terminal.py",
  ]) : null
}

# ── Generated runtime credentials (only when create_ram_user = true) ───────
output "app_access_key_id" {
  description = "AccessKey ID for the app's RAM user — copy to ALIBABA_ACCESS_KEY_ID"
  value       = var.create_ram_user ? alicloud_ram_access_key.app[0].id : null
  sensitive   = true
}

output "app_access_key_secret" {
  description = "AccessKey Secret for the app's RAM user — copy to ALIBABA_ACCESS_KEY_SECRET"
  value       = var.create_ram_user ? alicloud_ram_access_key.app[0].secret : null
  sensitive   = true
}

# ── Ready-to-paste .env block (non-secret fields) ─────────────────────────
output "env_block" {
  description = "Paste into .env, then fill credentials (or read them from the sensitive outputs)"
  value       = <<-EOT
    ALIBABA_REGION_ID=${var.region}
    SLS_ENDPOINT=
    SLS_PROJECT=${alicloud_log_project.app.project_name}
    SLS_LOGSTORE=${alicloud_log_store.app.logstore_name}
    OSS_ENDPOINT=https://oss-${var.region}.aliyuncs.com
    OSS_BUCKET_NAME=${alicloud_oss_bucket.reports.bucket}
    ECS_INSTANCE_ID=${var.create_ecs ? alicloud_instance.app[0].id : ""}
    CMS_NAMESPACE=acs_ecs_dashboard
  EOT
}
