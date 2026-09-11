from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import DocumentField, DocumentFieldRevision, DocumentVersion, DocumentVersionStatus


class DocumentVersionRepository(
    BaseRepository[DocumentVersion],
):

    def __init__(self, db: Session):
        super().__init__(db, DocumentVersion)

    def get_all(
        self,
        organization_id: UUID,
        document_id: UUID,
    ) -> list[DocumentVersion]:
        statement = (
            select(DocumentVersion)
            .where(
                DocumentVersion.organization_id == organization_id,
                DocumentVersion.document_id == document_id,
            )
            .order_by(DocumentVersion.version_number.desc())
        )

        return list(self.db.scalars(statement))

    def get_all_verified_for_organization(
        self,
        organization_id: UUID,
    ) -> list[DocumentVersion]:
        """
        Org-wide, current + VERIFIED only - Ask RegNova's
        DOCUMENTS_EXPIRING_WITHIN intent (see CLAUDE.md "Ask RegNova")
        must never surface an unreviewed or superseded version's fields
        as if they were live facts about the portfolio.
        """
        statement = select(DocumentVersion).where(
            DocumentVersion.organization_id == organization_id,
            DocumentVersion.status == DocumentVersionStatus.VERIFIED.value,
            DocumentVersion.superseded_by_id.is_(None),
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentVersion | None:
        statement = select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document_id,
            DocumentVersion.organization_id == organization_id,
        )

        return self.db.scalar(statement)

    def get_by_id_for_org(
        self,
        organization_id: UUID,
        version_id: UUID,
    ) -> DocumentVersion | None:
        """
        Org-scoped lookup by id alone, no document_id - used by
        evidence, which only ever receives document_version_id (flat
        route), not the parent document_id. Same shape as
        ProductMarketStateRepository.get_by_id_only.
        """
        statement = select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.organization_id == organization_id,
        )

        return self.db.scalar(statement)

    def get_current(
        self,
        document_id: UUID,
    ) -> DocumentVersion | None:
        """
        The not-yet-superseded version of a Document - there is always
        at most one, since create() always supersedes whatever was
        current before it.
        """
        statement = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.superseded_by_id.is_(None),
        )

        return self.db.scalar(statement)

    def get_latest_version_number(
        self,
        document_id: UUID,
    ) -> int:
        statement = (
            select(DocumentVersion.version_number)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        )

        return self.db.scalar(statement) or 0


class DocumentFieldRepository(
    BaseRepository[DocumentField],
):

    def __init__(self, db: Session):
        super().__init__(db, DocumentField)

    def get_all_for_version(
        self,
        document_version_id: UUID,
    ) -> list[DocumentField]:
        statement = select(DocumentField).where(
            DocumentField.document_version_id == document_version_id,
        )

        return list(self.db.scalars(statement))

    def get_by_key(
        self,
        document_version_id: UUID,
        field_key: str,
    ) -> DocumentField | None:
        statement = select(DocumentField).where(
            DocumentField.document_version_id == document_version_id,
            DocumentField.field_key == field_key,
        )

        return self.db.scalar(statement)


class DocumentFieldRevisionRepository(
    BaseRepository[DocumentFieldRevision],
):

    def __init__(self, db: Session):
        super().__init__(db, DocumentFieldRevision)

    def get_latest_revision_number(
        self,
        document_field_id: UUID,
    ) -> int:
        statement = (
            select(DocumentFieldRevision.revision_number)
            .where(DocumentFieldRevision.document_field_id == document_field_id)
            .order_by(DocumentFieldRevision.revision_number.desc())
        )

        return self.db.scalar(statement) or 0

    def get_latest(
        self,
        document_field_id: UUID,
    ) -> DocumentFieldRevision | None:
        """
        The actual current revision row - used by the assessment engine
        wiring (see CLAUDE.md "Assessment engine") to read a field's
        current value/confidence/location, unlike
        get_latest_revision_number above (which only ever needed the
        number, to compute the next one).
        """
        statement = (
            select(DocumentFieldRevision)
            .where(DocumentFieldRevision.document_field_id == document_field_id)
            .order_by(DocumentFieldRevision.revision_number.desc())
            .limit(1)
        )

        return self.db.scalar(statement)
