# =============================================================================
# Core data-plane resources the Flask app needs: SLS + OSS
# =============================================================================

provider "alicloud" {
  access_key = var.access_key
  secret_key = var.secret_key
  region     = var.region
}

# ── SLS: log project + logstore (the app ships its logs here) ──────────────
resource "alicloud_log_project" "app" {
  project_name = var.sls_project
  description  = "Log project for the instrumented Flask app"
  tags         = var.tags
}

resource "alicloud_log_store" "app" {
  project_name     = alicloud_log_project.app.project_name
  logstore_name    = var.sls_logstore
  shard_count      = var.sls_shard_count
  retention_period = var.sls_retention_days
}

# ── OSS: bucket for reports / artifacts ────────────────────────────────────
resource "alicloud_oss_bucket" "reports" {
  bucket = var.oss_bucket_name
  tags   = var.tags
}

# Keep the bucket private (separate resource in current provider versions).
resource "alicloud_oss_bucket_acl" "reports" {
  bucket = alicloud_oss_bucket.reports.bucket
  acl    = "private"
}
