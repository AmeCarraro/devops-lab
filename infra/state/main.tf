# The S3 bucket that keeps the Terraform state of infra/cluster: the state is not a file on
# one PC, every version of it is kept, and a lock file in the bucket stops two runs from
# changing the cluster at the same time.
# Applied once. Its own state stays in this folder: a bucket cannot hold the state of the
# stack that creates it.
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = "devops-lab"
    }
  }
}

variable "region" {
  description = "AWS region of the bucket, the same as the cluster's"
  type        = string
  default     = "eu-north-1"
}

data "aws_caller_identity" "me" {}

resource "aws_s3_bucket" "state" {
  # bucket names are global: the account ID makes this one unique
  bucket = "devops-lab-tfstate-${data.aws_caller_identity.me.account_id}"

  # the state is the only record of what Terraform created: a destroy must not take it away
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Old versions of the state are kept for 30 days: enough to go back after a bad apply
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# The state can hold secrets: refuse any request that is not encrypted in transit
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "HttpsOnly"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.state]
}

# The backend settings of infra/cluster, written next to it. Git-ignored: it names the account
resource "local_file" "cluster_backend" {
  filename        = "${path.module}/../cluster/backend.hcl"
  file_permission = "0644"
  content         = <<-EOT
    bucket       = "${aws_s3_bucket.state.id}"
    key          = "cluster/terraform.tfstate"
    region       = "${var.region}"
    use_lockfile = true
    encrypt      = true
  EOT
}

output "bucket" {
  value = aws_s3_bucket.state.id
}
