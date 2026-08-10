from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.user.models import User
from app.modules.user.repository import UserRepository

from .exceptions import (
    InactiveUser,
    InvalidCredentials,
)
from .jwt import (
    create_access_token,
    create_refresh_token,
)
from .schemas import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    TokenResponse,
)
from .security import (
    hash_password,
    verify_password,
)


class AuthService:
    """
    Authentication business logic.
    """

    def __init__(
        self,
        db: Session,
    ):
        self.db = db
        self.users = UserRepository(db)

    def login(
        self,
        payload: LoginRequest,
    ) -> TokenResponse:
        """
        Authenticate a user and return JWT tokens.
        """

        user = self.users.get_by_email_global(
            payload.email,
        )

        if user is None:
            raise InvalidCredentials()

        if not verify_password(
            payload.password,
            user.password_hash,
        ):
            raise InvalidCredentials()

        if not user.is_active:
            raise InactiveUser()

        user.last_login = datetime.now(
            timezone.utc,
        )

        self.users.update_last_login(user)

        self.db.commit()

        access_token = create_access_token(
            subject=str(user.id),
            additional_claims={
                "organization_id": str(
                    user.organization_id,
                ),
                "role_id": str(
                    user.role_id,
                ),
            },
        )

        refresh_token = create_refresh_token(
            subject=str(user.id),
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def me(
        self,
        user: User,
    ) -> CurrentUserResponse:
        """
        Return current authenticated user.
        """

        return CurrentUserResponse.model_validate(
            user,
        )

    def change_password(
        self,
        user: User,
        payload: ChangePasswordRequest,
    ) -> None:
        """
        Change current user's password.
        """

        if not verify_password(
            payload.current_password,
            user.password_hash,
        ):
            raise InvalidCredentials()

        user.password_hash = hash_password(
            payload.new_password,
        )

        self.db.commit()

    def refresh(
        self,
        user: User,
    ) -> TokenResponse:
        """
        Issue a fresh access token.
        """

        access_token = create_access_token(
            subject=str(user.id),
            additional_claims={
                "organization_id": str(
                    user.organization_id,
                ),
                "role_id": str(
                    user.role_id,
                ),
            },
        )

        refresh_token = create_refresh_token(
            subject=str(user.id),
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def logout(
        self,
    ) -> None:
        """
        Placeholder for logout.

        JWT is stateless, so logout simply
        returns success for now.
        """

        return