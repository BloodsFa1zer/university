"""OpenTelemetry tracing for the Python services (docs/00-common.md §6.12).

Call ``init_tracing`` right after ``setup_logging`` and before any connection is
opened: the automatic instrumentation of psycopg and pika only sees connections
created after it (G20). Without OTEL_EXPORTER_OTLP_ENDPOINT, or with
OTEL_SDK_DISABLED=true, everything here is a no-op.
"""

import logging
import os
import time

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None
EXPORT_LOG_INTERVAL_S = 30.0


class _EveryThirtySeconds(logging.Filter):
    """Lets through at most one OpenTelemetry record per 30 s, other records untouched.

    An unreachable Tempo makes the SDK log export failures and "queue full" warnings
    every few seconds; they must not flood the service log.
    """

    def __init__(self) -> None:
        super().__init__()
        self._last = float("-inf")

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.name.startswith("opentelemetry"):
            return True
        now = time.monotonic()
        if now - self._last < EXPORT_LOG_INTERVAL_S:
            return False
        self._last = now
        return True


def is_initialized() -> bool:
    """True once init_tracing has started the exporter in this process."""
    return _provider is not None


def tracing_enabled() -> bool:
    disabled = os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true"
    return not disabled and bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def init_tracing(service: str) -> bool:
    """Start exporting spans of ``service`` to Tempo; True if tracing is on. Safe to repeat."""
    global _provider
    if _provider is not None:
        return True
    if not tracing_enabled():
        return False

    resource = Resource.create({"service.name": service, "service.namespace": "bank"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"], insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider = provider

    # On the handlers, not on a logger: a logger's filter only sees its own records,
    # and the SDK logs from several modules. setup_logging() has installed the handler.
    export_filter = _EveryThirtySeconds()
    for handler in logging.getLogger().handlers:
        handler.addFilter(export_filter)

    _instrument_libraries()
    return True


def _instrument_libraries() -> None:
    """Instrument psycopg and pika when the service has them installed."""
    try:
        import psycopg  # noqa: F401
        from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    except ImportError:
        pass
    else:
        PsycopgInstrumentor().instrument(enable_commenter=False)
    try:
        import pika  # noqa: F401
        from opentelemetry.instrumentation.pika import PikaInstrumentor
    except ImportError:
        pass
    else:
        PikaInstrumentor().instrument()


def shutdown_tracing() -> None:
    """Send the spans still in the queue; call before the process exits."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None


def get_tracer(name: str = "bankmon"):
    return trace.get_tracer(name)


def current_trace_ids() -> tuple[str, str] | None:
    """(trace_id as 32 hex digits, span_id as 16) of the current span, or None."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")
