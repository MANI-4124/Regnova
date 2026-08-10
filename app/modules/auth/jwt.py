from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from app.core.settings import get_settings

settings = get_settings()


def create_access_token(
    subject: str,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a JWT access token.
    """

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes,
    )

    payload: dict[str, Any] = {
        "sub": subject,
        "type": "access",
        "exp": expire,
    }

    if additional_claims:
        payload.update(additional_claims)

    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(
    subject: str,
) -> str:
    """
    Create a JWT refresh token.
    """

    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days,
    )

    payload = {
        "sub": subject,
        "type": "refresh",
        "exp": expire,
    }

    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(
    token: str,
) -> dict[str, Any]:
    """
    Decode a JWT token.
    """

    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        raise

def verify_token(
    token: str,
    token_type: str = "access",
) -> dict[str, Any]:
    """
    Verify token validity and type.
    """

    payload = decode_token(token)

    if payload.get("type") != token_type:
        raise JWTError("Invalid token type.")

    return payload