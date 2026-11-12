"""What the generator does right now (docs/00-common.md §6.7). Pure logic, thread-safe."""

import threading
from datetime import datetime, timedelta

from bank_generator.scenarios import SCENARIOS

FIELDS = frozenset({"scenario", "rate", "running", "ttl_s"})
MAX_RATE = 500
MIN_TTL_S, MAX_TTL_S = 5, 3600


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat(timespec="seconds") if moment else None


class ControlState:
    """Scenario, rate and pause flag, changed by the API and read by the load loop."""

    def __init__(self, rate: float, now: datetime) -> None:
        self._lock = threading.Lock()
        self._scenario = "normal"
        self._rate = float(rate)
        self._running = True
        self._changed_at = now
        self._expires_at: datetime | None = None

    def validate(self, patch: dict) -> str:
        """Check a PUT body; return the scenario it leads to. Raise ValueError if invalid."""
        unknown = sorted(set(patch) - FIELDS)
        if unknown:
            raise ValueError(f"unknown fields: {', '.join(unknown)}")
        if "scenario" in patch and patch["scenario"] not in SCENARIOS:
            raise ValueError(
                f"unknown scenario {patch['scenario']!r}, use one of: {', '.join(SCENARIOS)}"
            )
        if "rate" in patch and not (_is_number(patch["rate"]) and 0 <= patch["rate"] <= MAX_RATE):
            raise ValueError(f"rate must be a number from 0 to {MAX_RATE}")
        if "running" in patch and not isinstance(patch["running"], bool):
            raise ValueError("running must be true or false")
        if "ttl_s" in patch:
            ttl = patch["ttl_s"]
            if (
                isinstance(ttl, bool)
                or not isinstance(ttl, int)
                or not MIN_TTL_S <= ttl <= MAX_TTL_S
            ):
                raise ValueError(f"ttl_s must be an integer from {MIN_TTL_S} to {MAX_TTL_S}")
            if patch.get("scenario", "normal") == "normal":
                raise ValueError("ttl_s needs a scenario other than normal in the same request")
        with self._lock:
            return patch.get("scenario", self._scenario)

    def apply(self, patch: dict, now: datetime) -> dict:
        """Validate and apply a PUT body; return the new state.

        Changing only `rate` or `running` keeps the scenario and its expiry.
        """
        self.validate(patch)
        with self._lock:
            if "scenario" in patch:
                self._scenario = patch["scenario"]
                ttl = patch.get("ttl_s")
                self._expires_at = now + timedelta(seconds=ttl) if ttl else None
            if "rate" in patch:
                self._rate = float(patch["rate"])
            if "running" in patch:
                self._running = patch["running"]
            self._changed_at = now
            return self._snapshot()

    def expire(self, now: datetime) -> bool:
        """Return to `normal` if the scenario's time is up; True if that happened."""
        with self._lock:
            if self._expires_at is None or now < self._expires_at:
                return False
            self._scenario = "normal"
            self._expires_at = None
            self._changed_at = now
            return True

    def current(self) -> tuple[str, float, bool]:
        """(scenario, rate, running) — cheap enough to call before every operation."""
        with self._lock:
            return self._scenario, self._rate, self._running

    @property
    def scenario(self) -> str:
        with self._lock:
            return self._scenario

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        return {
            "scenario": self._scenario,
            "rate": self._rate,
            "running": self._running,
            "changed_at": _iso(self._changed_at),
            "expires_at": _iso(self._expires_at),
            "scenarios": list(SCENARIOS),
        }
