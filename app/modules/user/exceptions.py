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