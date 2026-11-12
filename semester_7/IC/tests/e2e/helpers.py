"""Helpers for e2e tests. Each stage adds its own; reuse before writing new ones.

Waiting is done only by polling with a timeout (rule R12): this module is the
only place in tests/ where time.sleep is allowed.
"""

import base64
import json
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pika
import psycopg
import requests
from prometheus_client.parser import text_string_to_metric_families
from psycopg.rows import dict_row

from bankmon_common import amqp
from bankmon_common.messages import TransferRequested

WORKER_URL = os.environ.get("WORKER_URL", "http://worker:8000")
GENERATOR_URL = os.environ.get("GENERATOR_URL", "http://generator:8000")


def wait_until[T](
    fn: Callable[[], T], timeout: float = 30.0, interval: float = 0.5, desc: str = ""
) -> T:
    """Call ``fn`` until it returns a truthy value and return that value.

    Exceptions raised by ``fn`` count as "not yet". After ``timeout`` seconds an
    AssertionError reports ``desc`` and the last value or exception.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = fn()
            last = f"last value: {value!r}"
            if value:
                return value
        except Exception as exc:  # any failure means "not ready yet"
            last = f"last error: {exc!r}"
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {desc or fn}; {last}")
        time.sleep(interval)


# --- PostgreSQL (S1) ---------------------------------------------------------

_DSN_ENV = {"admin": "PG_ADMIN_DSN", "app": "PG_APP_DSN", "monitor": "PG_MONITOR_DSN"}


@contextmanager
def db(role: str = "admin") -> Iterator[psycopg.Connection]:
    """Connection to the bank database as "admin", "app" or "monitor".

    Nothing is saved unless the test calls ``conn.commit()``: closing the
    connection rolls back the open transaction.
    """
    conn = psycopg.connect(
        os.environ[_DSN_ENV[role]], connect_timeout=5, application_name="e2e-tests"
    )
    try:
        yield conn
    finally:
        conn.close()


# Invariants I1–I4 of §6.4. Each query returns the offending rows (at most 5).
_INVARIANTS = {
    "I1 balance equals the sum of its ledger entries": """
        SELECT a.id, a.balance, COALESCE(l.total, 0) AS ledger_total
        FROM accounts a
        LEFT JOIN (SELECT account_id, SUM(delta) AS total
                   FROM ledger_entries GROUP BY account_id) l ON l.account_id = a.id
        WHERE a.balance <> COALESCE(l.total, 0)
        ORDER BY a.id LIMIT 5""",
    "I2 transfer entries sum to zero": """
        SELECT total
        FROM (SELECT COALESCE(SUM(delta), 0) AS total FROM ledger_entries
              WHERE kind IN ('transfer_in', 'transfer_out')) s
        WHERE total <> 0""",
    "I3 no negative balances": """
        SELECT id, balance FROM accounts WHERE balance < 0 ORDER BY id LIMIT 5""",
    # The ledger is aggregated per transfer first and then joined: grouping the join
    # by t.id instead made the planner pick a nested loop (transfers × ledger), which
    # took minutes once the tables held a few hundred thousand rows.
    "I4 ledger entries match the transfer status": """
        SELECT t.id, t.status, COALESCE(p.entries, 0) AS entries
        FROM transfers t
        LEFT JOIN (
            SELECT transfer_id,
                   count(*) AS entries,
                   count(*) FILTER (WHERE kind = 'transfer_out') AS outs,
                   count(*) FILTER (WHERE kind = 'transfer_in') AS ins,
                   sum(delta) FILTER (WHERE kind = 'transfer_out') AS out_sum,
                   sum(delta) FILTER (WHERE kind = 'transfer_in') AS in_sum,
                   min(account_id) FILTER (WHERE kind = 'transfer_out') AS out_account,
                   min(account_id) FILTER (WHERE kind = 'transfer_in') AS in_account
            FROM ledger_entries
            WHERE transfer_id IS NOT NULL
            GROUP BY transfer_id
        ) p ON p.transfer_id = t.id
        -- COALESCE: a completed transfer without any entry makes the condition NULL,
        -- and NOT NULL would hide it.
        WHERE NOT COALESCE(
            (t.status = 'completed'
             AND p.entries = 2 AND p.outs = 1 AND p.ins = 1
             AND p.out_sum = -t.amount AND p.in_sum = t.amount
             AND p.out_account = t.from_account AND p.in_account = t.to_account)
            OR (t.status = 'failed' AND p.transfer_id IS NULL),
            false)
        LIMIT 5""",
}


def check_invariants(conn: psycopg.Connection | None = None) -> list[str]:
    """Check I1–I4 on one consistent snapshot; return the violations ([] means all hold).

    Without ``conn`` a fresh REPEATABLE READ connection is used, so transfers that
    commit while the checks run cannot make them disagree with each other.
    """
    if conn is None:
        with db() as own:
            own.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            return check_invariants(own)
    violations = []
    for name, query in _INVARIANTS.items():
        rows = conn.execute(query).fetchall()
        if rows:
            violations.append(f"{name}: {rows}")
    return violations


# --- RabbitMQ and the worker (S2) --------------------------------------------


@contextmanager
def amqp_channel() -> Iterator[pika.adapters.blocking_connection.BlockingChannel]:
    """A channel with publisher confirms: basic_publish returns once the broker has the message."""
    connection = pika.BlockingConnection(pika.URLParameters(os.environ["AMQP_URL"]))
    try:
        channel = connection.channel()
        channel.confirm_delivery()
        yield channel
    finally:
        if connection.is_open:
            connection.close()


def make_transfer(
    from_account: int,
    to_account: int,
    amount: Decimal | str,
    *,
    transfer_id: str | None = None,
    scenario: str = "normal",
) -> TransferRequested:
    return TransferRequested(
        transfer_id=uuid.UUID(transfer_id) if transfer_id else uuid.uuid4(),
        from_account=from_account,
        to_account=to_account,
        amount=Decimal(amount),
        requested_at=datetime.now(UTC),
        scenario=scenario,
    )


def publish_raw(body: bytes, *, channel=None) -> None:
    """Publish any body to the transfers exchange, the way the generator does."""
    if channel is None:
        with amqp_channel() as own:
            publish_raw(body, channel=own)
        return
    channel.basic_publish(
        exchange=amqp.TRANSFERS_EXCHANGE,
        routing_key=amqp.TRANSFER_ROUTING_KEY,
        body=body,
        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
        mandatory=True,
    )


def publish_transfer(
    from_account: int,
    to_account: int,
    amount: Decimal | str,
    *,
    transfer_id: str | None = None,
    scenario: str = "normal",
    channel=None,
) -> str:
    """Publish a valid TransferRequested; return its transfer_id."""
    msg = make_transfer(
        from_account, to_account, amount, transfer_id=transfer_id, scenario=scenario
    )
    publish_raw(msg.encode(), channel=channel)
    return str(msg.transfer_id)


def transfer_row(transfer_id: str) -> dict | None:
    with db() as conn:
        conn.row_factory = dict_row
        return conn.execute("SELECT * FROM transfers WHERE id = %s", (transfer_id,)).fetchone()


def wait_transfer(transfer_id: str, timeout: float = 10) -> dict:
    """Wait until the worker has recorded the transfer; return its row."""
    return wait_until(
        lambda: transfer_row(transfer_id),
        timeout=timeout,
        interval=0.2,
        desc=f"transfer {transfer_id}",
    )


def ledger_entries(transfer_id: str) -> list[dict]:
    with db() as conn:
        conn.row_factory = dict_row
        return conn.execute(
            "SELECT * FROM ledger_entries WHERE transfer_id = %s ORDER BY kind", (transfer_id,)
        ).fetchall()


def latency_s(transfer_id: str, timeout: float = 15) -> float:
    """Seconds between requested_at and processed_at of a transfer (waits for it)."""
    row = wait_transfer(transfer_id, timeout=timeout)
    return (row["processed_at"] - row["requested_at"]).total_seconds()


def rabbitmq_api(path: str) -> dict:
    """GET from the RabbitMQ management API. Its statistics lag by up to 5 s."""
    response = requests.get(
        f"{os.environ['RABBITMQ_API']}/api/{path}",
        auth=(os.environ["RABBITMQ_DEFAULT_USER"], os.environ["RABBITMQ_DEFAULT_PASS"]),
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def queue_info(name: str) -> dict:
    return rabbitmq_api(f"queues/%2F/{name}")


def queue_counts(name: str) -> tuple[int, int]:
    """(messages ready, consumers) of a queue, live from the broker (no statistics lag)."""
    with amqp_channel() as channel:
        method = channel.queue_declare(queue=name, passive=True).method
        return method.message_count, method.consumer_count


def wait_queue_drained(timeout: float = 60) -> None:
    wait_until(
        lambda: queue_counts(amqp.TRANSFERS_QUEUE)[0] == 0,
        timeout=timeout,
        desc="no messages waiting in transfers.requested",
    )


def drain_queue(name: str) -> list[bytes]:
    """Take (and acknowledge) every message waiting in a queue; return their bodies."""
    bodies = []
    with amqp_channel() as channel:
        while True:
            method, _properties, body = channel.basic_get(queue=name)
            if method is None:
                return bodies
            channel.basic_ack(method.delivery_tag)
            bodies.append(body)


def metric_value(url: str, name: str, labels: dict[str, str] | None = None) -> float:
    """Sum of the samples called ``name`` whose labels include ``labels``; 0 if none."""
    text = requests.get(f"{url}/metrics", timeout=5).text
    total = 0.0
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name and all(
                sample.labels.get(key) == value for key, value in (labels or {}).items()
            ):
                total += sample.value
    return total


def metric_families(url: str) -> set[str]:
    """Names of the metric families an endpoint exposes (counters without `_total`)."""
    text = requests.get(f"{url}/metrics", timeout=5).text
    return {family.name for family in text_string_to_metric_families(text)}


def _set_scenario_state(
    lock_order: str, lock_gap_ms: int, sleep_ms: int, scenario: str | None = None
) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE scenario_state
               SET scenario = COALESCE(%s::text, scenario), lock_order = %s,
                   lock_gap_ms = %s, sleep_ms = %s, updated_at = now()
               WHERE id = 1""",
            (scenario, lock_order, lock_gap_ms, sleep_ms),
        )
        conn.commit()


