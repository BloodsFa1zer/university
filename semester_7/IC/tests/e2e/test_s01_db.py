"""S1: PostgreSQL schema, seed, roles and server settings (docs/00-common.md §6.4)."""

import os
import uuid
from decimal import Decimal

import pytest
from psycopg import errors

from .helpers import check_invariants, db

APP_USER = os.environ["APP_DB_USER"]
MONITOR_USER = os.environ["MONITOR_DB_USER"]
TABLES = ("accounts", "transfers", "ledger_entries", "scenario_state")

TSTZ = "timestamp with time zone"
MONEY = "numeric(14,2)"

# (column, type, NOT NULL) in table order — copied from §6.4.
EXPECTED_COLUMNS = {
    "accounts": [
        ("id", "integer", True),
        ("owner_name", "text", True),
        ("balance", MONEY, True),
        ("created_at", TSTZ, True),
        ("updated_at", TSTZ, True),
    ],
    "transfers": [
        ("id", "uuid", True),
        ("from_account", "integer", True),
        ("to_account", "integer", True),
        ("amount", MONEY, True),
        ("status", "text", True),
        ("fail_reason", "text", False),
        ("attempts", "smallint", True),
        ("requested_at", TSTZ, True),
        ("processed_at", TSTZ, True),
    ],
    "ledger_entries": [
        ("id", "bigint", True),
        ("account_id", "integer", True),
        ("transfer_id", "uuid", False),
        ("kind", "text", True),
        ("delta", MONEY, True),
        ("created_at", TSTZ, True),
    ],
    "scenario_state": [
        ("id", "smallint", True),
        ("scenario", "text", True),
        ("lock_order", "text", True),
        ("lock_gap_ms", "integer", True),
        ("sleep_ms", "integer", True),
        ("updated_at", TSTZ, True),
    ],
}

# index name → (table, definition after "USING btree", unique)
EXPECTED_INDEXES = {
    "accounts_pkey": ("accounts", "(id)", True),
    "transfers_pkey": ("transfers", "(id)", True),
    "transfers_from_idx": ("transfers", "(from_account, processed_at DESC)", False),
    "transfers_to_idx": ("transfers", "(to_account, processed_at DESC)", False),
    "ledger_entries_pkey": ("ledger_entries", "(id)", True),
    "ledger_account_idx": ("ledger_entries", "(account_id, created_at DESC)", False),
    "scenario_state_pkey": ("scenario_state", "(id)", True),
}

EXPECTED_FOREIGN_KEYS = {
    ("transfers", "from_account", "accounts"),
    ("transfers", "to_account", "accounts"),
    ("ledger_entries", "account_id", "accounts"),
    ("ledger_entries", "transfer_id", "transfers"),
}

INSERT_TRANSFER = """
    INSERT INTO transfers (id, from_account, to_account, amount, status, fail_reason, requested_at)
    VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, now())
    RETURNING id"""

INSERT_SCENARIO = """
    INSERT INTO scenario_state (id, scenario, lock_order, lock_gap_ms, sleep_ms)
    VALUES (%s, 'normal', 'sorted', 0, 0)"""


# --- S1-AC1 ------------------------------------------------------------------


def test_s01_ac1_postgres_is_pinned_version():
    with db("app") as conn:
        (version,) = conn.execute("SHOW server_version").fetchone()
    assert version.startswith("17.11"), version


# --- S1-AC2: schema ----------------------------------------------------------


def test_s01_ac2_tables_and_columns():
    with db() as conn:
        rows = conn.execute("""
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY c.relname, a.attnum""").fetchall()
    actual: dict[str, list[tuple[str, str, bool]]] = {}
    for table, column, column_type, not_null in rows:
        actual.setdefault(table, []).append((column, column_type, not_null))
    assert actual == EXPECTED_COLUMNS


def test_s01_ac2_identity_columns():
    with db() as conn:
        rows = conn.execute("""
            SELECT c.relname, a.attname
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            WHERE a.attidentity = 'a'""").fetchall()
    assert set(rows) == {("accounts", "id"), ("ledger_entries", "id")}


def test_s01_ac2_indexes():
    with db() as conn:
        rows = conn.execute("""
            SELECT indexname, tablename, indexdef FROM pg_indexes
            WHERE schemaname = 'public'""").fetchall()
    actual = {
        name: (
            table,
            definition.split(" USING btree ", 1)[1],
            definition.startswith("CREATE UNIQUE"),
        )
        for name, table, definition in rows
    }
    assert actual == EXPECTED_INDEXES


