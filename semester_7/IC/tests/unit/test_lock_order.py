"""bank_worker.processor.order_accounts and the settings cache — S2-AC14."""

import pytest

from bank_worker.processor import order_accounts
from bank_worker.settings import ScenarioSettings, SettingsCache


@pytest.mark.parametrize(("from_account", "to_account"), [(1, 2), (2, 1), (200, 7), (7, 200)])
def test_s02_ac14_sorted_locks_smaller_id_first(from_account, to_account):
    expected = (min(from_account, to_account), max(from_account, to_account))
    assert order_accounts(from_account, to_account, "sorted") == expected


@pytest.mark.parametrize(("from_account", "to_account"), [(1, 2), (2, 1), (200, 7)])
def test_s02_ac14_naive_locks_sender_first(from_account, to_account):
    assert order_accounts(from_account, to_account, "naive") == (from_account, to_account)


def test_s02_ac14_unknown_lock_order_is_rejected():
    with pytest.raises(ValueError, match="random"):
        order_accounts(1, 2, "random")


class FakeConnection:
    """Returns the rows it is given, one per query, and counts the queries."""

    def __init__(self, *rows):
        self.rows = list(rows)
        self.queries = 0

    def execute(self, _query):
        self.queries += 1
        return self

    def fetchone(self):
        return self.rows.pop(0)


def test_s02_settings_cache_rereads_after_one_second():
    now = [100.0]
    conn = FakeConnection(("normal", "sorted", 0, 0), ("deadlocks", "naive", 150, 0))
    cache = SettingsCache(conn, clock=lambda: now[0])

    assert cache.get() == ScenarioSettings("normal", "sorted", 0, 0)
    now[0] += 0.5
    assert cache.get().scenario == "normal"  # still cached
    assert conn.queries == 1
    now[0] += 0.6
    assert cache.get() == ScenarioSettings("deadlocks", "naive", 150, 0)
    assert conn.queries == 2
