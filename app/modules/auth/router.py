from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.user.models import User

from .dependencies import get_current_active_user
from .schemas import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    TokenResponse,
)
from .service import AuthService

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


def get_auth_service(
    db: Session = Depends(get_db_session),
) -> AuthService:
    return AuthService(db)


@router.post(
    "/login",
    response_model=TokenResponse,
)
def login(
    payload: LoginRequest,
    service: AuthService = Depends(get_auth_service),
):
    return service.login(payload)


@router.get(
    "/me",
    response_model=CurrentUserResponse,
)
def me(
    current_user: User = Depends(get_current_active_user),
    service: AuthService = Depends(get_auth_service),
):
    return service.me(current_user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
)
def refresh(
    current_user: User = Depends(get_current_active_user),
    service: AuthService = Depends(get_auth_service),
):
    return service.refresh(current_user)


@router.put(
    "/change-password",
)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    service: AuthService = Depends(get_auth_service),
):
    service.change_password(
        current_user,
        payload,
    )

    return {
        "message": "Password changed successfully."
    }


@router.post(
    "/logout",
)
def logout(
    service: AuthService = Depends(get_auth_service),
):
    service.logout()

    return {
        "message": "Logged out successfully."
    }