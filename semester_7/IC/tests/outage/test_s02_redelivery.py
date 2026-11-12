"""S2-AC11: a transfer published while the worker is down is processed after it starts.

Phase 1 (worker stopped):  pytest tests/outage/test_s02_redelivery.py -k publish_while_down
Phase 2 (worker started):  pytest tests/outage/test_s02_redelivery.py -k processed_after_start
"""

from decimal import Decimal

from bankmon_common import amqp
from e2e.helpers import publish_transfer, queue_counts, transfer_row, wait_transfer


def test_publish_while_down(redelivery_transfer_id):
    _ready, consumers = queue_counts(amqp.TRANSFERS_QUEUE)
    assert consumers == 0, "stop the worker first: docker compose stop worker"
    publish_transfer(191, 192, Decimal("4.00"), transfer_id=redelivery_transfer_id)
    assert transfer_row(redelivery_transfer_id) is None
    ready, _consumers = queue_counts(amqp.TRANSFERS_QUEUE)
    assert ready >= 1


def test_processed_after_start(redelivery_transfer_id):
    row = wait_transfer(redelivery_transfer_id, timeout=60)
    assert row["status"] == "completed"
