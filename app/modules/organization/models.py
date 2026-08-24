from __future__ import annotations

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins import UUIDMixin, TimestampMixin


class Organization(UUIDMixin, TimestampMixin, Base):
    """
    Organization entity.
    """

    __tablename__ = "organizations"

    __table_args__ = (
        # At most one Organization may represent RegNova itself ("tenant
        # zero") - structural, not app-trust: internal_role_assignment's
        # entire enforcement of "no customer account can hold an
        # internal role" depends on there being exactly one unambiguous
        # answer to "which org is internal". Same partial-unique-index
        # mechanism as ProductMarketState's "at most one ACTIVE row per
        # (org, product, market)" - needs both postgresql_where and
        # sqlite_where to render as a genuine partial index on both
        # dialects.
        Index(
            "uq_organizations_single_internal",
            "is_internal",
            unique=True,
            postgresql_where=text("is_internal = true"),
            sqlite_where=text("is_internal = 1"),
        ),
    )

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

    # True for exactly one row: RegNova's own "tenant zero" organization,
    # whose Users are RegNova staff rather than customer-org accounts.
    # Never settable via the Create/Update API - no field for it in
    # organization/schemas.py - only ever set by a direct DB/seed
    # operation, same "structural, not API-driven" principle as
    # User.is_permanent_admin.
    is_internal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
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