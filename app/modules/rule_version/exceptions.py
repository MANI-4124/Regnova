from app.common.exceptions import NotFoundException


class RuleVersionNotFound(NotFoundException):
    """
    Rule version does not exist.
    """

    def __init__(self):
        super().__init__(
            "Rule version not found."
        )
