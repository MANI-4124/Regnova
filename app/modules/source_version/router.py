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
    SourceVersionCreate,
    SourceVersionResponse,
    SourceVersionUpdate,
)
from .service import SourceVersionService

router = APIRouter(
    prefix="/sources/{source_id}/versions",
    tags=["Source Versions"],
)


def get_source_version_service(
    db: Session = Depends(get_db_session),
) -> SourceVersionService:
    return SourceVersionService(db)


@router.get(
    "",
    response_model=list[SourceVersionResponse],
)
def get_source_versions(
    source_id: UUID,
    current_user: User = Depends(require_employee),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.get_all(source_id)


@router.get(
    "/{version_id}",
    response_model=SourceVersionResponse,
)
def get_source_version(
    source_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_employee),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.get_by_id(source_id, version_id)


@router.post(
    "",
    response_model=SourceVersionResponse,
)
def create_source_version(
    source_id: UUID,
    payload: SourceVersionCreate,
    current_user: User = Depends(require_regulatory_content_author),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.create(source_id, payload, author_user_id=current_user.id)


@router.put(
    "/{version_id}",
    response_model=SourceVersionResponse,
)
def update_source_version(
    source_id: UUID,
    version_id: UUID,
    payload: SourceVersionUpdate,
    current_user: User = Depends(require_regulatory_content_author),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.update(source_id, version_id, payload)


@router.post(
    "/{version_id}/submit-for-review",
    response_model=SourceVersionResponse,
)
def submit_source_version_for_review(
    source_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_regulatory_content_author),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.submit_for_review(source_id, version_id, actor_user_id=current_user.id)


@router.post(
    "/{version_id}/verify",
    response_model=SourceVersionResponse,
)
def verify_source_version(
    source_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.verify(
        source_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )


@router.post(
    "/{version_id}/activate",
    response_model=SourceVersionResponse,
)
def activate_source_version(
    source_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.activate(
        source_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )


@router.post(
    "/{version_id}/reject",
    response_model=SourceVersionResponse,
)
def reject_source_version(
    source_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.reject(
        source_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )
