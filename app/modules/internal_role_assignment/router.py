from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import require_admin, require_ceo
from app.modules.user.models import User

from .schemas import (
    InternalRoleAssignmentDecide,
    InternalRoleAssignmentDecideRevocation,
    InternalRoleAssignmentPropose,
    InternalRoleAssignmentProposeRevocation,
    InternalRoleAssignmentResponse,
    InternalRoleAssignmentRevoke,
)
from .service import InternalRoleAssignmentService

router = APIRouter(
    prefix="/internal-role-assignments",
    tags=["Internal Role Assignments"],
)


def get_internal_role_assignment_service(
    db: Session = Depends(get_db_session),
) -> InternalRoleAssignmentService:
    return InternalRoleAssignmentService(db)


@router.get(
    "",
    response_model=list[InternalRoleAssignmentResponse],
)
def get_internal_role_assignments(
    current_user: User = Depends(require_admin),
    service: InternalRoleAssignmentService = Depends(get_internal_role_assignment_service),
):
    return service.get_all()


@router.get(
    "/{assignment_id}",
    response_model=InternalRoleAssignmentResponse,
)
def get_internal_role_assignment(
    assignment_id: UUID,
    current_user: User = Depends(require_admin),
    service: InternalRoleAssignmentService = Depends(get_internal_role_assignment_service),
):
    return service.get_by_id(assignment_id)


@router.post(
    "",
    response_model=InternalRoleAssignmentResponse,
)
def propose_internal_role_assignment(
    payload: InternalRoleAssignmentPropose,
    # require_admin is an interim placeholder for "HR" - no HR
    # actor-type exists in RBAC yet. The service layer separately
    # requires the proposer to be tenant-zero staff, which require_admin
    # alone does not guarantee (any org's admin passes it).
    current_user: User = Depends(require_admin),
    service: InternalRoleAssignmentService = Depends(get_internal_role_assignment_service),
):
    return service.propose(
        user_id=payload.user_id,
        role_code=payload.role_code,
        scope=payload.scope,
        proposed_by_user_id=current_user.id,
        rationale=payload.rationale,
    )


@router.post(
    "/{assignment_id}/decide",
    response_model=InternalRoleAssignmentResponse,
)
def decide_internal_role_assignment(
    assignment_id: UUID,
    payload: InternalRoleAssignmentDecide,
    current_user: User = Depends(require_ceo),
    service: InternalRoleAssignmentService = Depends(get_internal_role_assignment_service),
):
    return service.decide(
        assignment_id=assignment_id,
        approver_user_id=current_user.id,
        approve=payload.approve,
        decision_rationale=payload.decision_rationale,
    )


@router.post(
    "/{assignment_id}/propose-revocation",
    response_model=InternalRoleAssignmentResponse,
)
def propose_internal_role_assignment_revocation(
    assignment_id: UUID,
    payload: InternalRoleAssignmentProposeRevocation,
    current_user: User = Depends(require_admin),
    service: InternalRoleAssignmentService = Depends(get_internal_role_assignment_service),
):
    return service.propose_revocation(
        assignment_id=assignment_id,
        proposed_by_user_id=current_user.id,
        rationale=payload.rationale,
    )


@router.post(
    "/{assignment_id}/decide-revocation",
    response_model=InternalRoleAssignmentResponse,
)
def decide_internal_role_assignment_revocation(
    assignment_id: UUID,
    payload: InternalRoleAssignmentDecideRevocation,
    current_user: User = Depends(require_ceo),
    service: InternalRoleAssignmentService = Depends(get_internal_role_assignment_service),
):
    return service.decide_revocation(
        assignment_id=assignment_id,
        approver_user_id=current_user.id,
        approve=payload.approve,
        decision_rationale=payload.decision_rationale,
    )


@router.post(
    "/{assignment_id}/revoke",
    response_model=InternalRoleAssignmentResponse,
)
def revoke_internal_role_assignment(
    assignment_id: UUID,
    payload: InternalRoleAssignmentRevoke,
    current_user: User = Depends(require_ceo),
    service: InternalRoleAssignmentService = Depends(get_internal_role_assignment_service),
):
    return service.revoke(
        assignment_id=assignment_id,
        actor_user_id=current_user.id,
        reason=payload.reason,
    )
