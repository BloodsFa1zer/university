"""bank_generator.scenarios — S3-AC16: the table equals docs/00-common.md §6.6."""

from bank_generator.scenarios import SCENARIOS

# (hot accounts, share of 1 000 000.00 transfers, lock_order, lock_gap_ms, sleep_ms)
EXPECTED = {
    "normal": (None, 0.0, "sorted", 0, 0),
    "slow_queries": (None, 0.0, "sorted", 0, 800),
    "lock_contention": (3, 0.0, "sorted", 0, 400),
    "deadlocks": (4, 0.0, "naive", 150, 0),
    "failures": (None, 0.5, "sorted", 0, 0),
}
EXPECTED_ALERTS = {
    "normal": (),
    "slow_queries": ("TransferProcessingSlow", "QueueBacklog"),
    "lock_contention": ("LockWaiters", "TransferProcessingSlow"),
    "deadlocks": ("DeadlocksDetected",),
    "failures": ("TransferFailureRatioHigh",),
}
TITLES = {
    "normal": "Звичайний режим",
    "slow_queries": "Повільні запити",
    "lock_contention": "Конкуренція за блокування",
    "deadlocks": "Взаємні блокування",
    "failures": "Масові відмови",
}


def test_s03_ac16_scenario_table_matches_the_contract():
    actual = {
        name: (s.hot_accounts, s.big_amount_share, s.lock_order, s.lock_gap_ms, s.sleep_ms)
        for name, s in SCENARIOS.items()
    }
    assert actual == EXPECTED
    assert list(SCENARIOS) == list(EXPECTED)  # the order of the buttons


def test_s03_ac16_titles_and_expected_alerts():
    assert {name: s.title_uk for name, s in SCENARIOS.items()} == TITLES
    assert {name: s.expected_alerts for name, s in SCENARIOS.items()} == EXPECTED_ALERTS
    assert all(s.description_uk for s in SCENARIOS.values())