def test_s01_ac2_foreign_keys():
    with db() as conn:
        rows = conn.execute("""
            SELECT src.relname, att.attname, ref.relname
            FROM pg_constraint con
            JOIN pg_class src ON src.oid = con.conrelid
            JOIN pg_class ref ON ref.oid = con.confrelid
            JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
            WHERE con.contype = 'f'""").fetchall()
    assert set(rows) == EXPECTED_FOREIGN_KEYS


@pytest.mark.parametrize(
    ("sql", "params", "error"),
    [
        pytest.param(
            "UPDATE accounts SET balance = -1 WHERE id = 1",
            None,
            errors.CheckViolation,
            id="negative_balance",
        ),
        pytest.param(
            INSERT_TRANSFER,
            (1, 1, Decimal("10"), "completed", None),
            errors.CheckViolation,
            id="same_account",
        ),
        pytest.param(
            INSERT_TRANSFER,
            (1, 2, Decimal("0"), "completed", None),
            errors.CheckViolation,
            id="zero_amount",
        ),
        pytest.param(
            INSERT_TRANSFER,
            (1, 2, Decimal("10"), "pending", None),
            errors.CheckViolation,
            id="unknown_status",
        ),
        pytest.param(
            INSERT_TRANSFER,
            (1, 2, Decimal("10"), "failed", None),
            errors.CheckViolation,
            id="failed_without_reason",
        ),
        pytest.param(
            INSERT_TRANSFER,
            (1, 2, Decimal("10"), "completed", "insufficient_funds"),
            errors.CheckViolation,
            id="completed_with_reason",
        ),
        pytest.param(
            INSERT_TRANSFER,
            (1, 999999, Decimal("10"), "completed", None),
            errors.ForeignKeyViolation,
            id="unknown_account",
        ),
        pytest.param(
            "INSERT INTO ledger_entries (account_id, kind, delta) VALUES (1, 'bonus', 1)",
            None,
            errors.CheckViolation,
            id="unknown_ledger_kind",
        ),
        pytest.param(INSERT_SCENARIO, (2,), errors.CheckViolation, id="second_scenario_row"),
        pytest.param(INSERT_SCENARIO, (1,), errors.UniqueViolation, id="duplicate_scenario_row"),
        pytest.param(
            "UPDATE scenario_state SET lock_order = 'random'",
            None,
            errors.CheckViolation,
            id="unknown_lock_order",
        ),
        pytest.param(
            "UPDATE scenario_state SET sleep_ms = -1",
            None,
            errors.CheckViolation,
            id="negative_sleep",
        ),
    ],
)
def test_s01_ac2_constraints(sql, params, error):
    # Every attempt runs in a transaction that is rolled back when the connection closes.
    with db() as conn, pytest.raises(error):
        conn.execute(sql, params)


# --- S1-AC3: seed and invariants ---------------------------------------------


def test_s01_ac3_seed_accounts():
    with db() as conn:
        rows = conn.execute("SELECT id, owner_name FROM accounts ORDER BY id").fetchall()
    assert [account_id for account_id, _ in rows] == list(range(1, 201))
    assert [name for _, name in rows] == [f"Клієнт {n:03d}" for n in range(1, 201)]


def test_s01_ac3_seed_opening_entries():
    with db() as conn:
        rows = conn.execute("""
            SELECT account_id, delta FROM ledger_entries
            WHERE kind = 'opening' ORDER BY account_id""").fetchall()
    assert [account_id for account_id, _ in rows] == list(range(1, 201))
    assert {delta for _, delta in rows} == {Decimal("10000.00")}


def test_s01_ac3_seed_scenario_state():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, scenario, lock_order, lock_gap_ms, sleep_ms FROM scenario_state"
        ).fetchall()
    assert rows == [(1, "normal", "sorted", 0, 0)]


def test_s01_ac3_invariants_hold():
    assert check_invariants() == []


@pytest.mark.parametrize(
    ("breakage", "invariant"),
    [
        pytest.param("UPDATE accounts SET balance = balance + 1 WHERE id = 1", "I1", id="I1"),
        pytest.param(
            "INSERT INTO ledger_entries (account_id, kind, delta) VALUES (1, 'transfer_in', 5)",
            "I2",
            id="I2",
        ),
        pytest.param(
            "INSERT INTO transfers (id, from_account, to_account, amount, status, requested_at)"
            " VALUES (gen_random_uuid(), 1, 2, 5, 'completed', now())",
            "I4",
            id="I4",
        ),
    ],
)
def test_s01_ac3_check_invariants_detects_violations(breakage, invariant):
    # The breakage is never committed: the checker sees it inside the same transaction.
    with db() as conn:
        conn.execute(breakage)
        violations = check_invariants(conn)
    assert any(v.startswith(invariant) for v in violations), violations


