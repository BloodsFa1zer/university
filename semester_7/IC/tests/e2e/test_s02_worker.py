"""S2: RabbitMQ topology and the worker (docs/00-common.md §6.5, §6.9).

Tests use accounts 191…200 and assert through the rows of their own transfers, not
through balances: from S3 on the generator changes balances in the background.
For the same reason counters that the generator can also move are checked with >=.
"""

import json
import os
import random
import uuid
from decimal import Decimal

from bankmon_common import amqp

from .helpers import (
    WORKER_URL,
    amqp_channel,
    check_invariants,
    db,
    drain_queue,
    latency_s,
    ledger_entries,
    make_transfer,
    metric_families,
    metric_value,
    publish_raw,
    publish_transfer,
    queue_counts,
    queue_info,
    rabbitmq_api,
    transfer_row,
    wait_queue_drained,
    wait_transfer,
    wait_until,
    worker_settings,
)

CONCURRENCY = int(os.environ["WORKER_CONCURRENCY"])
PROCESSED = "bank_transfers_processed_total"


def test_s02_ac1_topology_and_consumers():
    queue = queue_info(amqp.TRANSFERS_QUEUE)
    assert queue["durable"] is True
    assert queue["arguments"].get("x-dead-letter-exchange") == amqp.DEAD_LETTER_EXCHANGE
    assert queue_info(amqp.DEAD_LETTER_QUEUE)["durable"] is True
    assert rabbitmq_api(f"exchanges/%2F/{amqp.TRANSFERS_EXCHANGE}")["type"] == "direct"
    assert rabbitmq_api(f"exchanges/%2F/{amqp.DEAD_LETTER_EXCHANGE}")["type"] == "fanout"
    assert queue_counts(amqp.TRANSFERS_QUEUE)[1] == CONCURRENCY


def test_s02_ac2_valid_transfer_is_applied():
    transfer_id = publish_transfer(200, 199, Decimal("25.50"))
    row = wait_transfer(transfer_id, timeout=5)
    assert (row["status"], row["fail_reason"], row["attempts"]) == ("completed", None, 1)
    entries = [(e["kind"], e["account_id"], e["delta"]) for e in ledger_entries(transfer_id)]
    assert entries == [
        ("transfer_in", 199, Decimal("25.50")),
        ("transfer_out", 200, Decimal("-25.50")),
    ]


def test_s02_ac3_insufficient_funds_is_recorded_as_failed():
    labels = {"status": "failed", "reason": "insufficient_funds"}
    before = metric_value(WORKER_URL, PROCESSED, labels)
    transfer_id = publish_transfer(198, 197, Decimal("1000000.00"))
    row = wait_transfer(transfer_id)
    assert (row["status"], row["fail_reason"]) == ("failed", "insufficient_funds")
    assert ledger_entries(transfer_id) == []
    wait_until(
        lambda: metric_value(WORKER_URL, PROCESSED, labels) >= before + 1,
        timeout=5,
        desc="failed/insufficient_funds counter to grow",
    )


def test_s02_ac4_duplicate_message_is_applied_once():
    before = metric_value(WORKER_URL, "bank_worker_duplicates_total")
    msg = make_transfer(196, 195, Decimal("3.00"))
    with amqp_channel() as channel:
        publish_raw(msg.encode(), channel=channel)
        publish_raw(msg.encode(), channel=channel)
    wait_transfer(str(msg.transfer_id))
    wait_until(
        lambda: metric_value(WORKER_URL, "bank_worker_duplicates_total") == before + 1,
        timeout=10,
        desc="duplicate counter to grow by 1",
    )
    with db() as conn:
        (rows,) = conn.execute(
            "SELECT count(*) FROM transfers WHERE id = %s", (msg.transfer_id,)
        ).fetchone()
    assert rows == 1
    assert len(ledger_entries(str(msg.transfer_id))) == 2


