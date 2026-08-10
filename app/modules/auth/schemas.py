from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class LoginRequest(BaseModel):
    """
    Login request payload.
    """

    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    """
    Refresh token request.
    """

    refresh_token: str


class TokenResponse(BaseModel):
    """
    JWT token response.
    """

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"


class ChangePasswordRequest(BaseModel):
    """
    Change password request.
    """

    current_password: str
    new_password: str


class CurrentUserResponse(BaseModel):
    """
    Current authenticated user.
    """

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    role_id: UUID

    first_name: str
    last_name: str

    email: EmailStr

    is_active: bool
    is_verified: bool