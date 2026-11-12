"""bankmon_common.messages — S2-AC14."""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bankmon_common.messages import InvalidMessage, TransferRequested, decode

MESSAGE = TransferRequested(
    transfer_id=uuid.UUID("5b0c9a3e-8f0e-4c59-9c9b-2f3f0d6f1a11"),
    from_account=17,
    to_account=142,
    amount=Decimal("250.00"),
    requested_at=datetime(2026, 11, 12, 10, 15, 30, 123456, tzinfo=UTC),
    scenario="normal",
)
REMOVE = object()


def body(**changes) -> bytes:
    data = json.loads(MESSAGE.encode())
    for key, value in changes.items():
        if value is REMOVE:
            del data[key]
        else:
            data[key] = value
    return json.dumps(data).encode()


def test_s02_ac14_roundtrip():
    assert decode(MESSAGE.encode()) == MESSAGE


def test_s02_ac14_encoded_form_matches_the_contract():
    assert json.loads(MESSAGE.encode()) == {
        "schema": 1,
        "transfer_id": "5b0c9a3e-8f0e-4c59-9c9b-2f3f0d6f1a11",
        "from_account": 17,
        "to_account": 142,
        "amount": "250.00",
        "requested_at": "2026-11-12T10:15:30.123456+00:00",
        "scenario": "normal",
    }


@pytest.mark.parametrize("amount", ["1", "1.5", "0.01", "999999.99"])
def test_s02_ac14_valid_amounts(amount):
    assert decode(body(amount=amount)).amount == Decimal(amount)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        pytest.param(b"not json", "not JSON", id="not_json"),
        pytest.param(b"\xff\xfe", "not JSON", id="not_utf8"),
        pytest.param(b"[1, 2]", "JSON object", id="not_object"),
        pytest.param(body(schema=REMOVE), "schema", id="schema_missing"),
        pytest.param(body(schema=2), "schema", id="schema_2"),
        pytest.param(body(transfer_id="abc"), "transfer_id", id="transfer_id_text"),
        pytest.param(body(transfer_id=123), "transfer_id", id="transfer_id_number"),
        pytest.param(body(from_account="17"), "from_account", id="from_string"),
        pytest.param(body(from_account=0), "from_account", id="from_zero"),
        pytest.param(body(from_account=-1), "from_account", id="from_negative"),
        pytest.param(body(from_account=True), "from_account", id="from_bool"),
        pytest.param(body(from_account=1.5), "from_account", id="from_float"),
        pytest.param(body(to_account=REMOVE), "to_account", id="to_missing"),
        pytest.param(body(to_account=17), "different", id="same_account"),
        pytest.param(body(amount=250), "amount", id="amount_number"),
        pytest.param(body(amount="-5.00"), "amount", id="amount_negative"),
        pytest.param(body(amount="0.00"), "amount", id="amount_zero"),
        pytest.param(body(amount="1.234"), "amount", id="amount_3_decimals"),
        pytest.param(body(amount="1e3"), "amount", id="amount_exponent"),
        pytest.param(body(amount="abc"), "amount", id="amount_text"),
        pytest.param(body(requested_at=REMOVE), "requested_at", id="time_missing"),
        pytest.param(body(requested_at="yesterday"), "requested_at", id="time_text"),
        pytest.param(body(requested_at="2026-11-12T10:15:30"), "time zone", id="time_naive"),
        pytest.param(body(scenario=5), "scenario", id="scenario_number"),
    ],
)
def test_s02_ac14_invalid_messages(raw, reason):
    with pytest.raises(InvalidMessage, match=reason):
        decode(raw)
