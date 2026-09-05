from __future__ import annotations

from app.common.exceptions import AuthorizationException, ConflictException


class ContentVersionTransitionNotAllowed(ConflictException):
    """
    The content version's current status doesn't accept this
    transition - e.g. trying to verify() a version that's still DRAFT
    (verify() only accepts IN_REVIEW). Distinct from
    ContentVersionTransitionNotAuthorized, which is about who is
    asking, not what state the version is in.
    """

    error_code = "CONTENT_VERSION_TRANSITION_NOT_ALLOWED"

    def __init__(self, current_status: str, allowed: frozenset[str]):
        super().__init__(
            f"Content version is {current_status}; this action requires it to be "
            f"one of {sorted(allowed)}.",
        )


class UnknownContentType(ConflictException):
    """
    A bulk-verify/bulk-activate item named a content_type that isn't in
    the registry, or a content_id that doesn't resolve to any row of
    that type. Deliberately a 409-family "can't act on this item", not
    a 404 for the whole request - a bulk call's other items may still
    be perfectly valid.
    """

    error_code = "UNKNOWN_CONTENT_TYPE_OR_ID"

    def __init__(self, content_type: str, content_id):
        super().__init__(
            f"No {content_type!r} content version found for id {content_id}.",
        )


class ContentVersionTransitionNotAuthorized(AuthorizationException):
    """
    The actor lacks the role this specific transition requires -
    drafting/submitting needs REGULATORY_CONTENT_ADVISOR or
    REGULATORY_KNOWLEDGE_LEAD; verify/activate/reject need
    REGULATORY_KNOWLEDGE_LEAD specifically. Checked in the service
    layer, not only via the router dependency - see CLAUDE.md
    "Regulatory content approval workflow".
    """

    error_code = "CONTENT_VERSION_TRANSITION_NOT_AUTHORIZED"

    def __init__(self):
        super().__init__(
            "You are not authorized to perform this transition on this content version.",
        )
