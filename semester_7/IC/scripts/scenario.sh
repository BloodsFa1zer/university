#!/usr/bin/env bash
# Switch the load scenario from the command line.
# Usage: scripts/scenario.sh <scenario> [ttl_seconds]   (or: make scenario NAME=... TTL=...)
# The request goes to the generator from inside its own container, so it needs no login.
set -euo pipefail

names="normal slow_queries lock_contention deadlocks failures"
name="${1:-}"
ttl="${2:-}"

if [ -z "$name" ] || [[ " $names " != *" $name "* ]]; then
  echo "Unknown scenario '${name}'. Use one of: ${names}" >&2
  exit 2
fi

body="{\"scenario\": \"${name}\""
if [ -n "$ttl" ]; then
  body="${body}, \"ttl_s\": ${ttl}"
fi
body="${body}}"

read -r -d '' put <<'PY' || true
import json
import sys
import urllib.error
import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:8000/control/api/state",
    data=sys.argv[1].encode(),
    method="PUT",
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
except urllib.error.HTTPError as error:
    print(f"HTTP {error.code}: {error.read().decode()}", file=sys.stderr)
    sys.exit(1)
PY

docker compose exec -T generator python -c "$put" "$body"
