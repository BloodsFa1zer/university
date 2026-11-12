"""bank_auth.users — S4-AC15."""

import sqlite3

import pytest

from bank_auth.security import verify_password
from bank_auth.users import UserExists, UserStore


@pytest.fixture
def store(tmp_path) -> UserStore:
    return UserStore(str(tmp_path / "auth.db"))


def test_s04_ac15_create_and_get(store):
    store.create("anna", "pass-1234", "viewer")
    user = store.get("anna")
    assert (user.username, user.role) == ("anna", "viewer")
    assert verify_password("pass-1234", user.password_hash)
    assert store.get("nobody") is None


def test_s04_ac15_usernames_are_unique(store):
    store.create("anna", "pass-1234", "viewer")
    with pytest.raises(UserExists):
        store.create("anna", "other", "admin")
    assert store.count() == 1


def test_s04_ac15_unknown_role_is_refused(store):
    with pytest.raises(ValueError, match="role"):
        store.create("anna", "pass-1234", "root")


def test_s04_ac15_seed_creates_only_missing_users(store):
    seed = [("admin", "admin-pass", "admin"), ("viewer", "viewer-pass", "viewer")]
    assert store.ensure_seed(seed) == 2
    hash_before = store.get("admin").password_hash
    # A second start with a different password in .env must not overwrite the user.
    assert store.ensure_seed([("admin", "changed", "admin"), *seed[1:]]) == 0
    assert store.get("admin").password_hash == hash_before
    assert store.count() == 2


def test_s04_ac15_passwords_are_stored_hashed(tmp_path):
    path = str(tmp_path / "auth.db")
    UserStore(path).create("anna", "plain-text-password", "viewer")
    rows = sqlite3.connect(path).execute("SELECT password_hash, created_at FROM users").fetchall()
    (password_hash, created_at) = rows[0]
    assert password_hash.startswith("$2") and "plain-text-password" not in password_hash
    assert created_at


def test_s04_ac15_data_survives_a_new_store_on_the_same_file(tmp_path):
    path = str(tmp_path / "auth.db")
    UserStore(path).create("anna", "pass-1234", "viewer")
    assert UserStore(path).get("anna") is not None
