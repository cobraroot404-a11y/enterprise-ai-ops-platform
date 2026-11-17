# Terraform (illustrative AWS blueprint)

These files sketch the network, private PostgreSQL 16 instance and secret containers described in [cloud portability](../../docs/architecture/cloud-portability.md). Terraform 1.17.2 passed formatting and validated the configuration against AWS provider 5.100.0 on Windows amd64. The [local validation record](../../evaluation/terraform/provider-validation.md) gives the exact package, checksum and command results. No cloud resource was provisioned and no AWS credential was used.

## Local validation

In an isolated copy, set `TF_CLI_CONFIG_FILE` to a CLI configuration containing only a `filesystem_mirror` installation method for `registry.terraform.io/hashicorp/aws`. Populate the mirror with the checksum-verified package at `registry.terraform.io/hashicorp/aws/terraform-provider-aws_5.100.0_windows_amd64.zip`. Obtain owner approval for any missing package before retrieval. Disable checkpoint calls, then run:

```sh
terraform fmt -check -diff -recursive
terraform init -backend=false -input=false
terraform validate
terraform providers
terraform providers schema -json
```

The recorded run used Terraform. The OpenTofu alternative has not been exercised here. Cloud planning and deployment are outside this repository's local validation workflow.

| File | Purpose |
|---|---|
| `versions.tf` | Terraform and provider version constraints (AWS provider ~> 5.0); provider without credentials |
| `variables.tf` | Inputs with defaults |
| `main.tf` | VPC, two private subnets, security groups, Multi-AZ encrypted private PostgreSQL, secret containers |
| `outputs.tf` | VPC, subnets, database endpoint, application security group |
| `terraform.tfvars.example` | Example values, no secrets |

Not included on purpose: container images, ECS services, load balancer, WAF, egress proxy, IAM roles, Azure and Google equivalents (comparison only).
