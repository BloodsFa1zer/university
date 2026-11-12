"""Scenario settings the worker applies (the row of scenario_state, docs/00-common.md §6.6)."""

import time
from collections.abc import Callable
from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class ScenarioSettings:
    scenario: str
    lock_order: str  # "sorted" | "naive"
    lock_gap_ms: int
    sleep_ms: int


NORMAL = ScenarioSettings("normal", "sorted", 0, 0)


class SettingsCache:
    """Reads scenario_state at most once per second.

    The generator owns the row; re-reading it here means a scenario switch reaches
    the worker within a second, even for messages already waiting in the queue.
    Must be called outside the transfer transaction, on an autocommit connection.
    """

    MAX_AGE_S = 1.0

    def __init__(self, conn: psycopg.Connection, clock: Callable[[], float] = time.monotonic):
        self._conn = conn
        self._clock = clock
        self._value: ScenarioSettings | None = None
        self._read_at = 0.0

    def get(self) -> ScenarioSettings:
        now = self._clock()
        if self._value is None or now - self._read_at > self.MAX_AGE_S:
            row = self._conn.execute(
                "SELECT scenario, lock_order, lock_gap_ms, sleep_ms"
                " FROM scenario_state WHERE id = 1"
            ).fetchone()
            self._value = ScenarioSettings(*row) if row else NORMAL
            self._read_at = now
        return self._value
