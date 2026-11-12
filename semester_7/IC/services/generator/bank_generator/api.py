"""HTTP API and the control page (docs/00-common.md §6.7)."""

import html
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import psycopg
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from bank_generator.scenarios import SCENARIOS, Scenario
from bank_generator.state import ControlState
from bankmon_common.http import add_health_and_metrics, instrument_app

PAGE_TEMPLATE = Path(__file__).parent / "static" / "control.html"
PLACEHOLDER = "<!-- SCENARIO_BUTTONS -->"


def _scenario_button(scenario: Scenario) -> str:
    alerts = ", ".join(scenario.expected_alerts) or "немає"
    return (
        f'<button type="button" class="scenario" data-scenario="{scenario.name}">'
        f'<span class="title">{html.escape(scenario.title_uk)}</span>'
        f'<span class="desc">{html.escape(scenario.description_uk)}</span>'
        f'<span class="alerts">Очікувані алерти: {html.escape(alerts)}</span>'
        "</button>"
    )


def render_control_page() -> str:
    """The page with one button per scenario, built from the scenario table."""
    buttons = "\n".join(_scenario_button(s) for s in SCENARIOS.values())
    return PAGE_TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, buttons)


def create_app(
    control: ControlState,
    save_settings: Callable[[Scenario], None],
    on_change: Callable[[dict, dict], None],
) -> FastAPI:
    """``save_settings`` writes scenario_state; ``on_change(state, patch)`` runs after a change."""
    app = FastAPI(title="BankMonitor generator", docs_url=None, redoc_url=None, openapi_url=None)
    instrument_app(app)
    add_health_and_metrics(app)
    page = render_control_page()

    @app.get("/control/", response_class=HTMLResponse)
    def control_page() -> str:
        return page

    @app.get("/control/api/state")
    def get_state() -> dict:
        return control.snapshot()

    @app.put("/control/api/state")
    def put_state(patch: Annotated[dict[str, Any], Body()]) -> dict:
        try:
            target = control.validate(patch)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        # The worker reads its settings from the database: write them first, so a
        # 200 means the switch has really happened.
        try:
            save_settings(SCENARIOS[target])
        except psycopg.Error as exc:
            raise HTTPException(
                status_code=503, detail="database unavailable, nothing changed"
            ) from exc
        state = control.apply(patch, datetime.now(UTC))
        on_change(state, patch)
        return state

    return app
