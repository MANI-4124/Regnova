from app.common.exceptions import (
    ConflictException,
    NotFoundException,
)


class UserNotFound(NotFoundException):

    def __init__(self):
        super().__init__("User not found.")


class UserAlreadyExists(ConflictException):

    def __init__(self):
        super().__init__("User already exists.")


class PermanentAdminProtected(ConflictException):
    """
    Raised when an update/delete would change role, deactivate or
    remove the permanent-admin ("CEO") account - refused unconditionally,
    regardless of who is calling.
    """

    def __init__(self):
        super().__init__(
            "This account is permanently protected and cannot have its "
            "role changed, be deactivated or be deleted."
        )