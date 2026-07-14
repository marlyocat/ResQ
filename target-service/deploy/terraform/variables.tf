# ── Credentials & region ─────────────────────────────────────────────────
variable "access_key" {
  description = "Alibaba Cloud AccessKey ID used by Terraform to provision resources"
  type        = string
  sensitive   = true
}

variable "secret_key" {
  description = "Alibaba Cloud AccessKey Secret used by Terraform to provision resources"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "Deployment region. Malaysia (Kuala Lumpur) = ap-southeast-3"
  type        = string
  default     = "ap-southeast-3"
}

# ── SLS (Simple Log Service) ──────────────────────────────────────────────
variable "sls_project" {
  description = "SLS project name (globally unique, lowercase/numbers/hyphens)"
  type        = string
  default     = "flaskapp-logs"
}

variable "sls_logstore" {
  description = "SLS logstore name"
  type        = string
  default     = "app-logs"
}

variable "sls_retention_days" {
  description = "How many days SLS keeps logs"
  type        = number
  default     = 30
}

variable "sls_shard_count" {
  description = "Number of shards for the logstore"
  type        = number
  default     = 2
}

# ── OSS (Object Storage Service) ──────────────────────────────────────────
variable "oss_bucket_name" {
  description = "OSS bucket name (globally unique, 3-63 chars, lowercase/numbers/hyphens)"
  type        = string
  default     = "flaskapp-incident-reports"
}

# ── ECS (optional — a VM to run the Flask app on) ─────────────────────────
variable "create_ecs" {
  description = "Set true to provision a VPC + ECS instance to run the app on"
  type        = bool
  default     = false
}

variable "ecs_instance_cpu" {
  description = "vCPU count used to select an instance type"
  type        = number
  default     = 2
}

variable "ecs_instance_memory" {
  description = "Memory (GiB) used to select an instance type"
  type        = number
  default     = 4
}

variable "ssh_cidr" {
  description = "CIDR allowed to reach the instance over SSH (22) and the app port"
  type        = string
  default     = "0.0.0.0/0"
}

variable "app_port" {
  description = "Port the Flask app listens on (opened in the security group)"
  type        = number
  default     = 8000
}

variable "auto_incident" {
  description = "If true, the instance auto-injects an incident ~30s after boot. If false, trigger it manually via POST /api/scenario."
  type        = bool
  default     = false
}

# ── RAM (optional — a dedicated app user with least-privilege policies) ────
variable "create_ram_user" {
  description = "Set true to create a RAM user + AccessKey for the app to use at runtime"
  type        = bool
  default     = false
}

variable "ram_user_name" {
  description = "Name of the RAM user created for the app"
  type        = string
  default     = "flaskapp-runtime"
}

# ── Tags ──────────────────────────────────────────────────────────────────
variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default = {
    Project   = "flaskapp"
    ManagedBy = "terraform"
  }
}
