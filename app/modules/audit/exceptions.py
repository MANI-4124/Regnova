from app.common.exceptions import AuthorizationException


class AuditReaderNotAuthorized(AuthorizationException):
    """
    The caller holds none of the internal roles that grant any audit-log
    visibility tier at all (RA/Senior Reviewer/Knowledge Lead/Content
    Advisor -> customer-visible+internal-regulatory, Platform Admin ->
    technical-security, Auditor -> all three). Distinct from simply
    seeing zero rows - this is "not cleared for this endpoint at all",
    not "cleared, but nothing matched your filters".
    """

    def __init__(self):
        super().__init__(
            "You do not hold an internal role with any audit-log "
            "visibility tier."
        )
