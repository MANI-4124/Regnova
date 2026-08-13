from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.product_market_state.exceptions import ProductMarketStateNotFound
from app.modules.product_market_state.repository import ProductMarketStateRepository
from app.modules.rbac.dependencies import require_manager
from app.modules.user.models import User

from .schemas import FindingDetailResponse, FindingResponse, FindingRevisionResponse
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
    revisions = service.get_revisions(finding.id)

    return FindingDetailResponse(
        **FindingResponse.model_validate(finding).model_dump(),
        revisions=[
            FindingRevisionResponse.model_validate(revision) for revision in revisions
        ],
    )
