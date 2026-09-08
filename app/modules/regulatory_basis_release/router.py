from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_correlation_id, get_db_session
from app.modules.rbac.dependencies import (
    require_employee,
    require_regulatory_content_writer,
)
from app.modules.user.models import User

from .schemas import (
    RegulatoryBasisReleaseCreate,
    RegulatoryBasisReleaseResponse,
    RegulatoryBasisReleaseUpdate,
)
from .service import RegulatoryBasisReleaseService

router = APIRouter(
    prefix="/regulatory-basis-releases",
    tags=["Regulatory Basis Releases"],
)


def get_regulatory_basis_release_service(
    db: Session = Depends(get_db_session),
) -> RegulatoryBasisReleaseService:
    return RegulatoryBasisReleaseService(db)


@router.get(
    "",
    response_model=list[RegulatoryBasisReleaseResponse],
)
def get_regulatory_basis_releases(
    current_user: User = Depends(require_employee),
    service: RegulatoryBasisReleaseService = Depends(get_regulatory_basis_release_service),
):
    return service.get_all()


@router.get(
    "/{release_id}",
    response_model=RegulatoryBasisReleaseResponse,
)
def get_regulatory_basis_release(
    release_id: UUID,
    current_user: User = Depends(require_employee),
    service: RegulatoryBasisReleaseService = Depends(get_regulatory_basis_release_service),
):
    return service.get_by_id(release_id)


@router.post(
    "",
    response_model=RegulatoryBasisReleaseResponse,
)
def create_regulatory_basis_release(
    payload: RegulatoryBasisReleaseCreate,
    current_user: User = Depends(require_regulatory_content_writer),
    correlation_id: str = Depends(get_correlation_id),
    service: RegulatoryBasisReleaseService = Depends(get_regulatory_basis_release_service),
):
    return service.create(
        payload,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )


@router.put(
    "/{release_id}",
    response_model=RegulatoryBasisReleaseResponse,
)
def update_regulatory_basis_release(
    release_id: UUID,
    payload: RegulatoryBasisReleaseUpdate,
    current_user: User = Depends(require_regulatory_content_writer),
    correlation_id: str = Depends(get_correlation_id),
    service: RegulatoryBasisReleaseService = Depends(get_regulatory_basis_release_service),
):
    return service.update(
        release_id,
        payload,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )
