from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Document


class DocumentRepository(
    BaseRepository[Document],
):
    """
    Repository for Document. Organization-scoped, like Product/User/
    Role - customer data, unlike the regulatory-content family
    (Source/Requirement/Rule).
    """

    def __init__(
        self,
        db: Session,
    ):
        super().__init__(
            db,
            Document,
        )

    def get_all(
        self,
        organization_id: UUID,
        document_type: str | None = None,
    ) -> list[Document]:
        statement = select(Document).where(
            Document.organization_id == organization_id,
        )

        if document_type is not None:
            statement = statement.where(Document.document_type == document_type)

        statement = statement.order_by(Document.created_at.desc())

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        document_id: UUID,
    ) -> Document | None:
        statement = select(Document).where(
            Document.id == document_id,
            Document.organization_id == organization_id,
        )

        return self.db.scalar(statement)
