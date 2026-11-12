"""S4: the auth service and the gateway (docs/00-common.md §6.2, §6.8).

Everything here goes through the gateway, the way a browser would.
"""

import base64
import json
import os
import re
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
import requests

from .helpers import (
    ADMIN,
    AUTH_URL,
    GATEWAY_URL,
    VIEWER,
    control_get,
    gateway,
    login,
    metric_value,
    token,
)

TTL = int(os.environ["AUTH_TOKEN_TTL_S"])
DEFAULT_RATE = float(os.environ["GEN_RATE"])
INVALID = "Невірний логін або пароль"


def _cookie_attributes(set_cookie: str) -> dict[str, str]:
    """{"httponly": "", "path": "/", ...} from a Set-Cookie header (names lower-cased)."""
    attributes = {}
    for part in set_cookie.split(";")[1:]:
        name, _, value = part.strip().partition("=")
        attributes[name.lower()] = value
    return attributes


def test_s04_ac2_public_routes():
    session = gateway()
    assert session.get("/healthz").status_code == 200
    root = session.get("/")
    assert (root.status_code, root.headers["Location"]) == (302, "/grafana/")
    assert session.get("/nope").status_code == 404


def test_s04_ac3_anonymous_requests_are_stopped():
    session = gateway()
    page = session.get("/control/")
    assert page.status_code == 302
    location = page.headers["Location"]
    assert location.startswith("/auth/login?rd=")
    assert parse_qs(urlparse(location).query)["rd"] == ["/control/"]

    api = session.get("/control/api/state")
    assert api.status_code == 401
    assert api.headers["Content-Type"].startswith("application/json")
    assert api.json() == {"detail": "Not authenticated"}


def test_s04_ac4_login_sets_a_session_cookie():
    session = gateway()
    response = session.post(
        "/auth/login", data={"username": ADMIN[0], "password": ADMIN[1], "rd": "/control/"}
    )
    assert (response.status_code, response.headers["Location"]) == (303, "/control/")
    set_cookie = response.headers["Set-Cookie"]
    assert set_cookie.startswith("bank_session=")
    attributes = _cookie_attributes(set_cookie)
    assert "httponly" in attributes
    assert attributes["samesite"].lower() == "lax"
    assert attributes["path"] == "/"
    assert attributes["max-age"] == str(TTL)
    assert session.get("/control/").status_code == 200
    assert session.get("/control/api/state").status_code == 200


def test_s04_ac5_wrong_password_and_unknown_user():
    labels = {"result": "invalid_credentials"}
    before = metric_value(AUTH_URL, "bank_auth_logins_total", labels)
    for username, password in [(ADMIN[0], "not-the-password"), ("no-such-user", "whatever")]:
        response = gateway().post("/auth/login", data={"username": username, "password": password})
        assert response.status_code == 401
        assert INVALID in response.text
        assert f'value="{username}"' in response.text  # the login stays in the field
        assert "Set-Cookie" not in response.headers
    assert metric_value(AUTH_URL, "bank_auth_logins_total", labels) >= before + 2


def test_s04_ac6_token_endpoint_and_bearer_header():
    response = gateway().post("/auth/token", json={"username": ADMIN[0], "password": ADMIN[1]})
    assert response.status_code == 200
    body = response.json()
    assert (body["token_type"], body["expires_in"]) == ("bearer", TTL)
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert (claims["sub"], claims["role"], claims["exp"] - claims["iat"]) == (
        ADMIN[0],
        "admin",
        TTL,
    )

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    put = gateway().put("/control/api/state", json={"rate": DEFAULT_RATE}, headers=headers)
    assert put.status_code == 200
    me = gateway().get("/auth/me", headers=headers)
    assert me.json() == {"username": ADMIN[0], "role": "admin"}


def test_s04_ac7_viewer_cannot_control_the_load():
    session = login(*VIEWER)
    assert session.get("/control/").status_code == 403
    before = control_get()
    assert session.put("/control/api/state", json={"scenario": "failures"}).status_code == 403
    assert control_get() == before


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _bad_tokens() -> dict[str, str]:
    good = token(*ADMIN)
    header, payload, signature = good.split(".")
    flipped = "A" if signature[10] != "A" else "B"
    now = int(time.time())
    claims = {"sub": ADMIN[0], "role": "admin", "iat": now, "exp": now + 600}
    secret = os.environ["AUTH_JWT_SECRET"]
    return {
        "tampered_signature": f"{header}.{payload}.{signature[:10]}{flipped}{signature[11:]}",
        "other_key": jwt.encode(claims, "another-secret-another-secret-0000", algorithm="HS256"),
        "alg_none": f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}.",
        "expired": jwt.encode(
            {**claims, "iat": now - 7200, "exp": now - 3600}, secret, algorithm="HS256"
        ),
    }


def test_s04_ac8_bad_tokens_are_rejected():
    for name, bad in _bad_tokens().items():
        response = gateway().get("/control/api/state", headers={"Authorization": f"Bearer {bad}"})
        assert response.status_code == 401, name


@pytest.mark.parametrize("rd", ["https://evil.example", "//evil.example", "/\\evil.example", ""])
def test_s04_ac9_login_never_redirects_elsewhere(rd):
    response = gateway().post(
        "/auth/login", data={"username": ADMIN[0], "password": ADMIN[1], "rd": rd}
    )
    assert (response.status_code, response.headers["Location"]) == (303, "/grafana/")


def test_s04_ac10_identity_headers_from_the_client_are_ignored():
    spoofed = {"X-Auth-User": ADMIN[0], "X-Auth-Role": "admin"}
    assert gateway().get("/control/api/state", headers=spoofed).status_code == 401
    assert login(*VIEWER).get("/control/api/state", headers=spoofed).status_code == 403


def test_s04_ac11_logout_ends_the_session():
    session = login(*ADMIN)
    response = session.get("/auth/logout")
    assert (response.status_code, response.headers["Location"]) == (303, "/auth/login")
    assert _cookie_attributes(response.headers["Set-Cookie"])["max-age"] == "0"
    assert session.get("/control/").status_code == 302


@pytest.mark.parametrize(
    "path",
    [
        "/auth/verify",
        "/auth/verify?require=admin",
        "/auth/metrics",
        "/auth/healthz",
        "/metrics",
        "/control/../metrics",
        "/control/%2e%2e/metrics",
        "/_auth/admin",
        "/_auth/any",
    ],
)
def test_s04_ac12_internal_paths_are_not_reachable(path):
    session = login(*ADMIN)  # not even for an administrator
    # A prepared request keeps the path exactly as written (no dot-segment cleanup).
    prepared = session.prepare_request(requests.Request("GET", GATEWAY_URL + "/x"))
    prepared.url = GATEWAY_URL + path
    response = session.send(prepared, allow_redirects=False, timeout=10)
    assert not (response.status_code == 200 and "bank_build_info" in response.text)
    assert response.status_code in (400, 404), response.status_code


def test_s04_ac13_seeded_users_can_log_in():
    # The restart itself is driven from the host (docs/10-app.md, S4 "Перевірка");
    # here: both seeded users can log in.
    for credentials in (ADMIN, VIEWER):
        assert login(*credentials).get("/auth/me").json()["username"] == credentials[0]


def test_s04_gateway_preserves_the_query_string_for_the_control_api():
    session = login(*ADMIN)
    response = session.get("/control/api/state?ignored=1")
    assert response.status_code == 200
    assert re.fullmatch(r"\d+\.\d+", str(response.json()["rate"]))
