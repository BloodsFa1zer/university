"""Entry point: `python -m bank_worker.main`."""

import logging
import signal
import threading
import time

from bank_worker.consumer import Consumer
from bankmon_common.config import env_int, env_str
from bankmon_common.logging import log_event, setup_logging
from bankmon_common.metrics import register_build_info, start_metrics_server
from bankmon_common.tracing import init_tracing, shutdown_tracing

logger = logging.getLogger("bank_worker")

SHUTDOWN_TIMEOUT_S = 10.0


def main() -> None:
    setup_logging("worker")
    # Before any connection: the psycopg and pika instrumentation only sees later ones (G20).
    init_tracing("worker")
    logging.getLogger("pika").setLevel(logging.WARNING)

    concurrency = env_int("WORKER_CONCURRENCY", 4)
    database_url = env_str("DATABASE_URL")
    amqp_url = env_str("AMQP_URL")

    register_build_info("worker")
    start_metrics_server(8000)

    stopping = threading.Event()
    consumers = [Consumer(i, database_url, amqp_url, stopping) for i in range(concurrency)]

    def handle_signal(signum: int, _frame) -> None:
        logger.info("Received %s, finishing current messages", signal.Signals(signum).name)
        stopping.set()
        for consumer in consumers:
            consumer.request_stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    for consumer in consumers:
        consumer.start()
    log_event(
        logger,
        "info",
        "worker_started",
        f"Worker started with {concurrency} consumers",
        concurrency=concurrency,
    )

    while not stopping.wait(0.5):
        pass

    deadline = time.monotonic() + SHUTDOWN_TIMEOUT_S
    for consumer in consumers:
        consumer.join(timeout=max(0.0, deadline - time.monotonic()))
    shutdown_tracing()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
