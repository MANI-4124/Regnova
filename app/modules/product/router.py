from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_admin,
    require_manager,
)
from app.modules.user.models import User

from .schemas import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from .service import ProductService

router = APIRouter(
    prefix="/products",
    tags=["Products"],
)


def get_product_service(
    db: Session = Depends(
        get_db_session,
    ),
) -> ProductService:
    return ProductService(
        db,
    )


@router.get(
    "",
    response_model=list[ProductResponse],
)
def get_products(
    current_user: User = Depends(require_manager),
    service: ProductService = Depends(
        get_product_service,
    ),
):
    return service.get_all(
        current_user.organization_id,
    )


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
)
def get_product(
    product_id: UUID,
    current_user: User = Depends(require_manager),
    service: ProductService = Depends(
        get_product_service,
    ),
):
    return service.get_by_id(
        current_user.organization_id,
        product_id,
    )


@router.post(
    "",
    response_model=ProductResponse,
)
def create_product(
    payload: ProductCreate,
    current_user: User = Depends(require_admin),
    service: ProductService = Depends(
        get_product_service,
    ),
):
    return service.create(
        current_user.organization_id,
        payload,
    )


@router.put(
    "/{product_id}",
    response_model=ProductResponse,
)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    current_user: User = Depends(require_admin),
    service: ProductService = Depends(
        get_product_service,
    ),
):
    return service.update(
        current_user.organization_id,
        product_id,
        payload,
    )


@router.delete(
    "/{product_id}",
)
def delete_product(
    product_id: UUID,
    current_user: User = Depends(require_admin),
    service: ProductService = Depends(
        get_product_service,
    ),
):
    service.delete(
        current_user.organization_id,
        product_id,
    )

    return {
        "message": "Product deleted successfully."
    }