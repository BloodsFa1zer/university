"""The TransferRequested message, version 1 (docs/00-common.md §6.5)."""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

SCHEMA_VERSION = 1

# A positive decimal with at most two digits after the point: "250", "250.5", "250.00".
_AMOUNT_RE = re.compile(r"^\d+(\.\d{1,2})?$")


class InvalidMessage(ValueError):
    """The message body breaks the contract; the text says which rule."""


@dataclass(frozen=True)
class TransferRequested:
    transfer_id: uuid.UUID
    from_account: int
    to_account: int
    amount: Decimal
    requested_at: datetime
    scenario: str

    def encode(self) -> bytes:
        return json.dumps(
            {
                "schema": SCHEMA_VERSION,
                "transfer_id": str(self.transfer_id),
                "from_account": self.from_account,
                "to_account": self.to_account,
                "amount": f"{self.amount:.2f}",
                "requested_at": self.requested_at.isoformat(),
                "scenario": self.scenario,
            }
        ).encode()


def _account(data: dict, key: str) -> int:
    value = data.get(key)
    # bool is a subclass of int in Python, so it is excluded explicitly.
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InvalidMessage(f"{key} must be a positive integer, got {value!r}")
    return value


def decode(body: bytes) -> TransferRequested:
    """Parse and validate a message body; raise InvalidMessage on any violation."""
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidMessage("body is not JSON") from None
    if not isinstance(data, dict):
        raise InvalidMessage("body is not a JSON object")

    if data.get("schema") != SCHEMA_VERSION:
        raise InvalidMessage(f"unsupported schema {data.get('schema')!r}")

    raw_id = data.get("transfer_id")
    try:
        transfer_id = uuid.UUID(raw_id)
    except (TypeError, ValueError, AttributeError):
        raise InvalidMessage(f"transfer_id is not a UUID: {raw_id!r}") from None

    from_account = _account(data, "from_account")
    to_account = _account(data, "to_account")
    if from_account == to_account:
        raise InvalidMessage("from_account and to_account must be different")

    raw_amount = data.get("amount")
    if not isinstance(raw_amount, str) or not _AMOUNT_RE.match(raw_amount):
        raise InvalidMessage(f"amount must be a decimal string with 2 decimals, got {raw_amount!r}")
    amount = Decimal(raw_amount)
    if amount <= 0:
        raise InvalidMessage(f"amount must be greater than zero, got {raw_amount!r}")

    raw_time = data.get("requested_at")
    try:
        requested_at = datetime.fromisoformat(raw_time)
    except (TypeError, ValueError):
        raise InvalidMessage(f"requested_at is not an ISO 8601 time: {raw_time!r}") from None
    if requested_at.tzinfo is None:
        raise InvalidMessage("requested_at must include a time zone")

    scenario = data.get("scenario")
    if not isinstance(scenario, str):
        raise InvalidMessage(f"scenario must be a string, got {scenario!r}")

    return TransferRequested(transfer_id, from_account, to_account, amount, requested_at, scenario)
