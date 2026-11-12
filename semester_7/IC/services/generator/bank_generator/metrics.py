"""Generator metrics, the SQL probe's included (docs/00-common.md §6.9)."""

from prometheus_client import Counter, Gauge, Histogram

from bank_generator.scenarios import SCENARIOS
from bankmon_common.metrics import DURATION_BUCKETS

OPERATION_NAMES = ("transfer", "balance_check", "statement", "deposit")

OPERATIONS = Counter(
    "bank_generator_operations_total",
    "Client operations made by the generator",
    ["operation", "result"],
)
OPERATION_SECONDS = Histogram(
    "bank_generator_operation_duration_seconds",
    "Duration of a successful client operation",
    ["operation"],
    buckets=DURATION_BUCKETS,
)
TARGET_RATE = Gauge("bank_generator_target_rate", "Configured operations per second")
RUNNING = Gauge("bank_generator_running", "1 while the generator runs, 0 while paused")
SCENARIO_ACTIVE = Gauge(
    "bank_scenario_active", "1 for the active scenario, 0 for the others", ["scenario"]
)

# Filled by the SQL probe every 5 s.
LOCK_WAITERS = Gauge("bank_db_lock_waiters", "Sessions of the bank database waiting for a lock")
LONGEST_TRANSACTION = Gauge(
    "bank_db_longest_transaction_seconds", "Age of the oldest open transaction of other sessions"
)
TOTAL_BALANCE = Gauge("bank_db_accounts_total_balance", "SUM(balance) over all accounts")
PROBE_UP = Gauge("bank_db_probe_up", "1 if the last probe of the database succeeded")

for _operation in OPERATION_NAMES:
    for _result in ("ok", "error"):
        OPERATIONS.labels(operation=_operation, result=_result)


def publish_state(state: dict) -> None:
    """Mirror the control state into the gauges; all five scenario series always exist."""
    TARGET_RATE.set(state["rate"])
    RUNNING.set(1 if state["running"] else 0)
    for name in SCENARIOS:
        SCENARIO_ACTIVE.labels(scenario=name).set(1 if name == state["scenario"] else 0)
