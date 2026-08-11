from uuid import UUID

from fastapi import APIRouter, Depends,HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_correlation_id, get_db_session
from app.modules.rbac.dependencies import (
    require_admin,
    require_manager,
)
from app.modules.user.models import User
from .schemas import (
    UserCreate,
    UserResponse,
    UserUpdate,
)
from .service import UserService

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


def get_user_service(
    db: Session = Depends(get_db_session),
) -> UserService:
    return UserService(db)


@router.get(
    "",
    response_model=list[UserResponse],
)
def get_users(
    current_user: User = Depends(require_manager),
    service: UserService = Depends(get_user_service),
):
    return service.get_all(current_user.organization_id)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
)
def get_user(
    user_id: UUID,
    current_user: User = Depends(require_manager),
    service: UserService = Depends(get_user_service),
):
    return service.get_by_id(
        current_user.organization_id,
        user_id,
    )


@router.post(
    "",
    response_model=UserResponse,
)
def create_user(
    payload: UserCreate,
    current_user: User = Depends(require_admin),
    correlation_id: str = Depends(get_correlation_id),
    service: UserService = Depends(get_user_service),
):
    return service.create(
        current_user.organization_id,
        payload,
        correlation_id=correlation_id,
        actor_user_id=current_user.id,
    )


@router.put(
    "/{user_id}",
    response_model=UserResponse,
)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    current_user: User = Depends(require_admin),
    correlation_id: str = Depends(get_correlation_id),
    service: UserService = Depends(get_user_service),
):
    return service.update(
        current_user.organization_id,
        user_id,
        payload,
        correlation_id=correlation_id,
        actor_user_id=current_user.id,
    )


@router.delete("/{user_id}")
def delete_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    correlation_id: str = Depends(get_correlation_id),
    service: UserService = Depends(get_user_service),
):
    if current_user.id == user_id:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your own account.",
        )

    service.delete(
        current_user.organization_id,
        user_id,
        correlation_id=correlation_id,
        actor_user_id=current_user.id,
    )

    return {
        "message": "User deleted successfully."
    }