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
    ProductVersionCreate,
    ProductVersionResponse,
    ProductVersionUpdate,
)
from .service import ProductVersionService

router = APIRouter(
    prefix="/products/{product_id}/versions",
    tags=["Product Versions"],
)


def get_product_version_service(
    db: Session = Depends(
        get_db_session,
    ),
) -> ProductVersionService:
    return ProductVersionService(
        db,
    )


@router.get(
    "",
    response_model=list[ProductVersionResponse],
)
def get_product_versions(
    product_id: UUID,
    current_user: User = Depends(require_manager),
    service: ProductVersionService = Depends(
        get_product_version_service,
    ),
):
    return service.get_all(
        current_user.organization_id,
        product_id,
    )


@router.get(
    "/current",
    response_model=ProductVersionResponse,
)
def get_current_product_version(
    product_id: UUID,
    current_user: User = Depends(require_manager),
    service: ProductVersionService = Depends(
        get_product_version_service,
    ),
):
    return service.get_current(
        current_user.organization_id,
        product_id,
    )


@router.get(
    "/{version_id}",
    response_model=ProductVersionResponse,
)
def get_product_version(
    product_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_manager),
    service: ProductVersionService = Depends(
        get_product_version_service,
    ),
):
    return service.get_by_id(
        current_user.organization_id,
        product_id,
        version_id,
    )


@router.post(
    "",
    response_model=ProductVersionResponse,
)
def create_product_version(
    product_id: UUID,
    payload: ProductVersionCreate,
    current_user: User = Depends(require_admin),
    service: ProductVersionService = Depends(
        get_product_version_service,
    ),
):
    return service.create(
        current_user.organization_id,
        product_id,
        payload,
    )


@router.put(
    "/{version_id}",
    response_model=ProductVersionResponse,
)
def update_product_version(
    product_id: UUID,
    version_id: UUID,
    payload: ProductVersionUpdate,
    current_user: User = Depends(require_admin),
    service: ProductVersionService = Depends(
        get_product_version_service,
    ),
):
    return service.update(
        current_user.organization_id,
        product_id,
        version_id,
        payload,
    )


@router.delete(
    "/{version_id}",
)
def delete_product_version(
    product_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_admin),
    service: ProductVersionService = Depends(
        get_product_version_service,
    ),
):
    service.delete(
        current_user.organization_id,
        product_id,
        version_id,
    )

    return {
        "message": "Product version deleted successfully."
    }