# Each worker thread caches scenario_state for up to 1 s (§6.6) and re-reads it on its
# next message. So a message processed more than 1 s after a change is guaranteed to
# see the new settings, while a busy thread may still use the old ones before that.
SETTINGS_CACHE_S = 1.0


def wait_for_settings_refresh() -> None:
    """Let every worker thread's settings cache expire after a change of scenario_state."""
    time.sleep(SETTINGS_CACHE_S + 0.2)


@contextmanager
def worker_settings(lock_order: str, lock_gap_ms: int, sleep_ms: int) -> Iterator[None]:
    """Change what the worker applies; returns once every worker thread applies it.

    On exit the row always goes back to the values of the `normal` scenario.
    """
    _set_scenario_state(lock_order, lock_gap_ms, sleep_ms)
    wait_for_settings_refresh()
    try:
        yield
    finally:
        _set_scenario_state("sorted", 0, 0, scenario="normal")
        wait_for_settings_refresh()


# --- Generator (S3) ----------------------------------------------------------

CONTROL_STATE_URL = f"{GENERATOR_URL}/control/api/state"


def control_get() -> dict:
    response = requests.get(CONTROL_STATE_URL, timeout=5)
    response.raise_for_status()
    return response.json()


def control_put(**fields) -> dict:
    response = requests.put(CONTROL_STATE_URL, json=fields, timeout=10)
    response.raise_for_status()
    return response.json()


