from __future__ import annotations

from app.common.exceptions import ConflictException


class MarketReadinessPreflightFailed(ConflictException):
    """
    Carries the full list of unmet prerequisites, not just the first one
    found - FR-05: "Preflight validates... it explains every unmet
    prerequisite." The shared AppException/global-handler contract only
    ever serializes a single `message` string (see
    app/common/handlers.py) - extending that shared envelope to carry a
    structured array was out of scope for this feature, so all failures
    are joined into one message rather than raising on the first. The
    full structured list is still available as `.failures` on the
    exception instance for anything (tests, a future handler extension)
    that wants it directly.
    """

    error_code = "MARKET_READINESS_PREFLIGHT_FAILED"

    def __init__(self, failures: list[dict[str, str]]):
        self.failures = failures
        joined = "; ".join(f"{failure['code']}: {failure['message']}" for failure in failures)
        super().__init__(f"Preflight failed: {joined}")
