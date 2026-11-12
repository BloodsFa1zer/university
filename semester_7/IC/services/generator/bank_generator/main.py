"""Entry point: `python -m bank_generator.main`."""

import logging
import threading
from datetime import UTC, datetime

import psycopg
import uvicorn

from bank_generator import metrics
from bank_generator.api import create_app
from bank_generator.engine import Engine, store_scenario
from bank_generator.probe import Probe
from bank_generator.scenarios import NORMAL, Scenario
from bank_generator.state import ControlState
from bankmon_common import db
from bankmon_common.config import env_float, env_str
from bankmon_common.logging import log_event, setup_logging
from bankmon_common.metrics import register_build_info
from bankmon_common.tracing import init_tracing, shutdown_tracing

logger = logging.getLogger("bank_generator")


def main() -> None:
    setup_logging("generator")
    # Before any connection or app: instrumentation only sees what is created later (G20).
    init_tracing("generator")
    logging.getLogger("pika").setLevel(logging.WARNING)

    rate = env_float("GEN_RATE", 20.0)
    database_url = env_str("DATABASE_URL")
    monitor_url = env_str("MONITOR_DATABASE_URL")
    amqp_url = env_str("AMQP_URL")
    register_build_info("generator")

    control = ControlState(rate=rate, now=datetime.now(UTC))

    def save_settings(scenario: Scenario) -> None:
        with psycopg.connect(
            database_url, autocommit=True, connect_timeout=3, application_name="bank-generator"
        ) as conn:
            store_scenario(conn, scenario)

    def state_changed(state: dict, ttl_s: int | None = None) -> None:
        metrics.publish_state(state)
        mode = "running" if state["running"] else "paused"
        log_event(
            logger,
            "info",
            "scenario_changed",
            f"Scenario {state['scenario']}, {state['rate']:g} operations/s, {mode}",
            scenario=state["scenario"],
            rate=state["rate"],
            running=state["running"],
            ttl_s=ttl_s,
        )

    # A (re)started generator always begins in the normal scenario.
    with db.connect(database_url, application_name="bank-generator", autocommit=True) as conn:
        store_scenario(conn, NORMAL)
    metrics.publish_state(control.snapshot())

    stopping = threading.Event()
    Engine(control, database_url, amqp_url, stopping, on_expired=state_changed).start()
    Probe(monitor_url, stopping).start()

    app = create_app(
        control,
        save_settings,
        on_change=lambda state, patch: state_changed(state, patch.get("ttl_s")),
    )
    log_event(
        logger,
        "info",
        "generator_started",
        f"Generator started at {rate:g} operations/s",
        rate=rate,
    )
    # log_config=None: uvicorn logs through our JSON handler; it also handles SIGTERM.
    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=8000, log_config=None, access_log=False)
    )
    server.run()
    stopping.set()
    shutdown_tracing()
    logger.info("Generator stopped")


if __name__ == "__main__":
    main()
