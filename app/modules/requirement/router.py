from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_employee,
    require_regulatory_content_writer,
)
from app.modules.user.models import User

from .schemas import (
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate,
)
from .service import RequirementService

router = APIRouter(
    prefix="/requirements",
    tags=["Requirements"],
)


def get_requirement_service(
    db: Session = Depends(get_db_session),
) -> RequirementService:
    return RequirementService(db)


@router.get(
    "",
    response_model=list[RequirementResponse],
)
def get_requirements(
    current_user: User = Depends(require_employee),
    service: RequirementService = Depends(get_requirement_service),
):
    return service.get_all()


@router.get(
    "/{requirement_id}",
    response_model=RequirementResponse,
)
def get_requirement(
    requirement_id: UUID,
    current_user: User = Depends(require_employee),
    service: RequirementService = Depends(get_requirement_service),
):
    return service.get_by_id(requirement_id)


@router.post(
    "",
    response_model=RequirementResponse,
)
def create_requirement(
    payload: RequirementCreate,
    current_user: User = Depends(require_regulatory_content_writer),
    service: RequirementService = Depends(get_requirement_service),
):
    return service.create(payload)


@router.put(
    "/{requirement_id}",
    response_model=RequirementResponse,
)
def update_requirement(
    requirement_id: UUID,
    payload: RequirementUpdate,
    current_user: User = Depends(require_regulatory_content_writer),
    service: RequirementService = Depends(get_requirement_service),
):
    return service.update(requirement_id, payload)
