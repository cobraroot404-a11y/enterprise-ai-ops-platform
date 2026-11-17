terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# No credentials are configured here. `terraform validate` needs none; `plan` and `apply` are NOT part of this repository's workflow.
provider "aws" {
  region = var.region
}
