from app.common.exceptions import NotFoundException, ValidationException


class AskRegnovaQuestionEmpty(ValidationException):
    """
    A blank/whitespace-only question - rejected before it ever reaches
    the classifier.
    """

    def __init__(self):
        super().__init__("Question must not be empty.")


class AskRegnovaQueryNotFound(NotFoundException):
    """
    Query history lookup for an id that doesn't exist (or doesn't
    belong to this organization) - same cross-org information-hiding
    convention as every other org-scoped module (404, not 403).
    """

    def __init__(self):
        super().__init__("Ask RegNova query not found.")
