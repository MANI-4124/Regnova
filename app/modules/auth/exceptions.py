from app.common.exceptions import AuthenticationException


class InvalidCredentials(AuthenticationException):
    """
    Invalid email or password.
    """

    def __init__(self):
        super().__init__(
            "Invalid email or password.",
        )


class InvalidToken(AuthenticationException):
    """
    Invalid JWT.
    """

    def __init__(self):
        super().__init__(
            "Invalid authentication token.",
        )


class ExpiredToken(AuthenticationException):
    """
    JWT expired.
    """

    def __init__(self):
        super().__init__(
            "Authentication token has expired.",
        )


class InactiveUser(AuthenticationException):
    """
    User disabled.
    """

    def __init__(self):
        super().__init__(
            "User account is inactive.",
        )