from enum import Enum


class Permission(str, Enum):
    """
    Application permissions.
    """

    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_WRITE = "organization:write"

    ROLE_READ = "role:read"
    ROLE_WRITE = "role:write"

    USER_READ = "user:read"
    USER_WRITE = "user:write"

    AUTH_MANAGE = "auth:manage"

    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"