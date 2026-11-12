"""bank_auth.security — S4-AC15."""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from bank_auth.security import (
    decode_token,
    hash_password,
    issue_token,
    password_too_long,
    safe_redirect,
    verify_password,
)

SECRET = "unit-test-secret-unit-test-secret-1234"


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", SECRET)
    monkeypatch.setenv("AUTH_TOKEN_TTL_S", "3600")


def test_s04_ac15_password_hashing():
    first = hash_password("s3cret-пароль")
    assert first.startswith("$2")
    assert verify_password("s3cret-пароль", first)
    assert not verify_password("s3cret-пароль!", first)
    assert hash_password("s3cret-пароль") != first  # a fresh salt every time
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_s04_ac15_password_length_is_counted_in_bytes():
    assert not password_too_long("a" * 72)
    assert password_too_long("a" * 73)
    assert password_too_long("ї" * 37)  # 74 bytes in UTF-8


def test_s04_ac15_token_roundtrip():
    # PyJWT refuses tokens issued in the future, so "now" must be a real moment.
    now = datetime.now(UTC) - timedelta(seconds=5)
    claims = decode_token(issue_token("admin", "admin", now=now))
    assert claims == {
        "sub": "admin",
        "role": "admin",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _claims(**changes) -> dict:
    now = int(datetime.now(UTC).timestamp())
    return {"sub": "admin", "role": "admin", "iat": now, "exp": now + 600, **changes}


def _tampered() -> str:
    header, payload, signature = issue_token("viewer", "viewer").split(".")
    forged_payload = _b64(_claims())  # claims to be admin, keeps the viewer's signature
    return f"{header}.{forged_payload}.{signature}"


@pytest.mark.parametrize(
    "make_token",
    [
        pytest.param(_tampered, id="tampered_payload"),
        pytest.param(
            lambda: jwt.encode(_claims(), "another-secret-another-secret-0000", algorithm="HS256"),
            id="other_key",
        ),
        pytest.param(
            lambda: f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(_claims())}.", id="alg_none"
        ),
        pytest.param(
            lambda: jwt.encode(
                _claims(
                    iat=int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
                    exp=int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
                ),
                SECRET,
                algorithm="HS256",
            ),
            id="expired",
        ),
        pytest.param(
            lambda: jwt.encode({"sub": "admin", "role": "admin"}, SECRET, algorithm="HS256"),
            id="no_expiry",
        ),
        pytest.param(
            lambda: jwt.encode(_claims(role="root"), SECRET, algorithm="HS256"), id="unknown_role"
        ),
        pytest.param(lambda: "not-a-token", id="garbage"),
    ],
)
def test_s04_ac15_bad_tokens_decode_to_none(make_token):
    assert decode_token(make_token()) is None


@pytest.mark.parametrize(
    ("rd", "expected"),
    [
        ("/control/", "/control/"),
        ("/grafana/d/bank-overview?orgId=1", "/grafana/d/bank-overview?orgId=1"),
        ("https://evil.example", "/grafana/"),
        ("//evil.example", "/grafana/"),
        ("/\\evil.example", "/grafana/"),
        ("/control//x", "/grafana/"),
        ("/control/\r\nSet-Cookie: x=1", "/grafana/"),
        ("control/", "/grafana/"),
        ("", "/grafana/"),
        (None, "/grafana/"),
    ],
)
def test_s04_ac15_safe_redirect(rd, expected):
    assert safe_redirect(rd) == expected
