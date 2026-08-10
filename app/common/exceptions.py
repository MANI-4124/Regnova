from __future__ import annotations


class AppException(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.error_code,
            "message": self.message,
        }


class NotFoundException(AppException):
    """
    Resource does not exist.
    """

    status_code = 404
    error_code = "NOT_FOUND"


class ConflictException(AppException):
    status_code = 409
    error_code = "CONFLICT"


class ValidationException(AppException):
    status_code = 400
    error_code = "VALIDATION_ERROR"


class AuthenticationException(AppException):
    status_code = 401
    error_code = "UNAUTHORIZED"


class AuthorizationException(AppException):
    status_code = 403
    error_code = "FORBIDDEN"