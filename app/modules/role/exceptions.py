from app.common.exceptions import (
    ConflictException,
    NotFoundException,
)


class RoleNotFound(NotFoundException):

    def __init__(self):
        super().__init__("Role not found.")


class RoleAlreadyExists(ConflictException):

    def __init__(self):
        super().__init__("Role already exists.")