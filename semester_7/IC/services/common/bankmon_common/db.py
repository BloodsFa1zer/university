"""PostgreSQL connections that survive a database restart (rule R9).

Imported only by the services that install psycopg (worker, generator).
"""

import logging
import time

import psycopg

from bankmon_common.logging import log_event

logger = logging.getLogger(__name__)

MAX_RETRY_DELAY_S = 10.0


def connect(dsn: str, *, application_name: str, autocommit: bool = False) -> psycopg.Connection:
    """Open a connection, retrying forever with a pause that grows from 1 to 10 s."""
    delay = 1.0
    while True:
        try:
            return psycopg.connect(
                dsn,
                application_name=application_name,
                autocommit=autocommit,
                connect_timeout=5,
            )
        except psycopg.OperationalError as exc:
            log_event(
                logger,
                "warning",
                "connection_lost",
                f"PostgreSQL is unavailable, retrying in {delay:.0f} s",
                target="postgres",
                error=str(exc).strip(),
            )
            time.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY_S)
