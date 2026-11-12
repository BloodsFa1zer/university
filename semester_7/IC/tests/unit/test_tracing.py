"""bankmon_common.tracing and the trace ids in log lines — S8-AC14."""

import io
import json
import logging
import re

import pytest
from opentelemetry.sdk.trace import TracerProvider

from bankmon_common import tracing
from bankmon_common.logging import JsonFormatter, log_event


@pytest.fixture
def no_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)


def test_s08_ac14_without_an_endpoint_tracing_is_off(no_endpoint):
    assert tracing.init_tracing("unit") is False
    assert tracing.is_initialized() is False
    assert tracing.current_trace_ids() is None


def test_s08_ac14_sdk_disabled_switch(no_endpoint, monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo:4317")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert tracing.init_tracing("unit") is False
    assert tracing.is_initialized() is False


def _line(logger_name: str) -> dict:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("unit"))
    logger = logging.getLogger(logger_name)
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    log_event(logger, "info", "probe", "probe")
    return json.loads(stream.getvalue())


def test_s08_ac14_log_line_inside_a_span_has_trace_ids():
    # A local provider: spans exist in memory, nothing is exported.
    tracer = TracerProvider().get_tracer("unit")
    with tracer.start_as_current_span("work"):
        inside = _line("unit.inside")
        ids = tracing.current_trace_ids()
    assert re.fullmatch(r"[0-9a-f]{32}", inside["trace_id"])
    assert re.fullmatch(r"[0-9a-f]{16}", inside["span_id"])
    assert (inside["trace_id"], inside["span_id"]) == ids


def test_s08_ac14_log_line_outside_a_span_has_no_trace_ids():
    outside = _line("unit.outside")
    assert "trace_id" not in outside and "span_id" not in outside


def _record(logger_name: str) -> logging.LogRecord:
    return logging.LogRecord(logger_name, logging.WARNING, __file__, 1, "msg", None, None)


def test_s08_export_errors_are_rate_limited():
    limiter = tracing._EveryThirtySeconds()
    assert limiter.filter(_record("opentelemetry.exporter.otlp.proto.grpc.exporter")) is True
    # any other OpenTelemetry module counts towards the same limit
    assert limiter.filter(_record("opentelemetry.sdk._shared_internal")) is False
    # the service's own records are never dropped
    assert limiter.filter(_record("bank_worker.consumer")) is True
