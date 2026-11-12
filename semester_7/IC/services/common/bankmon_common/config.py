"""Typed access to environment variables.

A variable that is unset or set to an empty string counts as missing.
``default=None`` means the variable is required: if it is missing,
``RuntimeError`` names it, so a misconfigured container fails at start-up
with a clear message instead of somewhere deep in the code.
"""

import os
from collections.abc import Callable

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _read[T](name: str, default: T | None, convert: Callable[[str], T], kind: str) -> T:
    raw = os.environ.get(name, "")
    if raw == "":
        if default is None:
            raise RuntimeError(f"environment variable {name} is required but not set")
        return default
    try:
        return convert(raw)
    except ValueError:
        raise RuntimeError(f"environment variable {name} must be {kind}, got {raw!r}") from None


def _to_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(raw)


def env_str(name: str, default: str | None = None) -> str:
    return _read(name, default, str, "a string")


def env_int(name: str, default: int | None = None) -> int:
    return _read(name, default, int, "an integer")


def env_float(name: str, default: float | None = None) -> float:
    return _read(name, default, float, "a number")


def env_bool(name: str, default: bool | None = None) -> bool:
    return _read(name, default, _to_bool, "one of 1/0, true/false, yes/no, on/off")
