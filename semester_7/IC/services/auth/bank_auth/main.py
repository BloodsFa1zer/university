"""Entry point: `python -m bank_auth.main`."""

import logging

import uvicorn

from bank_auth.api import create_app
from bank_auth.users import UserStore
from bankmon_common.config import env_str
from bankmon_common.logging import log_event, setup_logging
from bankmon_common.metrics import register_build_info
from bankmon_common.tracing import init_tracing, shutdown_tracing

logger = logging.getLogger("bank_auth")

MIN_SECRET_LENGTH = 32


def main() -> None:
    setup_logging("auth")
    init_tracing("auth")  # before create_app, which instruments FastAPI

    if len(env_str("AUTH_JWT_SECRET")) < MIN_SECRET_LENGTH:
        logger.error(
            "AUTH_JWT_SECRET must be at least %d characters: a short HS256 key can be guessed",
            MIN_SECRET_LENGTH,
        )
        raise SystemExit(1)

    store = UserStore(env_str("AUTH_DB_PATH", "/data/auth.db"))
    created = store.ensure_seed(
        [
            (env_str("AUTH_ADMIN_USER"), env_str("AUTH_ADMIN_PASSWORD"), "admin"),
            (env_str("AUTH_VIEWER_USER"), env_str("AUTH_VIEWER_PASSWORD"), "viewer"),
        ]
    )
    log_event(logger, "info", "users_seeded", f"{created} users created", created=created)

    register_build_info("auth")
    app = create_app(store)
    log_event(logger, "info", "auth_started", "Auth service started")
    # log_config=None: uvicorn logs through our JSON handler; it also handles SIGTERM.
    uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=8000, log_config=None, access_log=False)
    ).run()
    shutdown_tracing()


if __name__ == "__main__":
    main()
