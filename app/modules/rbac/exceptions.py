from app.common.exceptions import AuthorizationException


class PermissionDenied(AuthorizationException):
    """
    User does not have permission.
    """

    def __init__(self):
        super().__init__(
            "You do not have permission to perform this action."
        )