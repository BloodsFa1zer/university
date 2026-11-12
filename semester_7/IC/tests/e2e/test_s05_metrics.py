"""S5: Prometheus, the database metrics and the alerting rules (§6.9, §6.10, §11)."""

import os
import re
from urllib.parse import urljoin

import pytest

from .helpers import (
    ADMIN,
    VIEWER,
    alert_states,
    control_put,
    gateway,
    login,
    prom_api,
    prom_query,
    prom_value,
    sample_for,
    wait_alert,
    wait_all_alerts_inactive,
    wait_until,
)

JOBS = ["prometheus", "postgres", "rabbitmq", "generator", "worker", "auth"]
CONCURRENCY = int(os.environ["WORKER_CONCURRENCY"])
DEFAULT_RATE = float(os.environ["GEN_RATE"])

POSTGRES_SERIES = [
    "pg_up",
    'pg_stat_database_xact_commit{datname="bank"}',
    'pg_stat_database_xact_rollback{datname="bank"}',
    'pg_stat_database_deadlocks{datname="bank"}',
    'pg_stat_database_tup_inserted{datname="bank"}',
    'pg_stat_database_tup_updated{datname="bank"}',
    'pg_stat_database_tup_fetched{datname="bank"}',
    'pg_stat_database_numbackends{datname="bank"}',
    'pg_stat_database_blks_hit{datname="bank"}',
    'pg_stat_database_blks_read{datname="bank"}',
    'pg_locks_count{datname="bank"}',
    'pg_stat_activity_count{datname="bank"}',
    'pg_database_size_bytes{datname="bank"}',
    "pg_settings_max_connections",
    'pg_stat_user_tables_n_live_tup{relname="transfers"}',
    '{__name__=~"pg_stat_statements_.+"}',
]
RABBITMQ_SERIES = [
    f'{name}{{queue="transfers.requested"}}'
    for name in (
        "rabbitmq_queue_messages_ready",
        "rabbitmq_queue_messages_unacked",
        "rabbitmq_queue_consumers",
    )
]
BANK_SERIES = [
    'bank_build_info{service="worker"}',
    'bank_build_info{service="generator"}',
    'bank_build_info{service="auth"}',
    "bank_transfers_processed_total",
    "bank_transfer_processing_seconds_bucket",
    "bank_transfer_e2e_seconds_bucket",
    "bank_transfer_retries_total",
    "bank_worker_messages_dead_lettered_total",
    "bank_worker_duplicates_total",
    "bank_worker_in_flight",
    "bank_generator_operations_total",
    "bank_generator_operation_duration_seconds_bucket",
    "bank_generator_target_rate",
    "bank_generator_running",
    "bank_scenario_active",
    "bank_db_lock_waiters",
    "bank_db_longest_transaction_seconds",
    "bank_db_accounts_total_balance",
    "bank_db_probe_up",
    "bank_auth_logins_total",
    "bank_auth_verify_total",
    "bank_http_requests_total",
    "bank_http_request_duration_seconds_bucket",
]

# §6.10: alert → severity
ALERTS = {
    "PostgresDown": "critical",
    "ServiceDown": "critical",
    "TransferFailureRatioHigh": "warning",
    "TransferProcessingSlow": "warning",
    "DeadlocksDetected": "warning",
    "LockWaiters": "warning",
    "QueueBacklog": "warning",
}


def _targets() -> list[dict]:
    return prom_api("targets")["activeTargets"]


def test_s05_ac2_all_targets_up_every_5_seconds():
    wait_until(
        lambda: all(t["health"] == "up" for t in _targets()),
        timeout=60,
        desc="every target to be up",
    )
    targets = _targets()
    assert set(JOBS) <= {t["labels"]["job"] for t in targets}
    assert {t["scrapeInterval"] for t in targets} == {"5s"}
    for job in JOBS:
        assert prom_value(f'up{{job="{job}"}}') == 1, job


