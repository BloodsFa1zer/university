"""One transfer = one database transaction (docs/10-app.md, stage S2, requirement 6).

The balance is never checked in Python: the CHECK (balance >= 0) constraint of the
database rejects an overdraft. That is deliberate — the refusal then shows up in
the statistics and logs of PostgreSQL, which is what this system monitors.
"""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from opentelemetry import trace
from psycopg import errors

from bank_worker import metrics
from bank_worker.settings import ScenarioSettings
from bankmon_common.logging import log_event
from bankmon_common.messages import TransferRequested

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BALANCE_CHECK = "accounts_balance_check"
TRANSFERS_PKEY = "transfers_pkey"


class UnknownAccount(Exception):
    """The message refers to an account that does not exist."""


@dataclass(frozen=True)
class Outcome:
    status: str  # "completed" | "failed" | "duplicate"
    reason: str | None  # None | "insufficient_funds" | "deadlock"
    attempts: int


def order_accounts(from_account: int, to_account: int, lock_order: str) -> tuple[int, int]:
    """Which account to lock first.

    "sorted" always locks the smaller id first, so two transfers can never wait for
    each other in a circle. "naive" locks the sender first — opposite transfers then
    deadlock, which is what the `deadlocks` scenario demonstrates.
    """
    if lock_order == "sorted":
        return min(from_account, to_account), max(from_account, to_account)
    if lock_order == "naive":
        return from_account, to_account
    raise ValueError(f"unknown lock_order {lock_order!r}")


def process_transfer(
    conn: psycopg.Connection,
    msg: TransferRequested,
    get_settings: Callable[[], ScenarioSettings],
) -> Outcome:
    """Apply a transfer. ``conn`` must be in autocommit mode: each attempt opens its own
    transaction with ``conn.transaction()``."""
    if _already_recorded(conn, msg):
        return Outcome("duplicate", None, 0)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        settings = get_settings()
        trace.get_current_span().set_attribute("bank.lock_order", settings.lock_order)
        try:
            with conn.transaction():
                _apply(conn, msg, settings, attempt)
            return Outcome("completed", None, attempt)
        except errors.CheckViolation as exc:
            if exc.diag.constraint_name != BALANCE_CHECK:
                raise
            metrics.DB_ERRORS.labels(sqlstate=exc.sqlstate).inc()
            return _record_failure(conn, msg, "insufficient_funds", attempt)
        except errors.UniqueViolation as exc:
            # Another consumer recorded the same transfer a moment earlier.
            if exc.diag.constraint_name != TRANSFERS_PKEY:
                raise
            return Outcome("duplicate", None, attempt)
        except errors.DeadlockDetected as exc:
            metrics.DB_ERRORS.labels(sqlstate=exc.sqlstate).inc()
            if attempt == MAX_ATTEMPTS:
                return _record_failure(conn, msg, "deadlock", attempt)
            metrics.RETRIES.labels(reason="deadlock").inc()
            trace.get_current_span().add_event("deadlock_retry", {"attempt": attempt})
            log_event(
                logger,
                "warning",
                "deadlock_retry",
                f"Deadlock on attempt {attempt}, retrying",
                transfer_id=str(msg.transfer_id),
                attempt=attempt,
            )
            time.sleep(random.uniform(0.05, 0.15))
    raise AssertionError("unreachable")  # the loop always returns


def _already_recorded(conn: psycopg.Connection, msg: TransferRequested) -> bool:
    row = conn.execute("SELECT 1 FROM transfers WHERE id = %s", (msg.transfer_id,)).fetchone()
    return row is not None


def _lock_account(conn: psycopg.Connection, account_id: int) -> None:
    # FOR NO KEY UPDATE is the row lock an UPDATE of a non-key column takes anyway.
    # Unlike FOR UPDATE it does not block the KEY SHARE locks of foreign-key checks,
    # so recording a failed transfer can never get stuck behind running transfers,
    # while two transfers over the same accounts still lock each other out.
    row = conn.execute(
        "SELECT id FROM accounts WHERE id = %s FOR NO KEY UPDATE", (account_id,)
    ).fetchone()
    if row is None:
        raise UnknownAccount(f"account {account_id} does not exist")


def _apply(
    conn: psycopg.Connection, msg: TransferRequested, settings: ScenarioSettings, attempt: int
) -> None:
    first, second = order_accounts(msg.from_account, msg.to_account, settings.lock_order)
    _lock_account(conn, first)
    if settings.lock_gap_ms > 0:
        conn.execute("SELECT pg_sleep(%s)", (settings.lock_gap_ms / 1000,))
    _lock_account(conn, second)
    if settings.sleep_ms > 0:
        conn.execute("SELECT pg_sleep(%s)", (settings.sleep_ms / 1000,))

    # processed_at is the moment the work is done, not the start of the transaction
    # (that is what now() would give), so the scenario pauses are included in it.
    conn.execute(
        """INSERT INTO transfers
             (id, from_account, to_account, amount, status, attempts, requested_at, processed_at)
           VALUES (%s, %s, %s, %s, 'completed', %s, %s, clock_timestamp())""",
        (msg.transfer_id, msg.from_account, msg.to_account, msg.amount, attempt, msg.requested_at),
    )
    conn.execute(
        "UPDATE accounts SET balance = balance - %s, updated_at = now() WHERE id = %s",
        (msg.amount, msg.from_account),
    )
    conn.execute(
        "UPDATE accounts SET balance = balance + %s, updated_at = now() WHERE id = %s",
        (msg.amount, msg.to_account),
    )
    conn.execute(
        """INSERT INTO ledger_entries (account_id, transfer_id, kind, delta)
           VALUES (%s, %s, 'transfer_out', %s)""",
        (msg.from_account, msg.transfer_id, -msg.amount),
    )
    conn.execute(
        """INSERT INTO ledger_entries (account_id, transfer_id, kind, delta)
           VALUES (%s, %s, 'transfer_in', %s)""",
        (msg.to_account, msg.transfer_id, msg.amount),
    )


def _record_failure(
    conn: psycopg.Connection, msg: TransferRequested, reason: str, attempts: int
) -> Outcome:
    """Record a failed transfer in its own short transaction (the failed one was rolled back)."""
    with conn.transaction():
        row = conn.execute(
            """INSERT INTO transfers
                 (id, from_account, to_account, amount, status, fail_reason, attempts,
                  requested_at)
               VALUES (%s, %s, %s, %s, 'failed', %s, %s, %s)
               ON CONFLICT (id) DO NOTHING
               RETURNING id""",
            (
                msg.transfer_id,
                msg.from_account,
                msg.to_account,
                msg.amount,
                reason,
                attempts,
                msg.requested_at,
            ),
        ).fetchone()
    if row is None:
        return Outcome("duplicate", None, attempts)
    return Outcome("failed", reason, attempts)
