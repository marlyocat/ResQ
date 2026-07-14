# =============================================================================
# Optional: run flaskapp on an ECS instance (VPC + instance), with the code
# delivered via OSS (no GitHub needed). Enable with `create_ecs = true`.
#
# Flow: zip the app -> upload to the OSS bucket -> the instance downloads it on
# boot, writes .env, installs deps, and runs it as a systemd service on :8000.
# =============================================================================

locals {
  app_root    = "${path.module}/../.."
  app_zip_key = "deploy/flaskapp.zip"
  app_zip_url = "https://${var.oss_bucket_name}.oss-${var.region}.aliyuncs.com/${local.app_zip_key}"
}

# ── Package the app (explicit file list: no secrets, no deploy/, no .git) ───
data "archive_file" "app" {
  count       = var.create_ecs ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/.build/flaskapp.zip"

  source {
    content  = file("${local.app_root}/app.py")
    filename = "app.py"
  }
  source {
    content  = file("${local.app_root}/requirements.txt")
    filename = "requirements.txt"
  }
  source {
    content  = file("${local.app_root}/integrations/__init__.py")
    filename = "integrations/__init__.py"
  }
  source {
    content  = file("${local.app_root}/integrations/config.py")
    filename = "integrations/config.py"
  }
  source {
    content  = file("${local.app_root}/integrations/sls_client.py")
    filename = "integrations/sls_client.py"
  }
  source {
    content  = file("${local.app_root}/integrations/oss_client.py")
    filename = "integrations/oss_client.py"
  }
  source {
    content  = file("${local.app_root}/integrations/ecs_client.py")
    filename = "integrations/ecs_client.py"
  }
  source {
    content  = file("${local.app_root}/integrations/cms_client.py")
    filename = "integrations/cms_client.py"
  }
  source {
    content  = file("${local.app_root}/demo/load_sim.py")
    filename = "demo/load_sim.py"
  }
}

# ── Upload the zip to OSS (public-read so the instance can curl it) ──────────
resource "alicloud_oss_bucket_object" "app" {
  count        = var.create_ecs ? 1 : 0
  bucket       = alicloud_oss_bucket.reports.bucket
  key          = local.app_zip_key
  source       = data.archive_file.app[0].output_path
  content_type = "application/zip"
  acl          = "public-read"
}

# ── Networking ──────────────────────────────────────────────────────────────
data "alicloud_zones" "default" {
  count                       = var.create_ecs ? 1 : 0
  available_resource_creation = "Instance"
  available_instance_type     = data.alicloud_instance_types.default[0].instance_types[0].id
}

data "alicloud_instance_types" "default" {
  count          = var.create_ecs ? 1 : 0
  cpu_core_count = var.ecs_instance_cpu
  memory_size    = var.ecs_instance_memory
}

data "alicloud_images" "ubuntu" {
  count       = var.create_ecs ? 1 : 0
  name_regex  = "^ubuntu_22"
  owners      = "system"
  most_recent = true
}

resource "alicloud_vpc" "app" {
  count      = var.create_ecs ? 1 : 0
  vpc_name   = "flaskapp-vpc"
  cidr_block = "172.16.0.0/16"
  tags       = var.tags
}

resource "alicloud_vswitch" "app" {
  count        = var.create_ecs ? 1 : 0
  vpc_id       = alicloud_vpc.app[0].id
  cidr_block   = "172.16.0.0/24"
  zone_id      = data.alicloud_zones.default[0].zones[0].id
  vswitch_name = "flaskapp-vswitch"
  tags         = var.tags
}

resource "alicloud_security_group" "app" {
  count               = var.create_ecs ? 1 : 0
  security_group_name = "flaskapp-sg"
  vpc_id              = alicloud_vpc.app[0].id
  tags                = var.tags
}

resource "alicloud_security_group_rule" "ssh" {
  count             = var.create_ecs ? 1 : 0
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "22/22"
  security_group_id = alicloud_security_group.app[0].id
  cidr_ip           = var.ssh_cidr
}

resource "alicloud_security_group_rule" "app_port" {
  count             = var.create_ecs ? 1 : 0
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "${var.app_port}/${var.app_port}"
  security_group_id = alicloud_security_group.app[0].id
  cidr_ip           = var.ssh_cidr
}

# ── The instance ─────────────────────────────────────────────────────────────
resource "alicloud_instance" "app" {
  count                      = var.create_ecs ? 1 : 0
  depends_on                 = [alicloud_oss_bucket_object.app]
  instance_name              = "flaskapp"
  instance_type              = data.alicloud_instance_types.default[0].instance_types[0].id
  image_id                   = data.alicloud_images.ubuntu[0].images[0].id
  security_groups            = [alicloud_security_group.app[0].id]
  vswitch_id                 = alicloud_vswitch.app[0].id
  internet_max_bandwidth_out = 10
  system_disk_category       = "cloud_essd"
  system_disk_size           = 40
  tags                       = var.tags

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    app_zip_url     = local.app_zip_url
    access_key      = var.access_key
    secret_key      = var.secret_key
    region          = var.region
    sls_project     = var.sls_project
    sls_logstore    = var.sls_logstore
    oss_bucket_name = var.oss_bucket_name
    app_port        = var.app_port
    scenario        = var.auto_incident ? 1 : 0
  })
}
