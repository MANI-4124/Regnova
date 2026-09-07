from app.common.exceptions import ConflictException, NotFoundException, ValidationException


class DocumentVersionNotFound(NotFoundException):
    """
    Document version does not exist (or doesn't belong to this
    document/organization).
    """

    def __init__(self):
        super().__init__(
            "Document version not found."
        )


class DocumentVersionInvalidFileType(ValidationException):
    """
    The uploaded bytes don't match an allowed V1 format (C8.1), or
    don't match what the client claimed - see
    service.py:sniff_content_type.
    """

    def __init__(self, declared_content_type: str):
        super().__init__(
            f"Unsupported or mismatched file type: {declared_content_type!r}."
        )


class DocumentVersionTooLarge(ValidationException):
    """
    FR-04's V1 upload limit (100 MB unless configured).
    """

    def __init__(self, max_size_bytes: int):
        super().__init__(
            f"File exceeds the maximum allowed size of {max_size_bytes} bytes."
        )


class DocumentVersionNotEditable(ConflictException):
    """
    Fields can only be entered/corrected while the version is
    REVIEW_REQUIRED - mirrors ContentReviewWorkflow.require_editable's
    DRAFT-only-edit precedent: once verified/rejected/quarantined, a
    version's recorded fields are a historical record, not a live
    document to keep rewriting.
    """

    def __init__(self):
        super().__init__(
            "Fields can only be entered or corrected while the document "
            "version is REVIEW_REQUIRED."
        )


class DocumentVersionTransitionNotAllowed(ConflictException):
    """
    verify()/reject()/quarantine() are only reachable from
    REVIEW_REQUIRED - not from VERIFIED/REJECTED/QUARANTINED, and there
    is no un-quarantine/un-reject path in this pass (see CLAUDE.md).
    """

    def __init__(self):
        super().__init__(
            "This transition is only allowed while the document version "
            "is REVIEW_REQUIRED."
        )
