terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Shared state for the team: create the bucket once, then uncomment and run `terraform init`.
  # backend "s3" {
  #   bucket       = "vishue-terraform-state-<account-id>"
  #   key          = "aws/terraform.tfstate"
  #   region       = "ap-northeast-2"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "vishue"
      ManagedBy = "terraform"
    }
  }
}
