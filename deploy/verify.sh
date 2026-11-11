#!/usr/bin/env bash
# Checks that the new version is really working. If not, goes back to the previous version.
#   1. wait for the rollout (all new pods pass their readiness probe)
#   2. call /health through the Service
#   3. smoke test: send real requests and allow zero errors
# Exit code 0 = healthy. Exit code 1 = it was unhealthy and a rollback was attempted.
set -uo pipefail

NAMESPACE="demo"
DEPLOYMENT="deployment/demo-app"
LOCAL_PORT=18080
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-120s}"
SMOKE_REQUESTS="${SMOKE_REQUESTS:-20}"

rollback() {
  echo "verify failed: $1"
  if kubectl -n "$NAMESPACE" rollout undo "$DEPLOYMENT"; then
    kubectl -n "$NAMESPACE" rollout status "$DEPLOYMENT" --timeout=120s || true
    echo "rolled back to the previous version"
  else
    echo "nothing to roll back to (this was the first deploy)"
  fi
  exit 1
}

kubectl -n "$NAMESPACE" rollout status "$DEPLOYMENT" --timeout="$ROLLOUT_TIMEOUT" || rollback "rollout did not finish in $ROLLOUT_TIMEOUT"

kubectl -n "$NAMESPACE" port-forward service/demo-app "$LOCAL_PORT:80" >/dev/null 2>&1 &
FORWARD_PID=$!
trap 'kill "$FORWARD_PID" 2>/dev/null || true' EXIT
BASE="http://127.0.0.1:${LOCAL_PORT}"

HEALTHY=""
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if BODY="$(curl -fsS "$BASE/health" 2>/dev/null)"; then
    echo "healthy: ${BODY}"
    HEALTHY="yes"
    break
  fi
  sleep 2
done
[[ -n "$HEALTHY" ]] || rollback "/health did not answer"

ERRORS=0
for request in $(seq 1 "$SMOKE_REQUESTS"); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/quote?amount=1000&coupon=WELCOME10")"
  [[ "$CODE" = "200" ]] || ERRORS=$((ERRORS + 1))
done
echo "smoke test: ${ERRORS} errors in ${SMOKE_REQUESTS} requests"
[[ "$ERRORS" -eq 0 ]] || rollback "smoke test had ${ERRORS} errors"
