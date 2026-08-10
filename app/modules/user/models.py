from __future__ import annotations

from uuid import UUID
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class User(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Organization User.
    """

    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "email",
            name="uq_user_email_per_org",
        ),
        Index(
            "ix_users_organization_id",
            "organization_id",
        ),
        Index(
            "ix_users_role_id",
            "role_id",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    role_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "roles.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    phone: Mapped[str | None] = mapped_column(
        String(25),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    organization = relationship(
        "Organization",
        back_populates="users",
    )

    role = relationship(
        "Role",
        back_populates="users",
    )