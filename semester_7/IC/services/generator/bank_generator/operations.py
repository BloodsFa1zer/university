"""The four client operations (docs/10-app.md, stage S3, requirement 3)."""

import random
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pika
import psycopg
from pika.adapters.blocking_connection import BlockingChannel

from bank_generator.scenarios import Scenario
from bankmon_common import amqp
from bankmon_common.messages import TransferRequested

BIG_AMOUNT = Decimal("1000000.00")
DEPOSIT_AMOUNT = Decimal("2000.00")


def transfer(
    channel: BlockingChannel, accounts: list[int], scenario: Scenario, rng: random.Random
) -> TransferRequested:
    """Ask for a transfer: publish TransferRequested and wait for the broker's confirm."""
    pool = accounts[: scenario.hot_accounts] if scenario.hot_accounts else accounts
    from_account, to_account = rng.sample(pool, 2)
    if rng.random() < scenario.big_amount_share:
        amount = BIG_AMOUNT
    else:
        amount = Decimal(rng.randint(100, 50_000)) / 100  # 1.00 … 500.00
    msg = TransferRequested(
        transfer_id=uuid.uuid4(),
        from_account=from_account,
        to_account=to_account,
        amount=amount,
        requested_at=datetime.now(UTC),
        scenario=scenario.name,
    )
    channel.basic_publish(
        exchange=amqp.TRANSFERS_EXCHANGE,
        routing_key=amqp.TRANSFER_ROUTING_KEY,
        body=msg.encode(),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
            message_id=str(msg.transfer_id),
        ),
        mandatory=True,
    )
    return msg


def balance_check(conn: psycopg.Connection, accounts: list[int], rng: random.Random) -> None:
    conn.execute("SELECT balance FROM accounts WHERE id = %s", (rng.choice(accounts),)).fetchone()


def statement(conn: psycopg.Connection, accounts: list[int], rng: random.Random) -> None:
    """The last 20 ledger entries of an account, with the status of their transfers."""
    conn.execute(
        """SELECT e.id, e.kind, e.delta, e.created_at, t.status
           FROM ledger_entries e
           LEFT JOIN transfers t ON t.id = e.transfer_id
           WHERE e.account_id = %s
           ORDER BY e.created_at DESC
           LIMIT 20""",
        (rng.choice(accounts),),
    ).fetchall()


def deposit(conn: psycopg.Connection) -> None:
    """Top up the poorest account by 2000.00, so balances do not drain over time.

    SKIP LOCKED: an account locked by a running transfer is skipped instead of waited for.
    """
    with conn.transaction():
        row = conn.execute(
            """SELECT id FROM accounts ORDER BY balance, id LIMIT 1
               FOR NO KEY UPDATE SKIP LOCKED"""
        ).fetchone()
        if row is None:
            return
        (account_id,) = row
        conn.execute(
            "UPDATE accounts SET balance = balance + %s, updated_at = now() WHERE id = %s",
            (DEPOSIT_AMOUNT, account_id),
        )
        conn.execute(
            "INSERT INTO ledger_entries (account_id, kind, delta) VALUES (%s, 'deposit', %s)",
            (account_id, DEPOSIT_AMOUNT),
        )
