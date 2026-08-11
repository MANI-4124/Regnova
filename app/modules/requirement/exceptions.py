from app.common.exceptions import NotFoundException


class RequirementNotFound(NotFoundException):
    """
    Requirement does not exist.
    """

    def __init__(self):
        super().__init__(
            "Requirement not found."
        )
