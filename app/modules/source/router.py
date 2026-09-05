from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_employee,
    require_regulatory_content_author,
)
from app.modules.user.models import User

from .schemas import SourceCreate, SourceResponse, SourceUpdate
from .service import SourceService

router = APIRouter(
    prefix="/sources",
    tags=["Sources"],
)


def get_source_service(
    db: Session = Depends(get_db_session),
) -> SourceService:
    return SourceService(db)


@router.get(
    "",
    response_model=list[SourceResponse],
)
def get_sources(
    current_user: User = Depends(require_employee),
    service: SourceService = Depends(get_source_service),
):
    return service.get_all()


@router.get(
    "/{source_id}",
    response_model=SourceResponse,
)
def get_source(
    source_id: UUID,
    current_user: User = Depends(require_employee),
    service: SourceService = Depends(get_source_service),
):
    return service.get_by_id(source_id)


@router.post(
    "",
    response_model=SourceResponse,
)
def create_source(
    payload: SourceCreate = SourceCreate(),
    current_user: User = Depends(require_regulatory_content_author),
    service: SourceService = Depends(get_source_service),
):
    return service.create(payload)


@router.put(
    "/{source_id}",
    response_model=SourceResponse,
)
def update_source(
    source_id: UUID,
    payload: SourceUpdate,
    current_user: User = Depends(require_regulatory_content_author),
    service: SourceService = Depends(get_source_service),
):
    return service.update(source_id, payload)
