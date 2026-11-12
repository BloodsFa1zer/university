"""S6: Grafana behind the gateway and the four dashboards (docs/00-common.md §6.13)."""

import base64
import os
import re
from urllib.parse import urlparse

import pytest

from .helpers import (
    ADMIN,
    VIEWER,
    dashboard_files,
    gateway,
    grafana_api,
    login,
    panel_exprs,
    prom_query,
    prom_value,
    wait_until,
)

STAGE_DASHBOARDS = {
    "bank-overview": "BankMonitor — огляд",
    "bank-db": "PostgreSQL",
    "bank-app": "Застосунок: перекази",
    "bank-queue": "RabbitMQ",
}
PANELS = {
    "bank-overview": {
        "Сервіси в роботі",
        "Транзакцій БД за секунду",
        "Переказів за секунду",
        "Частка відмов",
        "p95 обробки переказу",
        "Черга переказів",
        "Сесій чекають блокування",
        "Взаємних блокувань за хвилину",
        "Сценарій",
        "Активні алерти",
        "Перекази за статусом",
        "Час обробки: p50, p95, p99",
        "Глибина черги",
        "Блокування: очікування і взаємні блокування",
    },
    "bank-db": {
        "Зʼєднання за станом",
        "Використання ліміту зʼєднань",
        "Транзакції: підтверджені й відкочені",
        "Рядки: вставлено, оновлено, прочитано",
        "Взаємні блокування",
        "Блокування за режимом",
        "Сесії, що чекають блокування",
        "Найдовша транзакція",
        "Частка влучань у кеш",
        "Розмір бази",
        "Рядків у таблицях",
        "Сума балансів",
        "Найважчі запити",
    },
    "bank-app": {
        "Операції генератора за типом",
        "Помилки операцій генератора",
        "p95 тривалості операцій генератора",
        "Перекази за статусом і причиною",
        "Час обробки: p50, p95, p99",
        "Час від заявки до завершення: p95",
        "Повтори після взаємного блокування",
        "Помилки БД за кодом SQLSTATE",
        "Перекази в обробці",
        "Відхилені повідомлення",
        "Входи: успішні й невдалі",
        "HTTP-запити за статусом",
    },
    "bank-queue": {
        "Повідомлення в чергах",
        "Не підтверджені повідомлення",
        "Споживачі",
        "Опубліковано й оброблено за секунду",
        "Мертві повідомлення",
    },
}
# Empty when nothing is wrong — the one panel allowed to have no data (S6-AC6).
MAY_BE_EMPTY = {"Активні алерти"}


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def _org_role(session) -> tuple[str, str]:
    user = session.get("/grafana/api/user").json()
    (org,) = [o for o in session.get("/grafana/api/user/orgs").json() if o["orgId"] == 1]
    return user["login"], org["role"]


def test_s06_ac1_grafana_is_healthy_behind_the_gateway():
    health = login(*ADMIN).get("/grafana/api/health")
    assert health.status_code == 200 and health.json()["database"] == "ok"


def test_s06_ac2_users_and_roles_come_from_auth():
    viewer = login(*VIEWER)
    assert _org_role(viewer) == (VIEWER[0], "Viewer")
    saved = viewer.post(
        "/grafana/api/dashboards/db",
        json={"dashboard": {"title": "viewer-test", "panels": []}, "overwrite": False},
    )
    assert saved.status_code == 403
    assert _org_role(login(*ADMIN)) == (ADMIN[0], "Admin")


def test_s06_ac3_identity_cannot_be_forged():
    forged = {"X-WEBAUTH-USER": ADMIN[0], "X-WEBAUTH-ROLE": "Admin"}
    anonymous = gateway().get("/grafana/api/user", headers=forged)
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"].startswith("/auth/login?rd=")

    viewer = login(*VIEWER)
    assert _org_role_with(viewer, forged) == (VIEWER[0], "Viewer")
    internal_admin = {
        "Authorization": _basic(
            os.environ["GF_SECURITY_ADMIN_USER"], os.environ["GF_SECURITY_ADMIN_PASSWORD"]
        )
    }
    assert _org_role_with(viewer, internal_admin) == (VIEWER[0], "Viewer")


