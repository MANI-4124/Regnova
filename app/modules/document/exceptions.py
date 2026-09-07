from app.common.exceptions import NotFoundException


class DocumentNotFound(NotFoundException):
    """
    Document does not exist (or does not belong to the caller's org).
    """

    def __init__(self):
        super().__init__(
            "Document not found."
        )
