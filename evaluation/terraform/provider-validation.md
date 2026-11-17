# Phase 9 local Terraform provider validation

Run November 15, 2026, against `fc8323c9f40919120852814653d15bb971ac272e` using Terraform **1.17.2** on Windows amd64. Validated the unchanged AWS example in an isolated copy.

| Provider package | Verified result |
|---|---|
| Provider | `registry.terraform.io/hashicorp/aws` **5.100.0**, `windows_amd64` |
| ZIP | `terraform-provider-aws_5.100.0_windows_amd64.zip`, **156,704,800 bytes** |
| Download | [HashiCorp release ZIP](https://releases.hashicorp.com/terraform-provider-aws/5.100.0/terraform-provider-aws_5.100.0_windows_amd64.zip) |
| Package SHA-256 | `9f8b909d3ec50ade83c8062290378b1ec553edef6a447c56dadc01a99f4eaa93` |
| Published SHA-256 | `9f8b909d3ec50ade83c8062290378b1ec553edef6a447c56dadc01a99f4eaa93` ([official checksum file](https://releases.hashicorp.com/terraform-provider-aws/5.100.0/terraform-provider-aws_5.100.0_SHA256SUMS)) |
| Verification | Exact SHA-256 match before installation |

| Command | Result |
|---|---|
| `terraform fmt -check -diff -recursive` | Exit 0 |
| `terraform init -backend=false -input=false` | Exit 0. Installed only AWS 5.100.0 from the packed filesystem mirror. Terraform generated a Windows-only lock in the isolated copy and warned about its platform-specific checksums. The mirror installer labelled the package unauthenticated. The separate official SHA-256 check above passed. |
| `terraform validate` | Exit 0. `Success! The configuration is valid.` No schema diagnostics. |
| `terraform providers` | Exit 0. Only `registry.terraform.io/hashicorp/aws`, constrained to `~> 5.0`. |
| `terraform providers schema -json` | Exit 0. Schema format 1.0, 1,526 resource schemas and 608 data-source schemas. The schema contains all six resource types used by the example and the `aws_availability_zones` data source. |

The first two validation attempts failed before receiving the schema. The loopback plugin RPC reported an untrusted certificate during automatic mTLS. The successful validation and schema commands set `TF_DISABLE_PLUGIN_TLS=1` only for the isolated local processes. Provider code, Terraform configuration, version constraints and the repository lockfile state were unchanged. The captured schema JSON had SHA-256 `cb0e8a42f6eaea3983698d70cba213a630c661420f974a7246685d026da32781`.

The filesystem mirror was limited to the approved provider and omitted direct installation. Checkpoint was disabled. The subprocess environment omitted AWS credentials and pointed AWS configuration and credential paths at an empty directory. Traces recorded local schema and validation RPCs with no AWS configure/read/plan/apply operations or external HTTP activity. The only network retrievals were the ZIP and checksum file above. No remote backend, state files, plan, apply, destroy, cloud API calls, or cloud resource changes. The generated lockfile and installed plugin stayed in the isolated copy.

This proves local compatibility with the selected provider and platform. AWS deployment behavior, availability, permissions and cost were outside the check.
