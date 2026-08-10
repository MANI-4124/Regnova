from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.user.models import User
from app.modules.user.repository import UserRepository

from .exceptions import (
    InactiveUser,
    InvalidToken,
)
from .jwt import verify_token

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db_session),
) -> User:
    """
    Return the authenticated user from the JWT.
    """

    token = credentials.credentials

    try:
        payload = verify_token(token)

    except JWTError:
        raise InvalidToken()

    user_id = payload.get("sub")
    organization_id = payload.get("organization_id")

    if user_id is None or organization_id is None:
        raise InvalidToken()

    repository = UserRepository(db)

    user = repository.get_by_id(
        UUID(organization_id),
        UUID(user_id),
    )

    if user is None:
        raise InvalidToken()

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Ensure the authenticated user is active.
    """

    if not current_user.is_active:
        raise InactiveUser()

    return current_user