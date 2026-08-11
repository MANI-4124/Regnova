from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_admin,
    require_employee,
)
from app.modules.user.models import User

from .schemas import (
    SourceVersionCreate,
    SourceVersionResponse,
    SourceVersionUpdate,
)
from .service import SourceVersionService

router = APIRouter(
    prefix="/sources/{source_id}/versions",
    tags=["Source Versions"],
)


def get_source_version_service(
    db: Session = Depends(get_db_session),
) -> SourceVersionService:
    return SourceVersionService(db)


@router.get(
    "",
    response_model=list[SourceVersionResponse],
)
def get_source_versions(
    source_id: UUID,
    current_user: User = Depends(require_employee),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.get_all(source_id)


@router.get(
    "/{version_id}",
    response_model=SourceVersionResponse,
)
def get_source_version(
    source_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_employee),
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.get_by_id(source_id, version_id)


@router.post(
    "",
    response_model=SourceVersionResponse,
)
def create_source_version(
    source_id: UUID,
    payload: SourceVersionCreate,
    current_user: User = Depends(require_admin),  # interim placeholder - see CLAUDE.md
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.create(source_id, payload)


@router.put(
    "/{version_id}",
    response_model=SourceVersionResponse,
)
def update_source_version(
    source_id: UUID,
    version_id: UUID,
    payload: SourceVersionUpdate,
    current_user: User = Depends(require_admin),  # interim placeholder - see CLAUDE.md
    service: SourceVersionService = Depends(get_source_version_service),
):
    return service.update(source_id, version_id, payload)
