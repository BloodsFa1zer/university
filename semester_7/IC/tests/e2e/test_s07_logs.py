"""S7: Loki, Alloy and the logs (docs/00-common.md §6.11, §11)."""

import re
import time
import uuid
from decimal import Decimal

import pytest
import requests

from .helpers import (
    GATEWAY_URL,
    LOKI_URL,
    dashboard_files,
    db,
    gateway,
    grafana_api,
    loki_labels,
    loki_query,
    panel_exprs,
    prom_value,
    publish_transfer,
    wait_logs,
    wait_until,
)

LEVELS = {"debug", "info", "warning", "error"}
LOKI_OWN_LABELS = {"__name__", "__stream_shard__", "service_name", "detected_level"}
LOGS_PANELS = {
    "Обсяг логів за сервісами",
    "Помилки й попередження",
    "Логи сервісів",
    "PostgreSQL: повільні запити, блокування, помилки",
    "Невдалі входи",
    "Запити через gateway",
}


def test_s07_ac1_loki_and_alloy_are_ready():
    assert requests.get(f"{LOKI_URL}/ready", timeout=5).status_code == 200
    assert requests.get("http://alloy:12345/-/ready", timeout=5).status_code == 200


def _touch_quiet_services() -> None:
    """PostgreSQL and RabbitMQ only log on events: make one of each happen now."""
    with db() as conn, pytest.raises(Exception):  # noqa: B017 - any error will do
        conn.execute("SELECT 1 / 0")  # logged by PostgreSQL as ERROR
    requests.get(f"{GATEWAY_URL}/healthz", timeout=5)


def test_s07_ac2_every_service_has_logs():
    _touch_quiet_services()
    for service in ("postgres", "worker", "generator", "auth", "gateway", "grafana"):
        wait_logs(f'{{service="{service}"}}', since_s=300, timeout=30)
    # RabbitMQ and Prometheus log only on events (connections, compactions, start-up):
    # their lines are checked over the last hours, since the stack started.
    for service in ("rabbitmq", "prometheus"):
        wait_logs(f'{{service="{service}"}}', since_s=6 * 3600, timeout=30)


def test_s07_ac3_only_the_contract_labels():
    labels = loki_labels()
    assert {"service", "container", "level"} <= labels
    assert labels - {"service", "container", "level"} <= LOKI_OWN_LABELS, labels
    values = set(
        requests.get(f"{LOKI_URL}/loki/api/v1/label/level/values", timeout=5).json()["data"]
    )
    assert values <= LEVELS, values
    for service in ("worker", "generator", "auth"):
        rows = wait_logs(f'{{service="{service}"}}', since_s=300, timeout=30)
        assert all("level" in row["labels"] for row in rows), service
    postgres = wait_logs('{service="postgres"}', since_s=6 * 3600, timeout=30)
    assert not any("level" in row["labels"] for row in postgres)


def test_s07_ac4_worker_events_are_searchable():
    rows = wait_logs(
        '{service="worker"} | json | event="transfer_completed"', since_s=60, timeout=30
    )
    for field in ("transfer_id", "amount", "duration_ms"):
        assert field in rows[0]["json"], field


def test_s07_ac5_a_new_transfer_reaches_loki_quickly():
    transfer_id = publish_transfer(192, 191, Decimal("1.00"))
    rows = wait_logs(
        f'{{service="worker"}} |= "{transfer_id}" | json | event="transfer_completed"',
        since_s=120,
        timeout=15,
    )
    assert rows[0]["json"]["transfer_id"] == transfer_id


@pytest.mark.slow
def _since(started: float) -> float:
    """Seconds since ``started``: only lines written after the scenario switch count."""
    return time.time() - started + 1


def test_s07_ac6_slow_queries_show_up_in_the_postgres_log(scenario):
    started = time.time()
    scenario("slow_queries")
    wait_until(
        lambda: loki_query(
            '{service="postgres"} |= "duration:" |= "pg_sleep"', since_s=_since(started)
        ),
        timeout=60,
        desc="a slow pg_sleep statement in the PostgreSQL log",
    )


@pytest.mark.slow
def test_s07_ac7_deadlocks_show_up_in_both_logs(scenario):
    started = time.time()
    scenario("deadlocks")
    for logql in (
        '{service="postgres"} |= "deadlock detected"',
        '{service="worker"} | json | event="deadlock_retry"',
    ):
        wait_until(
            lambda logql=logql: loki_query(logql, since_s=_since(started)),
            timeout=120,
            desc=logql,
        )


def test_s07_ac8_failed_login_is_logged_without_the_password():
    username = f"e2e-{uuid.uuid4().hex[:8]}"
    password = f"pw-marker-{uuid.uuid4().hex}"
    response = gateway().post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 401
    rows = wait_logs(
        f'{{service="auth"}} | json | event="login_failed" | username="{username}"',
        since_s=120,
        timeout=30,
    )
    assert rows
    assert loki_query(f'{{service=~".+"}} |= "{password}"', since_s=300) == []


def test_s07_ac9_gateway_access_log_is_json():
    gateway().get("/healthz")
    gateway().get("/auth/login")
    rows = wait_logs('{service="gateway"} | json | status="200"', since_s=300, timeout=30)
    for field in ("method", "uri", "request_time"):
        assert field in rows[0]["json"], field


def test_s07_ac10_loki_data_source_and_logs_dashboard():
    health = grafana_api("datasources/uid/loki/health")
    assert health.status_code == 200 and health.json()["status"] == "OK", health.text
    found = grafana_api("search", params={"tag": "bankmonitor", "type": "dash-db"}).json()
    logs = [d for d in found if d["uid"] == "bank-logs"]
    assert logs and logs[0]["folderTitle"] == "BankMonitor" and logs[0]["title"] == "Логи"

    dashboard = dashboard_files()["bank-logs"]
    assert dashboard["id"] is None and dashboard["refresh"] == "5s"
    assert "bankmonitor" in dashboard["tags"] and "${DS_" not in repr(dashboard)
    assert {panel["title"] for panel in dashboard["panels"]} == LOGS_PANELS
    for panel in dashboard["panels"]:
        assert re.search(r"[а-яіїєґ]", panel["title"], re.I)
        assert panel["datasource"]["uid"] == "loki"
    for title, source, expr in panel_exprs(dashboard):
        assert source == "loki", title
        loki_query(expr, since_s=300)  # raises if Loki rejects the query


def test_s07_ac11_retention_is_seven_days():
    config = requests.get(f"{LOKI_URL}/config", timeout=5).text
    assert re.search(r"retention_period:\s*(168h|1w|7d)", config), "retention_period"
    assert re.search(r"retention_enabled:\s*true", config), "retention_enabled"


def test_s07_ac12_loki_and_alloy_are_scraped():
    for job in ("loki", "alloy"):
        wait_until(lambda job=job: prom_value(f'up{{job="{job}"}}') == 1, timeout=60, desc=job)
