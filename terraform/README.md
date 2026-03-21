# Terraform bootstrap

This directory bootstraps HCP Terraform workspace connectivity for `testnr/aiot-infra`.

Current status:
- remote state exists in HCP Terraform
- workspace is `aiot-infra`
- provider in state: `hashicorp/google`

Important:
- auto-apply must remain OFF
- do not run apply until full Terraform resource definitions are reconstructed
