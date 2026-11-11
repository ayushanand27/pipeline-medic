#!/usr/bin/env bash
# Checks the error rate that Prometheus measured. Rolls the app back if it is too high.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LOCAL_PORT=19090

kubectl -n demo rollout status deployment/prometheus --timeout=180s || { echo "Prometheus did not start"; exit 1; }

kubectl -n demo port-forward service/prometheus "$LOCAL_PORT:9090" >/dev/null 2>&1 &
FORWARD_PID=$!
trap 'kill "$FORWARD_PID" 2>/dev/null || true' EXIT
sleep 3

if python3 "$HERE/metrics_check.py" "http://127.0.0.1:${LOCAL_PORT}"; then
  exit 0
fi

echo "error rate too high: rolling back"
kubectl -n demo rollout undo deployment/demo-app && kubectl -n demo rollout status deployment/demo-app --timeout=120s
exit 1
