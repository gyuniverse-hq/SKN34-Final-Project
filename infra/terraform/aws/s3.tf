# Backup dumps, catalog archives, and future non-secret assets.
# Buckets stay private; apps reach them through the VPC S3 gateway endpoint (no NAT).

resource "aws_s3_bucket" "ops" {
  bucket_prefix = "${var.name}-ops-"
}

resource "aws_s3_bucket_public_access_block" "ops" {
  bucket = aws_s3_bucket.ops.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "ops" {
  bucket = aws_s3_bucket.ops.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ops" {
  bucket = aws_s3_bucket.ops.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "ops" {
  bucket = aws_s3_bucket.ops.id

  rule {
    id     = "expire-old-dumps"
    status = "Enabled"

    filter {
      prefix = "dumps/"
    }

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# Private subnets reach S3 without hairpinning through NAT (image layers + our dumps).
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids

  tags = {
    Name = "${var.name}-s3"
  }
}
