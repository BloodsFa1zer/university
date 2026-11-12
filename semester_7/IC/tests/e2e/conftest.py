"""Shared fixtures for e2e tests.

The tests run inside the `tests` container on the compose network and talk to
services by their names. Each stage adds the readiness checks it needs here.
"""

import os
from collections.abc import Callable, Iterator

import pytest
import requests

from bankmon_common import amqp

from .helpers import (
    AUTH_URL,
    GATEWAY_URL,
    GENERATOR_URL,
    LOKI_URL,
    PROM_URL,
    TEMPO_URL,
    WORKER_URL,
    control_get,
    control_put,
    db,
    grafana_api,
    loki_query,
    metric_value,
    queue_counts,
    wait_queue_drained,
    wait_until,
)

DEFAULT_STATE = {"scenario": "normal", "rate": float(os.environ["GEN_RATE"]), "running": True}


def _postgres_accepts_app() -> bool:
    with db("app") as conn:
        return conn.execute("SELECT 1").fetchone() == (1,)


def _worker_consuming() -> bool:
    requests.get(f"{WORKER_URL}/metrics", timeout=3).raise_for_status()
    _ready, consumers = queue_counts(amqp.TRANSFERS_QUEUE)
    return consumers == int(os.environ["WORKER_CONCURRENCY"])


def _generator_healthy() -> bool:
    requests.get(f"{GENERATOR_URL}/healthz", timeout=3).raise_for_status()
    return True


def _gateway_and_auth_healthy() -> bool:
    requests.get(f"{AUTH_URL}/healthz", timeout=3).raise_for_status()
    requests.get(f"{GATEWAY_URL}/healthz", timeout=3).raise_for_status()
    return True


def _prometheus_ready() -> bool:
    requests.get(f"{PROM_URL}/-/ready", timeout=3).raise_for_status()
    return True


def _grafana_ready() -> bool:
    response = grafana_api("health")
    return response.status_code == 200 and response.json().get("database") == "ok"


def _loki_ready() -> bool:
    requests.get(f"{LOKI_URL}/ready", timeout=3).raise_for_status()
    return True


def _worker_logs_in_loki() -> bool:
    # Alloy finds (re)created containers within its discovery interval: wait for it.
    return bool(loki_query('{service="worker"}', since_s=60, limit=1))


def _tempo_ready() -> bool:
    requests.get(f"{TEMPO_URL}/ready", timeout=3).raise_for_status()
    return True


def reset_generator(only_if_needed: bool = False) -> None:
    """Back to the normal scenario, default rate, running.

    With only_if_needed the state is left alone when it already is the default, so a
    freshly restarted generator can be checked as it came up (S3-AC12).
    """
    state = control_get()
    is_default = all(state[key] == value for key, value in DEFAULT_STATE.items())
    if not (only_if_needed and is_default and state["expires_at"] is None):
        control_put(**DEFAULT_STATE)


@pytest.fixture(scope="session", autouse=True)
def stack_ready() -> Iterator[None]:
    """Wait until the stack can serve the tests; leave it in the normal scenario."""
    wait_until(_postgres_accepts_app, timeout=180, interval=1, desc="PostgreSQL to accept bank_app")
    wait_until(_worker_consuming, timeout=180, interval=1, desc="all worker consumers to attach")
    wait_until(_generator_healthy, timeout=180, interval=1, desc="the generator to answer")
    wait_until(_gateway_and_auth_healthy, timeout=180, interval=1, desc="auth and the gateway")
    wait_until(_prometheus_ready, timeout=180, interval=1, desc="Prometheus to be ready")
    wait_until(_grafana_ready, timeout=180, interval=1, desc="Grafana to be ready")
    wait_until(_loki_ready, timeout=180, interval=2, desc="Loki to be ready")
    wait_until(_tempo_ready, timeout=180, interval=2, desc="Tempo to be ready")
    wait_until(_worker_logs_in_loki, timeout=180, interval=2, desc="worker logs to reach Loki")
    reset_generator(only_if_needed=True)
    yield
    reset_generator()


@pytest.fixture
def scenario() -> Iterator[Callable[..., dict]]:
    """Switch scenarios during a test: ``scenario("deadlocks")``.

    Afterwards: back to normal, and wait until the backlog the scenario built is processed.
    """

    def enable(name: str, **fields) -> dict:
        return control_put(scenario=name, **fields)

    yield enable
    control_put(**DEFAULT_STATE)
    wait_queue_drained(timeout=300)


@pytest.fixture
def paused_generator() -> Iterator[None]:
    """No background load: generator paused, queue empty, worker idle."""
    control_put(running=False)
    wait_queue_drained()
    wait_until(
        lambda: metric_value(WORKER_URL, "bank_worker_in_flight") == 0,
        timeout=30,
        desc="the worker to finish its messages",
    )
    yield
    control_put(running=True)
