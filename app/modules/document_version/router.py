from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.dependencies import get_correlation_id, get_db_session, get_document_storage
from app.modules.rbac.dependencies import require_employee, require_manager
from app.modules.user.models import User
from app.storage import DocumentStorage

from .schemas import (
    DocumentFieldResponse,
    DocumentFieldSetRequest,
    DocumentVersionRejectRequest,
    DocumentVersionResponse,
    DocumentVersionReviewRequest,
)
from .service import DocumentFieldService, DocumentVersionService

router = APIRouter(
    prefix="/documents/{document_id}/versions",
    tags=["Document Versions"],
)


def get_document_version_service(
    db: Session = Depends(get_db_session),
    storage: DocumentStorage = Depends(get_document_storage),
) -> DocumentVersionService:
    return DocumentVersionService(db, storage)


def get_document_field_service(
    db: Session = Depends(get_db_session),
) -> DocumentFieldService:
    return DocumentFieldService(db)


@router.get(
    "",
    response_model=list[DocumentVersionResponse],
)
def get_document_versions(
    document_id: UUID,
    current_user: User = Depends(require_employee),
    service: DocumentVersionService = Depends(get_document_version_service),
):
    return service.get_all(current_user.organization_id, document_id)


@router.get(
    "/{version_id}",
    response_model=DocumentVersionResponse,
)
def get_document_version(
    document_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_employee),
    service: DocumentVersionService = Depends(get_document_version_service),
):
    return service.get_by_id(current_user.organization_id, document_id, version_id)


@router.post(
    "",
    response_model=DocumentVersionResponse,
)
async def create_document_version(
    document_id: UUID,
    file: UploadFile = File(...),
    notes: str | None = Form(None),
    current_user: User = Depends(require_employee),
    correlation_id: str = Depends(get_correlation_id),
    service: DocumentVersionService = Depends(get_document_version_service),
):
    content = await file.read()

    return service.create(
        current_user.organization_id,
        document_id,
        filename=file.filename or "unnamed",
        declared_content_type=file.content_type or "application/octet-stream",
        content=content,
        notes=notes,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )


@router.post(
    "/{version_id}/verify",
    response_model=DocumentVersionResponse,
)
def verify_document_version(
    document_id: UUID,
    version_id: UUID,
    payload: DocumentVersionReviewRequest,
    current_user: User = Depends(require_manager),
    correlation_id: str = Depends(get_correlation_id),
    service: DocumentVersionService = Depends(get_document_version_service),
):
    return service.verify(
        current_user.organization_id,
        document_id,
        version_id,
        note=payload.note,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )


@router.post(
    "/{version_id}/reject",
    response_model=DocumentVersionResponse,
)
def reject_document_version(
    document_id: UUID,
    version_id: UUID,
    payload: DocumentVersionRejectRequest,
    current_user: User = Depends(require_manager),
    correlation_id: str = Depends(get_correlation_id),
    service: DocumentVersionService = Depends(get_document_version_service),
):
    return service.reject(
        current_user.organization_id,
        document_id,
        version_id,
        note=payload.note,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )


@router.post(
    "/{version_id}/quarantine",
    response_model=DocumentVersionResponse,
)
def quarantine_document_version(
    document_id: UUID,
    version_id: UUID,
    payload: DocumentVersionRejectRequest,
    current_user: User = Depends(require_manager),
    correlation_id: str = Depends(get_correlation_id),
    service: DocumentVersionService = Depends(get_document_version_service),
):
    return service.quarantine(
        current_user.organization_id,
        document_id,
        version_id,
        note=payload.note,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )


@router.get(
    "/{version_id}/fields",
    response_model=list[DocumentFieldResponse],
)
def get_document_fields(
    document_id: UUID,
    version_id: UUID,
    current_user: User = Depends(require_employee),
    service: DocumentFieldService = Depends(get_document_field_service),
):
    return service.get_all(current_user.organization_id, document_id, version_id)


@router.put(
    "/{version_id}/fields/{field_key}",
    response_model=DocumentFieldResponse,
)
def set_document_field(
    document_id: UUID,
    version_id: UUID,
    field_key: str,
    payload: DocumentFieldSetRequest,
    current_user: User = Depends(require_employee),
    correlation_id: str = Depends(get_correlation_id),
    service: DocumentFieldService = Depends(get_document_field_service),
):
    return service.set_field(
        current_user.organization_id,
        document_id,
        version_id,
        field_key,
        value=payload.value,
        confidence=payload.confidence,
        location=payload.location,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )
