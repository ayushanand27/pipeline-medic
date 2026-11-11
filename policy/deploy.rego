# Policy as code: rules a release must pass before it is deployed.
# Written in Rego and checked by Open Policy Agent (OPA).
#
# input.manifests = the Kubernetes objects we are about to apply
# input.security  = the summary written by `python -m medic.triage`
#
# Every rule adds a message to `deny`. An empty `deny` means the release may go out.
package deploy

import rego.v1

deployments contains manifest if {
	some manifest in input.manifests
	manifest.kind == "Deployment"
}

containers contains container if {
	some deployment in deployments
	some container in deployment.spec.template.spec.containers
}

# --- Kubernetes rules ---------------------------------------------------------

deny contains msg if {
	some container in containers
	not container.resources.limits
	msg := sprintf("container '%s' has no CPU/memory limits", [container.name])
}

deny contains msg if {
	some container in containers
	not container.readinessProbe
	msg := sprintf("container '%s' has no readiness probe", [container.name])
}

deny contains msg if {
	some container in containers
	endswith(container.image, ":latest")
	msg := sprintf("container '%s' uses the ':latest' tag, so we cannot tell which version runs", [container.name])
}

deny contains msg if {
	some container in containers
	count(split(container.image, ":")) < 2
	msg := sprintf("container '%s' has no image tag", [container.name])
}

deny contains msg if {
	some container in containers
	container.securityContext.privileged == true
	msg := sprintf("container '%s' runs in privileged mode", [container.name])
}

deny contains msg if {
	some deployment in deployments
	deployment.spec.replicas < 2
	msg := sprintf("deployment '%s' has fewer than 2 replicas, so one crash means downtime", [deployment.metadata.name])
}

# --- Security rules -----------------------------------------------------------

deny contains msg if {
	input.security.secrets > 0
	msg := sprintf("%d secret(s) found in the repo", [input.security.secrets])
}

deny contains msg if {
	input.security.critical_fixable > 0
	msg := sprintf("%d critical vulnerability(ies) with a fix available", [input.security.critical_fixable])
}

deny contains msg if {
	input.security.known_exploited_fixable > 0
	msg := sprintf("%d vulnerability(ies) that attackers are exploiting right now, with a fix available", [input.security.known_exploited_fixable])
}
