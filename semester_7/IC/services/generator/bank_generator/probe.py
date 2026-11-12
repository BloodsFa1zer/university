"""SQL probe: every 5 s reads the state of the database as the monitoring role."""

import logging
import threading

import psycopg

from bank_generator import metrics
from bankmon_common import db
from bankmon_common.logging import log_event

logger = logging.getLogger(__name__)

INTERVAL_S = 5.0

LOCK_WAITERS_SQL = """
    SELECT count(*) FROM pg_stat_activity
    WHERE datname = current_database() AND wait_event_type = 'Lock'"""

LONGEST_TRANSACTION_SQL = """
    SELECT COALESCE(EXTRACT(EPOCH FROM max(clock_timestamp() - xact_start)), 0)
    FROM pg_stat_activity
    WHERE datname = current_database() AND pid <> pg_backend_pid() AND xact_start IS NOT NULL"""

TOTAL_BALANCE_SQL = "SELECT COALESCE(SUM(balance), 0) FROM accounts"


class Probe(threading.Thread):
    def __init__(self, monitor_url: str, stopping: threading.Event) -> None:
        super().__init__(name="probe", daemon=True)
        self._monitor_url = monitor_url
        self._stopping = stopping
        self._conn: psycopg.Connection | None = None

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                if self._conn is None:
                    self._conn = db.connect(
                        self._monitor_url, application_name="bank-probe", autocommit=True
                    )
                self._collect()
                metrics.PROBE_UP.set(1)
            except psycopg.Error as exc:
                metrics.PROBE_UP.set(0)
                log_event(
                    logger,
                    "warning",
                    "probe_failed",
                    "Database probe failed",
                    error=str(exc).strip() or repr(exc),
                )
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
            self._stopping.wait(INTERVAL_S)

    def _collect(self) -> None:
        (waiters,) = self._conn.execute(LOCK_WAITERS_SQL).fetchone()
        (longest,) = self._conn.execute(LONGEST_TRANSACTION_SQL).fetchone()
        (total,) = self._conn.execute(TOTAL_BALANCE_SQL).fetchone()
        metrics.LOCK_WAITERS.set(waiters)
        metrics.LONGEST_TRANSACTION.set(float(longest))
        metrics.TOTAL_BALANCE.set(float(total))
