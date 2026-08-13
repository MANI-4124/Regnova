from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin

# outcome stays a plain string column (matching this codebase's usual
# enum-in-Python/string-in-DB convention), but which of these two closed
# vocabularies is valid depends on which RuleVersion.output_type produced
# it - enforced at the service layer (RequirementResultService.create),
# not by the column type. See CLAUDE.md "Assessment engine" for why one
# table serves both: C5.1's four-value applicability vocabulary and a
# rule's REQUIREMENT_RESULT satisfaction vocabulary are different
# meanings of the same shape (a requirement x rule evaluation with
# retained predicate inputs and lineage).
APPLICABILITY_OUTCOMES = frozenset({"APPLIES", "DOES_NOT_APPLY", "UNKNOWN", "CONFLICT"})
SATISFACTION_OUTCOMES = frozenset({"SATISFIED", "NOT_SATISFIED", "UNKNOWN"})

_JSON = JSON().with_variant(JSONB(), "postgresql")


class RequirementResult(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    C5.1's "future Requirement Result entity" - retains an applicability
    or requirement-satisfaction outcome with its predicate inputs and
    source/rule lineage, per C5.1's explicit retention requirement
    ("that decision must retain its predicate inputs and source/rule
    lineage"). One row per (StepRun, RuleVersion) evaluation - "RuleVersion(s)"
    plural (C10) is satisfied by potentially many rows per
    RequirementVersion, not a many-to-many on one row, mirroring
    RuleVersion's own single nullable requirement_version_id precedent.
    """

    __tablename__ = "requirement_results"

    __table_args__ = (
        UniqueConstraint("step_run_id", name="uq_requirement_result_step_run"),
        Index("ix_requirement_results_assessment_run_id", "assessment_run_id"),
        Index("ix_requirement_results_requirement_version_id", "requirement_version_id"),
    )

    step_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("step_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Redundant with step_run.assessment_run_id - kept directly for
    # query convenience (same "duplicate a scoping FK" precedent as
    # ProductVersion carrying both organization_id and product_id).
    assessment_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    requirement_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirement_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    rule_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rule_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    outcome: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    # Self-contained snapshot, duplicated from StepRun.input_facts - C5.1
    # frames the applicability decision itself as needing to "retain"
    # its predicate inputs, read as the result being reconstructable
    # without a join back to StepRun.
    predicate_inputs: Mapped[dict[str, Any]] = mapped_column(
        _JSON,
        nullable=False,
    )

    source_locations = relationship(
        "SourceLocation",
        secondary="requirement_result_source_locations",
    )

    @property
    def source_location_ids(self) -> list[UUID]:
        return [location.id for location in self.source_locations]


class RequirementResultSourceLocation(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "requirement_result_source_locations"

    __table_args__ = (
        UniqueConstraint(
            "requirement_result_id",
            "source_location_id",
            name="uq_requirement_result_source_location",
        ),
        Index("ix_rrsl_requirement_result_id", "requirement_result_id"),
        Index("ix_rrsl_source_location_id", "source_location_id"),
    )

    requirement_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirement_results.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_location_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_locations.id", ondelete="CASCADE"),
        nullable=False,
    )
