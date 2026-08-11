from app.common.exceptions import NotFoundException


class SourceLocationNotFound(NotFoundException):
    """
    Source location does not exist.
    """

    def __init__(self):
        super().__init__(
            "Source location not found."
        )
