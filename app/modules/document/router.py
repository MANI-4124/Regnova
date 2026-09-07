from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import require_employee
from app.modules.user.models import User

from .schemas import DocumentCreate, DocumentResponse
from .service import DocumentService

router = APIRouter(
    prefix="/documents",
    tags=["Documents"],
)


def get_document_service(
    db: Session = Depends(get_db_session),
) -> DocumentService:
    return DocumentService(db)


@router.get(
    "",
    response_model=list[DocumentResponse],
)
def get_documents(
    document_type: str | None = None,
    current_user: User = Depends(require_employee),
    service: DocumentService = Depends(get_document_service),
):
    return service.get_all(current_user.organization_id, document_type)


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
)
def get_document(
    document_id: UUID,
    current_user: User = Depends(require_employee),
    service: DocumentService = Depends(get_document_service),
):
    return service.get_by_id(current_user.organization_id, document_id)


@router.post(
    "",
    response_model=DocumentResponse,
)
def create_document(
    payload: DocumentCreate,
    current_user: User = Depends(require_employee),
    service: DocumentService = Depends(get_document_service),
):
    return service.create(
        current_user.organization_id,
        payload,
        actor_user_id=current_user.id,
    )
