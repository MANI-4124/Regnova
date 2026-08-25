from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.auth.dependencies import get_current_active_user
from app.modules.product_market_state.exceptions import ProductMarketStateNotFound
from app.modules.product_market_state.repository import ProductMarketStateRepository
from app.modules.rbac.dependencies import require_manager
from app.modules.user.models import User

from .schemas import (
    FindingDetailResponse,
    FindingRationaleRequest,
    FindingResolveRequest,
    FindingResponse,
    FindingRevisionResponse,
    FindingTransitionRequest,
)
from .service import FindingService

router = APIRouter(
    prefix="/findings",
    tags=["Findings"],
)


def get_finding_service(db: Session = Depends(get_db_session)) -> FindingService:
    return FindingService(db)


def _get_state_or_404(db: Session, organization_id: UUID, product_market_state_id: UUID):
    state = ProductMarketStateRepository(db).get_by_id_only(
        organization_id,
        product_market_state_id,
    )

    if state is None:
        raise ProductMarketStateNotFound()

    return state


def _to_detail_response(service: FindingService, finding) -> FindingDetailResponse:
    revisions = service.get_revisions(finding.id)

    return FindingDetailResponse(
        **FindingResponse.model_validate(finding).model_dump(),
        revisions=[
            FindingRevisionResponse.model_validate(revision) for revision in revisions
        ],
    )


@router.get(
    "",
    response_model=list[FindingResponse],
)
def get_findings(
    product_market_state_id: UUID,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db_session),
    service: FindingService = Depends(get_finding_service),
):
    state = _get_state_or_404(db, current_user.organization_id, product_market_state_id)
    return service.get_all(current_user.organization_id, state.id)


@router.get(
    "/{finding_id}",
    response_model=FindingDetailResponse,
)
def get_finding(
    finding_id: UUID,
    product_market_state_id: UUID,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db_session),
    service: FindingService = Depends(get_finding_service),
):
    state = _get_state_or_404(db, current_user.organization_id, product_market_state_id)
    finding = service.get_by_id(current_user.organization_id, state.id, finding_id)

    return _to_detail_response(service, finding)


# --- Transitions -----------------------------------------------------
#
# Deliberately gated by get_current_active_user (bare auth), not
# require_manager/require_ra/etc. - every transition's real
# authorization (customer role tier OR RA/Senior InternalRoleAssignment,
# and for resolve() the finding's own severity) is decided inside
# FindingService against the specific finding, not statically at the
# route. A router-level require_manager here would incorrectly block a
# tenant-zero RA/Senior actor on their own organization's role tier,
# which has nothing to do with their InternalRoleAssignment authority -
# see CLAUDE.md "Finding review workflow". Cross-tenant access is still
# denied - by the org-scoped get_by_id lookup inside each service
# method, the same boundary every other org-scoped module relies on.

@router.post(
    "/{finding_id}/accept",
    response_model=FindingDetailResponse,
)
def accept_finding(
    finding_id: UUID,
    product_market_state_id: UUID,
    payload: FindingTransitionRequest,
    current_user: User = Depends(get_current_active_user),
    service: FindingService = Depends(get_finding_service),
):
    finding = service.accept(
        organization_id=current_user.organization_id,
        product_market_state_id=product_market_state_id,
        finding_id=finding_id,
        actor_user_id=current_user.id,
        rationale=payload.rationale,
        disposition=payload.disposition,
    )
    return _to_detail_response(service, finding)


@router.post(
    "/{finding_id}/reject",
    response_model=FindingDetailResponse,
)
def reject_finding(
    finding_id: UUID,
    product_market_state_id: UUID,
    payload: FindingTransitionRequest,
    current_user: User = Depends(get_current_active_user),
    service: FindingService = Depends(get_finding_service),
):
    finding = service.reject(
        organization_id=current_user.organization_id,
        product_market_state_id=product_market_state_id,
        finding_id=finding_id,
        actor_user_id=current_user.id,
        rationale=payload.rationale,
        disposition=payload.disposition,
    )
    return _to_detail_response(service, finding)


@router.post(
    "/{finding_id}/mark-not-applicable",
    response_model=FindingDetailResponse,
)
def mark_finding_not_applicable(
    finding_id: UUID,
    product_market_state_id: UUID,
    payload: FindingTransitionRequest,
    current_user: User = Depends(get_current_active_user),
    service: FindingService = Depends(get_finding_service),
):
    finding = service.mark_not_applicable(
        organization_id=current_user.organization_id,
        product_market_state_id=product_market_state_id,
        finding_id=finding_id,
        actor_user_id=current_user.id,
        rationale=payload.rationale,
        disposition=payload.disposition,
    )
    return _to_detail_response(service, finding)


@router.post(
    "/{finding_id}/respond",
    response_model=FindingDetailResponse,
)
def respond_to_finding(
    finding_id: UUID,
    product_market_state_id: UUID,
    payload: FindingRationaleRequest,
    current_user: User = Depends(get_current_active_user),
    service: FindingService = Depends(get_finding_service),
):
    finding = service.respond(
        organization_id=current_user.organization_id,
        product_market_state_id=product_market_state_id,
        finding_id=finding_id,
        actor_user_id=current_user.id,
        rationale=payload.rationale,
    )
    return _to_detail_response(service, finding)


@router.post(
    "/{finding_id}/reopen",
    response_model=FindingDetailResponse,
)
def reopen_finding(
    finding_id: UUID,
    product_market_state_id: UUID,
    payload: FindingRationaleRequest,
    current_user: User = Depends(get_current_active_user),
    service: FindingService = Depends(get_finding_service),
):
    finding = service.reopen(
        organization_id=current_user.organization_id,
        product_market_state_id=product_market_state_id,
        finding_id=finding_id,
        actor_user_id=current_user.id,
        rationale=payload.rationale,
    )
    return _to_detail_response(service, finding)


@router.post(
    "/{finding_id}/resolve",
    response_model=FindingDetailResponse,
)
def resolve_finding(
    finding_id: UUID,
    product_market_state_id: UUID,
    payload: FindingResolveRequest,
    current_user: User = Depends(get_current_active_user),
    service: FindingService = Depends(get_finding_service),
):
    finding = service.resolve(
        organization_id=current_user.organization_id,
        product_market_state_id=product_market_state_id,
        finding_id=finding_id,
        actor_user_id=current_user.id,
        rationale=payload.rationale,
        disposition=payload.disposition,
        resolution_decision=payload.resolution_decision,
    )
    return _to_detail_response(service, finding)


@router.post(
    "/{finding_id}/accept-with-rationale",
    response_model=FindingDetailResponse,
)
def accept_finding_with_rationale(
    finding_id: UUID,
    product_market_state_id: UUID,
    payload: FindingTransitionRequest,
    current_user: User = Depends(get_current_active_user),
    service: FindingService = Depends(get_finding_service),
):
    finding = service.accept_with_rationale(
        organization_id=current_user.organization_id,
        product_market_state_id=product_market_state_id,
        finding_id=finding_id,
        actor_user_id=current_user.id,
        rationale=payload.rationale,
        disposition=payload.disposition,
    )
    return _to_detail_response(service, finding)
