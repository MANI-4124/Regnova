from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class SourceVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class TranslationStatus(str, Enum):
    ORIGINAL = "ORIGINAL"
    OFFICIAL_TRANSLATION = "OFFICIAL_TRANSLATION"
    UNOFFICIAL_TRANSLATION = "UNOFFICIAL_TRANSLATION"


class SourceVersion(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Immutable-once-published content snapshot of a Source, captured at a
    date/effective period (C4). Carries the descriptive/identity fields
    C4.1 lists under "Required Source Version fields" (title, jurisdiction,
    tier, etc.) rather than the parent Source, since those can change
    between versions of the same source.
    """

    __tablename__ = "source_versions"

    __table_args__ = (
        Index(
            "ix_source_versions_source_id",
            "source_id",
        ),
        Index(
            "ix_source_versions_status",
            "status",
        ),
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "sources.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    # --- identity / display (C4.1 bullet 1) ---

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    issuing_authority: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    jurisdiction: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    tier: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    source_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    official_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # --- checksums / language (bullet 2) ---

    file_checksum: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    canonical_text_checksum: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    language: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    translation_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=TranslationStatus.ORIGINAL.value,
    )

    retrieval_method: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --- dates + supersession (bullet 3, C9 bitemporal) ---

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "source_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "source_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # --- lifecycle (bullet 5) ---

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=SourceVersionStatus.DRAFT.value,
    )

    author_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    reviewer_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # --- licensing (bullet 6) ---

    license_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    usage_restrictions: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_full_text_displayable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # --- curation/provenance note - not a named C4.1 field, added so
    # curators can record how a version was sourced (e.g. AI-assisted
    # research pending RA verification), distinct from license_notes ---

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source = relationship(
        "Source",
        back_populates="versions",
    )

    locations = relationship(
        "SourceLocation",
        back_populates="source_version",
        cascade="all, delete-orphan",
    )
