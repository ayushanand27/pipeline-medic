#!/usr/bin/env bash
# Checks that the new version is really working. If not, goes back to the previous version.
#   1. wait for the rollout (all new pods pass their readiness probe)
#   2. call /health through the Service
set -uo pipefail

NAMESPACE="demo"
DEPLOYMENT="deployment/demo-app"
LOCAL_PORT=18080

rollback() {
  echo "verify failed: $1"
  kubectl -n "$NAMESPACE" describe "$DEPLOYMENT" | tail -n 20 || true
  if kubectl -n "$NAMESPACE" rollout undo "$DEPLOYMENT"; then
    kubectl -n "$NAMESPACE" rollout status "$DEPLOYMENT" --timeout=120s || true
    echo "rolled back to the previous version"
  else
    echo "nothing to roll back to (this was the first deploy)"
  fi
  exit 1
}

kubectl -n "$NAMESPACE" rollout status "$DEPLOYMENT" --timeout=120s || rollback "rollout did not finish"

kubectl -n "$NAMESPACE" port-forward service/demo-app "$LOCAL_PORT:80" >/dev/null 2>&1 &
FORWARD_PID=$!
trap 'kill "$FORWARD_PID" 2>/dev/null || true' EXIT

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if BODY="$(curl -fsS "http://127.0.0.1:${LOCAL_PORT}/health" 2>/dev/null)"; then
    echo "healthy: ${BODY}"
    exit 0
  fi
  sleep 2
done

rollback "/health did not answer"
