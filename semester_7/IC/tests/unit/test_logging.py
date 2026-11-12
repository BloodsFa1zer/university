"""bankmon_common.logging — S0-AC3."""

import io
import json
import logging
import re
from decimal import Decimal

import pytest

from bankmon_common.logging import REQUIRED_FIELDS, JsonFormatter, log_event, setup_logging

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|\+00:00)$")


def _json_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if isinstance(h.formatter, JsonFormatter)]


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def read_lines(monkeypatch, restore_root_logger):
    """Configure logging for service "test" at level info; return a reader of emitted lines.

    pytest swaps sys.stdout for every test phase, so a stream picked up during fixture
    setup is already closed when the test body runs. The handler therefore writes into
    a buffer here; test_s00_ac3_writes_to_stdout checks the real stdout separately.
    """
    monkeypatch.setenv("LOG_LEVEL", "info")
    setup_logging("test")
    buffer = io.StringIO()
    (handler,) = _json_handlers()
    handler.setStream(buffer)

    def read():
        lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
        buffer.seek(0)
        buffer.truncate()
        return lines

    return read


def test_s00_ac3_writes_to_stdout(capsys, monkeypatch, restore_root_logger):
    monkeypatch.setenv("LOG_LEVEL", "info")
    setup_logging("test")  # in the test body sys.stdout is the capsys buffer
    logging.getLogger("app").info("to stdout")
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["msg"] for line in lines] == ["to stdout"]


def test_s00_ac3_line_is_json_with_required_fields(read_lines):
    logging.getLogger("app.module").info("hello %s", "world")
    (line,) = read_lines()
    assert set(REQUIRED_FIELDS) <= line.keys()
    assert line["level"] == "info"
    assert line["service"] == "test"
    assert line["logger"] == "app.module"
    assert line["msg"] == "hello world"


def test_s00_ac3_ts_is_utc_with_milliseconds(read_lines):
    logging.getLogger("app").warning("tick")
    (line,) = read_lines()
    assert TS_RE.match(line["ts"]), line["ts"]


def test_s00_ac3_record_without_event_gets_event_log(read_lines):
    logging.getLogger("pika.connection").error("third-party message")
    (line,) = read_lines()
    assert line["event"] == "log"
    assert line["level"] == "error"


def test_s00_ac3_log_event_adds_fields(read_lines):
    log_event(
        logging.getLogger("worker"),
        "warning",
        "transfer_failed",
        "Transfer failed",
        transfer_id="5b0c9a3e",
        amount=Decimal("250.00"),
        attempts=2,
        owner="Клієнт 001",
    )
    (line,) = read_lines()
    assert line["event"] == "transfer_failed"
    assert line["level"] == "warning"
    assert line["msg"] == "Transfer failed"
    assert line["transfer_id"] == "5b0c9a3e"
    assert line["amount"] == "250.00"  # not JSON-serialisable → str()
    assert line["attempts"] == 2
    assert line["owner"] == "Клієнт 001"


def test_s00_ac3_extra_fields_do_not_override_required(read_lines):
    log_event(
        logging.getLogger("real"),
        "info",
        "real_event",
        "real message",
        ts="fake",
        level="error",
        service="fake",
        logger="fake",
        event="fake",
        msg="fake",
    )
    (line,) = read_lines()
    assert TS_RE.match(line["ts"])
    assert line["level"] == "info"
    assert line["service"] == "test"
    assert line["logger"] == "real"
    assert line["event"] == "real_event"
    assert line["msg"] == "real message"


def test_s00_ac3_exception_fields(read_lines):
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("app").exception("operation failed")
    (line,) = read_lines()
    assert line["exc_type"] == "ValueError"
    assert line["exc_message"] == "boom"
    assert "Traceback" in line["stack"]
    assert "ValueError: boom" in line["stack"]


def test_s00_ac3_log_event_with_exc_info(read_lines):
    try:
        raise KeyError("missing")
    except KeyError:
        log_event(logging.getLogger("app"), "error", "db_error", "Query failed", exc_info=True)
    (line,) = read_lines()
    assert line["event"] == "db_error"
    assert line["exc_type"] == "KeyError"
    assert "exc_info" not in line


def test_s00_ac3_debug_hidden_at_info(read_lines):
    logging.getLogger("app").debug("noise")
    log_event(logging.getLogger("app"), "debug", "noise", "noise")
    assert read_lines() == []


def test_s00_ac3_level_argument_overrides_env(capsys, monkeypatch, restore_root_logger):
    monkeypatch.setenv("LOG_LEVEL", "info")
    setup_logging("test", level="debug")
    logging.getLogger("app").debug("visible")
    assert len(capsys.readouterr().out.splitlines()) == 1


def test_s00_ac3_unknown_level_is_rejected(restore_root_logger):
    with pytest.raises(RuntimeError, match="verbose"):
        setup_logging("test", level="verbose")


def test_s00_ac3_critical_maps_to_error(read_lines):
    logging.getLogger("app").critical("fatal")
    (line,) = read_lines()
    assert line["level"] == "error"


def test_s00_ac3_multiline_message_stays_on_one_line(read_lines):
    logging.getLogger("app").info("first\nsecond")
    (line,) = read_lines()
    assert line["msg"] == "first\nsecond"


def test_s00_ac3_setup_is_idempotent(capsys, monkeypatch, restore_root_logger):
    monkeypatch.setenv("LOG_LEVEL", "info")
    setup_logging("test")
    setup_logging("test")
    assert len(_json_handlers()) == 1
    logging.getLogger("app").info("once")
    assert len(capsys.readouterr().out.splitlines()) == 1