def _org_role_with(session, headers: dict) -> tuple[str, str]:
    user = session.get("/grafana/api/user", headers=headers).json()
    orgs = session.get("/grafana/api/user/orgs", headers=headers).json()
    (org,) = [o for o in orgs if o["orgId"] == 1]
    return user["login"], org["role"]


def test_s06_ac4_prometheus_data_source():
    source = grafana_api("datasources/uid/prometheus").json()
    assert (source["type"], source["isDefault"]) == ("prometheus", True)
    health = grafana_api("datasources/uid/prometheus/health")
    assert health.status_code == 200 and health.json()["status"] == "OK", health.text


def test_s06_ac5_dashboards_are_provisioned():
    found = grafana_api("search", params={"tag": "bankmonitor", "type": "dash-db"}).json()
    by_uid = {d["uid"]: d for d in found}
    for uid, title in STAGE_DASHBOARDS.items():
        assert uid in by_uid, uid
        assert by_uid[uid]["title"] == title
        assert by_uid[uid]["folderTitle"] == "BankMonitor"
    # The organisation's home dashboard is set by the one-shot grafana-init service.
    assert grafana_api("org/preferences").json()["homeDashboardUID"] == "bank-overview"
    viewer = login(*VIEWER)
    home = viewer.get("/grafana/api/dashboards/home").json()
    assert "/d/bank-overview/" in home["redirectUri"], home
    assert viewer.get("/grafana/api/dashboards/uid/bank-overview").status_code == 200


QUERIES = [
    pytest.param(uid, title, expr, id=f"{uid}:{title}:{i}")
    for uid, dashboard in dashboard_files().items()
    for i, (title, source, expr) in enumerate(panel_exprs(dashboard))
    if source == "prometheus"
]


@pytest.mark.parametrize(("uid", "title", "expr"), QUERIES)
def test_s06_ac6_every_panel_query_returns_data(uid, title, expr):
    if title in MAY_BE_EMPTY:
        prom_query(expr)  # must still be a valid query
        return
    wait_until(lambda: prom_query(expr), timeout=60, interval=2, desc=f"{uid} / {title}: {expr}")


@pytest.mark.parametrize("uid", list(STAGE_DASHBOARDS))
def test_s06_ac7_dashboard_json_hygiene(uid):
    dashboard = dashboard_files()[uid]
    text = repr(dashboard)
    assert dashboard["uid"] == uid and dashboard["id"] is None
    assert dashboard["title"] == STAGE_DASHBOARDS[uid]
    assert "__inputs" not in dashboard and "${DS_" not in text
    assert "bankmonitor" in dashboard["tags"]
    assert dashboard["refresh"] == "5s"
    assert dashboard["time"] == {"from": "now-15m", "to": "now"}
    for panel in dashboard["panels"]:
        assert re.search(r"[а-яіїєґʼ]", panel["title"], re.I), panel["title"]
        assert panel["datasource"]["uid"] == "prometheus", panel["title"]
        for target in panel["targets"]:
            assert target["datasource"]["uid"] == "prometheus", panel["title"]
        if panel["type"] == "timeseries":
            assert panel["fieldConfig"]["defaults"].get("unit"), panel["title"]


@pytest.mark.parametrize("uid", list(STAGE_DASHBOARDS))
def test_s06_ac8_dashboards_have_the_planned_panels(uid):
    titles = {panel["title"] for panel in dashboard_files()[uid]["panels"]}
    assert titles == PANELS[uid]


def test_s06_ac9_grafana_is_scraped():
    wait_until(lambda: prom_value('up{job="grafana"}') == 1, timeout=60, desc="up{job=grafana}")


def test_s06_ac10_dashboard_page_stays_inside_the_site():
    session = login(*VIEWER)
    path = "/grafana/d/bank-overview"
    for _ in range(5):
        response = session.get(path)
        if response.status_code not in (301, 302, 303, 307, 308):
            break
        # Grafana may answer with an absolute URL built from root_url: check its path.
        location = urlparse(response.headers["Location"])
        assert location.path.startswith(("/grafana/", "/auth/")), location
        path = location.path + (f"?{location.query}" if location.query else "")
    assert response.status_code == 200
    assert "<html" in response.text.lower()
