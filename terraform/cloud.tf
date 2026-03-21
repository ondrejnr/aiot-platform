terraform {
  cloud {
    organization = "testnr"
    workspaces {
      name = "aiot-infra"
    }
  }

  required_version = ">= 1.7.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.24"
    }
  }
}
