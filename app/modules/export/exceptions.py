from __future__ import annotations

from app.common.exceptions import (
    AuthorizationException,
    ConflictException,
    NotFoundException,
    ValidationException,
)


class ExportNotFound(NotFoundException):
    def __init__(self):
        super().__init__("Export not found.")


class ExportNotReady(ConflictException):
    def __init__(self, status: str):
        super().__init__(f"Export is not ready for download (status: {status}).")


class ExportGenerationInvalidType(ValidationException):
    """
    Raised when a caller uses the wrong generation endpoint for the
    export_type they requested - POST /exports only accepts
    FINDINGS_CSV, POST /exports/internal only accepts
    EVIDENCE_PACK_JSON. Two endpoints, not one branching on a client-
    supplied type, exists specifically so the organization_id exception
    surface (see CLAUDE.md "Deliberate organization_id exceptions")
    stays structurally confined to the internal route.
    """

    def __init__(self, expected: str):
        super().__init__(f"This endpoint only generates {expected} exports.")


class ExportReaderNotAuthorized(AuthorizationException):
    def __init__(self):
        super().__init__(
            "This export requires INTERNAL_REGULATORY clearance or better "
            "(RA, Senior Reviewer, Regulatory Knowledge Lead, Content Advisor, or Auditor).",
        )


class ExportNoSnapshotAvailable(ConflictException):
    def __init__(self):
        super().__init__(
            "This Product x Market state has no State Snapshot yet - "
            "run a Market Readiness assessment before requesting an evidence pack.",
        )
