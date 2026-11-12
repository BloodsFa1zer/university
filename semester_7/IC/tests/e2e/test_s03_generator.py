"""S3: the generator, the scenarios and the control page (docs/00-common.md §6.6, §6.7)."""

import os
import re
from datetime import datetime, timedelta

import pytest
import requests

from bankmon_common import amqp

from .helpers import (
    CONTROL_STATE_URL,
    GENERATOR_URL,
    check_invariants,
    control_get,
    control_put,
    counter_deltas,
    db,
    measurement_window,
    metric_families,
    metric_value,
    queue_counts,
    rate_of,
    sample_for,
    wait_queue_drained,
    wait_until,
)

DEFAULT_RATE = float(os.environ["GEN_RATE"])
OPS = "bank_generator_operations_total"
OPERATIONS = ["transfer", "balance_check", "statement", "deposit"]

# §6.6, written out again on purpose: the test must not trust the code it checks.
SCENARIO_SETTINGS = {
    "normal": ("sorted", 0, 0),
    "slow_queries": ("sorted", 0, 800),
    "lock_contention": ("sorted", 0, 400),
    "deadlocks": ("naive", 150, 0),
    "failures": ("sorted", 0, 0),
}
TITLES = [
    "Звичайний режим",
    "Повільні запити",
    "Конкуренція за блокування",
    "Взаємні блокування",
    "Масові відмови",
]


def _scenario_row() -> tuple:
    with db() as conn:
        return conn.execute(
            "SELECT scenario, lock_order, lock_gap_ms, sleep_ms FROM scenario_state"
        ).fetchone()


def _switched_at(state: dict) -> datetime:
    # changed_at has whole seconds; transfers after this moment use the new scenario.
    return datetime.fromisoformat(state["changed_at"]) + timedelta(seconds=1.2)


@pytest.mark.slow
def test_s03_ac1_default_rate_and_operation_mix():
    labels = [{"operation": op, "result": "ok"} for op in OPERATIONS]
    deltas, elapsed = counter_deltas(GENERATOR_URL, OPS, labels, window_s=30)
    total = sum(deltas)
    assert 0.75 * DEFAULT_RATE <= total / elapsed <= 1.25 * DEFAULT_RATE, total / elapsed
    assert all(delta > 0 for delta in deltas), dict(zip(OPERATIONS, deltas, strict=True))
    assert 0.6 <= deltas[0] / total <= 0.8, deltas[0] / total


@pytest.mark.slow
def test_s03_ac2_rate_and_pause():
    try:
        control_put(rate=50)
        assert 37.5 <= rate_of(GENERATOR_URL, OPS, {"result": "ok"}, window_s=10) <= 62.5

        control_put(running=False)
        assert metric_value(GENERATOR_URL, "bank_generator_running") == 0
        (delta,), _elapsed = counter_deltas(GENERATOR_URL, OPS, [{}], window_s=5)
        assert delta <= 1

        control_put(running=True)
        assert metric_value(GENERATOR_URL, "bank_generator_running") == 1
        assert rate_of(GENERATOR_URL, OPS, {"result": "ok"}, window_s=3) > 0
    finally:
        control_put(scenario="normal", rate=DEFAULT_RATE, running=True)


def test_s03_ac3_every_scenario_reaches_the_database(scenario):
    for name, settings in SCENARIO_SETTINGS.items():
        state = scenario(name)
        assert state["scenario"] == name
        assert _scenario_row() == (name, *settings)
        active = {
            other: metric_value(GENERATOR_URL, "bank_scenario_active", {"scenario": other})
            for other in SCENARIO_SETTINGS
        }
        assert active == {other: float(other == name) for other in SCENARIO_SETTINGS}


@pytest.mark.parametrize(
    "body",
    [
        {"scenario": "nope"},
        {"rate": -1},
        {"rate": 501},
        {"rate": "fast"},
        {"running": "yes"},
        {"scenario": "failures", "ttl_s": 3},
        {"scenario": "normal", "ttl_s": 60},
        {"ttl_s": 60},
        {"color": "red"},
        ["normal"],
    ],
)
def test_s03_ac4_invalid_body_is_rejected(body):
    before = control_get()
    response = requests.put(CONTROL_STATE_URL, json=body, timeout=10)
    assert response.status_code == 422, response.text
    assert control_get() == before


