from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.modules.assessment_run.models import AssessmentRun, AssessmentRunStatus, DimensionAssessmentState
from app.modules.assessment_run.repository import AssessmentRunRepository, DimensionAssessmentRepository
from app.modules.assessment_run.service import AssessmentRunService
from app.modules.finding.models import TERMINAL_FINDING_STATUSES
from app.modules.finding.repository import FindingRepository, FindingRevisionRepository
from app.modules.product_market_state.exceptions import ProductMarketStateNotFound
from app.modules.product_market_state.models import ProductMarketStateGate
from app.modules.product_market_state.repository import ProductMarketStateRepository
from app.modules.product_version.repository import ProductVersionRepository
from app.modules.regulatory_basis_release.models import RegulatoryBasisReleaseStatus
from app.modules.regulatory_basis_release.repository import RegulatoryBasisReleaseRepository
from app.modules.requirement_result.repository import RequirementResultRepository
from app.modules.requirement_version.models import RequirementDimension, RequirementSeverity
from app.modules.requirement_version.repository import RequirementVersionRepository
from app.modules.state_snapshot.models import StateSnapshot
from app.modules.state_snapshot.repository import StateSnapshotRepository

from .exceptions import MarketReadinessPreflightFailed
from .schemas import MarketReadinessRunCreate

# B5.1 default portfolio weights - sum to 100, keyed exactly like
# RequirementDimension's own values.
DIMENSION_WEIGHTS: dict[str, int] = {
    RequirementDimension.CLASSIFICATION_ELIGIBILITY.value: 15,
    RequirementDimension.INGREDIENTS.value: 20,
    RequirementDimension.CLAIMS.value: 15,
    RequirementDimension.LABEL.value: 15,
    RequirementDimension.DOCUMENTS.value: 15,
    RequirementDimension.TESTING.value: 5,
    RequirementDimension.REPRESENTATION.value: 5,
    RequirementDimension.REGISTRATION_READINESS.value: 10,
}

_SEVERITY_ORDER = [
    RequirementSeverity.CRITICAL.value,
    RequirementSeverity.MAJOR.value,
    RequirementSeverity.MODERATE.value,
    RequirementSeverity.MINOR.value,
    RequirementSeverity.INFORMATIONAL.value,
]

# Statuses representing a completed disposition. Everything else -
# including PROPOSED, and now (with the review workflow built) genuine
# OPEN/CUSTOMER_RESPONDED findings too - blocks the gate. Resolved
# explicitly: gating strictly on status == "OPEN" would make G1
# permanently unreachable, which can't be AC-FR-05-02's intent.
# TERMINAL_FINDING_STATUSES is the one definition of this set - see
# finding/models.py, which also defines its exact complement
# (NON_TERMINAL_FINDING_STATUSES, used by FindingService's own
# transition-legality checks) so the two can't drift apart.
_CLOSED_FINDING_STATUSES = TERMINAL_FINDING_STATUSES

_DISPLAY_CAPS = {
    ProductMarketStateGate.G0.value: 49.0,
    ProductMarketStateGate.G2.value: 89.0,
    ProductMarketStateGate.G3.value: 79.0,
}


