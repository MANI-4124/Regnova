from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class Evidence(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Links one DocumentVersion to a Product (and optionally a specific
    RequirementVersion) - C8's entity catalog names Evidence and
    Evidence Link as two separate entities; collapsed into one table
    here for V1.

    Why collapsed: every evidence item is document-backed today, and
    the "one item, many links" reuse case C8/FR-04 both call out is
    fully served by several Evidence rows sharing the same
    document_version_id - the same shape
    RequirementVersionSourceLocation already uses in this codebase for
    a reusable SourceLocation linked from many RequirementVersions, with
    no separate "citation identity" object needed beyond SourceLocation
    itself. Building a near-empty intermediate Evidence identity ahead
    of a second (non-document) evidence source that would actually use
    it would repeat a pattern this codebase has avoided elsewhere (see
    Applicability Predicate staying inline JSON rather than a
    speculative normalized entity).

    C8's fuller Evidence field list (type, subject, issuer, claims
    supported, validity, scope) is likewise not duplicated here - that
    semantic content lives on DocumentField/DocumentFieldRevision
    instead (document_version module), the schema-versioned,
    document-type-specific home C8.1 already gives it, and where OCR
    will eventually populate it too. Storing it a second time here
    would just be the same data with no rule keeping it in sync.

    Un-collapse trigger: the day a non-document evidence type (authority
    record, test result, human attestation) is needed, reintroduce a
    real Evidence identity above this table the way C8 describes, and
    repoint what's here to become the link row under it. See CLAUDE.md
    "Document storage and versioning".
    """

    __tablename__ = "evidence"

    __table_args__ = (
        # Only catches the non-null requirement_version_id case - SQL
        # treats NULL as distinct from NULL, so two rows sharing the
        # same (document_version_id, product_id) with
        # requirement_version_id both NULL do not violate this. The
        # NULL case is caught by an explicit pre-check instead - see
        # EvidenceRepository.find_existing_link.
        UniqueConstraint(
            "document_version_id",
            "product_id",
            "requirement_version_id",
            name="uq_evidence_link",
        ),
        Index("ix_evidence_organization_id", "organization_id"),
        Index("ix_evidence_document_version_id", "document_version_id"),
        Index("ix_evidence_product_id", "product_id"),
        Index("ix_evidence_requirement_version_id", "requirement_version_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Nullable - C8 names Requirement/Finding/Claim/Case as targets;
    # this ticket only wires Requirement, and "linked to this product,
    # not yet a specific requirement" is itself a valid intermediate
    # state.
    requirement_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("requirement_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Currency - same is_current/stale_reason shape as StateSnapshot,
    # built now (not deferred) per explicit instruction. Set by
    # DocumentVersionService.create() when the DocumentVersion this
    # Evidence points at gets superseded by a new upload - see CLAUDE.md.

    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    stale_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
