from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_employee,
    require_regulatory_content_writer,
)
from app.modules.user.models import User

from .schemas import (
    SourceLocationCreate,
    SourceLocationResponse,
    SourceLocationUpdate,
)
from .service import SourceLocationService

router = APIRouter(
    prefix="/source-locations",
    tags=["Source Locations"],
)


def get_source_location_service(
    db: Session = Depends(get_db_session),
) -> SourceLocationService:
    return SourceLocationService(db)


@router.get(
    "",
    response_model=list[SourceLocationResponse],
)
def get_source_locations(
    source_version_id: UUID | None = None,
    current_user: User = Depends(require_employee),
    service: SourceLocationService = Depends(get_source_location_service),
):
    return service.get_all(source_version_id)


@router.get(
    "/{location_id}",
    response_model=SourceLocationResponse,
)
def get_source_location(
    location_id: UUID,
    current_user: User = Depends(require_employee),
    service: SourceLocationService = Depends(get_source_location_service),
):
    return service.get_by_id(location_id)


@router.post(
    "",
    response_model=SourceLocationResponse,
)
def create_source_location(
    payload: SourceLocationCreate,
    current_user: User = Depends(require_regulatory_content_writer),
    service: SourceLocationService = Depends(get_source_location_service),
):
    return service.create(payload)


@router.put(
    "/{location_id}",
    response_model=SourceLocationResponse,
)
def update_source_location(
    location_id: UUID,
    payload: SourceLocationUpdate,
    current_user: User = Depends(require_regulatory_content_writer),
    service: SourceLocationService = Depends(get_source_location_service),
):
    return service.update(location_id, payload)