def test_s03_ac5_scenario_returns_to_normal_by_itself(scenario):
    state = scenario("failures", ttl_s=5)
    assert state["expires_at"] is not None
    wait_until(lambda: control_get()["scenario"] == "normal", timeout=8, interval=0.2)
    assert control_get()["expires_at"] is None
    wait_until(lambda: _scenario_row() == ("normal", "sorted", 0, 0), timeout=2, interval=0.1)


@pytest.mark.slow
@pytest.mark.parametrize(("name", "pool"), [("lock_contention", 3), ("deadlocks", 4)])
def test_s03_ac6_scenario_uses_its_hot_accounts(scenario, name, pool):
    since = _switched_at(scenario(name))

    def transfers_since() -> list[tuple[int, int]]:
        with db() as conn:
            return conn.execute(
                "SELECT from_account, to_account FROM transfers WHERE requested_at > %s",
                (since,),
            ).fetchall()

    wait_until(lambda: len(transfers_since()) >= 15, timeout=90, desc="15 new transfers")
    outside = [pair for pair in transfers_since() if max(pair) > pool]
    assert not outside, outside[:5]


@pytest.mark.slow
def test_s03_ac7_failures_scenario_fails_about_half(scenario):
    since = _switched_at(scenario("failures"))
    measurement_window(20)
    until = since + timedelta(seconds=18)
    wait_queue_drained()
    with db() as conn:
        (failed, total) = conn.execute(
            """SELECT count(*) FILTER (WHERE status = 'failed'), count(*)
               FROM transfers WHERE requested_at BETWEEN %s AND %s""",
            (since, until),
        ).fetchone()
    assert total >= 100, total
    assert 0.35 <= failed / total <= 0.65, (failed, total)


def test_s03_ac8_probe_metrics(paused_generator):
    with db() as conn:
        (total,) = conn.execute("SELECT sum(balance) FROM accounts").fetchone()
    wait_until(
        lambda: (
            abs(metric_value(GENERATOR_URL, "bank_db_accounts_total_balance") - float(total))
            < 0.005
        ),
        timeout=10,
        desc="the probe to report SUM(balance)",
    )
    assert metric_value(GENERATOR_URL, "bank_db_probe_up") == 1
    assert metric_value(GENERATOR_URL, "bank_db_lock_waiters") == 0


def test_s03_ac9_control_page():
    response = requests.get(f"{GENERATOR_URL}/control/", timeout=5)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Керування навантаженням" in response.text
    missing = [title for title in TITLES if title not in response.text]
    assert not missing
    references = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', response.text)
    references += re.findall(r"fetch\(\s*['\"]([^'\"]*)", response.text)
    assert references, "the page should link to the dashboards"
    external = [ref for ref in references if re.match(r"^([a-z][a-z0-9+.-]*:)?//", ref, re.I)]
    assert not external, external


@pytest.mark.slow
def test_s03_ac10_steady_state_for_two_minutes():
    started_at = datetime.now().astimezone()
    ready = sample_for(lambda: queue_counts(amqp.TRANSFERS_QUEUE)[0], duration_s=120)
    assert max(ready) <= 50, max(ready)
    with db() as conn:
        (failed, total) = conn.execute(
            """SELECT count(*) FILTER (WHERE status = 'failed'), count(*)
               FROM transfers WHERE requested_at >= %s""",
            (started_at,),
        ).fetchone()
    assert total > 0
    assert failed / total < 0.05, (failed, total)
    assert check_invariants() == []


def test_s03_ac12_generator_state_is_default():
    state = control_get()
    assert (state["scenario"], state["rate"], state["running"], state["expires_at"]) == (
        "normal",
        DEFAULT_RATE,
        True,
        None,
    )
    assert _scenario_row() == ("normal", "sorted", 0, 0)


GENERATOR_METRICS = [
    "bank_build_info",
    "bank_generator_operations_total",
    "bank_generator_operation_duration_seconds",
    "bank_generator_target_rate",
    "bank_generator_running",
    "bank_scenario_active",
    "bank_db_lock_waiters",
    "bank_db_longest_transaction_seconds",
    "bank_db_accounts_total_balance",
    "bank_db_probe_up",
    "bank_http_requests_total",
    "bank_http_request_duration_seconds",
]


def test_s03_ac15_generator_metrics_are_exposed():
    control_get()
    families = metric_families(GENERATOR_URL)
    missing = [name for name in GENERATOR_METRICS if name.removesuffix("_total") not in families]
    assert not missing
    assert metric_value(GENERATOR_URL, "bank_build_info", {"service": "generator"}) == 1
    assert (
        metric_value(GENERATOR_URL, "bank_http_requests_total", {"route": "/control/api/state"}) > 0
    )
