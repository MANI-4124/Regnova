from app.common.exceptions import NotFoundException


class RequirementVersionNotFound(NotFoundException):
    """
    Requirement version does not exist.
    """

    def __init__(self):
        super().__init__(
            "Requirement version not found."
        )
