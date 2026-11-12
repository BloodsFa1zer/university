"""RabbitMQ topology (docs/00-common.md §6.5) and connections that survive a broker restart.

Imported only by the services that install pika (worker, generator).
"""

import logging
import time

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPConnectionError

from bankmon_common.logging import log_event

logger = logging.getLogger(__name__)

TRANSFERS_EXCHANGE = "bank.transfers"
TRANSFERS_QUEUE = "transfers.requested"
TRANSFER_ROUTING_KEY = "transfer.requested"
DEAD_LETTER_EXCHANGE = "bank.dlx"
DEAD_LETTER_QUEUE = "transfers.dead"

MAX_RETRY_DELAY_S = 10.0


def connect(url: str) -> pika.BlockingConnection:
    """Open a connection, retrying forever with a pause that grows from 1 to 10 s."""
    delay = 1.0
    while True:
        try:
            return pika.BlockingConnection(pika.URLParameters(url))
        except AMQPConnectionError as exc:
            log_event(
                logger,
                "warning",
                "connection_lost",
                f"RabbitMQ is unavailable, retrying in {delay:.0f} s",
                target="rabbitmq",
                error=repr(exc),
            )
            time.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY_S)


def declare_topology(channel: BlockingChannel) -> None:
    """Declare the exchanges and queues. Idempotent: every publisher and consumer calls it."""
    channel.exchange_declare(TRANSFERS_EXCHANGE, exchange_type="direct", durable=True)
    channel.exchange_declare(DEAD_LETTER_EXCHANGE, exchange_type="fanout", durable=True)
    channel.queue_declare(
        TRANSFERS_QUEUE,
        durable=True,
        arguments={"x-dead-letter-exchange": DEAD_LETTER_EXCHANGE},
    )
    channel.queue_bind(TRANSFERS_QUEUE, TRANSFERS_EXCHANGE, routing_key=TRANSFER_ROUTING_KEY)
    channel.queue_declare(DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(DEAD_LETTER_QUEUE, DEAD_LETTER_EXCHANGE)
