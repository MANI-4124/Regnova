from app.common.exceptions import ConflictException, NotFoundException


class OrganizationNotFound(NotFoundException):
    def __init__(self):
        super().__init__("Organization not found.")


class OrganizationAlreadyExists(ConflictException):
    def __init__(self):
        super().__init__("Organization already exists.")


class OrganizationHasAuditHistory(ConflictException):
    """
    RESTRICT, not CASCADE - see AuditEvent.organization_id's own
    docstring for why. A customer's compliance record must outlive
    their account (C15), so deleting the organization is refused
    outright while any AuditEvent still references it, rather than
    silently destroying that history along with the tenant.
    """

    def __init__(self):
        super().__init__(
            "This organization has audit history and cannot be deleted."
        )