from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import UnknownBehavior
from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class RequirementVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class RequirementDimension(str, Enum):
    CLASSIFICATION_ELIGIBILITY = "CLASSIFICATION_ELIGIBILITY"
    INGREDIENTS = "INGREDIENTS"
    CLAIMS = "CLAIMS"
    LABEL = "LABEL"
    DOCUMENTS = "DOCUMENTS"
    TESTING = "TESTING"
    REPRESENTATION = "REPRESENTATION"
    REGISTRATION_READINESS = "REGISTRATION_READINESS"


class RequirementSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MODERATE = "MODERATE"
    MINOR = "MINOR"
    INFORMATIONAL = "INFORMATIONAL"


class AuthorityInterpretationLabel(str, Enum):
    AUTHORITY_REQUIREMENT = "AUTHORITY_REQUIREMENT"
    RECOGNISED_STANDARD = "RECOGNISED_STANDARD"
    REGNOVA_INTERPRETATION = "REGNOVA_INTERPRETATION"
    SECONDARY_RESEARCH = "SECONDARY_RESEARCH"


_JSON = JSON().with_variant(JSONB(), "postgresql")


class RequirementVersion(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Effective, source-backed expression of a Requirement for a defined
    context (C5). Carries all eight C5 field groups - see CLAUDE.md
    "Regulatory content: requirement / requirement_version" for the
    Requirement/RequirementVersion split reasoning.
    """

    __tablename__ = "requirement_versions"

    __table_args__ = (
        Index(
            "ix_requirement_versions_requirement_id",
            "requirement_id",
        ),
        Index(
            "ix_requirement_versions_status",
            "status",
        ),
        Index(
            "ix_requirement_versions_dimension",
            "dimension",
        ),
    )

    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "requirements.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=RequirementVersionStatus.DRAFT.value,
    )

    # --- Scope ---

    jurisdiction: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    market: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    authority: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    subcategory: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    pathway: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    dimension: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    context: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    context_schema_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    context_schema_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # --- Applicability ---

    applicability_predicate: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    applicability_predicate_schema_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    applicability_predicate_schema_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    applicability_required_inputs: Mapped[list[Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    unknown_behavior: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=UnknownBehavior.HUMAN_REVIEW.value,
    )

    # --- Obligation ---

    obligation_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    canonical_statement: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    customer_safe_explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --- Evidence policy ---

    accepted_evidence_types: Mapped[list[Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    field_checks: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    validity_scope_rules: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    # Open string, not an enum - "verification level" isn't independently
    # defined anywhere in the spec; needs real definition from RegNova's
    # Regulatory Knowledge Lead before it's worth constraining.
    verification_level: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --- Risk ---

    default_severity: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    is_hard_gate: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    importance_weight: Mapped[float | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )

    approval_policy: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --- Provenance ---

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

    # Independently settable, not derived from linked source tiers.
    authority_interpretation_label: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    # --- Temporal (C9 bitemporal - same field names as SourceVersion) ---

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

    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "requirement_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "requirement_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    requirement = relationship(
        "Requirement",
        back_populates="versions",
    )

    source_locations = relationship(
        "SourceLocation",
        secondary="requirement_version_source_locations",
    )

    @property
    def source_location_ids(self) -> list[UUID]:
        return [location.id for location in self.source_locations]


class RequirementVersionSourceLocation(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Provenance link: which exact SourceLocation(s) back a
    RequirementVersion. Plain association table, no independent
    lifecycle - managed through RequirementVersion's own service.
    """

    __tablename__ = "requirement_version_source_locations"

    __table_args__ = (
        UniqueConstraint(
            "requirement_version_id",
            "source_location_id",
            name="uq_requirement_version_source_location",
        ),
        Index(
            "ix_rvsl_requirement_version_id",
            "requirement_version_id",
        ),
        Index(
            "ix_rvsl_source_location_id",
            "source_location_id",
        ),
    )

    requirement_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "requirement_versions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    source_location_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "source_locations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
