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
    RuleVersionCreate,
    RuleVersionResponse,
    RuleVersionUpdate,
)
from .service import RuleVersionService

router = APIRouter(
    prefix="/rules/{rule_id}/versions",
    tags=["Rule Versions"],
)


def get_rule_version_service(
    db: Session = Depends(get_db_session),
) -> RuleVersionService:
    return RuleVersionService(db)


@router.get(
    "",
    response_model=list[RuleVersionResponse],
)
def get_rule_versions(
    rule_id: UUID,
    current_user: User = Depends(require_employee),
    service: RuleVersionService = Depends(get_rule_version_service),
):
    return service.get_all(rule_id)


@router.get(
    "/{version_id}",
    response_model=RuleVersionResponse,
)
def get_rule_version(
    rule_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_employee),
    service: RuleVersionService = Depends(get_rule_version_service),
):
    return service.get_by_id(rule_id, version_id)


@router.post(
    "",
    response_model=RuleVersionResponse,
)
def create_rule_version(
    rule_id: UUID,
    payload: RuleVersionCreate,
    current_user: User = Depends(require_regulatory_content_author),
    service: RuleVersionService = Depends(get_rule_version_service),
):
    return service.create(rule_id, payload, author_user_id=current_user.id)


@router.put(
    "/{version_id}",
    response_model=RuleVersionResponse,
)
def update_rule_version(
    rule_id: UUID,
    version_id: UUID,
    payload: RuleVersionUpdate,
    current_user: User = Depends(require_regulatory_content_author),
    service: RuleVersionService = Depends(get_rule_version_service),
):
    return service.update(rule_id, version_id, payload)


@router.post(
    "/{version_id}/submit-for-review",
    response_model=RuleVersionResponse,
)
def submit_rule_version_for_review(
    rule_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_regulatory_content_author),
    service: RuleVersionService = Depends(get_rule_version_service),
):
    return service.submit_for_review(rule_id, version_id, actor_user_id=current_user.id)


@router.post(
    "/{version_id}/verify",
    response_model=RuleVersionResponse,
)
def verify_rule_version(
    rule_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: RuleVersionService = Depends(get_rule_version_service),
):
    return service.verify(
        rule_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )


@router.post(
    "/{version_id}/activate",
    response_model=RuleVersionResponse,
)
def activate_rule_version(
    rule_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: RuleVersionService = Depends(get_rule_version_service),
):
    return service.activate(
        rule_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )


@router.post(
    "/{version_id}/reject",
    response_model=RuleVersionResponse,
)
def reject_rule_version(
    rule_id: UUID,
    version_id: UUID,
    payload: ContentVersionTransitionRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: RuleVersionService = Depends(get_rule_version_service),
):
    return service.reject(
        rule_id, version_id,
        actor_user_id=current_user.id, rationale=payload.rationale,
    )
