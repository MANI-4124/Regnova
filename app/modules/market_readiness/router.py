from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analysis import ClaimAnalyzer
from app.core.dependencies import get_claim_analyzer, get_correlation_id, get_db_session
from app.modules.rbac.dependencies import require_admin
from app.modules.state_snapshot.schemas import StateSnapshotResponse
from app.modules.user.models import User

from .schemas import MarketReadinessRunCreate
from .service import MarketReadinessService

router = APIRouter(
    prefix="/market-readiness-runs",
    tags=["Market Readiness"],
)


def get_market_readiness_service(
    db: Session = Depends(get_db_session),
    claim_analyzer: ClaimAnalyzer = Depends(get_claim_analyzer),
) -> MarketReadinessService:
    return MarketReadinessService(db, claim_analyzer=claim_analyzer)


@router.post(
    "",
    response_model=StateSnapshotResponse,
)
def run_market_readiness(
    payload: MarketReadinessRunCreate,
    current_user: User = Depends(require_admin),
    correlation_id: str = Depends(get_correlation_id),
    service: MarketReadinessService = Depends(get_market_readiness_service),
):
    return service.run(
        current_user.organization_id,
        payload,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )
