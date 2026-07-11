# Terraform state storage on Alibaba Cloud OSS

# OSS Bucket for state
resource "alicloud_oss_bucket" "terraform_state" {
  bucket = "resq-terraform-state"
  acl    = "private"
  
  versioning {
    status = "Enabled"
  }
  
  server_side_encryption_rule {
    sse_algorithm = "AES256"
  }
  
  tags = {
    Name = "ResQ Terraform State"
    Project = "ResQ"
  }
}