def measurement_window(seconds: float) -> None:
    """Let the system run for a fixed time to measure it (not waiting for a condition)."""
    time.sleep(seconds)


def counter_deltas(
    url: str, name: str, label_sets: list[dict[str, str]], window_s: float
) -> tuple[list[float], float]:
    """How much each labelled series of a counter grows over a window; also the real window."""
    before = [metric_value(url, name, labels) for labels in label_sets]
    started = time.monotonic()
    measurement_window(window_s)
    after = [metric_value(url, name, labels) for labels in label_sets]
    return [b - a for a, b in zip(before, after, strict=True)], time.monotonic() - started


def rate_of(url: str, name: str, labels: dict[str, str] | None, window_s: float) -> float:
    """Per-second growth of a counter over a window."""
    (delta,), elapsed = counter_deltas(url, name, [labels or {}], window_s)
    return delta / elapsed


def sample_for[T](fn: Callable[[], T], duration_s: float, interval_s: float = 1.0) -> list[T]:
    """Call fn every interval_s for duration_s; return what it returned."""
    samples = []
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        samples.append(fn())
        time.sleep(interval_s)
    return samples


# --- Gateway and auth (S4) ---------------------------------------------------

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8080")
AUTH_URL = os.environ.get("AUTH_URL", "http://auth:8000")
ADMIN = (os.environ.get("AUTH_ADMIN_USER", "admin"), os.environ.get("AUTH_ADMIN_PASSWORD", ""))
VIEWER = (os.environ.get("AUTH_VIEWER_USER", "viewer"), os.environ.get("AUTH_VIEWER_PASSWORD", ""))


