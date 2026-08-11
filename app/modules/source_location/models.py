from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class SourceLocation(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Exact citation coordinate within a SourceVersion (C4: "addresses an
    exact section, article, schedule, page, table or paragraph").

    A single row can carry several coordinate dimensions at once
    (e.g. section + schedule + page together), since real regulatory
    citations are usually compound rather than a single coordinate type.
    At least one of the coordinate fields must be set (enforced in
    schemas.py, not here).
    """

    __tablename__ = "source_locations"

    __table_args__ = (
        Index(
            "ix_source_locations_source_version_id",
            "source_version_id",
        ),
    )

    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "source_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    article: Mapped[str | None] = mapped_column(String(100), nullable=True)
    schedule: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Named table_ref, not table - "table" is a reserved SQL keyword;
    # avoiding it entirely rather than relying on dialect auto-quoting.
    table_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    paragraph: Mapped[str | None] = mapped_column(String(100), nullable=True)

    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    ocr_confidence: Mapped[float | None] = mapped_column(
        Numeric(4, 3),
        nullable=True,
    )

    is_manually_corrected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    original_ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    corrected_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    source_version = relationship(
        "SourceVersion",
        back_populates="locations",
    )
