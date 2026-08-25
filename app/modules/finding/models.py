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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin

# Finding severity is explicitly "inherited from the requirement" per B4
# ("Severity... Definition... inherited from the requirement") - not an
# independently-defined vocabulary the way every other module's status
# enum is. Reusing RequirementSeverity directly is the second deliberate
# cross-module enum exception (after UnknownBehavior), textually
# justified the same way.
from app.modules.requirement_version.models import RequirementSeverity  # noqa: F401


class FindingStatus(str, Enum):
    """
    B4's Finding status vocabulary, verbatim.
    """

    PROPOSED = "PROPOSED"
    OPEN = "OPEN"
    CUSTOMER_RESPONDED = "CUSTOMER_RESPONDED"
    RESOLVED = "RESOLVED"
    ACCEPTED_WITH_RATIONALE = "ACCEPTED_WITH_RATIONALE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


# The two-way split of the 8 statuses above: a Finding still awaiting a
# human disposition versus one that's reached one. Defined once here,
# not duplicated - market_readiness/service.py's own gate-blocking set
# is exactly this same complement, and FindingService's transition
# legality checks (only NON_TERMINAL statuses accept a new transition)
# are exactly this concept from the other side. SUPERSEDED is terminal
# but currently unreachable by any transition this pass - see
# CLAUDE.md "Finding review workflow" for why (no C11 change-detection
# exists yet to trigger it).
TERMINAL_FINDING_STATUSES = frozenset({
    FindingStatus.RESOLVED.value,
    FindingStatus.ACCEPTED_WITH_RATIONALE.value,
    FindingStatus.NOT_APPLICABLE.value,
    FindingStatus.REJECTED.value,
    FindingStatus.SUPERSEDED.value,
})

NON_TERMINAL_FINDING_STATUSES = frozenset({
    FindingStatus.PROPOSED.value,
    FindingStatus.OPEN.value,
    FindingStatus.CUSTOMER_RESPONDED.value,
})


_JSON = JSON().with_variant(JSONB(), "postgresql")


class Finding(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Stable issue identity for a Product x Market context (C7). Thin
    anchor only - same Requirement/RequirementVersion split reasoning:
    everything that changes per assessment (observation, decision,
    recommendation, lineage) lives on FindingRevision, never here.
    """

    __tablename__ = "findings"

    __table_args__ = (
        Index("ix_findings_organization_id", "organization_id"),
        Index("ix_findings_product_market_state_id", "product_market_state_id"),
        Index("ix_findings_dimension", "dimension"),
        Index(
            "ix_findings_identity_lookup",
            "product_market_state_id",
            "requirement_version_id",
            "subject_key",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    product_market_state_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_market_states.id", ondelete="CASCADE"),
        nullable=False,
    )

    dimension: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Deliberately NOT revision-scoped, unlike the rest of C7's
    # "Regulatory link" group - these three plus dimension are what make
    # re-running an assessment recognize "the same issue" rather than
    # spawning a duplicate Finding every run (propose() matches on
    # exactly this tuple). A genuinely different rule/requirement/claim
    # is a different Finding, not a new revision of this one.
    requirement_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("requirement_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    rule_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rule_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    subject_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    human_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    revisions = relationship(
        "FindingRevision",
        back_populates="finding",
        order_by="FindingRevision.revision_number",
        foreign_keys="FindingRevision.finding_id",
    )


class FindingRevision(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Immutable snapshot of one Finding's observation/decision at a
    specific Assessment Run (C7). Never updated in place, unlike every
    other version-bearing module here - C7 is explicit that the whole
    point of the Finding/FindingRevision split is keeping each
    assessment result immutable, so any change is a new row with the
    next revision_number, not a setattr loop. See CLAUDE.md "Finding /
    Finding Revision" for the full field-group reasoning, including
    which C7 groups are deliberately left unpopulated in this pass
    (Recommendation, AI lineage, Human lineage, most of Resolution).
    """

    __tablename__ = "finding_revisions"

    __table_args__ = (
        UniqueConstraint(
            "finding_id",
            "revision_number",
            name="uq_finding_revision_number",
        ),
        Index("ix_finding_revisions_finding_id", "finding_id"),
        Index("ix_finding_revisions_assessment_run_id", "assessment_run_id"),
        Index("ix_finding_revisions_status", "status"),
    )

    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False,
    )

    revision_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # --- Context ---

    assessment_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Regulatory link's requirement_version_id/rule_version_id live on
    # Finding, not here - see the comment there.

    # --- Observation ---

    issue_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    observed_value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    normalized_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Provisional shape (e.g. {"claim_id": "...", "subject_key": "..."}) -
    # pending C8's Document/page/region model, which doesn't exist yet.
    observed_location: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    # --- Decision (C7's "NO FREE-TEXT-ONLY FINDINGS" required fields) ---

    severity: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=FindingStatus.PROPOSED.value,
    )

    disposition: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    hard_gate_effect: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    rationale: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # C7's "Human lineage" group ("reviewer... reason, approval and
    # timestamps") was entirely absent from this model before the
    # review workflow - this is the one field it actually needed: who
    # decided this revision. Nullable because propose()'s engine-
    # written revisions have no human actor. No separate decided_at -
    # this row's own created_at already stamps that moment, since a
    # transition always creates a new revision rather than mutating one
    # (see CLAUDE.md "Finding / Finding Revision").
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Recommendation ---
    # Deliberately unpopulated in this pass - RuleVersion has nowhere to
    # source a structured action template from yet (see CLAUDE.md).
    # Columns exist now so a future template mechanism doesn't need a
    # migration, but nothing writes to them today.

    action_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    suggested_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    resolution_criteria: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --- Resolution ---
    # AI lineage and Human lineage groups are omitted entirely for this
    # pass (confirmed) - no AI/RA-review layer exists yet to populate
    # them, and unlike Recommendation there's no rule-authoring-time
    # data that would need a column ready in advance.

    resolution_decision: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    superseding_finding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("findings.id", ondelete="SET NULL"),
        nullable=True,
    )

    finding = relationship(
        "Finding",
        back_populates="revisions",
        foreign_keys=[finding_id],
    )

    source_locations = relationship(
        "SourceLocation",
        secondary="finding_revision_source_locations",
    )

    @property
    def source_location_ids(self) -> list[UUID]:
        return [location.id for location in self.source_locations]


class FindingRevisionSourceLocation(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "finding_revision_source_locations"

    __table_args__ = (
        UniqueConstraint(
            "finding_revision_id",
            "source_location_id",
            name="uq_finding_revision_source_location",
        ),
        Index("ix_frsl_finding_revision_id", "finding_revision_id"),
        Index("ix_frsl_source_location_id", "source_location_id"),
    )

    finding_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("finding_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_location_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_locations.id", ondelete="CASCADE"),
        nullable=False,
    )
