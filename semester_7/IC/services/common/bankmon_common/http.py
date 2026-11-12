"""HTTP helpers for the FastAPI services (generator, auth): request metrics, /healthz, /metrics.

Imported only by the services that install FastAPI.
"""

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.routing import Match

from bankmon_common import tracing
from bankmon_common.metrics import DURATION_BUCKETS

HTTP_REQUESTS = Counter(
    "bank_http_requests_total",
    "HTTP requests by method, route template and status",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "bank_http_request_duration_seconds",
    "HTTP request duration by method and route template",
    ["method", "route"],
    buckets=DURATION_BUCKETS,
)

# Service endpoints scraped every few seconds; counting them would drown the real traffic.
_NOT_MEASURED = frozenset({"/metrics", "/healthz"})


def route_template(app: FastAPI, scope: dict) -> str:
    """The path template of the route serving a request, e.g. "/control/api/state".

    A template, not the real path, keeps the number of label values small.
    """
    partial = None
    for route in app.router.routes:
        match, _child_scope = route.matches(scope)
        if match == Match.FULL:
            return route.path
        if match == Match.PARTIAL and partial is None:
            partial = route.path  # the path matches, the method does not (405)
    return partial or "unmatched"


def instrument_app(app: FastAPI) -> None:
    """Count and time every request except /metrics and /healthz; trace them if tracing is on.

    Call after init_tracing.
    """
    if tracing.is_initialized():
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics,/healthz")

    @app.middleware("http")
    async def measure(request: Request, call_next):
        if request.url.path in _NOT_MEASURED:
            return await call_next(request)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = route_template(app, request.scope)
            HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
            HTTP_DURATION.labels(request.method, route).observe(time.perf_counter() - started)


def add_health_and_metrics(app: FastAPI) -> None:
    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
