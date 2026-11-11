#!/usr/bin/env bash
# Proves that the rollback really works, on every pipeline run.
#   1. ship a broken release on purpose (its health check always fails)
#   2. verify.sh must catch it and roll back
#   3. the previous good version must still be serving
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== shipping a broken release on purpose"
kubectl -n demo set env deployment/demo-app FAIL_HEALTH=true

if ROLLOUT_TIMEOUT=45s "$HERE/verify.sh"; then
  echo "drill FAILED: the broken release was accepted"
  exit 1
fi

echo "== checking that the good version is back"
if "$HERE/verify.sh"; then
  echo "drill passed: the broken release was caught and rolled back"
else
  echo "drill FAILED: the app is not healthy after the rollback"
  exit 1
fi
