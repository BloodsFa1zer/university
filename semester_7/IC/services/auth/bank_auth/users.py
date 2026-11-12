"""Users in SQLite (docs/00-common.md §6.8). Each operation opens its own connection,
which keeps the store safe to use from the threads of the web server."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from bank_auth.security import ROLES, hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
  created_at TEXT NOT NULL
)"""


class UserExists(Exception):
    pass


@dataclass(frozen=True)
class User:
    username: str
    password_hash: str
    role: str


class UserStore:
    def __init__(self, path: str) -> None:
        self._path = path
        with self._connection() as conn:
            conn.execute(SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        try:
            with conn:  # commits on success, rolls back on an exception
                yield conn
        finally:
            conn.close()

    def get(self, username: str) -> User | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, password_hash, role FROM users WHERE username = ?", (username,)
            ).fetchone()
        return User(*row) if row else None

    def create(self, username: str, password: str, role: str) -> User:
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        user = User(username, hash_password(password), role)
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (user.username, user.password_hash, user.role, datetime.now(UTC).isoformat()),
                )
        except sqlite3.IntegrityError:
            raise UserExists(username) from None
        return user

    def ensure_seed(self, users: list[tuple[str, str, str]]) -> int:
        """Create the (username, password, role) users that do not exist yet.

        Existing users are left exactly as they are. Returns how many were created.
        """
        created = 0
        for username, password, role in users:
            if self.get(username) is None:
                self.create(username, password, role)
                created += 1
        return created

    def count(self) -> int:
        with self._connection() as conn:
            (count,) = conn.execute("SELECT count(*) FROM users").fetchone()
        return count
