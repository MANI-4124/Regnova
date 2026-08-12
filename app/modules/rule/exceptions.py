from app.common.exceptions import NotFoundException


class RuleNotFound(NotFoundException):
    """
    Rule does not exist.
    """

    def __init__(self):
        super().__init__(
            "Rule not found."
        )
