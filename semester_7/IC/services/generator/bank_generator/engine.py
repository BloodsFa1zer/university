"""The load loop: one thread with its own PostgreSQL and RabbitMQ connections."""

import contextlib
import logging
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg
from pika.exceptions import AMQPError

from bank_generator import metrics, operations
from bank_generator.scenarios import NORMAL, SCENARIOS, Scenario
from bank_generator.state import ControlState
from bankmon_common import amqp, db
from bankmon_common.logging import log_event
from bankmon_common.tracing import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer("bank_generator")

OPERATION_WEIGHTS = {"transfer": 70, "balance_check": 20, "statement": 8, "deposit": 2}
MAX_LAG_S = 1.0
IDLE_STEP_S = 0.2


def next_run_at(previous: float, now: float, rate: float, max_lag: float = MAX_LAG_S) -> float:
    """When the next operation is due, given when the previous one was due.

    Operations are spaced 1/rate apart. If the loop fell behind by more than
    ``max_lag`` (a slow query, a reconnect), the schedule restarts from ``now``
    instead of firing all the missed operations in one burst.
    """
    due = previous + 1.0 / rate
    return now if now - due > max_lag else due


def store_scenario(conn: psycopg.Connection, scenario: Scenario) -> None:
    """Write what the worker must apply into scenario_state (autocommit connection)."""
    conn.execute(
        """UPDATE scenario_state
           SET scenario = %s, lock_order = %s, lock_gap_ms = %s, sleep_ms = %s,
               updated_at = now()
           WHERE id = 1""",
        (scenario.name, scenario.lock_order, scenario.lock_gap_ms, scenario.sleep_ms),
    )


class Engine(threading.Thread):
    def __init__(
        self,
        control: ControlState,
        database_url: str,
        amqp_url: str,
        stopping: threading.Event,
        on_expired: Callable[[dict], None],
    ) -> None:
        super().__init__(name="engine", daemon=True)
        self._control = control
        self._database_url = database_url
        self._amqp_url = amqp_url
        self._stopping = stopping
        self._on_expired = on_expired
        self._rng = random.Random()
        self._db: psycopg.Connection | None = None
        self._amqp = None
        self._channel = None
        self._accounts: list[int] = []

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._connect()
                self._loop()
            except psycopg.OperationalError as exc:
                self._connection_lost("postgres", exc)
            except AMQPError as exc:
                self._connection_lost("rabbitmq", exc)
            except Exception:
                logger.exception("Load loop failed unexpectedly, restarting it")
            finally:
                self._close()
            self._stopping.wait(1.0)

    def _connect(self) -> None:
        self._db = db.connect(
            self._database_url, application_name="bank-generator", autocommit=True
        )
        self._accounts = [row[0] for row in self._db.execute("SELECT id FROM accounts ORDER BY id")]
        # After a database restart the row may be stale: bring it in line with our state.
        store_scenario(self._db, SCENARIOS[self._control.scenario])
        self._amqp = amqp.connect(self._amqp_url)
        self._channel = self._amqp.channel()
        amqp.declare_topology(self._channel)
        self._channel.confirm_delivery()

    def _close(self) -> None:
        if self._amqp is not None and self._amqp.is_open:
            with contextlib.suppress(AMQPError):
                self._amqp.close()
        if self._db is not None:
            self._db.close()
        self._amqp = self._channel = self._db = None

    def _connection_lost(self, target: str, exc: BaseException) -> None:
        log_event(
            logger,
            "warning",
            "connection_lost",
            f"Lost connection to {target}, reconnecting",
            target=target,
            error=str(exc).strip() or repr(exc),
        )

    def _loop(self) -> None:
        due = time.monotonic()
        while not self._stopping.is_set():
            if self._control.expire(datetime.now(UTC)):
                store_scenario(self._db, NORMAL)
                self._on_expired(self._control.snapshot())

            scenario_name, rate, running = self._control.current()
            if not running or rate <= 0:
                self._amqp.sleep(IDLE_STEP_S)  # also keeps the AMQP heartbeats going
                due = time.monotonic()
                continue
            now = time.monotonic()
            if now < due:
                self._amqp.sleep(min(due - now, IDLE_STEP_S))
                continue
            self._run_one(SCENARIOS[scenario_name])
            due = next_run_at(due, time.monotonic(), rate)

    def _run_one(self, scenario: Scenario) -> None:
        operation = self._rng.choices(
            list(OPERATION_WEIGHTS), weights=list(OPERATION_WEIGHTS.values())
        )[0]
        started = time.perf_counter()
        try:
            # One span per client operation; a transfer's span is the root of a trace that
            # continues through RabbitMQ into the worker (§6.12).
            with tracer.start_as_current_span(f"generator.{operation}") as span:
                span.set_attribute("bank.scenario", scenario.name)
                if operation == "transfer":
                    msg = operations.transfer(self._channel, self._accounts, scenario, self._rng)
                    span.set_attribute("bank.transfer_id", str(msg.transfer_id))
                    span.set_attribute("bank.from_account", msg.from_account)
                    span.set_attribute("bank.to_account", msg.to_account)
                    span.set_attribute("bank.amount", f"{msg.amount:.2f}")
                elif operation == "balance_check":
                    operations.balance_check(self._db, self._accounts, self._rng)
                elif operation == "statement":
                    operations.statement(self._db, self._accounts, self._rng)
                else:
                    operations.deposit(self._db)
        except (psycopg.Error, AMQPError) as exc:
            metrics.OPERATIONS.labels(operation=operation, result="error").inc()
            log_event(
                logger,
                "error",
                "operation_failed",
                f"Operation {operation} failed",
                operation=operation,
                error=str(exc).strip() or repr(exc),
            )
            if self._db.closed or self._db.broken or not self._channel.is_open:
                raise  # the connection itself is gone: reconnect
            return
        metrics.OPERATIONS.labels(operation=operation, result="ok").inc()
        metrics.OPERATION_SECONDS.labels(operation=operation).observe(time.perf_counter() - started)
