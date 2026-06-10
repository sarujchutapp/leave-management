terraform {
  required_version = ">= 1.10"

  # Remote state in S3 with native lockfile (use_lockfile, Terraform 1.10+) — no
  # DynamoDB lock table. The bucket is created once out-of-band (see SETUP.md §5)
  # and is not managed by Terraform. Backends can't take variables, so these are
  # literals; the bucket lives in the same region as the rest of the stack.
  backend "s3" {
    bucket       = "your-tfstate-bucket"
    key          = "leave-management/terraform.tfstate"
    region       = "ap-southeast-7"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
