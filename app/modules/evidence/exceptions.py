from app.common.exceptions import ConflictException, NotFoundException


class EvidenceNotFound(NotFoundException):
    """
    Evidence link does not exist (or does not belong to the caller's
    org).
    """

    def __init__(self):
        super().__init__(
            "Evidence not found."
        )


class EvidenceDocumentVersionNotVerified(ConflictException):
    """
    AC-FR-04-01's compensating control for V1 - see CLAUDE.md "Document
    storage and versioning". No malware scanner exists yet; this check
    is NOT a substitute scan result, only the closest available
    stand-in: a human must have cleared the file to VERIFIED before it
    may be linked as evidence for anything.
    """

    def __init__(self):
        super().__init__(
            "Only a VERIFIED document version may be linked as evidence."
        )


class EvidenceAlreadyLinked(ConflictException):
    """
    This exact (document_version, product, requirement_version)
    combination is already linked.
    """

    def __init__(self):
        super().__init__(
            "This document version is already linked as evidence for "
            "this product/requirement combination."
        )
