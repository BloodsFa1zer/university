#!/usr/bin/env bash
# Rule R7: among the running containers of the project, only `gateway` may publish
# ports on the host. Prints `PORTS OK`, or the offenders and exits non-zero.
# Meant for the base mode (`make up`); the dev mode publishes extra ports on purpose.
set -euo pipefail

project="${COMPOSE_PROJECT_NAME:-bankmon}"
listing="$(docker ps --filter "label=com.docker.compose.project=${project}" \
  --format '{{.Label "com.docker.compose.service"}}|{{.Ports}}')"

violations=""
while IFS='|' read -r service ports; do
  # Published ports look like "127.0.0.1:5432->5432/tcp"; merely exposed ones have no "->".
  if [ -n "$service" ] && [ "$service" != "gateway" ] && [[ "$ports" == *"->"* ]]; then
    violations="${violations}  ${service}: ${ports}"$'\n'
  fi
done <<< "$listing"

if [ -n "$violations" ]; then
  echo "PORTS FAIL — published by services other than gateway:"
  printf '%s' "$violations"
  exit 1
fi
echo "PORTS OK"
