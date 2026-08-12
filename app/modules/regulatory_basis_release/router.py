from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_admin,
    require_employee,
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
    # NOTE: require_admin here is an interim placeholder, not a real
    # authorization decision - same unresolved actor-model gap as
    # Source/Requirement/Rule. See CLAUDE.md "Regulatory content
    # ownership".
    current_user: User = Depends(require_admin),
    service: RegulatoryBasisReleaseService = Depends(get_regulatory_basis_release_service),
):
    return service.create(payload)


@router.put(
    "/{release_id}",
    response_model=RegulatoryBasisReleaseResponse,
)
def update_regulatory_basis_release(
    release_id: UUID,
    payload: RegulatoryBasisReleaseUpdate,
    current_user: User = Depends(require_admin),  # interim placeholder - see CLAUDE.md
    service: RegulatoryBasisReleaseService = Depends(get_regulatory_basis_release_service),
):
    return service.update(release_id, payload)
