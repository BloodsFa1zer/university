"""bank_auth.api through FastAPI's test client — S4-AC15."""

import pytest
from fastapi.testclient import TestClient

from bank_auth.api import create_app
from bank_auth.users import UserStore

SECRET = "unit-test-secret-unit-test-secret-1234"
ADMIN = ("admin", "admin-pass")
VIEWER = ("viewer", "viewer-pass")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("AUTH_JWT_SECRET", SECRET)
        patch.setenv("AUTH_TOKEN_TTL_S", "3600")
        store = UserStore(str(tmp_path_factory.mktemp("auth") / "auth.db"))
        store.ensure_seed([(*ADMIN, "admin"), (*VIEWER, "viewer")])
        yield create_app(store)


@pytest.fixture
def client(app, monkeypatch) -> TestClient:
    monkeypatch.setenv("AUTH_JWT_SECRET", SECRET)
    monkeypatch.setenv("AUTH_TOKEN_TTL_S", "3600")
    return TestClient(app, follow_redirects=False)


def _login(client, username, password, rd=""):
    return client.post("/auth/login", data={"username": username, "password": password, "rd": rd})


def test_s04_ac15_login_form_is_ukrainian_and_escapes_rd(client):
    page = client.get("/auth/login", params={"rd": '"><script>x</script>'})
    assert page.status_code == 200
    for text in ("Вхід до BankMonitor", "Логін", "Пароль", "Увійти"):
        assert text in page.text
    assert "<script>x</script>" not in page.text
    assert "&quot;&gt;&lt;script&gt;" in page.text


def test_s04_ac15_successful_login(client):
    response = _login(client, *ADMIN, rd="/control/")
    assert (response.status_code, response.headers["location"]) == (303, "/control/")
    cookie = response.headers["set-cookie"].lower()
    for attribute in ("bank_session=", "httponly", "samesite=lax", "path=/", "max-age=3600"):
        assert attribute in cookie


def test_s04_ac15_failed_login_keeps_the_username(client):
    response = _login(client, "admin<b>", "wrong")
    assert response.status_code == 401
    assert "Невірний логін або пароль" in response.text
    assert 'value="admin&lt;b&gt;"' in response.text
    assert "set-cookie" not in response.headers


def test_s04_ac15_over_long_password_is_refused(client):
    assert _login(client, "admin", "a" * 73).status_code == 422
    response = client.post("/auth/token", json={"username": "admin", "password": "a" * 73})
    assert response.status_code == 422


def test_s04_ac15_token_and_me(client):
    response = client.post("/auth/token", json={"username": ADMIN[0], "password": ADMIN[1]})
    assert response.status_code == 200
    bearer = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/auth/me", headers=bearer).json() == {"username": "admin", "role": "admin"}
    assert client.get("/auth/me").status_code == 401
    wrong = client.post("/auth/token", json={"username": "admin", "password": "nope"})
    assert wrong.status_code == 401


def test_s04_ac15_verify(client):
    assert client.get("/auth/verify").status_code == 401

    _login(client, *VIEWER)  # the client keeps the cookie
    ok = client.get("/auth/verify")
    assert ok.status_code == 200
    assert (ok.headers["x-auth-user"], ok.headers["x-auth-role"]) == ("viewer", "viewer")
    assert ok.headers["x-auth-grafana-role"] == "Viewer"
    assert client.get("/auth/verify", params={"require": "admin"}).status_code == 403
    assert client.get("/auth/verify", params={"require": "root"}).status_code == 400

    _login(client, *ADMIN)
    admin = client.get("/auth/verify", params={"require": "admin"})
    assert (admin.status_code, admin.headers["x-auth-grafana-role"]) == (200, "Admin")


def test_s04_ac15_bearer_header_wins_over_the_cookie(client):
    _login(client, *VIEWER)
    response = client.post("/auth/token", json={"username": ADMIN[0], "password": ADMIN[1]})
    bearer = {"Authorization": f"Bearer {response.json()['access_token']}"}
    verified = client.get("/auth/verify", params={"require": "admin"}, headers=bearer)
    assert verified.status_code == 200


def test_s04_ac15_logout_clears_the_cookie(client):
    _login(client, *ADMIN)
    response = client.get("/auth/logout")
    assert (response.status_code, response.headers["location"]) == (303, "/auth/login")
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_s04_ac15_metrics(client):
    _login(client, "admin", "wrong")
    _login(client, *ADMIN)
    metrics = client.get("/metrics").text
    assert 'bank_auth_logins_total{result="invalid_credentials"}' in metrics
    assert 'bank_auth_logins_total{result="success"}' in metrics
    assert "bank_auth_verify_total" in metrics
