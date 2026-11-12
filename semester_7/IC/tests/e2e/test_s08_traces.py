"""S8: Tempo, OpenTelemetry and the links between metrics, logs and traces (§6.12)."""

import re
import time
from decimal import Decimal

import pytest
import requests

from .helpers import (
    ADMIN,
    AUTH_URL,
    TEMPO_URL,
    check_invariants,
    dashboard_files,
    db,
    gateway,
    grafana_api,
    loki_query,
    panel_exprs,
    prom_api,
    prom_value,
    publish_transfer,
    tempo_search,
    tempo_trace,
    trace_spans,
    wait_alert,
    wait_traces,
    wait_transfer,
    wait_until,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX16 = re.compile(r"^[0-9a-f]{16}$")
TRACES_PANELS = {
    "Повільні перекази",
    "Невдалі перекази",
    "Перекази з повторами",
    "Спани з помилками",
    "Корисні запити TraceQL",
}


def _since(started: float) -> float:
    return time.time() - started + 1


def _generator_transfer_id() -> str:
    """A transfer the generator made in the last seconds (tests use accounts 191…200)."""

    def recent():
        with db() as conn:
            row = conn.execute(
                """SELECT id FROM transfers
                   WHERE status = 'completed' AND from_account < 191 AND to_account < 191
                     AND processed_at > now() - interval '10 seconds'
                   ORDER BY processed_at DESC LIMIT 1"""
            ).fetchone()
        return str(row[0]) if row else None

    return wait_until(recent, timeout=30, desc="a fresh transfer made by the generator")


def _by_name(spans: list[dict], name: str) -> dict:
    (span,) = [s for s in spans if s["name"] == name]
    return span


def _descendants(spans: list[dict], root: dict) -> list[dict]:
    children = {}
    for span in spans:
        children.setdefault(span["parent_span_id"], []).append(span)
    found, stack = [], [root["span_id"]]
    while stack:
        for child in children.get(stack.pop(), []):
            found.append(child)
            stack.append(child["span_id"])
    return found


def _sql_spans(spans: list[dict]) -> list[dict]:
    return [
        s for s in spans if "db.system" in s["attributes"] or "db.system.name" in s["attributes"]
    ]


def _sql_text(span: dict) -> str:
    attributes = span["attributes"]
    return str(attributes.get("db.statement") or attributes.get("db.query.text") or span["name"])


def test_s08_ac1_tempo_is_ready_and_scraped():
    assert requests.get(f"{TEMPO_URL}/ready", timeout=5).status_code == 200
    wait_until(lambda: prom_value('up{job="tempo"}') == 1, timeout=60, desc="up{job=tempo}")


@pytest.fixture(scope="module")
def generator_transfer():
    """One transfer of the generator and its trace, shared by S8-AC2, AC3 and AC7."""
    transfer_id = _generator_transfer_id()
    (found,) = wait_traces(
        f'{{ span.bank.transfer_id = "{transfer_id}" }}', since_s=120, timeout=30
    )
    trace_id = found["traceID"]
    spans = trace_spans(tempo_trace(trace_id))
    return transfer_id, trace_id, spans


def test_s08_ac2_one_trace_from_generator_to_sql(generator_transfer):
    transfer_id, trace_id, spans = generator_transfer
    assert len(tempo_search(f'{{ span.bank.transfer_id = "{transfer_id}" }}', since_s=120)) == 1
    assert {"generator", "worker"} <= {s["service"] for s in spans}
    generator_span = _by_name(spans, "generator.transfer")
    worker_span = _by_name(spans, "worker.process_transfer")
    kinds = {s["kind"] for s in spans}
    assert {"producer", "consumer"} <= kinds, kinds
    assert len(_sql_spans(_descendants(spans, worker_span))) >= 5
    by_id = {s["span_id"]: s for s in spans}
    ancestor, ancestors = worker_span, []
    while ancestor["parent_span_id"] in by_id:
        ancestor = by_id[ancestor["parent_span_id"]]
        ancestors.append(ancestor["span_id"])
    assert generator_span["span_id"] in ancestors


def test_s08_ac3_span_attributes(generator_transfer):
    transfer_id, _trace_id, spans = generator_transfer
    worker_span = _by_name(spans, "worker.process_transfer")["attributes"]
    for key in (
        "bank.transfer_id",
        "bank.scenario",
        "bank.lock_order",
        "bank.status",
        "bank.attempts",
    ):
        assert key in worker_span, key
    assert worker_span["bank.transfer_id"] == transfer_id
    assert isinstance(worker_span["bank.attempts"], int)
    generator_span = _by_name(spans, "generator.transfer")["attributes"]
    for key in (
        "bank.transfer_id",
        "bank.from_account",
        "bank.to_account",
        "bank.amount",
        "bank.scenario",
    ):
        assert key in generator_span, key
    assert isinstance(generator_span["bank.from_account"], int)
    assert isinstance(generator_span["bank.amount"], str)


@pytest.mark.slow
def test_s08_ac4_failed_transfer_trace(scenario):
    started = time.time()
    scenario("failures")
    query = '{ span.bank.status = "failed" && span.bank.fail_reason = "insufficient_funds" }'
    found = wait_until(lambda: tempo_search(query, since_s=_since(started)), timeout=60, desc=query)
    spans = trace_spans(tempo_trace(found[0]["traceID"]))
    assert _by_name(spans, "worker.process_transfer")["status"] != "error"
    assert any(s["status"] == "error" for s in _sql_spans(spans))


@pytest.mark.slow
def test_s08_ac5_slow_transfer_trace(scenario):
    started = time.time()
    scenario("slow_queries")
    query = (
        '{ resource.service.name = "worker" && name = "worker.process_transfer"'
        " && duration > 700ms }"
    )
    found = wait_until(lambda: tempo_search(query, since_s=_since(started)), timeout=90, desc=query)
    spans = trace_spans(tempo_trace(found[0]["traceID"]))
    sleeps = [s for s in _sql_spans(spans) if "pg_sleep" in _sql_text(s)]
    assert sleeps and max(s["duration_ms"] for s in sleeps) >= 700


@pytest.mark.slow
def test_s08_ac6_retried_transfer_trace(scenario):
    started = time.time()
    scenario("deadlocks")
    query = "{ span.bank.attempts > 1 }"
    found = wait_until(
        lambda: tempo_search(query, since_s=_since(started)), timeout=120, desc=query
    )
    spans = trace_spans(tempo_trace(found[0]["traceID"]))
    events = {event["name"] for event in _by_name(spans, "worker.process_transfer")["events"]}
    assert "deadlock_retry" in events


def test_s08_ac7_log_line_carries_the_trace_id(generator_transfer):
    transfer_id, trace_id, _spans = generator_transfer
    rows = wait_until(
        lambda: loki_query(
            f'{{service="worker"}} |= "{transfer_id}" | json | event="transfer_completed"',
            since_s=300,
        ),
        timeout=30,
        desc="the transfer_completed line",
    )
    line = rows[0]["json"]
    assert line["trace_id"] == trace_id
    assert HEX16.match(line["span_id"])


def test_s08_ac8_data_sources_are_linked():
    loki = grafana_api("datasources/uid/loki").json()["jsonData"]
    assert any(f.get("datasourceUid") == "tempo" for f in loki.get("derivedFields", []))
    tempo = grafana_api("datasources/uid/tempo").json()["jsonData"]
    assert tempo["tracesToLogsV2"]["datasourceUid"] == "loki"
    prometheus = grafana_api("datasources/uid/prometheus").json()["jsonData"]
    assert any(
        d.get("datasourceUid") == "tempo" for d in prometheus.get("exemplarTraceIdDestinations", [])
    )
    health = grafana_api("datasources/uid/tempo/health")
    assert health.status_code == 200 and health.json()["status"] == "OK", health.text


def test_s08_ac9_exemplars_lead_to_traces():
    def exemplar_trace_ids() -> list[str]:
        now = time.time()
        data = prom_api(
            "query_exemplars",
            query="bank_transfer_processing_seconds_bucket",
            start=now - 300,
            end=now,
        )
        return [
            exemplar["labels"]["trace_id"]
            for series in data
            for exemplar in series["exemplars"]
            if "trace_id" in exemplar["labels"]
        ]

    trace_ids = wait_until(exemplar_trace_ids, timeout=60, desc="an exemplar with trace_id")
    assert HEX32.match(trace_ids[-1])
    wait_until(lambda: tempo_trace(trace_ids[-1]), timeout=30, desc="the exemplar's trace in Tempo")


def test_s08_ac10_auth_is_traced_but_not_its_health_checks():
    started = time.time()
    response = gateway().post(
        "/auth/token",
        json={"username": ADMIN[0], "password": ADMIN[1]},
    )
    assert response.status_code == 200
    wait_until(
        lambda: tempo_search('{ resource.service.name = "auth" }', since_s=_since(started)),
        timeout=30,
        desc="a trace of the auth service",
    )
    requests.get(f"{AUTH_URL}/healthz", timeout=5)
    requests.get(f"{AUTH_URL}/metrics", timeout=5)
    for route in ("/healthz", "/metrics"):
        query = f'{{ resource.service.name = "auth" && span.http.route = "{route}" }}'
        assert tempo_search(query, since_s=300) == [], route


def test_s08_ac12_traces_dashboard():
    dashboard = dashboard_files()["bank-traces"]
    assert dashboard["id"] is None and dashboard["refresh"] == "5s"
    assert "bankmonitor" in dashboard["tags"] and "${DS_" not in repr(dashboard)
    assert {panel["title"] for panel in dashboard["panels"]} == TRACES_PANELS
    for panel in dashboard["panels"]:
        assert re.search(r"[а-яіїєґ]", panel["title"], re.I)
        if panel["type"] != "text":
            assert panel["datasource"]["uid"] == "tempo", panel["title"]
    for title, source, query in panel_exprs(dashboard):
        assert source == "tempo", title
        tempo_search(query, since_s=900)  # raises if Tempo rejects the query
    found = grafana_api("search", params={"tag": "bankmonitor", "type": "dash-db"}).json()
    assert [d["folderTitle"] for d in found if d["uid"] == "bank-traces"] == ["BankMonitor"]


def test_s08_ac13_tracing_costs_little():
    wait_alert("TransferProcessingSlow", "inactive", timeout=180)
    p95_query = (
        "histogram_quantile(0.95, sum by (le) (rate(bank_transfer_processing_seconds_bucket[1m])))"
    )
    # Earlier tests ran slow scenarios: wait until the 1-minute window holds normal load only.
    wait_until(
        lambda: (p95 := prom_value(p95_query)) is not None and p95 < 0.1,
        timeout=150,
        interval=5,
        desc="p95 of the processing time under normal load to drop below 0.1 s",
    )
    assert check_invariants() == []


def test_s08_tracing_does_not_break_a_plain_transfer():
    transfer_id = publish_transfer(191, 192, Decimal("1.00"))
    assert wait_transfer(transfer_id)["status"] == "completed"
