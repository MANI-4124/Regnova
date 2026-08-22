from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.product_market_state.exceptions import ProductMarketStateNotFound
from app.modules.product_market_state.repository import ProductMarketStateRepository
from app.modules.rbac.dependencies import require_manager
from app.modules.user.models import User

from .schemas import StateSnapshotResponse
from .service import StateSnapshotService

router = APIRouter(
    prefix="/state-snapshots",
    tags=["State Snapshots"],
)


def get_state_snapshot_service(db: Session = Depends(get_db_session)) -> StateSnapshotService:
    return StateSnapshotService(db)


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
    response_model=list[StateSnapshotResponse],
)
def get_state_snapshots(
    product_market_state_id: UUID,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db_session),
    service: StateSnapshotService = Depends(get_state_snapshot_service),
):
    state = _get_state_or_404(db, current_user.organization_id, product_market_state_id)
    return service.get_all(current_user.organization_id, state.id)


@router.get(
    "/{snapshot_id}",
    response_model=StateSnapshotResponse,
)
def get_state_snapshot(
    snapshot_id: UUID,
    product_market_state_id: UUID,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db_session),
    service: StateSnapshotService = Depends(get_state_snapshot_service),
):
    state = _get_state_or_404(db, current_user.organization_id, product_market_state_id)
    return service.get_by_id(current_user.organization_id, state.id, snapshot_id)
