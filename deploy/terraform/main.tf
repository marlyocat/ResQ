# Terraform configuration for Alibaba Cloud deployment
# This demonstrates infrastructure-as-code for ResQ backend

# Provider configuration
provider "alicloud" {
  access_key = var.alicloud_access_key
  secret_key = var.alicloud_secret_key
  region     = var.region
}

# Variables
variable "alicloud_access_key" {
  description = "Alibaba Cloud Access Key ID"
  type        = string
  sensitive   = true
}

variable "alicloud_secret_key" {
  description = "Alibaba Cloud Access Key Secret"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "Deployment region"
  type        = string
  default     = "cn-hangzhou"
}

# ECS Instance for ResQ orchestrator
resource "alicloud_instance" "resq_orchestrator" {
  instance_name        = "resq-orchestrator"
  instance_type        = "ecs.g7.xlarge"
  security_groups      = [alicloud_security_group.resq_sg.id]
  vswitch_id           = alicloud_vswitch.resq_vswitch.id
  internet_max_bandwidth_out = 10
  
  image_id = "ubuntu_22_04_x64_20G_alibase_20240101.vhd"
  
  system_disk_category = "cloud_essd"
  system_disk_size     = 40
  
  user_data = <<-EOF
    #!/bin/bash
    apt-get update
    apt-get install -y python3 python3-pip
    pip3 install openai python-dotenv
    cd /opt/resq
    python3 main.py --baseline-comparison
  EOF

  tags = {
    Name = "ResQ Orchestrator"
    Project = "ResQ"
    Hackathon = "Qwen Cloud AI Hackathon 2024"
  }
}

# Security Group
resource "alicloud_security_group" "resq_sg" {
  name   = "resq-security-group"
  vpc_id = alicloud_vpc.resq_vpc.id

  ingress {
    ip_protocol  = "tcp"
    port_range   = "22/22"
    cidr_ips     = ["0.0.0.0/0"]
  }
}

# VPC
resource "alicloud_vpc" "resq_vpc" {
  vpc_name   = "resq-vpc"
  cidr_block = "172.16.0.0/16"
}

# VSwitch
resource "alicloud_vswitch" "resq_vswitch" {
  vpc_id       = alicloud_vpc.resq_vpc.id
  cidr_block   = "172.16.0.0/24"
  zone_id      = "${var.region}-a"
  vswitch_name = "resq-vswitch"
}

# SLS Log Project (for log ingestion)
resource "alicloud_log_project" "resq_logs" {
  name        = "resq-incident-logs"
  description = "Log project for ResQ incident analysis"
}

resource "alicloud_log_store" "resq_logstore" {
  project = alicloud_log_project.resq_logs.name
  name    = "incidents"
  ttl     = 30
  shard_count = 2
}

# Outputs
output "orchestrator_public_ip" {
  value = alicloud_instance.resq_orchestrator.public_ip
}

output "log_project_name" {
  value = alicloud_log_project.resq_logs.name
}
