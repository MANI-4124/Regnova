from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Evidence


class EvidenceRepository(
    BaseRepository[Evidence],
):

    def __init__(self, db: Session):
        super().__init__(db, Evidence)

    def get_all(
        self,
        organization_id: UUID,
        product_id: UUID | None = None,
    ) -> list[Evidence]:
        statement = select(Evidence).where(
            Evidence.organization_id == organization_id,
        )

        if product_id is not None:
            statement = statement.where(Evidence.product_id == product_id)

        statement = statement.order_by(Evidence.created_at.desc())

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        evidence_id: UUID,
    ) -> Evidence | None:
        statement = select(Evidence).where(
            Evidence.id == evidence_id,
            Evidence.organization_id == organization_id,
        )

        return self.db.scalar(statement)

    def find_existing_link(
        self,
        organization_id: UUID,
        document_version_id: UUID,
        product_id: UUID,
        requirement_version_id: UUID | None,
    ) -> Evidence | None:
        """
        Explicit duplicate check, not just the DB's own UniqueConstraint -
        SQL treats NULL as distinct from NULL, so two rows sharing the
        same (document_version_id, product_id) with requirement_version_id
        both NULL do NOT violate uq_evidence_link on either Postgres or
        SQLite. The DB constraint alone only catches the non-null case;
        this catches both, checked before every create().
        """
        conditions = [
            Evidence.organization_id == organization_id,
            Evidence.document_version_id == document_version_id,
            Evidence.product_id == product_id,
        ]

        if requirement_version_id is not None:
            conditions.append(Evidence.requirement_version_id == requirement_version_id)
        else:
            conditions.append(Evidence.requirement_version_id.is_(None))

        return self.db.scalar(select(Evidence).where(*conditions))

    def mark_stale_for_document_version(
        self,
        document_version_id: UUID,
        reason: str,
    ) -> None:
        """
        Called from DocumentVersionService.create() in the same
        transaction as a supersession, not through EvidenceService -
        same "reach into the lower layer directly" precedent as
        ProductMarketStateService flagging StateSnapshot stale via
        StateSnapshotRepository. See CLAUDE.md "Document storage and
        versioning".
        """
        statement = select(Evidence).where(
            Evidence.document_version_id == document_version_id,
            Evidence.is_current.is_(True),
        )

        for evidence in self.db.scalars(statement):
            evidence.is_current = False
            evidence.stale_reason = reason

        self.db.flush()
