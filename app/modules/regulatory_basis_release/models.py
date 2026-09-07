from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class RegulatoryBasisReleaseStatus(str, Enum):
    """
    Deliberately 3 states, not the 6-state DRAFT/IN_REVIEW/VERIFIED/
    ACTIVE/SUPERSEDED/ARCHIVED used elsewhere - C9.1 calls Release
    immutable outright (no editable draft phase), and line 945's
    lifecycle enumeration names Source/Requirement/Rule Versions but
    excludes Release. Interpretation, not a certainty.
    """

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


_JSON = JSON().with_variant(JSONB(), "postgresql")


class RegulatoryBasisRelease(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Immutable, content-addressed manifest of approved Source/
    Requirement/Rule Versions (C9.1). No organization_id - same
    ownership model as Source/Requirement/Rule. See CLAUDE.md
    "Regulatory content: regulatory_basis_release" for the full
    reasoning behind every field here.
    """

    __tablename__ = "regulatory_basis_releases"

    __table_args__ = (
        Index("ix_rbr_jurisdiction", "jurisdiction"),
        Index("ix_rbr_market", "market"),
        Index("ix_rbr_category", "category"),
        Index("ix_rbr_status", "status"),
    )

    jurisdiction: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Non-authoritative going forward, same status as
    # ProductMarketState.market - see CLAUDE.md "Category scoping".
    # `jurisdiction` + `category` are the real resolution key as of
    # this fix; RegulatoryBasisReleaseRepository.get_active_for_jurisdiction_and_category
    # no longer reads this field at all.
    market: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Added by the category-scoping fix - NOT NULL, no default. Every
    # requirement_version included in this release must share this
    # exact value (validated in RegulatoryBasisReleaseService.create(),
    # not just recorded here) - see CLAUDE.md "Category scoping".
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=RegulatoryBasisReleaseStatus.ACTIVE.value,
    )

    # Content-addressed integrity/dedup mechanism - SHA-256 over the
    # sorted set of included version ids + configuration, computed once
    # at creation (never recomputed - the release is immutable).
    content_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )

    configuration: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    configuration_schema_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    configuration_schema_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
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

    verified_at: Mapped[datetime | None] = mapped_column(
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
            "regulatory_basis_releases.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "regulatory_basis_releases.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source_versions = relationship(
        "SourceVersion",
        secondary="regulatory_basis_release_source_versions",
    )

    requirement_versions = relationship(
        "RequirementVersion",
        secondary="regulatory_basis_release_requirement_versions",
    )

    rule_versions = relationship(
        "RuleVersion",
        secondary="regulatory_basis_release_rule_versions",
    )

    @property
    def source_version_ids(self) -> list[UUID]:
        return [v.id for v in self.source_versions]

    @property
    def requirement_version_ids(self) -> list[UUID]:
        return [v.id for v in self.requirement_versions]

    @property
    def rule_version_ids(self) -> list[UUID]:
        return [v.id for v in self.rule_versions]


class RegulatoryBasisReleaseSourceVersion(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "regulatory_basis_release_source_versions"

    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "source_version_id",
            name="uq_rbr_source_version",
        ),
        Index("ix_rbrsv_release_id", "release_id"),
        Index("ix_rbrsv_source_version_id", "source_version_id"),
    )

    release_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "regulatory_basis_releases.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "source_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )


class RegulatoryBasisReleaseRequirementVersion(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "regulatory_basis_release_requirement_versions"

    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "requirement_version_id",
            name="uq_rbr_requirement_version",
        ),
        Index("ix_rbrrv_release_id", "release_id"),
        Index("ix_rbrrv_requirement_version_id", "requirement_version_id"),
    )

    release_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "regulatory_basis_releases.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    requirement_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "requirement_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )


class RegulatoryBasisReleaseRuleVersion(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "regulatory_basis_release_rule_versions"

    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "rule_version_id",
            name="uq_rbr_rule_version",
        ),
        Index("ix_rbrulv_release_id", "release_id"),
        Index("ix_rbrulv_rule_version_id", "rule_version_id"),
    )

    release_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "regulatory_basis_releases.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    rule_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "rule_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
