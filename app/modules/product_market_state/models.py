from __future__ import annotations

from enum import Enum
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class ProductMarketStateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProductMarketStateGate(str, Enum):
    G0 = "G0"  # Assessment Incomplete
    G1 = "G1"  # Not Ready
    G2 = "G2"  # Customer Action Required
    G3 = "G3"  # RegNova Review Required
    G4 = "G4"  # Ready for Registration
    G5 = "G5"  # Authority Confirmed


class ProductMarketState(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Persistent workspace binding a Product to a market (FR-03) - a
    single mutable row per (organization_id, product_id, market), not
    a versioned entity like Source/Requirement/Rule/Release. See
    CLAUDE.md "Product x Market state" for the full reasoning.
    """

    __tablename__ = "product_market_states"

    __table_args__ = (
        Index("ix_pms_organization_id", "organization_id"),
        Index("ix_pms_product_id", "product_id"),
        Index("ix_pms_market", "market"),
        Index("ix_pms_jurisdiction", "jurisdiction"),
        # Partial unique index: at most one ACTIVE row per (org, product,
        # jurisdiction) - moved from `market` to `jurisdiction` as part
        # of the category-scoping fix (see CLAUDE.md "Category
        # scoping"): jurisdiction is now the real pinning key, `market`
        # is kept only as a non-authoritative legacy field, and two rows
        # differing only in `market` for the same real jurisdiction
        # would otherwise both be eligible to pin against the same
        # release. Needs BOTH postgresql_where and sqlite_where to
        # render as a genuine partial index on both dialects - verified
        # empirically that omitting sqlite_where silently produces a
        # full (non-partial) unique index on SQLite instead.
        Index(
            "uq_pms_active_per_product_jurisdiction",
            "organization_id",
            "product_id",
            "jurisdiction",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
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

    product_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "product_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # Non-authoritative going forward - see CLAUDE.md "Category
    # scoping": `jurisdiction` below is now the real pinning key.
    # market's own long-term fate (display label / deprecated /
    # a genuine third axis) is an open question this fix does not
    # resolve; kept as-is (still required) rather than removed.
    market: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # The real pinning key, distinct from `market` above - added by the
    # category-scoping fix. Immutable after creation (not exposed on
    # ProductMarketStateUpdate), same as market's own existing behavior.
    jurisdiction: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    regulatory_basis_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "regulatory_basis_releases.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    gate: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=ProductMarketStateGate.G0.value,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ProductMarketStateStatus.ACTIVE.value,
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
