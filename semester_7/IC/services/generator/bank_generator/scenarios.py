"""The load scenarios: docs/00-common.md §6.6 (parameters) and §11 (expected alerts)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    name: str
    title_uk: str
    description_uk: str
    hot_accounts: int | None  # transfers only between the first N accounts; None = all
    big_amount_share: float  # share of transfers for 1 000 000.00 (they always fail)
    lock_order: str  # what the worker applies: "sorted" | "naive"
    lock_gap_ms: int  # pause between locking the first and the second account
    sleep_ms: int  # pause after both accounts are locked
    expected_alerts: tuple[str, ...] = ()


SCENARIOS: dict[str, Scenario] = {
    scenario.name: scenario
    for scenario in (
        Scenario(
            "normal",
            "Звичайний режим",
            "Перекази між усіма рахунками на суми до 500 — система працює спокійно.",
            None,
            0.0,
            "sorted",
            0,
            0,
        ),
        Scenario(
            "slow_queries",
            "Повільні запити",
            "Кожна транзакція переказу триває щонайменше 0,8 с — worker не встигає, черга росте.",
            None,
            0.0,
            "sorted",
            0,
            800,
            ("TransferProcessingSlow", "QueueBacklog"),
        ),
        Scenario(
            "lock_contention",
            "Конкуренція за блокування",
            "Усі перекази — між трьома рахунками: транзакції стоять у черзі на блокування рядків.",
            3,
            0.0,
            "sorted",
            0,
            400,
            ("LockWaiters", "TransferProcessingSlow"),
        ),
        Scenario(
            "deadlocks",
            "Взаємні блокування",
            "Зустрічні перекази між чотирма рахунками блокують їх у різному порядку — "
            "PostgreSQL перериває одну з транзакцій.",
            4,
            0.0,
            "naive",
            150,
            0,
            ("DeadlocksDetected",),
        ),
        Scenario(
            "failures",
            "Масові відмови",
            "Половина переказів — на 1 000 000: коштів бракує, транзакції відкочуються.",
            None,
            0.5,
            "sorted",
            0,
            0,
            ("TransferFailureRatioHigh",),
        ),
    )
}

NORMAL = SCENARIOS["normal"]
