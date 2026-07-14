terraform {
  required_version = ">= 1.3.0"

  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = ">= 1.220.0, < 2.0.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4.0"
    }
  }
}
