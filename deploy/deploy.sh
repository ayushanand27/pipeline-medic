#!/usr/bin/env bash
# Usage: ./deploy/deploy.sh demo-app:<tag>
# Applies the manifests with the given image. Needs kubectl pointed at the cluster.
set -euo pipefail

IMAGE="${1:?give the image, for example demo-app:abc123}"
HERE="$(cd "$(dirname "$0")" && pwd)"

sed "s|demo-app:IMAGE_TAG|${IMAGE}|" "$HERE/k8s/deployment.yaml" | kubectl apply -f -
echo "applied ${IMAGE}"
