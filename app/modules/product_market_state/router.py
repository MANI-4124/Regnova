from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_correlation_id, get_db_session
from app.modules.rbac.dependencies import (
    require_admin,
    require_manager,
)
from app.modules.user.models import User

from .schemas import (
    ProductMarketStateCreate,
    ProductMarketStateResponse,
    ProductMarketStateUpdate,
)
from .service import ProductMarketStateService

router = APIRouter(
    prefix="/products/{product_id}/market-states",
    tags=["Product Market States"],
)


def get_product_market_state_service(
    db: Session = Depends(get_db_session),
) -> ProductMarketStateService:
    return ProductMarketStateService(db)


@router.get(
    "",
    response_model=list[ProductMarketStateResponse],
)
def get_product_market_states(
    product_id: UUID,
    market: str | None = None,
    current_user: User = Depends(require_manager),
    service: ProductMarketStateService = Depends(get_product_market_state_service),
):
    return service.get_all(current_user.organization_id, product_id, market)


@router.get(
    "/{state_id}",
    response_model=ProductMarketStateResponse,
)
def get_product_market_state(
    product_id: UUID,
    state_id: UUID,
    current_user: User = Depends(require_manager),
    service: ProductMarketStateService = Depends(get_product_market_state_service),
):
    return service.get_by_id(current_user.organization_id, product_id, state_id)


@router.post(
    "",
    response_model=ProductMarketStateResponse,
)
def create_product_market_state(
    product_id: UUID,
    payload: ProductMarketStateCreate,
    current_user: User = Depends(require_admin),
    service: ProductMarketStateService = Depends(get_product_market_state_service),
):
    return service.create(
        current_user.organization_id,
        product_id,
        payload,
        actor_user_id=current_user.id,
    )


@router.put(
    "/{state_id}",
    response_model=ProductMarketStateResponse,
)
def update_product_market_state(
    product_id: UUID,
    state_id: UUID,
    payload: ProductMarketStateUpdate,
    current_user: User = Depends(require_admin),
    correlation_id: str = Depends(get_correlation_id),
    service: ProductMarketStateService = Depends(get_product_market_state_service),
):
    return service.update(
        current_user.organization_id,
        product_id,
        state_id,
        payload,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )
