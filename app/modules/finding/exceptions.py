from __future__ import annotations

from app.common.exceptions import AuthorizationException, ConflictException, NotFoundException


class FindingNotFound(NotFoundException):
    error_code = "FINDING_NOT_FOUND"

    def __init__(self):
        super().__init__("Finding not found")


class FindingTransitionNotAllowed(ConflictException):
    """
    The finding's current status doesn't accept this transition - e.g.
    trying to /respond a Finding that's still PROPOSED (respond() only
    accepts OPEN). Distinct from FindingTransitionNotAuthorized, which
    is about who is asking, not what state the finding is in.
    """

    error_code = "FINDING_TRANSITION_NOT_ALLOWED"

    def __init__(self, current_status: str, allowed: frozenset[str]):
        super().__init__(
            f"Finding is {current_status}; this action requires it to be one of "
            f"{sorted(allowed)}.",
        )


class FindingTransitionNotAuthorized(AuthorizationException):
    """
    The actor lacks the role/InternalRoleAssignment this specific
    transition requires. Deliberately checked against the finding's own
    organization and latest severity, not a static router-level
    require_* dependency - see CLAUDE.md "Finding review workflow".
    """

    error_code = "FINDING_TRANSITION_NOT_AUTHORIZED"

    def __init__(self):
        super().__init__(
            "You are not authorized to perform this transition on this finding.",
        )
