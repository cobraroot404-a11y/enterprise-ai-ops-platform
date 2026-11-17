variable "region" {
  description = "AWS region for the illustrative blueprint."
  type        = string
  default     = "eu-west-1"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "eaop-example"
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "db_instance_class" {
  description = "RDS instance class (PostgreSQL 16 with the pgvector extension enabled by the migration task)."
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage_gb" {
  description = "Allocated database storage in GB."
  type        = number
  default     = 50
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = { project = "enterprise-ai-operations-platform", purpose = "illustrative-blueprint" }
}
