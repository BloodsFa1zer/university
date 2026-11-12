"""Auth metrics (docs/00-common.md §6.9)."""

from prometheus_client import Counter

LOGINS = Counter("bank_auth_logins_total", "Login attempts by result", ["result"])
VERIFICATIONS = Counter(
    "bank_auth_verify_total", "Token checks made for the gateway, by result", ["result"]
)

for _result in ("success", "invalid_credentials"):
    LOGINS.labels(result=_result)
for _result in ("ok", "unauthorized", "forbidden"):
    VERIFICATIONS.labels(result=_result)
