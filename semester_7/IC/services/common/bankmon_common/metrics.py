"""Prometheus helpers shared by all services (docs/00-common.md §6.9)."""

from prometheus_client import Gauge, start_http_server

from bankmon_common import __version__

# Histogram buckets, in seconds.
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
E2E_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)

BUILD_INFO = Gauge("bank_build_info", "Service name and version; always 1", ["service", "version"])


def register_build_info(service: str) -> None:
    BUILD_INFO.labels(service=service, version=__version__).set(1)


def start_metrics_server(port: int = 8000) -> None:
    """Serve /metrics on all interfaces in a background thread."""
    start_http_server(port)
