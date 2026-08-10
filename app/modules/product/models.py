from __future__ import annotations

from uuid import UUID
from enum import Enum

from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
    Text,
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


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"


class Product(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "products"

    __table_args__ = (
        Index(
            "ix_products_organization_id",
            "organization_id",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    brand: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ProductStatus.DRAFT.value,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    organization = relationship(
        "Organization",
    )

    versions = relationship(
        "ProductVersion",
        back_populates="product",
        cascade="all, delete-orphan",
    )