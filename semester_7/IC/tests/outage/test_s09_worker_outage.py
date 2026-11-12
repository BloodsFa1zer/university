"""S9-AC6: the worker is stopped and started again; nothing is lost.

Three pytest runs, `make outage-test` stops and starts the worker in between:
  phase0 — baseline: how many transfers exist and how many the generator has sent;
  phase1 — worker stopped: the target is down, the queue grows, two alerts fire;
  phase2 — worker started: the backlog drains, every sent transfer is recorded.
The phases share their numbers through a file on the `tests_state` volume.
"""

import json

from bankmon_common import amqp
from e2e.helpers import (
    GENERATOR_URL,
    WORKER_URL,
    alert_states,
    check_invariants,
    control_put,
    db,
    metric_value,
    prom_value,
    queue_counts,
    wait_alert,
    wait_queue_drained,
    wait_until,
)

SENT = {"operation": "transfer", "result": "ok"}


def _snapshot() -> dict:
    """Count of transfer rows and of transfers the generator sent, with no load running."""
    control_put(running=False)
    wait_queue_drained(timeout=180)
    wait_until(
        lambda: metric_value(WORKER_URL, "bank_worker_in_flight") == 0,
        timeout=30,
        desc="the worker to finish its messages",
    )
    with db() as conn:
        (rows,) = conn.execute("SELECT count(*) FROM transfers").fetchone()
    sent = metric_value(GENERATOR_URL, "bank_generator_operations_total", SENT)
    return {"rows": rows, "sent": sent}


def test_phase0_baseline(state_file):
    try:
        state_file.write_text(json.dumps(_snapshot()))
    finally:
        control_put(running=True)


def test_phase1_backlog():
    wait_until(lambda: prom_value('up{job="worker"}') == 0, timeout=30, desc="worker down")
    wait_until(
        lambda: queue_counts(amqp.TRANSFERS_QUEUE)[0] > 200,
        timeout=60,
        desc="more than 200 waiting messages",
    )
    wait_alert("QueueBacklog", "firing", timeout=120)
    wait_alert("ServiceDown", "firing", timeout=120)


def test_phase2_recovery(state_file):
    before = json.loads(state_file.read_text())
    wait_until(
        lambda: queue_counts(amqp.TRANSFERS_QUEUE)[0] < 50,
        timeout=120,
        desc="the backlog to drain",
    )
    try:
        after = _snapshot()
        # Every transfer the generator sent while the worker was away is now a row.
        assert after["rows"] - before["rows"] == after["sent"] - before["sent"], (before, after)
        assert check_invariants() == []
    finally:
        control_put(running=True)
    wait_until(
        lambda: set(alert_states().values()) == {"inactive"},
        timeout=150,
        interval=2,
        desc="every alert to clear",
    )
