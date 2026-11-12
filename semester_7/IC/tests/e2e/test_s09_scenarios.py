"""S9: every anomaly scenario is visible in metrics, logs and traces (docs/00-common.md §11).

Each test: quiet system → scenario on → its alerts fire → its metrics, log lines and
traces are there → back to normal → every alert clears, the queue drains, the books
still balance.
"""

import time

import pytest

from bankmon_common import amqp

from .helpers import (
    alert_states,
    check_invariants,
    control_put,
    loki_query,
    prom_value,
    queue_counts,
    tempo_search,
    tempo_trace,
    trace_spans,
    wait_alert,
    wait_all_alerts_inactive,
    wait_queue_drained,
    wait_until,
)

P95 = "histogram_quantile(0.95, sum by (le) (rate(bank_transfer_processing_seconds_bucket[1m])))"
FAILED_RATIO = (
    'sum(rate(bank_transfers_processed_total{status="failed"}[1m]))'
    " / sum(rate(bank_transfers_processed_total[1m]))"
)
DEADLOCKS = 'sum(pg_stat_database_deadlocks{datname="bank"})'
RETRIES = 'sum(bank_transfer_retries_total{reason="deadlock"})'
ROLLBACKS = 'sum(rate(pg_stat_database_xact_rollback{datname="bank"}[1m]))'
QUEUE = 'rabbitmq_queue_messages_ready{queue="transfers.requested"}'


def _since(started: float) -> float:
    return time.time() - started + 1


def _value(expr: str) -> float:
    value = prom_value(expr)
    return value if value is not None else 0.0


def _quiet_system() -> None:
    wait_all_alerts_inactive(timeout=240)
    wait_queue_drained(timeout=120)


def _wait_firing(alerts: list[str]) -> None:
    for alert in alerts:
        wait_alert(alert, "firing", timeout=120)


def _wait_metric(expr: str, ok, desc: str, timeout: float = 90) -> None:
    wait_until(
        lambda: (value := prom_value(expr)) is not None and ok(value),
        timeout=timeout,
        interval=2,
        desc=desc,
    )


def _wait_logs(logql: str, started: float) -> list[dict]:
    return wait_until(lambda: loki_query(logql, since_s=_since(started)), timeout=60, desc=logql)


def _wait_traces(traceql: str, started: float) -> list[dict]:
    return wait_until(
        lambda: tempo_search(traceql, since_s=_since(started)), timeout=60, desc=traceql
    )


def _back_to_normal_and_settled() -> None:
    control_put(scenario="normal")
    wait_until(
        lambda: set(alert_states().values()) == {"inactive"},
        timeout=150,
        interval=2,
        desc="every alert to clear after the scenario",
    )
    wait_until(
        lambda: queue_counts(amqp.TRANSFERS_QUEUE)[0] < 50,
        timeout=120,
        desc="the queue to drain",
    )
    assert check_invariants() == []


@pytest.mark.slow
def test_s09_ac1_slow_queries(scenario):
    _quiet_system()
    started = time.time()
    scenario("slow_queries")
    _wait_firing(["TransferProcessingSlow", "QueueBacklog"])
    _wait_metric(P95, lambda v: v > 0.5, "p95 above 0.5 s")
    _wait_metric(QUEUE, lambda v: v > 200, "more than 200 waiting messages")
    _wait_logs('{service="postgres"} |= "duration:" |= "pg_sleep"', started)
    _wait_traces(
        '{ resource.service.name = "worker" && name = "worker.process_transfer"'
        " && duration > 700ms }",
        started,
    )
    _back_to_normal_and_settled()


@pytest.mark.slow
def test_s09_ac2_lock_contention(scenario):
    _quiet_system()
    started = time.time()
    scenario("lock_contention")
    _wait_firing(["LockWaiters", "TransferProcessingSlow"])
    _wait_metric("max_over_time(bank_db_lock_waiters[1m])", lambda v: v >= 1, "lock waiters")
    _wait_metric(
        "max_over_time(bank_db_longest_transaction_seconds[1m])",
        lambda v: v > 0.3,
        "a transaction older than 0.3 s",
    )
    _wait_logs('{service="postgres"} |= "still waiting for"', started)
    _wait_traces(
        '{ resource.service.name = "worker" && name = "worker.process_transfer"'
        " && duration > 300ms }",
        started,
    )
    _back_to_normal_and_settled()


@pytest.mark.slow
def test_s09_ac3_deadlocks(scenario):
    _quiet_system()
    deadlocks_before, retries_before = _value(DEADLOCKS), _value(RETRIES)
    started = time.time()
    scenario("deadlocks")
    _wait_firing(["DeadlocksDetected"])
    _wait_metric(DEADLOCKS, lambda v: v >= deadlocks_before + 3, "3 more deadlocks")
    _wait_metric(RETRIES, lambda v: v > retries_before, "deadlock retries")
    _wait_logs('{service="postgres"} |= "deadlock detected"', started)
    _wait_logs('{service="worker"} | json | event="deadlock_retry"', started)
    _wait_traces("{ span.bank.attempts > 1 }", started)
    _back_to_normal_and_settled()


@pytest.mark.slow
def test_s09_ac4_failures(scenario):
    _quiet_system()
    rollbacks_before = _value(ROLLBACKS)
    started = time.time()
    scenario("failures")
    _wait_firing(["TransferFailureRatioHigh"])
    _wait_metric(FAILED_RATIO, lambda v: v > 0.2, "failed share above 20 %")
    _wait_metric(ROLLBACKS, lambda v: v > rollbacks_before, "more rollbacks than before")
    _wait_logs('{service="postgres"} |= "violates check constraint"', started)
    _wait_logs(
        '{service="worker"} | json | event="transfer_failed" | reason="insufficient_funds"',
        started,
    )
    _wait_traces(
        '{ span.bank.status = "failed" && span.bank.fail_reason = "insufficient_funds" }',
        started,
    )
    _back_to_normal_and_settled()


@pytest.mark.slow
def test_s09_ac5_metric_log_trace_chain(scenario):
    """From a failed transfer to its log line, from the line to its trace, and back."""
    started = time.time()
    scenario("failures")
    rows = _wait_logs(
        '{service="worker"} | json | event="transfer_failed" | reason="insufficient_funds"',
        started,
    )
    line = rows[0]["json"]
    transfer_id, trace_id = line["transfer_id"], line["trace_id"]

    def worker_span() -> dict | None:
        # Spans arrive in batches: the trace may exist before the worker's span is in it.
        trace = tempo_trace(trace_id)
        spans = [s for s in trace_spans(trace or {}) if s["name"] == "worker.process_transfer"]
        return spans[0] if spans else None

    span = wait_until(worker_span, timeout=30, desc=f"worker span of trace {trace_id}")
    assert span["attributes"]["bank.transfer_id"] == transfer_id
    assert span["attributes"]["bank.status"] == "failed"
    control_put(scenario="normal")
