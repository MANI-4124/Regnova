from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, JSON, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class StateSnapshot(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Immutable aggregate decision for a Product Version x Market x
    Regulatory Basis x Assessment Run (C1, C1.1). Never updated in place
    except for the Currency group's is_current/stale_reason/
    superseded_by_snapshot_id, written once by a later snapshot - same
    "one mutable exception, everything else immutable" shape as
    FindingRevision's own superseding fields.

    Only a subset of C1.1's seven field groups are real today - see
    CLAUDE.md "Market readiness: state_snapshot, market_readiness" for
    exactly which fields are populated vs. deferred (Approvals omitted
    entirely; document/model/prompt/parser versions, evidence
    sufficiency and impact_analysis_id all deferred pending C8/D-layer/
    C11, none of which exist yet).
    """

    __tablename__ = "state_snapshots"

    __table_args__ = (
        Index("ix_state_snapshots_organization_id", "organization_id"),
        Index("ix_state_snapshots_product_market_state_id", "product_market_state_id"),
        Index("ix_state_snapshots_is_current", "is_current"),
    )

    # --- Identity ---

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

    # The AssessmentRun created for THIS Market Readiness invocation -
    # may have executed zero dimensions if every dimension was safe to
    # reuse from an earlier run. dimension_summary (below) is the
    # complete, self-contained record of which DimensionAssessment
    # actually backs each dimension, whether newly created under this
    # run or reused from an older one - this FK alone doesn't capture
    # that.
    assessment_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Decision ---

    overall_gate: Mapped[str] = mapped_column(String(10), nullable=False)

    raw_progress: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    displayed_progress: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    # Named for exactly what it is, not for C1.1's "risk" field (which
    # implies a real risk-scoring model this codebase doesn't have) -
    # the highest severity among this state's currently open
    # (non-dispositioned) Findings, or null if there are none.
    highest_open_severity: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # C1.1's Decision group also lists "verification state" - omitted
    # entirely (not even a nullable column), same principle as Approvals
    # below: no Approval model exists yet to ever populate it with
    # anything but a fixed placeholder, so the column doesn't exist
    # until that layer does.

    readiness_reason_codes: Mapped[list[Any]] = mapped_column(_JSON, nullable=False)

    outstanding_action_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Dimensions ---
    # Self-contained, per requirement_result.predicate_inputs' own
    # "retain enough to reconstruct without a join" precedent -
    # {dimension: {dimension_assessment_id, state, score, reused}}.
    dimension_summary: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False)

    # --- Findings and evidence ---
    # {severity: count} across non-dispositioned Findings for this state.
    # Evidence sufficiency / evidence-link revisions deferred - no
    # Evidence model exists (C8).
    unresolved_severity_counts: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False)

    # --- Approvals ---
    # Omitted entirely, not even nullable columns - no Approval model
    # exists yet, same "no rule-authoring-time data to reserve columns
    # for in advance" precedent as Finding's AI/Human lineage groups.

    # --- Lineage ---
    # source/rule/requirement versions are derivable via
    # regulatory_basis_release_id (RegulatoryBasisRelease already owns
    # that manifest); document versions and model/prompt/parser versions
    # deferred (no Document model, no AI layer). configuration_hash
    # omitted entirely - no release-scoped engine configuration exists
    # yet to hash (only one hardcoded constant, DEFAULT_MIN_CONFIDENCE),
    # same "don't reserve a column for a layer that doesn't exist"
    # principle as verification_state above. engine_build is real, not
    # a placeholder - the running application's own settings.app_version.
    engine_build: Mapped[str] = mapped_column(String(50), nullable=False)

    # --- Currency ---

    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    stale_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # impact_analysis_id deferred - C11's cascading impact-propagation
    # layer isn't built; this snapshot only ever gets marked stale by a
    # newer snapshot directly superseding it (see market_readiness),
    # never by an upstream fact change alone.
    superseded_by_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("state_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
