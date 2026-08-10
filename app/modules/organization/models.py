from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins import UUIDMixin, TimestampMixin


class Organization(UUIDMixin, TimestampMixin, Base):
    """
    Organization entity.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    industry: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    country: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    
    roles = relationship(
    "Role",
    back_populates="organization",
    cascade="all, delete-orphan",
)
    users = relationship(
    "User",
    back_populates="organization",
    cascade="all, delete-orphan",
)