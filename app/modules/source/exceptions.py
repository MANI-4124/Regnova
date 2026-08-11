from app.common.exceptions import NotFoundException


class SourceNotFound(NotFoundException):
    """
    Source does not exist.
    """

    def __init__(self):
        super().__init__(
            "Source not found."
        )
