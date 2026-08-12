from app.common.exceptions import ConflictException, NotFoundException


class RegulatoryBasisReleaseNotFound(NotFoundException):
    """
    Regulatory basis release does not exist.
    """

    def __init__(self):
        super().__init__(
            "Regulatory basis release not found."
        )


class RegulatoryBasisReleaseAlreadyActive(ConflictException):
    """
    An active release already exists for this jurisdiction/market.
    """

    def __init__(self):
        super().__init__(
            "An active regulatory basis release already exists for this "
            "jurisdiction/market. Set supersedes_id to that release's id "
            "to replace it."
        )


class RegulatoryBasisReleaseIneligibleVersion(ConflictException):
    """
    A version referenced for inclusion is not ACTIVE + verified.
    """

    def __init__(self):
        super().__init__(
            "Only ACTIVE, verified versions may be included in a "
            "regulatory basis release."
        )


class RegulatoryBasisReleaseDuplicateContent(ConflictException):
    """
    Another release with the exact same content_hash already exists.
    """

    def __init__(self):
        super().__init__(
            "A release with this exact set of included versions and "
            "configuration already exists (content_hash collision)."
        )
