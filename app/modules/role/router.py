from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_admin,
    require_manager,
)
from app.modules.user.models import User
from .schemas import (
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)
from .service import RoleService

router = APIRouter(
    prefix="/roles",
    tags=["Roles"],
)


def get_role_service(
    db: Session = Depends(get_db_session),
) -> RoleService:
    return RoleService(db)


@router.get(
    "",
    response_model=list[RoleResponse],
)
def get_roles(
    current_user: User = Depends(require_manager),
    service: RoleService = Depends(get_role_service),
):
    return service.get_all(
        current_user.organization_id,
    )


@router.get(
    "/{role_id}",
    response_model=RoleResponse,
)
def get_role(
    role_id: UUID,
    current_user: User = Depends(require_manager),
    service: RoleService = Depends(get_role_service),
):
    return service.get_by_id(
        current_user.organization_id,
        role_id,
    )


@router.post(
    "",
    response_model=RoleResponse,
)
def create_role(
    payload: RoleCreate,
    current_user: User = Depends(require_admin),
    service: RoleService = Depends(get_role_service),
):
    return service.create(
        current_user.organization_id,
        payload,
    )


@router.put(
    "/{role_id}",
    response_model=RoleResponse,
)
def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    current_user: User = Depends(require_admin),
    service: RoleService = Depends(get_role_service),
):
    return service.update(
        current_user.organization_id,
        role_id,
        payload,
    )


@router.delete(
    "/{role_id}",
)
def delete_role(
    role_id: UUID,
    current_user: User = Depends(require_admin),
    service: RoleService = Depends(get_role_service),
):
    service.delete(
        current_user.organization_id,
        role_id,
    )

    return {
        "message": "Role deleted successfully."
    }