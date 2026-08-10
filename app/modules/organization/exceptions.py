from app.common.exceptions import ConflictException, NotFoundException


class OrganizationNotFound(NotFoundException):
    def __init__(self):
        super().__init__("Organization not found.")


class OrganizationAlreadyExists(ConflictException):
    def __init__(self):
        super().__init__("Organization already exists.")