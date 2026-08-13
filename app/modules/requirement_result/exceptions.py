from __future__ import annotations

from app.common.exceptions import ValidationException


class InvalidRequirementResultOutcome(ValidationException):
    """
    outcome must belong to the closed vocabulary for whichever
    RuleOutputType produced it - APPLICABILITY's four-value set or
    REQUIREMENT_RESULT's satisfaction set. The column itself stays a
    plain string; this is a service-layer invariant, not a DB constraint.
    """

    error_code = "INVALID_REQUIREMENT_RESULT_OUTCOME"

    def __init__(self, outcome: str, allowed: frozenset[str]):
        super().__init__(
            f"{outcome!r} is not a valid outcome for this output_type "
            f"(expected one of {sorted(allowed)})",
        )
