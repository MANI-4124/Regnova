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
    An active release already exists for this jurisdiction/category -
    see CLAUDE.md "Category scoping" for why this moved off jurisdiction/
    market.
    """

    def __init__(self):
        super().__init__(
            "An active regulatory basis release already exists for this "
            "jurisdiction/category. Set supersedes_id to that release's "
            "id to replace it."
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


class RegulatoryBasisReleaseVersionScopeMismatch(ConflictException):
    """
    A Requirement/Rule Version's own jurisdiction+category doesn't match
    this release's - see CLAUDE.md "Category scoping". Deliberately
    distinct from RegulatoryBasisReleaseIneligibleVersion (which is
    about lifecycle status/verification) rather than reused for it -
    these are two genuinely different reasons a version can't be
    included, and collapsing them would make the 409 body's message
    misleading for one case or the other.
    """

    def __init__(self):
        super().__init__(
            "Every included Requirement/Rule Version must match this "
            "release's jurisdiction and category exactly."
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
