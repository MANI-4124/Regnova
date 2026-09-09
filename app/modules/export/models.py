from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class ExportType(str, Enum):
    """
    FR-14's two V1 formats - PDF/DOCX-style assessment reports are
    explicitly deferred (no rendering dependency exists, layout is its
    own design question). FINDINGS_CSV is the customer-facing,
    live-data operational export ("CSV for authorized findings/tasks");
    EVIDENCE_PACK_JSON is the internal, snapshot-pinned reconstruction
    artifact ("JSON for internal evidence packs") satisfying
    AC-FR-14-01. See CLAUDE.md "Exports" for why these are treated as
    genuinely different animals, not two views of the same data.
    """

    FINDINGS_CSV = "FINDINGS_CSV"
    EVIDENCE_PACK_JSON = "EVIDENCE_PACK_JSON"


class ExportStatus(str, Enum):
    """
    FR-14's own state list is "Requested -> Generating -> Ready/Expired;
    alternate Failed." Requested/Generating collapse into GENERATING,
    committed BEFORE generation starts (mirroring AssessmentRun's own
    "a failure must still leave a visible, terminal record" precedent),
    then updated to READY or FAILED after - the caller's HTTP response
    only ever returns once one of those two is reached, since export
    generation is synchronous, this codebase's established convention.
    EXPIRED is deliberately not modeled - no expiry/TTL mechanism
    exists (matches the deferred-signed-URLs decision), same "don't
    model a state nothing can reach" principle already applied to
    DocumentVersionStatus/DimensionAssessmentState.
    """

    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"


class Export(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Generated report/data artifact (Appendix 2: "Versioned report/data
    artifact ready" -> ExportGenerated). Organization-scoped like
    Document/Evidence/ProductMarketState - customer data, even when the
    requester is an internal actor exercising the EVIDENCE_PACK_JSON
    cross-org exception (organization_id here is always the CUSTOMER
    org this export is about, never the internal requester's own
    tenant-zero org - same "whose data this is about" convention
    AuditEvent.organization_id uses everywhere).

    Reuses app/storage/DocumentStorage rather than a second storage
    abstraction - `checksum` is both the identity and the storage key,
    same content-addressed shape as DocumentVersion, giving the same
    free dedup property.
    """

    __tablename__ = "exports"

    __table_args__ = (
        Index("ix_exports_organization_id", "organization_id"),
        Index("ix_exports_product_market_state_id", "product_market_state_id"),
        Index("ix_exports_state_snapshot_id", "state_snapshot_id"),
        Index("ix_exports_status", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    export_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    product_market_state_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_market_states.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Only EVIDENCE_PACK_JSON uses this - the pinned snapshot AC-FR-14-01
    # reconstruction is built against. FINDINGS_CSV is deliberately
    # live/unpinned (see ExportType), so this stays null for it.
    state_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("state_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ExportStatus.GENERATING.value,
    )

    checksum: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    content_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    size_bytes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
