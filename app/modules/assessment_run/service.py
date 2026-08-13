from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.enums import UnknownBehavior
from app.engine import evaluate_condition
from app.modules.finding.repository import FindingRevisionRepository
from app.modules.finding.service import FindingService
from app.modules.product_market_state.exceptions import ProductMarketStateNotFound
from app.modules.product_market_state.repository import ProductMarketStateRepository
from app.modules.regulatory_basis_release.repository import RegulatoryBasisReleaseRepository
from app.modules.requirement_result.repository import RequirementResultRepository
from app.modules.requirement_version.repository import RequirementVersionRepository
from app.modules.rule_version.models import RuleOutputType
from app.modules.rule_version.repository import RuleVersionRepository

from .exceptions import (
    AssessmentRunMissingRegulatoryBasis,
    AssessmentRunNotFound,
    UnsupportedDimension,
)
from .models import (
    AssessmentRun,
    AssessmentRunStatus,
    DimensionAssessment,
    DimensionAssessmentState,
    StepRun,
    StepRunStatus,
    StepType,
)
from .repository import AssessmentRunRepository, DimensionAssessmentRepository, StepRunRepository
from .schemas import AssessmentRunCreate

SUPPORTED_DIMENSIONS = frozenset({"CLAIMS"})


class AssessmentRunService:
    """
    Orchestrates one AssessmentRun end to end: resolves the pinned rule
    set per requested dimension (C6: only Verified+Active rule versions
    included in the pinned Regulatory Basis Release), evaluates each
    against caller-supplied input facts, and writes StepRun/
    RequirementResult/Finding rows. Entirely synchronous within the
    request - no job queue exists yet. See CLAUDE.md "Assessment engine"
    for the condition under which this needs to become async.
    """

    def __init__(self, db: Session):
        self.db = db
        self.runs = AssessmentRunRepository(db)
        self.step_runs = StepRunRepository(db)
        self.dimension_assessments = DimensionAssessmentRepository(db)
        self.product_market_states = ProductMarketStateRepository(db)
        self.releases = RegulatoryBasisReleaseRepository(db)
        self.rule_versions = RuleVersionRepository(db)
        self.requirement_versions = RequirementVersionRepository(db)
        self.requirement_results = RequirementResultRepository(db)
        self.finding_revisions = FindingRevisionRepository(db)
        self.findings = FindingService(db)

    def _get_state_or_404(self, organization_id: UUID, product_market_state_id: UUID):
        state = self.product_market_states.get_by_id_only(
            organization_id,
            product_market_state_id,
        )

        if state is None:
            raise ProductMarketStateNotFound()

        return state

    def get_all(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> list[AssessmentRun]:
        self._get_state_or_404(organization_id, product_market_state_id)
        return self.runs.get_all(organization_id, product_market_state_id)

    def get_by_id(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        run_id: UUID,
    ) -> AssessmentRun:
        self._get_state_or_404(organization_id, product_market_state_id)
        run = self.runs.get_by_id(organization_id, product_market_state_id, run_id)

        if run is None:
            raise AssessmentRunNotFound()

        return run

    def create_and_run(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        payload: AssessmentRunCreate,
        actor_user_id: UUID | None = None,
    ) -> AssessmentRun:
        state = self._get_state_or_404(organization_id, product_market_state_id)

        for dimension in payload.dimensions:
            if dimension not in SUPPORTED_DIMENSIONS:
                raise UnsupportedDimension(dimension, SUPPORTED_DIMENSIONS)

        if state.regulatory_basis_release_id is None:
            raise AssessmentRunMissingRegulatoryBasis()

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

        try:
            for dimension in payload.dimensions:
                self._run_dimension(run, dimension, payload.input_facts.get(dimension, {}))
            run.status = AssessmentRunStatus.COMPLETED.value
        except Exception as exc:  # noqa: BLE001
            # Deliberately broad: a run-level failure must still leave a
            # visible, terminal record (B6's "recoverable failure state"),
            # not a bare 500 with no trace of what was attempted.
            run.status = AssessmentRunStatus.FAILED.value
            run.error_message = str(exc)

        run.completed_at = datetime.now(timezone.utc)
        self.runs.update(run)
        self.db.commit()

        return run

    def _run_dimension(
        self,
        run: AssessmentRun,
        dimension: str,
        dimension_facts: dict[str, Any],
    ) -> None:
        release = self.releases.get_by_id(run.regulatory_basis_release_id)
        rule_versions = self.rule_versions.get_verified_active_for_dimension(
            dimension,
            release.rule_version_ids if release else [],
        )

        product_facts = dimension_facts.get("product", {})
        claims = dimension_facts.get("claims", [])

        for claim in claims:
            subject_key = claim.get("claim_id")
            claim_facts = {"product": product_facts, **claim}

            for rule_version in rule_versions:
                self._run_step(run, dimension, rule_version, subject_key, claim_facts)

        state = self._derive_dimension_state(run.id, dimension)
        assessment = DimensionAssessment(
            assessment_run_id=run.id,
            dimension=dimension,
            state=state,
        )
        self.dimension_assessments.create(assessment)
        self.db.commit()

    def _run_step(
        self,
        run: AssessmentRun,
        dimension: str,
        rule_version,
        subject_key: str | None,
        facts: dict[str, Any],
    ) -> None:
        input_hash = hashlib.sha256(
            json.dumps(facts, sort_keys=True, default=str).encode("utf-8"),
        ).hexdigest()

        step = StepRun(
            assessment_run_id=run.id,
            dimension=dimension,
            step_type=StepType.RULE_EVALUATION.value,
            rule_version_id=rule_version.id,
            subject_key=subject_key,
            input_facts=facts,
            input_hash=input_hash,
            status=StepRunStatus.COMPLETED.value,
        )

        try:
            result = evaluate_condition(rule_version.condition, facts)
        except Exception as exc:  # noqa: BLE001
            # Any single rule's evaluation failing (unknown normalize
            # function, malformed condition) is isolated to this one
            # StepRun - it must not take down the whole dimension/run.
            step.status = StepRunStatus.FAILED.value
            step.error_message = str(exc)
            self.step_runs.create(step)
            self.db.commit()
            return

        step.outcome = result.outcome
        step.trace = result.trace
        self.step_runs.create(step)
        self.db.commit()

        self._apply_output(run, rule_version, step, result, facts)

    def _apply_output(self, run, rule_version, step, result, facts) -> None:
        output_type = rule_version.output_type

        if output_type == RuleOutputType.APPLICABILITY.value:
            outcome = self._resolve_applicability_outcome(result, rule_version.unknown_behavior)
            self._create_requirement_result(run, rule_version, step, output_type, outcome, facts)

        elif output_type == RuleOutputType.REQUIREMENT_RESULT.value:
            outcome = self._resolve_satisfaction_outcome(result, rule_version.unknown_behavior)
            self._create_requirement_result(run, rule_version, step, output_type, outcome, facts)

        elif output_type == RuleOutputType.FINDING_PROPOSAL.value:
            self._maybe_propose_finding(run, rule_version, step, result, facts)

        # EVIDENCE_REQUEST / WORKFLOW_GATE / CALCULATION_COMPONENT: stubbed
        # in this pass - no Evidence/Document or workflow-engine model
        # exists yet to write anything meaningful to.

    def _resolve_applicability_outcome(self, result, unknown_behavior: str) -> str:
        if result.outcome == "MATCH":
            return "APPLIES"
        if result.outcome == "NO_MATCH":
            return "DOES_NOT_APPLY"

        # UNKNOWN: fail-closed assumes the requirement stays in scope -
        # excluding it would be the "default pass" C6 forbids.
        # REQUEST_INPUT/HUMAN_REVIEW both leave the outcome UNKNOWN; the
        # distinction is read back later from rule_version.unknown_behavior
        # (see _unknown_reason), not stored redundantly here.
        if unknown_behavior == UnknownBehavior.FAIL_CLOSED.value:
            return "APPLIES"
        return "UNKNOWN"

    def _resolve_satisfaction_outcome(self, result, unknown_behavior: str) -> str:
        if result.outcome == "MATCH":
            return "SATISFIED"
        if result.outcome == "NO_MATCH":
            return "NOT_SATISFIED"
        if unknown_behavior == UnknownBehavior.FAIL_CLOSED.value:
            return "NOT_SATISFIED"
        return "UNKNOWN"

    def _create_requirement_result(
        self,
        run: AssessmentRun,
        rule_version,
        step: StepRun,
        output_type: str,
        outcome: str,
        facts: dict[str, Any],
    ) -> None:
        if rule_version.requirement_version_id is None:
            # Nothing to attach a Requirement Result to - not an error,
            # just nothing further to persist beyond the StepRun itself.
            return

        self.requirement_results.create_validated(
            step_run_id=step.id,
            assessment_run_id=run.id,
            requirement_version_id=rule_version.requirement_version_id,
            rule_version_id=rule_version.id,
            output_type=output_type,
            outcome=outcome,
            predicate_inputs=facts,
            source_locations=list(rule_version.source_locations),
        )
        self.db.commit()

    def _maybe_propose_finding(self, run, rule_version, step, result, facts) -> None:
        unknown_behavior = rule_version.unknown_behavior

        if result.outcome == "MATCH":
            rationale = f"Condition matched: {self._trace_summary(result.trace)}"
        elif result.outcome == "UNKNOWN":
            if unknown_behavior == UnknownBehavior.FAIL_CLOSED.value:
                rationale = (
                    "Required input missing; proposed under fail-closed "
                    "unknown-behavior policy rather than silently passing."
                )
            elif unknown_behavior == UnknownBehavior.HUMAN_REVIEW.value:
                rationale = (
                    "Required input missing; escalated to human review "
                    "per this rule's unknown-behavior policy."
                )
            else:  # REQUEST_INPUT - no finding, only a data gap
                return
        else:  # NO_MATCH - no issue detected
            return

        requirement_version = None
        if rule_version.requirement_version_id:
            requirement_version = self.requirement_versions.get_by_id_only(
                rule_version.requirement_version_id,
            )

        severity = requirement_version.default_severity if requirement_version else "MODERATE"
        hard_gate_effect = requirement_version.is_hard_gate if requirement_version else False
        issue_type = (
            requirement_version.obligation_type if requirement_version else f"rule:{rule_version.id}"
        )

        self.findings.propose(
            organization_id=run.organization_id,
            product_market_state_id=run.product_market_state_id,
            dimension=step.dimension,
            assessment_run_id=run.id,
            requirement_version_id=rule_version.requirement_version_id,
            rule_version_id=rule_version.id,
            subject_key=step.subject_key,
            issue_type=issue_type,
            observed_value=self._observed_value(facts),
            severity=severity,
            hard_gate_effect=hard_gate_effect,
            rationale=rationale,
        )
        self.db.commit()

    def _observed_value(self, facts: dict[str, Any]) -> str:
        wording = facts.get("wording")
        if isinstance(wording, str):
            return wording
        return json.dumps(facts, sort_keys=True, default=str)

    def _trace_summary(self, trace: list[dict]) -> str:
        return "; ".join(
            f"{entry['op']}({entry['field']})={entry['outcome']}" for entry in trace
        )

    def _derive_dimension_state(self, assessment_run_id: UUID, dimension: str) -> str:
        # Worst-first precedence, mirroring B5.3's own gate philosophy -
        # not spec-stated explicitly, flagged when this was proposed.
        #
        # Unknown-signal detection scans StepRun (the universal ledger,
        # written for every output_type) rather than RequirementResult
        # (written only for APPLICABILITY/REQUIREMENT_RESULT) - a
        # FINDING_PROPOSAL rule under REQUEST_INPUT creates neither a
        # Finding nor a RequirementResult, so RequirementResult alone
        # would silently lose that signal and the dimension would read
        # COMPLIANT instead of PENDING_INPUT.
        steps = self.step_runs.get_for_run_dimension(assessment_run_id, dimension)
        results = self.requirement_results.get_for_run_dimension(assessment_run_id, dimension)
        findings_proposed = self.finding_revisions.count_proposed_for_run_dimension(
            assessment_run_id,
            dimension,
        )

        if not steps:
            return DimensionAssessmentState.UNKNOWN.value

        engine_errored = any(s.status == StepRunStatus.FAILED.value for s in steps)

        non_compliant = findings_proposed > 0 or any(
            r.outcome == "NOT_SATISFIED" for r in results
        )
        if non_compliant:
            return DimensionAssessmentState.NON_COMPLIANT.value

        unknown_steps = [s for s in steps if s.outcome == "UNKNOWN"]

        human_review = engine_errored or any(
            self._unknown_reason_for_rule(s.rule_version_id) == UnknownBehavior.HUMAN_REVIEW.value
            for s in unknown_steps
        )
        if human_review:
            return DimensionAssessmentState.HUMAN_REVIEW_REQUIRED.value

        pending_input = any(
            self._unknown_reason_for_rule(s.rule_version_id) == UnknownBehavior.REQUEST_INPUT.value
            for s in unknown_steps
        )
        if pending_input:
            return DimensionAssessmentState.PENDING_INPUT.value

        if results and all(r.outcome == "DOES_NOT_APPLY" for r in results):
            return DimensionAssessmentState.NOT_APPLICABLE.value

        return DimensionAssessmentState.COMPLIANT.value

    def _unknown_reason_for_rule(self, rule_version_id: UUID | None) -> str | None:
        if rule_version_id is None:
            return None
        rule_version = self.rule_versions.get_by_id_only(rule_version_id)
        return rule_version.unknown_behavior if rule_version else None
