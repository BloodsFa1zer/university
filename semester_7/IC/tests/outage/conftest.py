"""Fixtures for the outage tests.

These tests run in several phases (separate pytest runs) while a service is
stopped and started in between, so they are not part of `make e2e`. The phases
share data through the environment: S02_TRANSFER_ID must be the same uuid in both
phases of test_s02_redelivery.py.
"""

import os
from pathlib import Path

import pytest

from e2e.helpers import db, wait_until


@pytest.fixture(scope="session", autouse=True)
def database_ready() -> None:
    def ready() -> bool:
        with db("app") as conn:
            return conn.execute("SELECT 1").fetchone() == (1,)

    wait_until(ready, timeout=120, interval=1, desc="PostgreSQL to accept bank_app")


@pytest.fixture(scope="session")
def redelivery_transfer_id() -> str:
    value = os.environ.get("S02_TRANSFER_ID")
    if not value:
        pytest.fail("set S02_TRANSFER_ID to the same uuid for both phases (docs/10-app.md, S2)")
    return value


@pytest.fixture
def state_file() -> Path:
    """Numbers shared by the three phases of test_s09_worker_outage.py (tests_state volume)."""
    return Path("/state") / "s09_worker_outage.json"
