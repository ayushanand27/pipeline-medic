package deploy_test

import rego.v1

import data.deploy

good_container := {
	"name": "demo-app",
	"image": "demo-app:abc123",
	"readinessProbe": {"httpGet": {"path": "/health", "port": 8000}},
	"resources": {"limits": {"cpu": "250m", "memory": "128Mi"}},
}

manifest(replicas, container) := {
	"kind": "Deployment",
	"metadata": {"name": "demo-app"},
	"spec": {"replicas": replicas, "template": {"spec": {"containers": [container]}}},
}

clean := {"secrets": 0, "critical_fixable": 0, "known_exploited_fixable": 0}

test_good_release_is_allowed if {
	count(deploy.deny) == 0 with input as {"manifests": [manifest(2, good_container)], "security": clean}
}

test_latest_tag_is_denied if {
	container := object.union(good_container, {"image": "demo-app:latest"})
	count(deploy.deny) == 1 with input as {"manifests": [manifest(2, container)], "security": clean}
}

test_missing_tag_is_denied if {
	container := object.union(good_container, {"image": "demo-app"})
	count(deploy.deny) == 1 with input as {"manifests": [manifest(2, container)], "security": clean}
}

test_missing_limits_is_denied if {
	container := object.remove(good_container, ["resources"])
	count(deploy.deny) == 1 with input as {"manifests": [manifest(2, container)], "security": clean}
}

test_missing_readiness_probe_is_denied if {
	container := object.remove(good_container, ["readinessProbe"])
	count(deploy.deny) == 1 with input as {"manifests": [manifest(2, container)], "security": clean}
}

test_privileged_container_is_denied if {
	container := object.union(good_container, {"securityContext": {"privileged": true}})
	count(deploy.deny) == 1 with input as {"manifests": [manifest(2, container)], "security": clean}
}

test_single_replica_is_denied if {
	count(deploy.deny) == 1 with input as {"manifests": [manifest(1, good_container)], "security": clean}
}

test_secret_in_repo_is_denied if {
	count(deploy.deny) == 1 with input as {
		"manifests": [manifest(2, good_container)],
		"security": {"secrets": 1, "critical_fixable": 0},
	}
}

test_fixable_critical_vulnerability_is_denied if {
	count(deploy.deny) == 1 with input as {
		"manifests": [manifest(2, good_container)],
		"security": {"secrets": 0, "critical_fixable": 3},
	}
}

test_exploited_vulnerability_is_denied_even_if_not_critical if {
	count(deploy.deny) == 1 with input as {
		"manifests": [manifest(2, good_container)],
		"security": {"secrets": 0, "critical_fixable": 0, "known_exploited_fixable": 1},
	}
}