# --- S1-AC4: roles -----------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_s01_ac4_app_privilege_matrix(table):
    expected = {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": False, "TRUNCATE": False}
    with db() as conn:
        actual = {
            privilege: conn.execute(
                "SELECT has_table_privilege(%s, %s, %s)", (APP_USER, table, privilege)
            ).fetchone()[0]
            for privilege in expected
        }
    assert actual == expected


def test_s01_ac4_app_reads_and_writes_all_tables():
    with db("app") as conn:
        for table in TABLES:
            conn.execute(f"SELECT * FROM {table} LIMIT 1")
        (account_id,) = conn.execute(
            "INSERT INTO accounts (owner_name, balance) VALUES ('e2e', 0) RETURNING id"
        ).fetchone()
        (transfer_id,) = conn.execute(
            INSERT_TRANSFER, (199, 200, Decimal("1.00"), "completed", None)
        ).fetchone()
        conn.execute(
            "INSERT INTO ledger_entries (account_id, transfer_id, kind, delta)"
            " VALUES (%s, %s, 'transfer_out', -1)",
            (199, transfer_id),
        )
        conn.execute(
            "INSERT INTO scenario_state (id, scenario, lock_order, lock_gap_ms, sleep_ms)"
            " VALUES (1, 'normal', 'sorted', 0, 0) ON CONFLICT (id) DO NOTHING"
        )
        conn.execute("UPDATE accounts SET updated_at = now() WHERE id = %s", (account_id,))
        conn.execute("UPDATE transfers SET attempts = 2 WHERE id = %s", (transfer_id,))
        conn.execute("UPDATE ledger_entries SET delta = -1 WHERE transfer_id = %s", (transfer_id,))
        conn.execute("UPDATE scenario_state SET updated_at = now() WHERE id = 1")
    # Closing without commit rolls everything back; the seed must be untouched.
    assert check_invariants() == []


@pytest.mark.parametrize(
    "sql",
    [f"DELETE FROM {table} WHERE false" for table in TABLES]
    + [f"TRUNCATE {table}" for table in TABLES]
    + ["CREATE TABLE s01_must_fail (x integer)"],
)
def test_s01_ac4_app_cannot_delete_truncate_or_create(sql):
    with db("app") as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute(sql)


def test_s01_ac4_monitor_role_membership():
    with db() as conn:
        (is_member,) = conn.execute(
            "SELECT pg_has_role(%s, 'pg_monitor', 'member')", (MONITOR_USER,)
        ).fetchone()
    assert is_member is True


def test_s01_ac4_monitor_sees_query_text_of_other_sessions():
    marker = f"s01-marker-{uuid.uuid4().hex}"
    # The marker is part of the SQL text (a hex uuid, safe to inline): a bound
    # parameter would show up in pg_stat_activity as "$1", not as the value.
    app_query = f"SELECT '{marker}'::text"
    with db("app") as app_conn, db("monitor") as monitor_conn:
        app_conn.execute(app_query)
        rows = monitor_conn.execute(
            "SELECT usename, query FROM pg_stat_activity"
            " WHERE pid <> pg_backend_pid() AND query LIKE %s",
            (f"%{marker}%",),
        ).fetchall()
    assert rows == [(APP_USER, app_query)]


def test_s01_ac4_monitor_reads_accounts_but_cannot_write():
    with db("monitor") as conn:
        assert conn.execute("SELECT count(*) FROM accounts").fetchone() == (200,)
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("UPDATE accounts SET owner_name = owner_name WHERE id = 1")


# --- S1-AC5: server settings -------------------------------------------------

EXPECTED_SETTINGS = {
    "log_min_duration_statement": "200ms",
    "log_lock_waits": "on",
    "deadlock_timeout": "500ms",
    "track_io_timing": "on",
    "log_line_prefix": "%m [%p] %u@%d ",
}


def test_s01_ac5_server_settings():
    with db() as conn:
        actual = {name: conn.execute(f"SHOW {name}").fetchone()[0] for name in EXPECTED_SETTINGS}
        (libraries,) = conn.execute("SHOW shared_preload_libraries").fetchone()
    assert actual == EXPECTED_SETTINGS
    assert "pg_stat_statements" in libraries


def test_s01_ac5_pg_stat_statements_readable_by_monitor():
    with db("monitor") as conn:
        (count,) = conn.execute("SELECT count(*) FROM pg_stat_statements").fetchone()
    assert count > 0
