from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_admin,
    require_manager,
)
from app.modules.user.models import User

from .schemas import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from .service import OrganizationService

router = APIRouter(
    prefix="/organizations",
    tags=["Organizations"],
)


def get_organization_service(
    db: Session = Depends(get_db_session),
) -> OrganizationService:
    return OrganizationService(db)


@router.get(
    "",
    response_model=list[OrganizationResponse],
)
def get_organizations(
    service: OrganizationService = Depends(get_organization_service),
):
    return service.get_all()


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
)
def get_organization(
    organization_id: UUID,
    current_user: User = Depends(require_manager),
    service: OrganizationService = Depends(get_organization_service),
):
    try:
        return service.get_by_id(organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.post(
    "",
    response_model=OrganizationResponse,
)
def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(require_admin),
    service: OrganizationService = Depends(get_organization_service),
):
    return service.create(payload)


@router.put(
    "/{organization_id}",
    response_model=OrganizationResponse,
)
def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    current_user: User = Depends(require_admin),
    service: OrganizationService = Depends(get_organization_service),
):
    try:
        return service.update(
            organization_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.delete(
    "/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_organization(
    organization_id: UUID,
    current_user: User = Depends(require_admin),
    service: OrganizationService = Depends(get_organization_service),
):
    try:
        service.delete(organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)