from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository
from app.modules.document.models import Document
from app.modules.document_version.models import DocumentVersion, DocumentVersionStatus

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

    def get_current_verified_for_product_and_document_type(
        self,
        organization_id: UUID,
        product_id: UUID,
        document_type: str,
    ) -> list[Evidence]:
        """
        Real DOCUMENTS-checklist resolution (see CLAUDE.md "Assessment
        engine") - only Evidence that's both is_current and whose
        DocumentVersion is VERIFIED; the VERIFIED check is redundant
        with is_current today (a version can only reach VERIFIED once
        and Evidence can only be created against one already VERIFIED -
        see "Document storage and versioning"), kept anyway as cheap,
        forward-compatible insurance in case a revoke-verification
        transition is ever added to document_version.

        Document.document_type matched case-INSENSITIVELY - a real,
        present-day mismatch: existing RequirementVersion.obligation_type
        content is authored lowercase snake_case, DocumentType is a
        closed uppercase enum. This is a shim, not a fix - new
        regulatory content should use DocumentType values verbatim so
        this normalization stops being load-bearing. Ordered by
        created_at/id for deterministic multi-document ordering, since
        the caller hashes this list for reuse comparison and a
        nondeterministic DB row order would produce spurious hash
        mismatches between two calls that saw identical data.
        """
        statement = (
            select(Evidence)
            .join(DocumentVersion, Evidence.document_version_id == DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(
                Evidence.organization_id == organization_id,
                Evidence.product_id == product_id,
                Evidence.is_current.is_(True),
                DocumentVersion.status == DocumentVersionStatus.VERIFIED.value,
                func.upper(Document.document_type) == document_type.upper(),
            )
            .order_by(Evidence.created_at, Evidence.id)
        )

        return list(self.db.scalars(statement))

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
