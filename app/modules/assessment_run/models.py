from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class AssessmentRunStatus(str, Enum):
    """
    Minimal execution-status vocabulary - deliberately NOT FR-05's own
    "Preflight Failed -> Queued -> Assessing -> AI Assessed -> RA
    Review -> ..." list, which describes the *resulting* dimension/gate
    state, not the run's own execution lifecycle. See CLAUDE.md
    "Assessment engine" for the sync-only implementation and the
    condition under which this needs revisiting.
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepType(str, Enum):
    """
    C10's six lineage hop types, named for schema completeness even
    though only RULE_EVALUATION has anything to execute in this pass -
    same "store the full vocabulary, implement a subset" precedent as
    RuleVersion.output_type.
    """

    EXTRACTION = "EXTRACTION"
    RULE_EVALUATION = "RULE_EVALUATION"
    AI_ANALYSIS = "AI_ANALYSIS"
    RA_DECISION = "RA_DECISION"
    STATE_CALCULATION = "STATE_CALCULATION"
    AUTHORITY_OUTCOME = "AUTHORITY_OUTCOME"


class StepRunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DimensionAssessmentState(str, Enum):
    """
    Subset of B3's dimension-state vocabulary actually reachable by a
    rule-only engine (no AI/RA-review layer in this pass) - RegNova
    Verified/Customer Action Required/Authority Confirmed all require
    layers this slice doesn't build.
    """

    UNKNOWN = "UNKNOWN"
    PENDING_INPUT = "PENDING_INPUT"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


_JSON = JSON().with_variant(JSONB(), "postgresql")


class AssessmentRun(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Orchestration record (C10) - runs one or more dimensions against a
    ProductMarketState. product_version_id/regulatory_basis_release_id
    are snapshotted at creation from the (mutable) ProductMarketState,
    not live FKs to it - AC-FR-05-01 requires reproducibility, and
    ProductMarketState's own pointers can move after a run starts.
    """

    __tablename__ = "assessment_runs"

    __table_args__ = (
        Index("ix_assessment_runs_organization_id", "organization_id"),
        Index("ix_assessment_runs_product_market_state_id", "product_market_state_id"),
        Index("ix_assessment_runs_status", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    product_market_state_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_market_states.id", ondelete="CASCADE"),
        nullable=False,
    )

    product_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    regulatory_basis_release_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulatory_basis_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AssessmentRunStatus.QUEUED.value,
    )

    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    step_runs = relationship(
        "StepRun",
        back_populates="assessment_run",
    )

    dimension_assessments = relationship(
        "DimensionAssessment",
        back_populates="assessment_run",
    )


class StepRun(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Raw execution ledger - one row per (rule_version, subject) pair
    evaluated. Always created, regardless of output_type; RequirementResult
    and Finding are semantic artifacts derived from a subset of these
    (see AssessmentRunService._apply_output).
    """

    __tablename__ = "step_runs"

    __table_args__ = (
        Index("ix_step_runs_assessment_run_id", "assessment_run_id"),
        Index("ix_step_runs_dimension", "dimension"),
        Index("ix_step_runs_rule_version_id", "rule_version_id"),
    )

    assessment_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    dimension: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    step_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=StepType.RULE_EVALUATION.value,
    )

    rule_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rule_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Which claim (or other per-subject item) this step evaluated - the
    # engine only ever sees one flat scalar facts dict at a time; the
    # per-claim iteration lives in AssessmentRunService, not the engine.
    subject_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    input_facts: Mapped[dict[str, Any]] = mapped_column(
        _JSON,
        nullable=False,
    )

    input_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    outcome: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # Only set when outcome == "UNKNOWN" - "missing" (a referenced field
    # was absent) or "low_confidence" (present but below its confidence
    # threshold, e.g. Label's OCR-extracted fields). A real queryable
    # column, not just embedded in trace JSON - DimensionAssessment's
    # state derivation needs to distinguish the two per-step to apply
    # the AC-FR-06-02 hard-pin (low_confidence always forces HUMAN_REVIEW
    # regardless of the rule's own unknown_behavior) without re-parsing
    # trace. See CLAUDE.md "Assessment engine".
    unknown_reason: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    trace: Mapped[list[Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    assessment_run = relationship(
        "AssessmentRun",
        back_populates="step_runs",
    )


class DimensionAssessment(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Derived rollup of one dimension's StepRuns for one AssessmentRun
    (C10). Does not store its own requirement-result/finding lists -
    those are queried from RequirementResult/Finding filtered by
    (assessment_run_id, dimension), avoiding denormalized data that
    could drift from the rows it's supposedly summarizing.
    """

    __tablename__ = "dimension_assessments"

    __table_args__ = (
        Index("ix_dimension_assessments_assessment_run_id", "assessment_run_id"),
        Index("ix_dimension_assessments_dimension", "dimension"),
    )

    assessment_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    dimension: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    state: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    assessment_run = relationship(
        "AssessmentRun",
        back_populates="dimension_assessments",
    )
