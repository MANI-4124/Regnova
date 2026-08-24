from __future__ import annotations

from app.common.exceptions import ConflictException, NotFoundException, ValidationException


class InternalRoleAssignmentNotFound(NotFoundException):
    error_code = "INTERNAL_ROLE_ASSIGNMENT_NOT_FOUND"

    def __init__(self):
        super().__init__("Internal role assignment not found")


class TenantZeroNotConfigured(ConflictException):
    error_code = "TENANT_ZERO_NOT_CONFIGURED"

    def __init__(self):
        super().__init__(
            "No organization is configured as RegNova's internal "
            "(tenant-zero) organization yet.",
        )


class TargetUserNotInternal(ValidationException):
    error_code = "TARGET_USER_NOT_INTERNAL"

    def __init__(self):
        super().__init__(
            "This user does not belong to RegNova's internal "
            "organization - customer-org accounts cannot hold an "
            "internal role.",
        )


class InvalidInternalRoleCode(ValidationException):
    error_code = "INVALID_INTERNAL_ROLE_CODE"

    def __init__(self, role_code: str, valid: frozenset[str]):
        super().__init__(
            f"{role_code!r} is not a recognized internal role code "
            f"(valid: {sorted(valid)})",
        )


class ScopeNotAllowedForRole(ValidationException):
    error_code = "SCOPE_NOT_ALLOWED_FOR_ROLE"

    def __init__(self, role_code: str):
        super().__init__(
            f"scope is only meaningful for PLATFORM_ADMIN, not {role_code!r}.",
        )


class AssignmentNotPending(ConflictException):
    error_code = "ASSIGNMENT_NOT_PENDING"

    def __init__(self, status: str):
        super().__init__(f"This assignment is {status}, not PROPOSED - it cannot be decided.")


class AssignmentNotActive(ConflictException):
    error_code = "ASSIGNMENT_NOT_ACTIVE"

    def __init__(self, status: str):
        super().__init__(f"This assignment is {status}, not APPROVED - it cannot be revoked.")


class RevocationAlreadyPending(ConflictException):
    error_code = "REVOCATION_ALREADY_PENDING"

    def __init__(self):
        super().__init__("A revocation proposal is already pending for this assignment.")


class NoRevocationPending(ConflictException):
    error_code = "NO_REVOCATION_PENDING"

    def __init__(self):
        super().__init__("No revocation proposal is pending for this assignment.")
