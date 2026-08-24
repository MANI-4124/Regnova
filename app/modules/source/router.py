from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_employee,
    require_regulatory_content_writer,
)
from app.modules.user.models import User

from .schemas import SourceResponse
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
    current_user: User = Depends(require_regulatory_content_writer),
    service: SourceService = Depends(get_source_service),
):
    return service.create()
