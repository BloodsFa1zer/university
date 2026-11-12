"""bankmon_common.config — S0-AC3."""

import pytest

from bankmon_common.config import env_bool, env_float, env_int, env_str

VAR = "BANKMON_TEST_VAR"


@pytest.fixture(autouse=True)
def clean_var(monkeypatch):
    monkeypatch.delenv(VAR, raising=False)


def test_s00_ac3_str_returns_value(monkeypatch):
    monkeypatch.setenv(VAR, "hello")
    assert env_str(VAR) == "hello"
    assert env_str(VAR, "fallback") == "hello"


def test_s00_ac3_str_default_when_missing():
    assert env_str(VAR, "fallback") == "fallback"


def test_s00_ac3_empty_counts_as_missing(monkeypatch):
    monkeypatch.setenv(VAR, "")
    assert env_str(VAR, "fallback") == "fallback"
    with pytest.raises(RuntimeError, match=VAR):
        env_str(VAR)


@pytest.mark.parametrize("reader", [env_str, env_int, env_float, env_bool])
def test_s00_ac3_missing_required_names_the_variable(reader):
    with pytest.raises(RuntimeError, match=VAR):
        reader(VAR)


def test_s00_ac3_int(monkeypatch):
    monkeypatch.setenv(VAR, "42")
    assert env_int(VAR) == 42


def test_s00_ac3_falsy_defaults_are_returned():
    # 0 and False are real defaults, not "required".
    assert env_int(VAR, 0) == 0
    assert env_float(VAR, 0.0) == 0.0
    assert env_bool(VAR, False) is False


def test_s00_ac3_invalid_int_names_the_variable(monkeypatch):
    monkeypatch.setenv(VAR, "forty-two")
    with pytest.raises(RuntimeError, match=VAR):
        env_int(VAR, 1)


def test_s00_ac3_float(monkeypatch):
    monkeypatch.setenv(VAR, "0.25")
    assert env_float(VAR) == 0.25
    monkeypatch.setenv(VAR, "fast")
    with pytest.raises(RuntimeError, match=VAR):
        env_float(VAR)


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " True "])
def test_s00_ac3_bool_true(monkeypatch, raw):
    monkeypatch.setenv(VAR, raw)
    assert env_bool(VAR) is True


@pytest.mark.parametrize("raw", ["0", "false", "False", "no", "off"])
def test_s00_ac3_bool_false(monkeypatch, raw):
    monkeypatch.setenv(VAR, raw)
    assert env_bool(VAR) is False


def test_s00_ac3_bool_invalid(monkeypatch):
    monkeypatch.setenv(VAR, "maybe")
    with pytest.raises(RuntimeError, match=VAR):
        env_bool(VAR, True)
