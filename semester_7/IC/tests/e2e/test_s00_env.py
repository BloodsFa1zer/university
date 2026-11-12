"""S0: the test container gets the environment from .env; wait_until works."""

import os
from pathlib import Path

import pytest

from .helpers import wait_until

REPO = Path(__file__).resolve().parents[2]


def _read_env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


def test_s00_ac6_env():
    expected_keys = _read_env_file(REPO / ".env.example")
    actual = _read_env_file(REPO / ".env")
    assert len(expected_keys) == 20
    missing = [key for key in expected_keys if key not in os.environ]
    assert not missing, f"not passed into the container: {missing}"
    wrong = [key for key in expected_keys if os.environ[key] != actual.get(key)]
    assert not wrong, f"container values differ from .env: {wrong}"


def test_s00_wait_until_returns_first_truthy_value():
    calls = iter([0, None, "", "ready"])
    assert wait_until(lambda: next(calls), timeout=5, interval=0.01) == "ready"


def test_s00_wait_until_treats_exceptions_as_not_ready():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("not up yet")
        return True

    assert wait_until(flaky, timeout=5, interval=0.01) is True


def test_s00_wait_until_times_out_with_description():
    def always_fails():
        raise ConnectionError("refused")

    with pytest.raises(AssertionError, match=r"waiting for database.*refused"):
        wait_until(always_fails, timeout=0.05, interval=0.01, desc="database")
