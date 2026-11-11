# Infrastructure as code: this file describes the Kubernetes cluster.
# "kind" runs a Kubernetes cluster inside Docker containers, so it works on a laptop and in CI.

terraform {
  required_version = ">= 1.5"

  required_providers {
    kind = {
      source  = "tehcyx/kind"
      version = ">= 0.5.0"
    }
  }
}

provider "kind" {}

variable "cluster_name" {
  description = "Name of the kind cluster"
  type        = string
  default     = "pipeline-medic"
}

resource "kind_cluster" "this" {
  name            = var.cluster_name
  wait_for_ready  = true
  kubeconfig_path = abspath("${path.module}/kubeconfig")
}

output "kubeconfig_path" {
  description = "Point KUBECONFIG at this file to use kubectl with the cluster"
  value       = kind_cluster.this.kubeconfig_path
}

output "endpoint" {
  value = kind_cluster.this.endpoint
}
