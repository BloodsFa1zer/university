#!/usr/bin/env bash
# Confirms that every image pinned in docs/00-common.md §3 exists in its registry
# and has a build for this Docker host's CPU architecture.
# Prints one line per image and `IMAGES OK (10)` at the end; exits non-zero on any failure.
set -euo pipefail

IMAGES="
postgres:17.11
rabbitmq:4.3.7-management
prom/prometheus:v3.15.1
prometheuscommunity/postgres-exporter:v0.20.1
grafana/grafana:13.2.6
grafana/loki:3.6.20
grafana/alloy:v1.21.3
grafana/tempo:2.10.10
nginx:1.30.6-alpine
python:3.13.18-slim
"

arch="$(docker version --format '{{.Server.Arch}}')"
ok=0
failed=0

for image in $IMAGES; do
  if ! manifest="$(docker manifest inspect "$image" 2>&1)"; then
    echo "FAIL  $image: ${manifest%%$'\n'*}"
    failed=$((failed + 1))
  elif ! grep -q "\"architecture\": *\"$arch\"" <<< "$manifest"; then
    echo "FAIL  $image: no linux/$arch build"
    failed=$((failed + 1))
  else
    echo "OK    $image (linux/$arch)"
    ok=$((ok + 1))
  fi
done

if [ "$failed" -gt 0 ]; then
  echo "IMAGES FAILED ($failed of $((ok + failed)))"
  exit 1
fi
echo "IMAGES OK ($ok)"
