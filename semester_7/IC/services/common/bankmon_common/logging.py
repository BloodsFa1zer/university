"""JSON logging in the format of docs/00-common.md §6.11.

Every record becomes one JSON object on one line of stdout:

    {"ts": "2026-11-12T10:15:30.123Z", "level": "info", "service": "worker",
     "logger": "bank_worker.consumer", "event": "transfer_completed",
     "msg": "Transfer completed", "transfer_id": "...", ...}

Use ``log_event`` for events of the contract; plain ``logger.info(...)`` calls
(including those of third-party libraries) get ``event = "log"``.
"""

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime

try:
    from bankmon_common.tracing import current_trace_ids
except ImportError:  # OpenTelemetry is not installed: no trace ids in the log

    def current_trace_ids() -> tuple[str, str] | None:
        return None


REQUIRED_FIELDS = ("ts", "level", "service", "logger", "event", "msg")

_LEVEL_NUMBERS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

# LogRecord attributes used to carry our data; prefixed so they never clash
# with the attributes the standard library sets itself.
_EVENT_ATTR = "bank_event"
_FIELDS_ATTR = "bank_fields"


def _level_name(levelno: int) -> str:
    """Loki gets `level` as a label, so only these four values may appear (§6.11)."""
    if levelno >= logging.ERROR:
        return "error"  # CRITICAL included
    if levelno >= logging.WARNING:
        return "warning"
    if levelno >= logging.INFO:
        return "info"
    return "debug"


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        payload = {
            "ts": ts.replace("+00:00", "Z"),
            "level": _level_name(record.levelno),
            "service": self.service,
            "logger": record.name,
            "event": getattr(record, _EVENT_ATTR, None) or "log",
            "msg": record.getMessage(),
        }
        # Written inside a span: the ids link this line to its trace in Tempo (§6.11).
        trace_ids = current_trace_ids()
        if trace_ids:
            payload["trace_id"], payload["span_id"] = trace_ids
        for key, value in getattr(record, _FIELDS_ATTR, {}).items():
            if key not in payload:  # extra fields never overwrite the required ones
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc, tb = record.exc_info
            payload["exc_type"] = exc_type.__name__
            payload["exc_message"] = str(exc)
            payload["stack"] = "".join(traceback.format_exception(exc_type, exc, tb))
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(service: str, level: str | None = None) -> None:
    """Send all logging to stdout as JSON. Safe to call more than once."""
    level_name = (level or os.environ.get("LOG_LEVEL") or "info").lower()
    if level_name not in _LEVEL_NUMBERS:
        raise RuntimeError(f"unknown log level {level_name!r}, use one of {list(_LEVEL_NUMBERS)}")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(_LEVEL_NUMBERS[level_name])


def log_event(
    logger: logging.Logger, level: str | int, event: str, msg: str, /, **fields: object
) -> None:
    """Log a contract event (§6.11) with extra fields.

    ``level`` is "debug" / "info" / "warning" / "error" or a logging constant.
    Pass ``exc_info=True`` inside an ``except`` block to attach the exception.
    """
    levelno = _LEVEL_NUMBERS[level] if isinstance(level, str) else level
    exc_info = fields.pop("exc_info", None)
    logger.log(
        levelno,
        msg,
        exc_info=exc_info,
        extra={_EVENT_ATTR: event, _FIELDS_ATTR: fields},
    )
