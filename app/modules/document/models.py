from __future__ import annotations

from enum import Enum
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class DocumentType(str, Enum):
    """
    C8.1's minimum V1 extraction schemas, closed rather than an open
    string the way obligation_type/verification_level are elsewhere in
    this codebase - unlike those, C8.1 gives a genuinely finite,
    already-confirmed list. SAFETY_ASSESSMENT_REPORT is the eighth
    schema recorded in CLAUDE.md's "Regulatory content decisions"
    section, not part of C8.1's original seven. This enum only
    classifies WHICH document a file is - the per-type structured
    extraction schemas themselves (OCR/extraction) are a separate,
    later project, not built here.
    """

    FORMULA_INCI = "FORMULA_INCI"
    ARTWORK = "ARTWORK"
    GMP_CERTIFICATE = "GMP_CERTIFICATE"
    CFS = "CFS"
    COA = "COA"
    STABILITY_REPORT = "STABILITY_REPORT"
    LOA = "LOA"
    SAFETY_ASSESSMENT_REPORT = "SAFETY_ASSESSMENT_REPORT"


class Document(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Logical document record (C8) - customer data, organization-scoped
    like Product/ProductMarketState, unlike Source/Requirement/Rule.
    Deliberately NOT product-scoped: the same document (e.g. one
    facility's GMP certificate) is meant to be linkable to several
    products - see the `evidence` module, which is where that scoping
    actually happens.

    `document_type` lives here, not on DocumentVersion - a deliberate
    deviation from the Source/Requirement/Rule "everything descriptive
    lives on the Version" convention. See CLAUDE.md "Document storage
    and versioning" for the reasoning: classification is closer to
    Requirement.human_reference (an identity property) than to
    SourceVersion.title (reviewable content that can legitimately
    change between versions) - a GMP certificate replaced by a newer
    GMP certificate is still a GMP certificate; changing type would
    really mean "this is a different logical document."
    """

    __tablename__ = "documents"

    __table_args__ = (
        Index("ix_documents_organization_id", "organization_id"),
        Index("ix_documents_document_type", "document_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    document_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        order_by="DocumentVersion.version_number",
    )
