"""Routes of the auth service (docs/00-common.md §6.8)."""

import html
import logging
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from bank_auth import metrics
from bank_auth.security import (
    COOKIE_NAME,
    decode_token,
    hash_password,
    issue_token,
    password_too_long,
    safe_redirect,
    token_ttl_s,
    verify_password,
)
from bank_auth.users import User, UserStore
from bankmon_common.http import add_health_and_metrics, instrument_app
from bankmon_common.logging import log_event

logger = logging.getLogger(__name__)

LOGIN_TEMPLATE = (Path(__file__).parent / "templates" / "login.html").read_text(encoding="utf-8")
INVALID_CREDENTIALS = "Невірний логін або пароль"
GRAFANA_ROLES = {"admin": "Admin", "viewer": "Viewer"}


class Credentials(BaseModel):
    username: str
    password: str


def render_login(rd: str = "", username: str = "", error: bool = False) -> str:
    message = f'<p class="error" role="alert">{INVALID_CREDENTIALS}</p>' if error else ""
    return (
        LOGIN_TEMPLATE.replace("{{error}}", message)
        .replace("{{username}}", html.escape(username))
        .replace("{{rd}}", html.escape(rd))
    )


def claims_from(request: Request) -> dict | None:
    """The claims of the token in `Authorization: Bearer …` or, failing that, in the cookie."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return decode_token(header[7:].strip())
    cookie = request.cookies.get(COOKIE_NAME)
    return decode_token(cookie) if cookie else None


def create_app(store: UserStore) -> FastAPI:
    app = FastAPI(title="BankMonitor auth", docs_url=None, redoc_url=None, openapi_url=None)
    instrument_app(app)
    add_health_and_metrics(app)
    # Unknown users are checked against this hash too, so the response time does not
    # tell whether a login exists.
    dummy_hash = hash_password("no such user")

    def authenticate(username: str, password: str) -> User | None:
        if password_too_long(password):
            raise HTTPException(status_code=422, detail="password longer than 72 bytes")
        user = store.get(username)
        if user is None:
            verify_password(password, dummy_hash)
            return None
        return user if verify_password(password, user.password_hash) else None

    def record_login(username: str, user: User | None) -> None:
        if user is None:
            metrics.LOGINS.labels(result="invalid_credentials").inc()
            log_event(logger, "warning", "login_failed", "Login failed", username=username)
        else:
            metrics.LOGINS.labels(result="success").inc()
            log_event(
                logger,
                "info",
                "login_succeeded",
                "Login succeeded",
                username=user.username,
                role=user.role,
            )

    @app.get("/auth/login", response_class=HTMLResponse)
    def login_form(rd: str = "") -> str:
        return render_login(rd=rd)

    @app.post("/auth/login")
    def login(
        username: Annotated[str, Form()] = "",
        password: Annotated[str, Form()] = "",
        rd: Annotated[str, Form()] = "",
    ) -> Response:
        user = authenticate(username, password)
        record_login(username, user)
        if user is None:
            return HTMLResponse(render_login(rd, username, error=True), status_code=401)
        response = RedirectResponse(safe_redirect(rd), status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            issue_token(user.username, user.role),
            max_age=token_ttl_s(),
            path="/",
            httponly=True,
            samesite="lax",
        )
        return response

    @app.post("/auth/token")
    def token(credentials: Credentials) -> dict:
        user = authenticate(credentials.username, credentials.password)
        record_login(credentials.username, user)
        if user is None:
            raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)
        return {
            "access_token": issue_token(user.username, user.role),
            "token_type": "bearer",
            "expires_in": token_ttl_s(),
        }

    @app.get("/auth/me")
    def me(request: Request) -> Response:
        claims = claims_from(request)
        if claims is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return JSONResponse({"username": claims["sub"], "role": claims["role"]})

    @app.get("/auth/logout")
    def logout() -> Response:
        response = RedirectResponse("/auth/login", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
        return response

    @app.get("/auth/verify")
    def verify(request: Request, require: str | None = None) -> Response:
        """Asked by the gateway (nginx auth_request) before every protected request."""
        if require not in (None, "admin"):
            return Response(status_code=400)  # a gateway misconfiguration, never a pass
        claims = claims_from(request)
        if claims is None:
            metrics.VERIFICATIONS.labels(result="unauthorized").inc()
            return Response(status_code=401)
        if require == "admin" and claims["role"] != "admin":
            metrics.VERIFICATIONS.labels(result="forbidden").inc()
            return Response(status_code=403)
        metrics.VERIFICATIONS.labels(result="ok").inc()
        return Response(
            status_code=200,
            headers={
                "X-Auth-User": claims["sub"],
                "X-Auth-Role": claims["role"],
                "X-Auth-Grafana-Role": GRAFANA_ROLES[claims["role"]],
            },
        )

    return app