def test_s02_ac5_invalid_messages_go_to_the_dead_letter_queue():
    before = metric_value(WORKER_URL, "bank_worker_messages_dead_lettered_total")
    template = json.loads(make_transfer(194, 193, Decimal("2.00")).encode())

    def body(**changes) -> bytes:
        return json.dumps({**template, "transfer_id": str(uuid.uuid4()), **changes}).encode()

    unknown_account = body(to_account=999999)
    bodies = [
        f"not json {uuid.uuid4().hex}".encode(),
        body(to_account=194),  # the same account on both sides
        body(amount="-5.00"),
        unknown_account,
    ]
    with amqp_channel() as channel:
        for raw in bodies:
            publish_raw(raw, channel=channel)

    seen: set[bytes] = set()

    def all_dead_lettered() -> bool:
        seen.update(drain_queue(amqp.DEAD_LETTER_QUEUE))
        return set(bodies) <= seen

    wait_until(all_dead_lettered, timeout=15, desc="4 messages in transfers.dead")
    wait_until(
        lambda: metric_value(WORKER_URL, "bank_worker_messages_dead_lettered_total") == before + 4,
        timeout=5,
        desc="dead-letter counter to grow by 4",
    )
    assert transfer_row(json.loads(unknown_account)["transfer_id"]) is None

    transfer_id = publish_transfer(194, 193, Decimal("2.00"))
    assert wait_transfer(transfer_id)["status"] == "completed"


def test_s02_ac6_burst_of_300_transfers():
    rng = random.Random(6)
    transfer_ids = []
    with amqp_channel() as channel:
        for _ in range(300):
            from_account, to_account = rng.sample(range(196, 201), 2)
            amount = Decimal(rng.randint(100, 500)) / 100
            transfer_ids.append(publish_transfer(from_account, to_account, amount, channel=channel))

    def recorded() -> int:
        with db() as conn:
            (count,) = conn.execute(
                "SELECT count(*) FROM transfers WHERE id = ANY(%s::uuid[])", (transfer_ids,)
            ).fetchone()
        return count

    wait_until(lambda: recorded() == 300, timeout=30, desc="all 300 transfers recorded")
    assert check_invariants() == []


def test_s02_ac7_sleep_setting_slows_processing_down():
    with worker_settings("sorted", 0, 300):
        # The worker re-reads the settings within a second: poll with fresh transfers.
        wait_until(
            lambda: latency_s(publish_transfer(193, 194, Decimal("1.00"))) >= 0.3,
            timeout=15,
            interval=0.1,
            desc="a transfer to take at least 0.3 s",
        )
    wait_queue_drained()
    wait_until(
        lambda: latency_s(publish_transfer(193, 194, Decimal("1.00"))) < 0.2,
        timeout=15,
        interval=0.1,
        desc="a transfer to take less than 0.2 s again",
    )


def _pg_deadlocks() -> int:
    with db() as conn:
        (deadlocks,) = conn.execute(
            "SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()"
        ).fetchone()
    return deadlocks


def test_s02_ac8_naive_lock_order_deadlocks_and_retries():
    deadlocks_before = _pg_deadlocks()
    retries_before = metric_value(WORKER_URL, "bank_transfer_retries_total", {"reason": "deadlock"})
    transfer_ids: list[str] = []
    with worker_settings("naive", 150, 0):
        wait_until(
            lambda: latency_s(publish_transfer(199, 200, Decimal("1.00"))) >= 0.15,
            timeout=15,
            interval=0.1,
            desc="the naive settings to reach the worker",
        )
        with amqp_channel() as channel:
            for i in range(40):
                from_account, to_account = (199, 200) if i % 2 == 0 else (200, 199)
                transfer_ids.append(
                    publish_transfer(from_account, to_account, Decimal("1.00"), channel=channel)
                )
        rows = [wait_transfer(transfer_id, timeout=90) for transfer_id in transfer_ids]

    outcomes = {(row["status"], row["fail_reason"]) for row in rows}
    assert outcomes <= {("completed", None), ("failed", "deadlock")}, outcomes
    assert any(row["status"] == "completed" and row["attempts"] > 1 for row in rows)
    assert (
        metric_value(WORKER_URL, "bank_transfer_retries_total", {"reason": "deadlock"})
        > retries_before
    )
    wait_until(
        lambda: _pg_deadlocks() > deadlocks_before,
        timeout=30,
        desc="pg_stat_database.deadlocks to grow",
    )
    assert check_invariants() == []


WORKER_METRICS = [
    "bank_build_info",
    "bank_transfers_processed_total",
    "bank_transfer_processing_seconds",
    "bank_transfer_e2e_seconds",
    "bank_transfer_retries_total",
    "bank_worker_db_errors_total",
    "bank_worker_messages_dead_lettered_total",
    "bank_worker_duplicates_total",
    "bank_worker_in_flight",
]


def test_s02_ac9_worker_metrics_are_exposed():
    families = metric_families(WORKER_URL)
    missing = [name for name in WORKER_METRICS if name.removesuffix("_total") not in families]
    assert not missing
    assert metric_value(WORKER_URL, "bank_build_info", {"service": "worker"}) == 1
