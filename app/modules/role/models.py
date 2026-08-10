from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    Boolean,
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


class Role(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Organization Role.
    """

    __tablename__ = "roles"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_role_code_per_org",
        ),
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_role_name_per_org",
        ),
        Index(
            "ix_roles_organization_id",
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

    code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    organization = relationship(
        "Organization",
        back_populates="roles",
    )

    users = relationship(
    "User",
    back_populates="role",
)