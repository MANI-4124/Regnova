from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class DocumentVersionStatus(str, Enum):
    """
    Narrowed from FR-04's own eight-state list (Uploading -> Scanning
    -> Processing -> Extracted -> Review Required -> Verified;
    alternate terminal Rejected/Failed/Quarantined) - see CLAUDE.md
    "Document storage and versioning" and "Malware scanning".

    SCANNING and FAILED are now real (added alongside malware scanning -
    see CLAUDE.md "Malware scanning"): SCANNING has a genuine,
    measurable duration (a synchronous network round trip to the
    scanner, possibly a timeout), unlike UPLOADING below, and FAILED is
    reachable when the scanner itself couldn't be reached or return a
    conclusive answer. QUARANTINED is now reachable two ways: manually
    (quarantine(), a human reviewer's own decision, unchanged) and
    automatically (an INFECTED scan result - no human ever sees an
    infected file for review).

    PROCESSING is now real too (added alongside document extraction -
    see CLAUDE.md "Document extraction"): a genuine, measurable
    duration (a synchronous vision-model call, possibly a timeout),
    same reasoning as SCANNING. Entered only for a document_type with a
    shipped extraction schema (app.extraction.EXTRACTION_SCHEMAS) -
    skipped entirely, not entered-and-no-op'd, for any other type.

    EXTRACTED deliberately does NOT become a real status value, despite
    FR-04 naming it - a considered call, not an oversight. Unlike
    SCANNING (which forks into three behaviourally different outcomes -
    REVIEW_REQUIRED/QUARANTINED/FAILED, each meaning something
    different a caller must act on differently), PROCESSING has exactly
    ONE outcome regardless of extraction success or failure:
    REVIEW_REQUIRED, always - extraction failure must never block
    anything (graceful degradation: the document stays fully usable via
    manual entry). "Succeeded with fields" vs. "failed, no fields" is
    real information, but it's INFORMATIONAL, not behavioural - so it's
    recorded on extraction_status/extraction_error (mirroring
    malware_signature/scan_error's own side-column pattern for SCANNING)
    rather than forking the status enum for a distinction nothing acts
    on differently.

    UPLOADING remains excluded, on the same "don't model a state
    nothing rests in" principle: nothing gates the moment between
    bytes-received and SCANNING, so a version is created directly in
    SCANNING rather than passing through a persisted-but-instantaneous
    UPLOADED row-state that would never actually be observed at rest.
    """

    SCANNING = "SCANNING"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"


class DocumentVersion(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Immutable binary + metadata snapshot of a Document (C8, FR-04:
    "Document Version is immutable. Replacement creates a new version
    and preserves links/history"). The binary itself lives in
    app/storage/ (see DocumentStorage), addressed by `checksum` - never
    touched once written; only this row's own status/review fields
    ever change after creation.
    """

    __tablename__ = "document_versions"

    __table_args__ = (
        Index("ix_document_versions_document_id", "document_id"),
        Index("ix_document_versions_organization_id", "organization_id"),
        Index("ix_document_versions_status", "status"),
        Index("ix_document_versions_checksum", "checksum"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Denormalized, same "duplicate a scoping FK for query convenience"
    # precedent as ProductVersion carrying both organization_id and
    # product_id.
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Simple sequential counter per document, for human display only -
    # "current" is derived from superseded_by_id IS NULL, not from this.
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    checksum: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    storage_backend: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    original_filename: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    # The SNIFFED content type (see service.py:sniff_content_type),
    # not necessarily the client-supplied header verbatim - AC-FR-04's
    # own "MIME mismatch" edge case is exactly what sniffing guards
    # against.
    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DocumentVersionStatus.REVIEW_REQUIRED.value,
    )

    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Review (verify/reject/quarantine - see DocumentVersionService) ---
    # Shared across all three transitions rather than three separate
    # reviewer/timestamp pairs, since exactly one of them ever fires per
    # version - same "one shared field, whichever transition writes it"
    # shape as Finding.decided_by_user_id.

    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --- Scan (SCANNING -> REVIEW_REQUIRED/QUARANTINED/FAILED) ---
    # Dedicated, queryable columns rather than overloading review_note,
    # which means "why a HUMAN decided this" - these are system-
    # written, no reviewer involved. See CLAUDE.md "Malware scanning".

    malware_signature: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    scan_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --- Extraction (PROCESSING -> REVIEW_REQUIRED, always) ---
    # Same "dedicated column, not overloaded review_note" precedent as
    # the scan columns above - system-written, no reviewer involved.
    # null means no extraction schema exists yet for this document_type
    # (PROCESSING was never entered) - not a third status value, see
    # DocumentVersionStatus's own docstring. See CLAUDE.md "Document
    # extraction".

    extraction_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    extraction_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    document = relationship(
        "Document",
        back_populates="versions",
    )

    fields = relationship(
        "DocumentField",
        back_populates="document_version",
        cascade="all, delete-orphan",
    )


class DocumentField(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Stable identity of one structured field on a DocumentVersion (e.g.
    "expiry_date" on a GMP certificate, per C8.1's per-document-type
    field lists). Never holds the value itself - see
    DocumentFieldRevision below, which mirrors Finding/FindingRevision's
    "stable anchor + append-only revisions" split. Load-bearing here,
    not just precedent-following: AC-FR-04-02 requires corrections to
    create a revision and an audit event, not overwrite a value in
    place.
    """

    __tablename__ = "document_fields"

    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "field_key",
            name="uq_document_field_key",
        ),
        Index("ix_document_fields_document_version_id", "document_version_id"),
    )

    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    field_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    document_version = relationship(
        "DocumentVersion",
        back_populates="fields",
    )

    revisions = relationship(
        "DocumentFieldRevision",
        back_populates="document_field",
        order_by="DocumentFieldRevision.revision_number",
    )


class DocumentFieldRevision(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Immutable per-correction history of one DocumentField's value -
    never updated in place. `method` defaults to "MANUAL"; document
    extraction (see CLAUDE.md "Document extraction") writes rows with
    method="AI_EXTRACTED" plus ai_model_identifier/ai_prompt_version -
    the future pass this docstring originally anticipated, landed
    without restructuring anything, exactly as predicted.

    `confidence` is nullable and defaults to null, not 1.0 - a human
    not having expressed doubt about a value isn't the same claim as
    the value being certain, and null keeps a future "flag this as
    uncertain" affordance open without this ticket having already
    claimed perfection on every manually-entered field. If a future
    consumer (the engine-wiring ticket) needs a concrete number where
    none was recorded, defaulting null to 1.0 is that ticket's decision
    to make explicitly at the point of use - not baked in at write time
    here.
    """

    __tablename__ = "document_field_revisions"

    __table_args__ = (
        UniqueConstraint(
            "document_field_id",
            "revision_number",
            name="uq_document_field_revision_number",
        ),
        Index("ix_document_field_revisions_document_field_id", "document_field_id"),
    )

    document_field_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_fields.id", ondelete="CASCADE"),
        nullable=False,
    )

    revision_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    value: Mapped[Any] = mapped_column(
        _JSON,
        nullable=False,
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    method: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="MANUAL",
    )

    # Provisional {"page": ..., "region": ...} shape, same as
    # FindingRevision.observed_location - pending C8's real Document/
    # page/region model, which doesn't exist yet.
    location: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    entered_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- AI lineage (method == "AI_EXTRACTED" only) ---
    # Same shape as FindingRevision's own AI lineage group. Null for
    # every MANUAL revision.

    ai_model_identifier: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    ai_prompt_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    document_field = relationship(
        "DocumentField",
        back_populates="revisions",
    )
