"""Passwords, tokens and redirects (docs/00-common.md §6.8)."""

from datetime import UTC, datetime

import bcrypt
import jwt

from bankmon_common.config import env_int, env_str

ALGORITHM = "HS256"
ROLES = ("admin", "viewer")
COOKIE_NAME = "bank_session"
DEFAULT_REDIRECT = "/grafana/"
# bcrypt only looks at the first 72 bytes of a password; longer ones are refused, not cut.
MAX_PASSWORD_BYTES = 72


def token_ttl_s() -> int:
    return env_int("AUTH_TOKEN_TTL_S", 3600)


def _secret() -> str:
    return env_str("AUTH_JWT_SECRET")


def password_too_long(password: str) -> bool:
    return len(password.encode()) > MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # a malformed hash or an over-long password
        return False


def issue_token(username: str, role: str, now: datetime | None = None) -> str:
    issued = int((now or datetime.now(UTC)).timestamp())
    claims = {"sub": username, "role": role, "iat": issued, "exp": issued + token_ttl_s()}
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """The claims of a valid token, or None for anything else (never raises).

    The algorithm list is fixed, so a token with "alg": "none" or any other
    algorithm is rejected instead of being trusted.
    """
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "role", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None
    if claims["role"] not in ROLES:
        return None
    return claims


def safe_redirect(rd: str | None) -> str:
    """Where to go after login: only a local path, so the form cannot send users elsewhere."""
    if rd and rd.startswith("/") and "//" not in rd and "\\" not in rd and rd.isprintable():
        return rd
    return DEFAULT_REDIRECT
