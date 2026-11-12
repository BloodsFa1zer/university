#!/usr/bin/env bash
# Full check of BankMonitor from a clean state (docs/30-release.md, S9).
# Steps run one after another; each is timed. The last line is `VERIFY OK`, or the
# failed step with the state of the containers. The stack stays up afterwards.
set -uo pipefail
cd "$(dirname "$0")/.."

report=""
started_all=$(date +%s)

finish_failed() {
  local step="$1"
  echo
  echo "VERIFY FAILED at step: $step"
  docker compose ps -a
  for name in $(docker compose ps -a --format '{{.Service}} {{.Status}}' \
      | grep -v -E 'healthy\)|^grafana-init Exited \(0\)|^(loki|alloy|tempo) Up' \
      | awk '{print $1}'); do
    echo "----- last 40 lines of $name -----"
    docker compose logs --no-log-prefix --tail 40 "$name"
  done
  exit 1
}

run_step() {
  local name="$1"
  shift
  local started
  started=$(date +%s)
  echo
  echo "===== $name ====="
  if "$@"; then
    report="${report}$(printf '%-26s %6ss   OK' "$name" "$(( $(date +%s) - started ))")"$'\n'
  else
    report="${report}$(printf '%-26s %6ss   FAIL' "$name" "$(( $(date +%s) - started ))")"$'\n'
    printf '%s' "$report"
    finish_failed "$name"
  fi
}

json_logs() {
  scripts/check_json_logs.sh worker && scripts/check_json_logs.sh generator \
    && scripts/check_json_logs.sh auth
}

final_state() {
  # Scenario, generator and alerts, checked from inside the network.
  docker compose --profile test run --rm -T tests python - <<'PY' || return 1
import sys
sys.path.insert(0, "/repo/tests")
from e2e.helpers import alert_states, control_get, wait_until

state = control_get()
assert state["scenario"] == "normal" and state["running"], state
wait_until(lambda: set(alert_states().values()) == {"inactive"}, timeout=180, interval=2,
           desc="every alert to be inactive")
print("scenario normal, generator running, no active alerts")
PY
  # No container was restarted by Docker during the run.
  local restarted
  restarted=$(docker ps -q --filter label=com.docker.compose.project=bankmon \
    | xargs docker inspect -f '{{.Name}} {{.RestartCount}}' | awk '$2 != 0')
  if [ -n "$restarted" ]; then
    echo "restarted containers: $restarted"
    return 1
  fi
  echo "every container: RestartCount 0"
}

run_step "make clean" make clean
run_step "check images" scripts/check_images.sh
run_step "make up" make up
run_step "make check-ports" make check-ports
run_step "make lint" make lint
run_step "make unit" make unit
run_step "make e2e" make e2e
run_step "make outage-test" make outage-test
run_step "JSON logs" json_logs
run_step "final state" final_state

echo
echo "Step                       Time    Result"
printf '%s' "$report"
echo "Total: $(( $(date +%s) - started_all ))s"
echo "VERIFY OK"
