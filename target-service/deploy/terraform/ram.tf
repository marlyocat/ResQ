# =============================================================================
# Optional: a dedicated RAM user for the app to authenticate with at runtime,
# scoped to exactly the four services it uses. Enable with `create_ram_user = true`.
# The generated AccessKey is exposed via outputs (sensitive) — copy it into .env.
# =============================================================================

resource "alicloud_ram_user" "app" {
  count    = var.create_ram_user ? 1 : 0
  name     = var.ram_user_name
  comments = "Runtime identity for the instrumented Flask app"
}

resource "alicloud_ram_access_key" "app" {
  count     = var.create_ram_user ? 1 : 0
  user_name = alicloud_ram_user.app[0].name
}

locals {
  app_policies = var.create_ram_user ? [
    "AliyunLogFullAccess",             # SLS: ship + query logs
    "AliyunOSSFullAccess",             # OSS: store + read reports
    "AliyunECSReadOnlyAccess",         # ECS: describe instances
    "AliyunCloudMonitorReadOnlyAccess" # CMS: read metrics + alarms
  ] : []
}

resource "alicloud_ram_user_policy_attachment" "app" {
  for_each    = toset(local.app_policies)
  policy_name = each.value
  policy_type = "System"
  user_name   = alicloud_ram_user.app[0].name
}