class GatewaySession(requests.Session):
    """A browser-like session against the gateway: relative paths, redirects not followed."""

    def request(self, method, url, *args, **kwargs):
        kwargs.setdefault("allow_redirects", False)
        kwargs.setdefault("timeout", 10)
        if url.startswith("/"):
            url = GATEWAY_URL + url
        return super().request(method, url, *args, **kwargs)

    def get(self, url, **kwargs):
        # requests.Session.get passes allow_redirects=True itself; keep our default.
        kwargs.setdefault("allow_redirects", False)
        return self.request("GET", url, **kwargs)


def gateway() -> GatewaySession:
    return GatewaySession()


def login(username: str, password: str) -> GatewaySession:
    """A session that went through the login form; it carries the bank_session cookie."""
    session = gateway()
    response = session.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 303, (response.status_code, response.text[:200])
    return session


def token(username: str, password: str) -> str:
    response = gateway().post("/auth/token", json={"username": username, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


# --- Prometheus (S5) ---------------------------------------------------------

PROM_URL = os.environ.get("PROM_URL", "http://prometheus:9090")


def prom_api(path: str, **params) -> dict | list:
    """The `data` of a Prometheus HTTP API answer."""
    response = requests.get(f"{PROM_URL}/api/v1/{path}", params=params, timeout=10)
    response.raise_for_status()
    body = response.json()
    assert body["status"] == "success", body
    return body["data"]


def prom_query(expr: str, at: float | None = None) -> list[dict]:
    params = {"query": expr}
    if at is not None:
        params["time"] = at
    return prom_api("query", **params)["result"]


def prom_value(expr: str) -> float | None:
    """The value of the first series of an instant query, or None if there is none."""
    result = prom_query(expr)
    return float(result[0]["value"][1]) if result else None


def alert_states() -> dict[str, str]:
    """{alert name: "inactive" | "pending" | "firing"} for every alerting rule."""
    groups = prom_api("rules", type="alert")["groups"]
    return {rule["name"]: rule["state"] for group in groups for rule in group["rules"]}


def wait_alert(name: str, state: str, timeout: float) -> None:
    wait_until(
        lambda: alert_states()[name] == state,
        timeout=timeout,
        interval=2,
        desc=f"alert {name} to become {state}",
    )


def wait_all_alerts_inactive(timeout: float = 240) -> None:
    wait_until(
        lambda: set(alert_states().values()) == {"inactive"},
        timeout=timeout,
        interval=2,
        desc="every alert to be inactive",
    )


# --- Grafana (S6) ------------------------------------------------------------

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000/grafana")
DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "observability" / "grafana" / "dashboards"


def grafana_api(path: str, method: str = "GET", **kwargs) -> requests.Response:
    """Grafana HTTP API as the internal administrator (only reachable inside the network)."""
    auth = (os.environ["GF_SECURITY_ADMIN_USER"], os.environ["GF_SECURITY_ADMIN_PASSWORD"])
    return requests.request(method, f"{GRAFANA_URL}/api/{path}", auth=auth, timeout=10, **kwargs)


def dashboard_files() -> dict[str, dict]:
    """{uid: dashboard JSON} of every provisioned dashboard file."""
    dashboards = {}
    for path in sorted(DASHBOARD_DIR.glob("*.json")):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        dashboards[dashboard["uid"]] = dashboard
    return dashboards


def panel_exprs(dashboard: dict) -> list[tuple[str, str, str]]:
    """(panel title, data source uid, query) for every query of every panel.

    Grafana variables are replaced by what Grafana itself would use for a
    15-minute range, so the query can be sent to the data source directly.
    """
    replacements = {
        "$__rate_interval": "1m",
        "$__interval": "15s",
        "$__range": "15m",
        # template variables of the logs dashboard, at their defaults
        "$service": ".+",
        "$search": "",
    }
    queries = []
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            query = target.get("expr") or target.get("query") or ""
            for variable, value in replacements.items():
                query = query.replace(variable, value)
            uid = (target.get("datasource") or panel.get("datasource") or {}).get("uid", "")
            queries.append((panel["title"], uid, query))
    return queries


# --- Loki (S7) ---------------------------------------------------------------

LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100")


def loki_query(logql: str, since_s: float = 300, limit: int = 100) -> list:
    """Lines of a LogQL query over the last ``since_s`` seconds, newest first.

    Each line: {"ts": ns, "labels": {...}, "line": str, "json": dict | None}.
    A metric query (count_over_time, …) returns Loki's matrix result as is.
    """
    end = time.time_ns()
    response = requests.get(
        f"{LOKI_URL}/loki/api/v1/query_range",
        params={
            "query": logql,
            "start": end - int(since_s * 1e9),
            "end": end,
            "limit": limit,
            "direction": "backward",
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()["data"]
    if data["resultType"] != "streams":
        return data["result"]
    rows = []
    for stream in data["result"]:
        for ts, line in stream["values"]:
            try:
                parsed = json.loads(line)
            except ValueError:
                parsed = None
            rows.append(
                {
                    "ts": int(ts),
                    "labels": stream["stream"],
                    "line": line,
                    "json": parsed if isinstance(parsed, dict) else None,
                }
            )
    rows.sort(key=lambda row: row["ts"], reverse=True)
    return rows


def loki_labels() -> set[str]:
    response = requests.get(f"{LOKI_URL}/loki/api/v1/labels", timeout=10)
    response.raise_for_status()
    return set(response.json().get("data") or [])


def wait_logs(logql: str, since_s: float = 300, timeout: float = 30, min_lines: int = 1) -> list:
    """Wait until a LogQL query returns at least ``min_lines`` lines; return them."""

    def enough():
        rows = loki_query(logql, since_s=since_s)
        return rows if len(rows) >= min_lines else None

    return wait_until(enough, timeout=timeout, interval=1, desc=f"logs {logql}")


# --- Tempo (S8) --------------------------------------------------------------

TEMPO_URL = os.environ.get("TEMPO_URL", "http://tempo:3200")


def tempo_search(traceql: str, since_s: float = 300, limit: int = 20) -> list[dict]:
    """Traces matching a TraceQL query over the last ``since_s`` seconds."""
    end = int(time.time()) + 1
    response = requests.get(
        f"{TEMPO_URL}/api/search",
        params={"q": traceql, "start": int(end - since_s) - 1, "end": end, "limit": limit},
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("traces") or []


def tempo_trace(trace_id: str) -> dict | None:
    """The whole trace in OTLP JSON, or None while Tempo does not have it yet."""
    response = requests.get(f"{TEMPO_URL}/api/traces/{trace_id}", timeout=20)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _hex_id(value: str) -> str:
    """Span and trace ids come as hex or as base64, depending on the API version."""
    if not value:
        return ""
    if len(value) in (16, 32) and all(c in "0123456789abcdef" for c in value.lower()):
        return value.lower()
    return base64.b64decode(value).hex()


def _attribute_value(value: dict):
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in value:
            return value[key]
    if "intValue" in value:
        return int(value["intValue"])
    return value


def _attributes(items: list[dict] | None) -> dict:
    return {item["key"]: _attribute_value(item.get("value", {})) for item in items or []}


_KINDS = {1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer"}
_STATUSES = {0: "unset", 1: "ok", 2: "error"}


def _kind(value) -> str:
    if isinstance(value, int):
        return _KINDS.get(value, "unspecified")
    return str(value or "").removeprefix("SPAN_KIND_").lower() or "unspecified"


def _status(status: dict | None) -> str:
    code = (status or {}).get("code", 0)
    if isinstance(code, int):
        return _STATUSES.get(code, "unset")
    return str(code).removeprefix("STATUS_CODE_").lower()


def trace_spans(trace: dict) -> list[dict]:
    """Every span of a trace as a flat dict: service, name, ids, duration, status, …"""
    batches = trace.get("batches") or trace.get("resourceSpans")
    if batches is None:
        batches = (trace.get("trace") or {}).get("resourceSpans", [])
    spans = []
    for batch in batches:
        service = _attributes(batch.get("resource", {}).get("attributes")).get("service.name")
        scopes = batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or []
        for scope in scopes:
            for span in scope.get("spans", []):
                start, end = int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"])
                spans.append(
                    {
                        "service": service,
                        "name": span["name"],
                        "span_id": _hex_id(span.get("spanId", "")),
                        "parent_span_id": _hex_id(span.get("parentSpanId", "")),
                        "kind": _kind(span.get("kind")),
                        "duration_ms": (end - start) / 1e6,
                        "status": _status(span.get("status")),
                        "attributes": _attributes(span.get("attributes")),
                        "events": [
                            {"name": e["name"], "attributes": _attributes(e.get("attributes"))}
                            for e in span.get("events", [])
                        ],
                    }
                )
    return spans


def wait_traces(traceql: str, since_s: float = 300, timeout: float = 30, min_traces: int = 1):
    """Wait until a TraceQL query finds at least ``min_traces`` traces; return them."""

    def enough():
        traces = tempo_search(traceql, since_s=since_s)
        return traces if len(traces) >= min_traces else None

    return wait_until(enough, timeout=timeout, interval=1, desc=f"traces {traceql}")
