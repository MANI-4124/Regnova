from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import require_admin
from app.modules.state_snapshot.schemas import StateSnapshotResponse
from app.modules.user.models import User

from .schemas import MarketReadinessRunCreate
from .service import MarketReadinessService

router = APIRouter(
    prefix="/market-readiness-runs",
    tags=["Market Readiness"],
)


def get_market_readiness_service(db: Session = Depends(get_db_session)) -> MarketReadinessService:
    return MarketReadinessService(db)


@router.post(
    "",
    response_model=StateSnapshotResponse,
)
def run_market_readiness(
    payload: MarketReadinessRunCreate,
    current_user: User = Depends(require_admin),
    service: MarketReadinessService = Depends(get_market_readiness_service),
):
    return service.run(
        current_user.organization_id,
        payload,
        actor_user_id=current_user.id,
    )
