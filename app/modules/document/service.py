from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from .exceptions import DocumentNotFound
from .models import Document
from .repository import DocumentRepository
from .schemas import DocumentCreate


class DocumentService:
    """
    Business logic for Document. Thin - see models.py for why
    document_type lives here rather than on DocumentVersion.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = DocumentRepository(db)

    def get_all(
        self,
        organization_id: UUID,
        document_type: str | None = None,
    ) -> list[Document]:
        return self.repository.get_all(organization_id, document_type)

    def get_by_id(
        self,
        organization_id: UUID,
        document_id: UUID,
    ) -> Document:
        document = self.repository.get_by_id(organization_id, document_id)

        if document is None:
            raise DocumentNotFound()

        return document

    def create(
        self,
        organization_id: UUID,
        payload: DocumentCreate,
        actor_user_id: UUID | None = None,
    ) -> Document:
        document = Document(
            organization_id=organization_id,
            document_type=payload.document_type.value,
            notes=payload.notes,
            created_by_user_id=actor_user_id,
        )

        self.repository.create(document)
        self.db.commit()

        return document