@pytest.mark.parametrize("series", POSTGRES_SERIES + RABBITMQ_SERIES + BANK_SERIES)
def test_s05_ac3_series_exist(series):
    wait_until(lambda: prom_query(series), timeout=30, desc=f"series {series}")


def test_s05_ac4_values_under_normal_load():
    checks = {
        'sum(rate(pg_stat_database_xact_commit{datname="bank"}[1m]))': lambda v: v > 5,
        'sum(rate(pg_stat_database_tup_inserted{datname="bank"}[1m]))': lambda v: v > 0,
        'sum(rate(pg_stat_database_tup_updated{datname="bank"}[1m]))': lambda v: v > 0,
        'rabbitmq_queue_consumers{queue="transfers.requested"}': lambda v: v == CONCURRENCY,
        "bank_db_accounts_total_balance": lambda v: v > 0,
    }
    for expr, ok in checks.items():
        wait_until(
            lambda expr=expr, ok=ok: (value := prom_value(expr)) is not None and ok(value),
            timeout=90,
            interval=2,
            desc=expr,
        )


def test_s05_ac5_retention_is_15_days():
    assert prom_api("status/flags")["storage.tsdb.retention.time"] == "15d"


def test_s05_ac6_alerting_rules_are_loaded():
    rules = [
        rule
        for group in prom_api("rules", type="alert")["groups"]
        for rule in group["rules"]
        if group["name"] == "bank"
    ]
    assert {rule["name"]: rule["labels"]["severity"] for rule in rules} == ALERTS
    for rule in rules:
        assert rule["annotations"]["summary"].strip(), rule["name"]
        assert re.search(r"[а-яіїєґ]", rule["annotations"]["description"], re.I), rule["name"]


@pytest.mark.slow
def test_s05_ac6_no_alert_in_normal_mode():
    control_put(scenario="normal", rate=DEFAULT_RATE, running=True)
    wait_all_alerts_inactive()
    samples = sample_for(alert_states, duration_s=60, interval_s=5)
    not_inactive = [
        (name, state) for sample in samples for name, state in sample.items() if state != "inactive"
    ]
    assert not not_inactive


@pytest.mark.slow
def test_s05_ac7_failures_fire_and_clear_the_failure_ratio_alert(scenario):
    wait_alert("TransferFailureRatioHigh", "inactive", timeout=180)
    scenario("failures")
    wait_alert("TransferFailureRatioHigh", "firing", timeout=120)
    control_put(scenario="normal")
    wait_alert("TransferFailureRatioHigh", "inactive", timeout=150)


@pytest.mark.slow
def test_s05_ac8_deadlocks_fire_and_clear_the_deadlock_alert(scenario):
    wait_alert("DeadlocksDetected", "inactive", timeout=180)
    scenario("deadlocks")
    wait_alert("DeadlocksDetected", "firing", timeout=120)
    control_put(scenario="normal")
    wait_alert("DeadlocksDetected", "inactive", timeout=150)


def test_s05_ac9_prometheus_through_the_gateway():
    admin = login(*ADMIN)
    targets = admin.get("/prometheus/api/v1/targets")
    assert targets.status_code == 200 and targets.json()["status"] == "success"
    assert login(*VIEWER).get("/prometheus/api/v1/targets").status_code == 403

    anonymous = gateway()
    page = anonymous.get("/prometheus/")
    assert page.status_code == 302 and page.headers["Location"].startswith("/auth/login?rd=")
    api = anonymous.get("/prometheus/api/v1/query", params={"query": "up"})
    assert api.status_code == 401 and api.json() == {"detail": "Not authenticated"}

    ui = admin.get("/prometheus/query")
    assert ui.status_code == 200 and "<html" in ui.text.lower()
    assets = re.findall(r'<script[^>]+src="([^"]+)"', ui.text)
    assets += re.findall(r'<link[^>]+href="([^"]+)"', ui.text)
    assert assets
    resolved = [urljoin("/prometheus/query", asset) for asset in assets]
    outside = [path for path in resolved if not path.startswith("/prometheus/")]
    assert not outside, outside
    assert admin.get(resolved[0]).status_code == 200
