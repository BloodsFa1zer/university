"""bank_generator.state and the HTTP API on top of it — S3-AC16, S3-AC4 without a database."""

import re
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from bank_generator.api import create_app
from bank_generator.state import ControlState

T0 = datetime(2026, 11, 12, 10, 0, 0, tzinfo=UTC)

INVALID_PATCHES = [
    pytest.param({"scenario": "nope"}, "unknown scenario", id="unknown_scenario"),
    pytest.param({"rate": -1}, "rate", id="rate_negative"),
    pytest.param({"rate": 501}, "rate", id="rate_too_high"),
    pytest.param({"rate": True}, "rate", id="rate_bool"),
    pytest.param({"rate": "fast"}, "rate", id="rate_text"),
    pytest.param({"running": "yes"}, "running", id="running_text"),
    pytest.param({"scenario": "failures", "ttl_s": 3}, "ttl_s", id="ttl_too_short"),
    pytest.param({"scenario": "failures", "ttl_s": 3601}, "ttl_s", id="ttl_too_long"),
    pytest.param({"scenario": "failures", "ttl_s": 5.5}, "ttl_s", id="ttl_float"),
    pytest.param({"scenario": "normal", "ttl_s": 60}, "other than normal", id="ttl_with_normal"),
    pytest.param({"ttl_s": 60}, "other than normal", id="ttl_without_scenario"),
    pytest.param({"color": "red"}, "unknown fields", id="unknown_field"),
]


@pytest.fixture
def control() -> ControlState:
    return ControlState(rate=20, now=T0)


def test_s03_ac16_initial_state(control):
    assert control.snapshot() == {
        "scenario": "normal",
        "rate": 20.0,
        "running": True,
        "changed_at": "2026-11-12T10:00:00+00:00",
        "expires_at": None,
        "scenarios": ["normal", "slow_queries", "lock_contention", "deadlocks", "failures"],
    }


@pytest.mark.parametrize(("patch", "reason"), INVALID_PATCHES)
def test_s03_ac16_invalid_patch_changes_nothing(control, patch, reason):
    before = control.snapshot()
    with pytest.raises(ValueError, match=reason):
        control.apply(patch, T0 + timedelta(seconds=1))
    assert control.snapshot() == before


def test_s03_ac16_scenario_with_ttl_expires(control):
    state = control.apply({"scenario": "deadlocks", "ttl_s": 30}, T0)
    assert state["expires_at"] == "2026-11-12T10:00:30+00:00"
    assert control.expire(T0 + timedelta(seconds=29)) is False
    assert control.scenario == "deadlocks"
    assert control.expire(T0 + timedelta(seconds=30)) is True
    assert control.snapshot()["scenario"] == "normal"
    assert control.snapshot()["expires_at"] is None
    assert control.expire(T0 + timedelta(seconds=31)) is False


def test_s03_ac16_rate_change_keeps_scenario_and_expiry(control):
    control.apply({"scenario": "slow_queries", "ttl_s": 60}, T0)
    state = control.apply({"rate": 50}, T0 + timedelta(seconds=5))
    assert (state["scenario"], state["rate"]) == ("slow_queries", 50.0)
    assert state["expires_at"] == "2026-11-12T10:01:00+00:00"
    state = control.apply({"running": False}, T0 + timedelta(seconds=6))
    assert (state["scenario"], state["running"]) == ("slow_queries", False)


def test_s03_ac16_scenario_without_ttl_clears_expiry(control):
    control.apply({"scenario": "failures", "ttl_s": 60}, T0)
    assert control.apply({"scenario": "deadlocks"}, T0)["expires_at"] is None


# --- the API, with a fake database writer --------------------------------------


class Recorder:
    def __init__(self, fail: bool = False):
        self.saved, self.changes, self.fail = [], [], fail

    def save(self, scenario):
        if self.fail:
            raise psycopg.OperationalError("database is down")
        self.saved.append(scenario.name)

    def changed(self, state, patch):
        self.changes.append((state["scenario"], patch))


def client_for(control: ControlState, recorder: Recorder) -> TestClient:
    return TestClient(create_app(control, recorder.save, recorder.changed))


def test_s03_api_put_saves_settings_before_answering(control):
    recorder = Recorder()
    response = client_for(control, recorder).put(
        "/control/api/state", json={"scenario": "deadlocks", "ttl_s": 30}
    )
    assert response.status_code == 200
    assert response.json()["scenario"] == "deadlocks"
    assert recorder.saved == ["deadlocks"]
    assert recorder.changes == [("deadlocks", {"scenario": "deadlocks", "ttl_s": 30})]


@pytest.mark.parametrize(("patch", "reason"), INVALID_PATCHES)
def test_s03_ac4_api_rejects_invalid_body(control, patch, reason):
    recorder = Recorder()
    response = client_for(control, recorder).put("/control/api/state", json=patch)
    assert response.status_code == 422
    assert reason in response.json()["detail"]
    assert recorder.saved == [] and recorder.changes == []


def test_s03_ac4_api_rejects_non_object_body(control):
    response = client_for(control, Recorder()).put("/control/api/state", json=["normal"])
    assert response.status_code == 422


def test_s03_api_database_down_changes_nothing(control):
    recorder = Recorder(fail=True)
    response = client_for(control, recorder).put(
        "/control/api/state", json={"scenario": "failures"}
    )
    assert response.status_code == 503
    assert control.scenario == "normal"
    assert recorder.changes == []


def test_s03_api_page_health_and_metrics(control):
    client = client_for(control, Recorder())
    page = client.get("/control/")
    assert page.status_code == 200
    assert "Масові відмови" in page.text and "<!-- SCENARIO_BUTTONS -->" not in page.text
    assert len(re.findall(r'class="scenario"', page.text)) == 5
    assert client.get("/healthz").json() == {"status": "ok"}
    client.get("/control/api/state")
    client.get("/no/such/path")
    metrics = client.get("/metrics").text
    assert 'route="/control/api/state"' in metrics
    assert 'route="unmatched"' in metrics
    assert 'route="/metrics"' not in metrics and 'route="/healthz"' not in metrics
