from app.common.exceptions import NotFoundException


class SourceVersionNotFound(NotFoundException):
    """
    Source version does not exist.
    """

    def __init__(self):
        super().__init__(
            "Source version not found."
        )
