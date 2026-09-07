from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.document_version.exceptions import DocumentVersionNotFound
from app.modules.document_version.models import DocumentVersionStatus
from app.modules.document_version.repository import DocumentVersionRepository
from app.modules.product.exceptions import ProductNotFound
from app.modules.product.repository import ProductRepository
from app.modules.requirement_version.exceptions import RequirementVersionNotFound
from app.modules.requirement_version.repository import RequirementVersionRepository

from .exceptions import (
    EvidenceAlreadyLinked,
    EvidenceDocumentVersionNotVerified,
    EvidenceNotFound,
)
from .models import Evidence
from .repository import EvidenceRepository
from .schemas import EvidenceCreate


class EvidenceService:
    """
    Business logic for Evidence - see models.py for why this is one
    collapsed table rather than C8's separate Evidence + Evidence Link.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = EvidenceRepository(db)
        self.products = ProductRepository(db)
        self.document_versions = DocumentVersionRepository(db)
        self.requirement_versions = RequirementVersionRepository(db)

    def get_all(
        self,
        organization_id: UUID,
        product_id: UUID | None = None,
    ) -> list[Evidence]:
        return self.repository.get_all(organization_id, product_id)

    def get_by_id(
        self,
        organization_id: UUID,
        evidence_id: UUID,
    ) -> Evidence:
        evidence = self.repository.get_by_id(organization_id, evidence_id)

        if evidence is None:
            raise EvidenceNotFound()

        return evidence

    def create(
        self,
        organization_id: UUID,
        payload: EvidenceCreate,
        actor_user_id: UUID | None = None,
    ) -> Evidence:
        if self.products.get_by_id(organization_id, payload.product_id) is None:
            raise ProductNotFound()

        document_version = self.document_versions.get_by_id_for_org(
            organization_id,
            payload.document_version_id,
        )

        if document_version is None:
            raise DocumentVersionNotFound()

        # AC-FR-04-01's compensating control, not a real scan result -
        # see CLAUDE.md "Document storage and versioning".
        if document_version.status != DocumentVersionStatus.VERIFIED.value:
            raise EvidenceDocumentVersionNotVerified()

        if payload.requirement_version_id is not None:
            if self.requirement_versions.get_by_id_only(payload.requirement_version_id) is None:
                raise RequirementVersionNotFound()

        # Explicit pre-check, not just the DB constraint - see
        # EvidenceRepository.find_existing_link for why NULL
        # requirement_version_id needs it too.
        if self.repository.find_existing_link(
            organization_id,
            payload.document_version_id,
            payload.product_id,
            payload.requirement_version_id,
        ) is not None:
            raise EvidenceAlreadyLinked()

        evidence = Evidence(
            organization_id=organization_id,
            document_version_id=payload.document_version_id,
            product_id=payload.product_id,
            requirement_version_id=payload.requirement_version_id,
            notes=payload.notes,
            created_by_user_id=actor_user_id,
        )

        try:
            self.repository.create(evidence)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise EvidenceAlreadyLinked()

        return evidence

    def delete(
        self,
        organization_id: UUID,
        evidence_id: UUID,
    ) -> None:
        evidence = self.get_by_id(organization_id, evidence_id)

        self.repository.delete(evidence)
        self.db.commit()
