"""bank_generator.engine.next_run_at — S3-AC16."""

import pytest

from bank_generator.engine import next_run_at


def test_s03_ac16_operations_are_evenly_spaced():
    due, now = 100.0, 100.0
    schedule = []
    for _ in range(5):
        due = next_run_at(due, now, rate=20)
        schedule.append(due)
        now = due + 0.001  # each operation takes 1 ms
    gaps = [later - earlier for earlier, later in zip(schedule, schedule[1:], strict=False)]
    assert gaps == pytest.approx([0.05] * 4)


def test_s03_ac16_small_lag_is_caught_up():
    # 0.5 s behind (less than max_lag): keep the schedule, run the next one right away.
    assert next_run_at(100.0, now=100.55, rate=20) == pytest.approx(100.05)


def test_s03_ac16_large_lag_restarts_the_schedule():
    # 5 s behind: no burst of 100 missed operations, start again from now.
    assert next_run_at(100.0, now=105.0, rate=20) == 105.0
