#!/usr/bin/env bash
# Checks that the last 200 log lines of a service are JSON objects with the required
# fields of docs/00-common.md §6.11. Prints `JSON LOGS OK (<service>, <lines>)`.
# Usage: scripts/check_json_logs.sh <service>
set -euo pipefail

service="${1:?usage: $0 <service>}"
logs="$(docker compose logs --no-log-prefix --no-color --tail 200 "$service")"
if [ -z "$logs" ]; then
  echo "JSON LOGS FAIL ($service): the service has no log lines"
  exit 1
fi

# Validated with Python inside the tests image, so the host needs nothing but Docker.
read -r -d '' check <<'PY' || true
import json
import sys

service = sys.argv[1]
required = ("ts", "level", "service", "logger", "event", "msg")
levels = {"debug", "info", "warning", "error"}
lines = [line for line in sys.stdin.read().splitlines() if line.strip()]
problems = []
for number, line in enumerate(lines, 1):
    try:
        record = json.loads(line)
    except ValueError:
        problems.append(f"line {number} is not JSON: {line[:150]}")
        continue
    if not isinstance(record, dict):
        problems.append(f"line {number} is not a JSON object")
        continue
    missing = [key for key in required if key not in record]
    if missing:
        problems.append(f"line {number} misses {missing}")
    elif record["service"] != service:
        problems.append(f"line {number} has service={record['service']!r}")
    elif record["level"] not in levels:
        problems.append(f"line {number} has level={record['level']!r}")
if problems:
    print(f"JSON LOGS FAIL ({service}):")
    print("\n".join(problems[:10]))
    sys.exit(1)
print(f"JSON LOGS OK ({service}, {len(lines)})")
PY

docker compose --profile test run --rm -T --no-deps tests python -c "$check" "$service" <<< "$logs" 2>/dev/null
