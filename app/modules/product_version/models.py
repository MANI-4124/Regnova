from __future__ import annotations

from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Index,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.core.database import Base
from app.shared.mixins.uuid import UUIDMixin
from app.shared.mixins.timestamp import TimestampMixin


class ProductVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"


class ProductVersion(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "product_versions"

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "version",
            name="uq_product_version_per_product",
        ),
        Index(
            "ix_product_versions_organization_id",
            "organization_id",
        ),
        Index(
            "ix_product_versions_product_id",
            "product_id",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "products.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Fixes the "category scoping is unmodelled" limitation (see
    # CLAUDE.md) - the specific formulation/dossier this version
    # represents is what market-readiness actually assesses, so this is
    # where a genuine reformulation-driven reclassification would show
    # up, not on Product itself. NOT NULL, no default - every real
    # product version must be deliberately classified; no NULL/sentinel
    # "uncategorized" bucket is provided (see CLAUDE.md "Category
    # scoping" for the AC-FR-03-03 connection this leaves open, not
    # closed).
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ProductVersionStatus.DRAFT.value,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    organization = relationship(
        "Organization",
    )

    product = relationship(
        "Product",
        back_populates="versions",
    )
