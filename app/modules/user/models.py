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
    text,
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
        # At most one User may hold the permanent-admin ("CEO") seat -
        # structural, not app-trust. Same partial-unique-index mechanism
        # as Organization.is_internal.
        Index(
            "uq_users_single_permanent_admin",
            "is_permanent_admin",
            unique=True,
            postgresql_where=text("is_permanent_admin = true"),
            sqlite_where=text("is_permanent_admin = 1"),
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

    # True for exactly one User: RegNova's CEO seat, structurally
    # protected against role change, deactivation and deletion by
    # anyone including other admins (UserService.update()/delete()).
    # Never settable via UserCreate/UserUpdate - no field for it in
    # user/schemas.py's write schemas - only ever set by a direct DB
    # operation, never through the API. No endpoint exists to transfer
    # this flag to a new account either (e.g. on CEO succession) -
    # deliberately: an endpoint able to move it would defeat the
    # flag's whole purpose (anyone who could call it could also use it
    # to seize the seat). Logged as a known limitation in CLAUDE.md,
    # not silently absent.
    is_permanent_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    organization = relationship(
        "Organization",
        back_populates="users",
    )

    role = relationship(
        "Role",
        back_populates="users",
    )