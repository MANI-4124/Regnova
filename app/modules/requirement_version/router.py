from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.content_review.schemas import ContentVersionTransitionRequest
from app.modules.rbac.dependencies import (
    require_employee,
    require_regulatory_content_author,
    require_regulatory_content_writer,
)
from app.modules.user.models import User

from .schemas import (
    RequirementVersionCreate,
    RequirementVersionResponse,
    RequirementVersionUpdate,
)
from .service import RequirementVersionService

router = APIRouter(
    prefix="/requirements/{requirement_id}/versions",
    tags=["Requirement Versions"],
)


def get_requirement_version_service(
    db: Session = Depends(get_db_session),
) -> RequirementVersionService:
    return RequirementVersionService(db)


@router.get(
    "",
    response_model=list[RequirementVersionResponse],
)
def get_requirement_versions(
    requirement_id: UUID,
    current_user: User = Depends(require_employee),
    service: RequirementVersionService = Depends(get_requirement_version_service),
):
    return service.get_all(requirement_id)


@router.get(
    "/{version_id}",
    response_model=RequirementVersionResponse,
)
def get_requirement_version(
    requirement_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_employee),
    service: RequirementVersionService = Depends(get_requirement_version_service),
):
    return service.get_by_id(requirement_id, version_id)


@router.post(
    "",
    response_model=RequirementVersionResponse,
)
def create_requirement_version(
    requirement_id: UUID,
    payload: RequirementVersionCreate,
    current_user: User = Depends(require_regulatory_content_author),
    service: RequirementVersionService = Depends(get_requirement_version_service),
):
    return service.create(requirement_id, payload, author_user_id=current_user.id)


@router.put(
    "/{version_id}",
    response_model=RequirementVersionResponse,
)
def update_requirement_version(
    requirement_id: UUID,
    version_id: UUID,
    payload: RequirementVersionUpdate,
    current_user: User = Depends(require_regulatory_content_author),
    service: RequirementVersionService = Depends(get_requirement_version_service),
):
    return service.update(requirement_id, version_id, payload)


@router.post(
    "/{version_id}/submit-for-review",
    response_model=RequirementVersionResponse,
)
def submit_requirement_version_for_review(
    requirement_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_regulatory_content_author),
    service: RequirementVersionService = Depends(get_requirement_version_service),
):
    return service.submit_for_review(requirement_id, version_id, actor_user_id=current_user.id)


@router.post(
    "/{version_id}/verify",
    response_model=RequirementVersionResponse,
)
def verify_requirement_version(
    requirement_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: RequirementVersionService = Depends(get_requirement_version_service),
):
    return service.verify(
        requirement_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )


@router.post(
    "/{version_id}/activate",
    response_model=RequirementVersionResponse,
)
def activate_requirement_version(
    requirement_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: RequirementVersionService = Depends(get_requirement_version_service),
):
    return service.activate(
        requirement_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )


@router.post(
    "/{version_id}/reject",
    response_model=RequirementVersionResponse,
)
def reject_requirement_version(
    requirement_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: RequirementVersionService = Depends(get_requirement_version_service),
):
    return service.reject(
        requirement_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )
