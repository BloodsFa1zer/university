"""Worker metrics (docs/00-common.md §6.9)."""

from prometheus_client import Counter, Gauge, Histogram

from bankmon_common.metrics import DURATION_BUCKETS, E2E_BUCKETS

TRANSFERS_PROCESSED = Counter(
    "bank_transfers_processed_total",
    "Transfers recorded by the worker, by final status and failure reason",
    ["status", "reason"],
)
PROCESSING_SECONDS = Histogram(
    "bank_transfer_processing_seconds",
    "Time to process one message, retries included",
    ["status"],
    buckets=DURATION_BUCKETS,
)
E2E_SECONDS = Histogram(
    "bank_transfer_e2e_seconds",
    "Time from requested_at to the end of processing",
    buckets=E2E_BUCKETS,
)
RETRIES = Counter(
    "bank_transfer_retries_total",
    "Transfer attempts repeated after an error",
    ["reason"],
)
DB_ERRORS = Counter(
    "bank_worker_db_errors_total",
    "Database errors by SQLSTATE, expected ones (deadlock, check violation) included",
    ["sqlstate"],
)
DEAD_LETTERED = Counter(
    "bank_worker_messages_dead_lettered_total",
    "Messages rejected to the dead-letter queue",
)
DUPLICATES = Counter(
    "bank_worker_duplicates_total",
    "Messages for transfers that were already recorded",
)
IN_FLIGHT = Gauge("bank_worker_in_flight", "Messages being processed right now")

# Create the expected series up front, so dashboards and alerts see zeros instead of gaps.
for _status, _reason in (
    ("completed", "none"),
    ("failed", "insufficient_funds"),
    ("failed", "deadlock"),
):
    TRANSFERS_PROCESSED.labels(status=_status, reason=_reason)
for _status in ("completed", "failed"):
    PROCESSING_SECONDS.labels(status=_status)
RETRIES.labels(reason="deadlock")
