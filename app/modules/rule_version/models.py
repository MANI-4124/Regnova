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

from app.common.enums import UnknownBehavior
from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class RuleVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class RuleOutputType(str, Enum):
    APPLICABILITY = "APPLICABILITY"
    REQUIREMENT_RESULT = "REQUIREMENT_RESULT"
    FINDING_PROPOSAL = "FINDING_PROPOSAL"
    EVIDENCE_REQUEST = "EVIDENCE_REQUEST"
    WORKFLOW_GATE = "WORKFLOW_GATE"
    CALCULATION_COMPONENT = "CALCULATION_COMPONENT"


_JSON = JSON().with_variant(JSONB(), "postgresql")


class RuleVersion(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Executable regulatory logic (C6). requirement_version_id is a
    nullable single FK, not many-to-many - C6's Provenance row marks
    "Source Location(s)" plural but not "Requirement Version", and a
    rule whose output_type is CALCULATION_COMPONENT may not belong to
    one specific requirement. See CLAUDE.md "Regulatory content: rule /
    rule_version" for the full reasoning behind every field here.
    """

    __tablename__ = "rule_versions"

    __table_args__ = (
        Index(
            "ix_rule_versions_rule_id",
            "rule_id",
        ),
        Index(
            "ix_rule_versions_status",
            "status",
        ),
        Index(
            "ix_rule_versions_requirement_version_id",
            "requirement_version_id",
        ),
    )

    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "rules.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=RuleVersionStatus.DRAFT.value,
    )

    requirement_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "requirement_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # --- Inputs ---
    # Field existence/content grounded in C6's own "Inputs" row (typed
    # fields from a published Product Version, verified extraction,
    # market/pathway or prior rule output). The schema-versioning
    # wrapper (inputs_schema_name/version) is NOT spec-stated - it's an
    # inferred structural convention, applied by analogy to
    # RequirementVersion.applicability_required_inputs (itself already
    # an analogy-based choice, not something C5 specified either).

    inputs: Mapped[list[Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    inputs_schema_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    inputs_schema_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # --- Condition (the constrained declarative expression tree) ---

    condition: Mapped[dict[str, Any]] = mapped_column(
        _JSON,
        nullable=False,
    )

    condition_schema_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    condition_schema_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # --- Unknown policy ---

    unknown_behavior: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=UnknownBehavior.HUMAN_REVIEW.value,
    )

    # --- Output ---

    output_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    # --- AI analysis opt-in (Claims semantic analysis) ---
    # NULL = deterministic only - every rule, unchanged. "SEMANTIC_EQUIVALENCE"
    # = also run the AI semantic peer hop when this rule's deterministic
    # condition returns NO_MATCH (CLAIMS dimension only, FINDING_PROPOSAL only -
    # see AssessmentRunService._maybe_run_claim_semantic_hop). Open string, not
    # an enum - one value now, same "needs real definition before constraining"
    # treatment as obligation_type/verification_level. See CLAUDE.md "Claims
    # semantic analysis".
    ai_analysis_mode: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # --- Governance ---

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

    approval_policy: Mapped[str | None] = mapped_column(
        String(100),
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

    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "rule_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "rule_versions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # Inert data only - no execution engine built to run these against
    # `condition`. See CLAUDE.md.
    test_fixtures: Mapped[list[Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    test_fixtures_schema_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    test_fixtures_schema_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    rule = relationship(
        "Rule",
        back_populates="versions",
    )

    requirement_version = relationship(
        "RequirementVersion",
    )

    source_locations = relationship(
        "SourceLocation",
        secondary="rule_version_source_locations",
    )

    @property
    def source_location_ids(self) -> list[UUID]:
        return [location.id for location in self.source_locations]


class RuleVersionSourceLocation(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Provenance link: which exact SourceLocation(s) back a RuleVersion.
    Plain association table, no independent lifecycle - managed
    through RuleVersion's own service.
    """

    __tablename__ = "rule_version_source_locations"

    __table_args__ = (
        UniqueConstraint(
            "rule_version_id",
            "source_location_id",
            name="uq_rule_version_source_location",
        ),
        Index(
            "ix_rvsl2_rule_version_id",
            "rule_version_id",
        ),
        Index(
            "ix_rvsl2_source_location_id",
            "source_location_id",
        ),
    )

    rule_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "rule_versions.id",
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