class MarketReadinessService:
    """
    Orchestrates FR-05's Market Readiness assessment: preflight, reuse-
    vs-rerun across all eight canonical dimensions, gate/progress
    calculation and StateSnapshot creation. See CLAUDE.md "Market
    readiness: state_snapshot, market_readiness" for the full mapping
    of B5/B3/FR-05 concepts onto what's actually built.
    """

    def __init__(self, db: Session):
        self.db = db
        self.states = ProductMarketStateRepository(db)
        self.product_versions = ProductVersionRepository(db)
        self.releases = RegulatoryBasisReleaseRepository(db)
        self.runs = AssessmentRunRepository(db)
        self.dimension_assessments = DimensionAssessmentRepository(db)
        self.assessment_runs = AssessmentRunService(db)
        self.requirement_versions = RequirementVersionRepository(db)
        self.requirement_results = RequirementResultRepository(db)
        self.findings = FindingRepository(db)
        self.finding_revisions = FindingRevisionRepository(db)
        self.snapshots = StateSnapshotRepository(db)
        # Real, not a placeholder - the running application's own
        # version, the closest thing to C10's "engine build" field this
        # codebase has today.
        self.engine_build = get_settings().app_version

    def _get_state_or_404(self, organization_id: UUID, product_market_state_id: UUID):
        state = self.states.get_by_id_only(organization_id, product_market_state_id)

        if state is None:
            raise ProductMarketStateNotFound()

        return state

    def run_preflight(self, organization_id: UUID, state) -> list[dict[str, str]]:
        """
        Returns every unmet prerequisite, not just the first (FR-05:
        "it explains every unmet prerequisite"). "Published" is resolved
        against the publish() concept (ProductVersion.released_at), not
        ProductVersionStatus - the two lifecycles aren't reconciled
        (known gap, logged elsewhere in CLAUDE.md); using released_at is
        the more literal reading of "published". Required intake fields
        are deliberately NOT checked - no such checklist is modeled
        anywhere in this codebase yet, and inventing a synthetic one
        wasn't asked for.
        """

        failures: list[dict[str, str]] = []

        if state.product_version_id is None:
            failures.append({
                "code": "NO_PRODUCT_VERSION",
                "message": "No product version is pinned to this Product x Market state.",
            })
        else:
            version = self.product_versions.get_by_id(
                organization_id, state.product_id, state.product_version_id,
            )
            if version is None or version.released_at is None:
                failures.append({
                    "code": "PRODUCT_VERSION_NOT_PUBLISHED",
                    "message": "The pinned product version has not been published.",
                })

        if state.regulatory_basis_release_id is None:
            failures.append({
                "code": "NO_REGULATORY_BASIS",
                "message": "No Regulatory Basis Release is pinned to this Product x Market state.",
            })
        else:
            release = self.releases.get_by_id(state.regulatory_basis_release_id)
            if release is None or release.status != RegulatoryBasisReleaseStatus.ACTIVE.value:
                failures.append({
                    "code": "REGULATORY_BASIS_NOT_ACTIVE",
                    "message": "The pinned Regulatory Basis Release is not (or is no longer) ACTIVE.",
                })

        return failures

    def run(
        self,
        organization_id: UUID,
        payload: MarketReadinessRunCreate,
        actor_user_id: UUID | None = None,
    ) -> StateSnapshot:
        state = self._get_state_or_404(organization_id, payload.product_market_state_id)

        preflight_failures = self.run_preflight(organization_id, state)
        if preflight_failures:
            raise MarketReadinessPreflightFailed(preflight_failures)

        # Presence of the key - even with an empty facts dict - is an
        # explicit rerun request for that dimension, not just a
        # non-empty-value check (see MarketReadinessRunCreate).
        forced_rerun_dimensions = set(payload.input_facts.keys())

        run = AssessmentRun(
            organization_id=organization_id,
            product_market_state_id=state.id,
            product_version_id=state.product_version_id,
            regulatory_basis_release_id=state.regulatory_basis_release_id,
            status=AssessmentRunStatus.RUNNING.value,
            requested_by_user_id=actor_user_id,
            started_at=datetime.now(timezone.utc),
        )
        self.runs.create(run)
        self.db.commit()

        dimension_summary_raw: dict[str, dict[str, Any]] = {}

        try:
            for dimension in RequirementDimension:
                dimension_value = dimension.value
                assessment, reused = self._resolve_dimension(
                    run, state, dimension_value, payload.input_facts, forced_rerun_dimensions,
                )
                score, excluded = self._dimension_score(assessment)
                dimension_summary_raw[dimension_value] = {
                    "dimension_assessment_id": assessment.id,
                    "state": assessment.state,
                    "score": score,
                    "excluded": excluded,
                    "reused": reused,
                }

            run.status = AssessmentRunStatus.COMPLETED.value
        except Exception as exc:  # noqa: BLE001
            # Same "a run-level failure must still leave a visible,
            # terminal record" reasoning as create_and_run.
            run.status = AssessmentRunStatus.FAILED.value
            run.error_message = str(exc)

        run.completed_at = datetime.now(timezone.utc)
        self.runs.update(run)
        self.db.commit()

        return self._build_snapshot(state, run, dimension_summary_raw)

    def _resolve_dimension(self, run, state, dimension_value, input_facts, forced_rerun_dimensions):
        """
        Two distinct reuse checks, not one - see CLAUDE.md "Market
        readiness" for the full reasoning:

        - Key absent (dimension_value not in forced_rerun_dimensions):
          the caller submitted nothing this run for this dimension.
          Pins alone decide reuse, exactly as before this hash existed -
          there is nothing submitted to compare against.
        - Key present: the caller resupplied this dimension's facts.
          That used to force an unconditional rerun regardless of
          content; now identical resupply (matching pins AND a matching
          submitted_facts_hash) still reuses safely, and only genuinely
          different content falls through to a real rerun.
        """

        dimension_facts = input_facts.get(dimension_value, {})

        if dimension_value not in forced_rerun_dimensions:
            reusable = self.dimension_assessments.get_latest_reusable(
                state.id, dimension_value, state.product_version_id, state.regulatory_basis_release_id,
            )
        else:
            facts_hash = self.assessment_runs.hash_facts(dimension_facts)
            reusable = self.dimension_assessments.get_latest_reusable(
                state.id, dimension_value, state.product_version_id, state.regulatory_basis_release_id,
                submitted_facts_hash=facts_hash,
            )

        if reusable is not None:
            return reusable, True

        self.assessment_runs.run_dimension(run, dimension_value, dimension_facts)
        assessment = self.dimension_assessments.get_latest_for_run_dimension(run.id, dimension_value)
        return assessment, False

    def _dimension_score(self, assessment) -> tuple[float | None, bool]:
        """
        B5.2 weighted progress within a dimension. Returns
        (score, excluded) - excluded=True means the whole dimension is
        Not Applicable and should drop out of both the numerator and
        denominator of the overall (B5.1) weighted average, mirroring
        how a Not-Applicable requirement is excluded within a dimension
        (B5.2, and line 1146's "Only Does Not Apply may exclude a
        requirement from the readiness denominator") - extended here to
        the dimension level too, since B3's own Not-Applicable
        definition explicitly names "the dimension/requirement", not
        just requirements.

        Only 3 of B5.2's 6 progress-factor rows are reachable without
        the unbuilt AI/RA-review layer: SATISFIED -> 1.00, Not
        Applicable -> Excluded, everything else -> 0.00 - same "6 of 12
        B3 states reachable" pattern as DimensionAssessmentState.

        Grouped by requirement_version_id first, not scored per row:
        the same RequirementVersion can have both an APPLICABILITY row
        and a REQUIREMENT_RESULT row (two different RuleVersions), and
        each must contribute its importance_weight exactly once, not
        once per row, or the denominator double-counts it.

        A RequirementVersion enforced purely via FINDING_PROPOSAL rules
        never produces a RequirementResult row at all (FINDING_PROPOSAL
        writes only a Finding), so it never appears here and its weight
        is never counted - a known, documented gap, not a silent one.

        APPLIES alone (no accompanying REQUIREMENT_RESULT outcome for
        the same requirement) does not itself earn progress credit -
        applicability establishes relevance, not satisfaction; scoring
        it as compliant would overstate readiness for a requirement
        nothing has actually verified.
        """

        results = self.requirement_results.get_for_run_dimension(
            assessment.assessment_run_id, assessment.dimension,
        )

        by_requirement: dict[UUID, list[str]] = {}
        for result in results:
            by_requirement.setdefault(result.requirement_version_id, []).append(result.outcome)

        weighted_sum = 0.0
        weight_total = 0.0

        for requirement_version_id, outcomes in by_requirement.items():
            if "DOES_NOT_APPLY" in outcomes:
                continue

            requirement_version = self.requirement_versions.get_by_id_only(requirement_version_id)
            weight = (
                float(requirement_version.importance_weight)
                if requirement_version and requirement_version.importance_weight is not None
                else 1.0
            )

            factor = 1.0 if "SATISFIED" in outcomes else 0.0

            weighted_sum += factor * weight
            weight_total += weight

        if weight_total == 0:
            if assessment.state == DimensionAssessmentState.NOT_APPLICABLE.value:
                return None, True
            if assessment.state == DimensionAssessmentState.COMPLIANT.value:
                return 100.0, False
            return 0.0, False

        return round((weighted_sum / weight_total) * 100, 2), False

    def _open_findings(self, organization_id: UUID, product_market_state_id: UUID) -> list[dict[str, Any]]:
        open_findings: list[dict[str, Any]] = []

        for finding in self.findings.get_all(organization_id, product_market_state_id):
            latest = self.finding_revisions.get_latest(finding.id)
            if latest is None or latest.status in _CLOSED_FINDING_STATUSES:
                continue
            open_findings.append({
                "severity": latest.severity,
                "status": latest.status,
                "hard_gate_effect": latest.hard_gate_effect,
            })

        return open_findings

    def _compute_gate(
        self,
        dimension_summary: dict[str, dict[str, Any]],
        open_findings: list[dict[str, Any]],
    ) -> tuple[str, list[str]]:
        """
        B5.3 gate order, resolved:
        - Finding-status blocking: non-dispositioned statuses (anything
          outside _CLOSED_FINDING_STATUSES) block, not just "OPEN".
        - An open finding with hard_gate_effect=True forces G1
          regardless of its own severity - B5.3's G1 condition ("any
          open Critical finding, explicit ineligibility or
          non-compliant blocking rule") names three independent
          triggers, and C5/C7 both list hard-gate status and severity
          as separate fields, never one derived from the other. Additive
          to, not a replacement for, the severity check below - a
          Critical finding on a non-hard-gate requirement must still
          block on its own, and a hard-gate finding at any severity
          (Moderate/Minor/Informational included) must also block on
          its own. See CLAUDE.md "Market readiness" for the full
          reasoning and the adjacent gap this does NOT close.
        - G3 <- HUMAN_REVIEW_REQUIRED dimension state (flagged as
          inferred - G3's literal wording is about AI-only/confidence-
          unmet decisions, which HUMAN_REVIEW_REQUIRED is the closest
          existing analog to).
        - G4/G5 are permanently unreachable this pass - the absence of
          an Approval model is not the same as approvals being
          satisfied. Whatever would otherwise be G4 is capped at G3,
          with a distinct reason code from the real HUMAN_REVIEW
          case so the two are never confused.
        """

        reasons: list[str] = []

        dimension_unknown = any(
            info["state"] == DimensionAssessmentState.UNKNOWN.value
            for info in dimension_summary.values()
        )
        if dimension_unknown:
            reasons.append("DIMENSION_UNKNOWN")
            return ProductMarketStateGate.G0.value, reasons

        critical_open = any(f["severity"] == RequirementSeverity.CRITICAL.value for f in open_findings)
        hard_gate_open = any(f["hard_gate_effect"] for f in open_findings)
        non_compliant = any(
            info["state"] == DimensionAssessmentState.NON_COMPLIANT.value
            for info in dimension_summary.values()
        )
        if critical_open or hard_gate_open or non_compliant:
            if critical_open:
                reasons.append("CRITICAL_FINDING_OPEN")
            if hard_gate_open:
                reasons.append("HARD_GATE_FINDING_OPEN")
            if non_compliant:
                reasons.append("NON_COMPLIANT_DIMENSION")
            return ProductMarketStateGate.G1.value, reasons

        major_open = any(f["severity"] == RequirementSeverity.MAJOR.value for f in open_findings)
        pending_input = any(
            info["state"] == DimensionAssessmentState.PENDING_INPUT.value
            for info in dimension_summary.values()
        )
        if major_open or pending_input:
            if major_open:
                reasons.append("MAJOR_FINDING_OPEN")
            if pending_input:
                reasons.append("PENDING_INPUT")
            return ProductMarketStateGate.G2.value, reasons

        human_review = any(
            info["state"] == DimensionAssessmentState.HUMAN_REVIEW_REQUIRED.value
            for info in dimension_summary.values()
        )
        if human_review:
            reasons.append("HUMAN_REVIEW_REQUIRED")
            return ProductMarketStateGate.G3.value, reasons

        # Everything else clean - would be G4, but G4/G5 are explicitly
        # blocked this pass (resolution: "absence of approval
        # infrastructure is not approval").
        reasons.append("G4_UNREACHABLE_NO_APPROVAL_MODEL")
        return ProductMarketStateGate.G3.value, reasons

    def _build_snapshot(self, state, run, dimension_summary_raw: dict[str, dict[str, Any]]) -> StateSnapshot:
        open_findings = self._open_findings(state.organization_id, state.id)

        unresolved_severity_counts = {severity: 0 for severity in _SEVERITY_ORDER}
        for finding in open_findings:
            unresolved_severity_counts[finding["severity"]] = (
                unresolved_severity_counts.get(finding["severity"], 0) + 1
            )

        highest_open_severity = next(
            (severity for severity in _SEVERITY_ORDER if unresolved_severity_counts.get(severity, 0) > 0),
            None,
        )

        gate, reasons = self._compute_gate(dimension_summary_raw, open_findings)

        weighted_sum = 0.0
        weight_total = 0.0
        for dimension_value, info in dimension_summary_raw.items():
            if info["excluded"]:
                continue
            weight = DIMENSION_WEIGHTS[dimension_value]
            weighted_sum += (info["score"] or 0.0) * weight
            weight_total += weight

        raw_progress = round(weighted_sum / weight_total, 2) if weight_total else 0.0
        displayed_progress = min(raw_progress, _DISPLAY_CAPS[gate]) if gate in _DISPLAY_CAPS else raw_progress

        dimension_summary = {
            dimension_value: {
                "dimension_assessment_id": str(info["dimension_assessment_id"]),
                "state": info["state"],
                "score": info["score"],
                "reused": info["reused"],
            }
            for dimension_value, info in dimension_summary_raw.items()
        }

        previous_current = self.snapshots.get_current(state.id)

        snapshot = StateSnapshot(
            organization_id=state.organization_id,
            product_market_state_id=state.id,
            product_version_id=state.product_version_id,
            regulatory_basis_release_id=state.regulatory_basis_release_id,
            assessment_run_id=run.id,
            overall_gate=gate,
            raw_progress=raw_progress,
            displayed_progress=displayed_progress,
            highest_open_severity=highest_open_severity,
            readiness_reason_codes=reasons,
            outstanding_action_count=len(open_findings),
            dimension_summary=dimension_summary,
            unresolved_severity_counts=unresolved_severity_counts,
            engine_build=self.engine_build,
            is_current=True,
        )
        self.snapshots.create(snapshot)
        self.db.flush()

        if previous_current is not None:
            previous_current.is_current = False
            previous_current.stale_reason = "SUPERSEDED_BY_NEW_SNAPSHOT"
            previous_current.superseded_by_snapshot_id = snapshot.id
            self.snapshots.update(previous_current)

        state.gate = gate
        self.states.update(state)

        self.db.commit()
        self.db.refresh(snapshot)

        return snapshot
