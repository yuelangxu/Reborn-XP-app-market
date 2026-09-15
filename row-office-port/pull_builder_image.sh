#!/usr/bin/env bash
set -euo pipefail

IMAGE=${1:?builder image is required}
MAX_ATTEMPTS=${ROW_IMAGE_PULL_ATTEMPTS:-6}

if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "[ROW] builder image already present locally: $IMAGE"
  docker image inspect --format='[ROW] local builder image id: {{.Id}}' "$IMAGE" || true
  exit 0
fi

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  if [ "$attempt" -gt 1 ]; then
    case "$attempt" in
      2) delay=15 ;;
      3) delay=30 ;;
      4) delay=60 ;;
      5) delay=90 ;;
      *) delay=120 ;;
    esac
    echo "[ROW] builder image pull retry $attempt/$MAX_ATTEMPTS after ${delay}s"
    sleep "$delay"
  else
    echo "[ROW] builder image pull attempt $attempt/$MAX_ATTEMPTS"
  fi

  if docker pull "$IMAGE"; then
    echo "[ROW] builder image pull succeeded"
    docker image inspect --format='[ROW] pulled builder image id: {{.Id}}' "$IMAGE" || true
    docker image inspect --format='[ROW] repo digests: {{join .RepoDigests ","}}' "$IMAGE" || true
    exit 0
  fi

  echo "[ROW] WARNING: builder image pull attempt $attempt failed"
  attempt=$((attempt + 1))
done

echo "[ROW] ERROR: unable to obtain builder image after $MAX_ATTEMPTS attempts" >&2
exit 75
