from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
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
from app.modules.requirement_version.models import RequirementVersionSubjectKind
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

SUPPORTED_DIMENSIONS = frozenset({"CLAIMS", "LABEL", "DOCUMENTS"})


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

    def run_dimension(
        self,
        run: AssessmentRun,
        dimension: str,
        dimension_facts: dict[str, Any],
    ) -> None:
        """
        Public entrypoint for orchestrators (MarketReadinessService) that
        already own an AssessmentRun and need to execute a single
        dimension against it directly - bypasses SUPPORTED_DIMENSIONS
        validation, which is `create_and_run`'s guardrail for direct
        single-dimension callers via POST /assessment-runs. Market
        Readiness deliberately attempts all eight canonical dimensions
        every time; the five with no rule content yet naturally settle
        at DimensionAssessmentState.UNKNOWN (no rules -> no StepRuns ->
        `_derive_dimension_state`'s own `if not steps: return UNKNOWN`),
        which is exactly the signal G0's "required dimension Unknown"
        gate condition needs - not a reason to special-case anything
        here.
        """

        self._run_dimension(run, dimension, dimension_facts)

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

        if dimension == "DOCUMENTS":
            self._run_documents_dimension(run, dimension_facts, rule_versions)
        else:
            self._run_subject_list_dimension(run, dimension, dimension_facts, rule_versions)

        state = self._derive_dimension_state(run.id, dimension)
        assessment = DimensionAssessment(
            assessment_run_id=run.id,
            dimension=dimension,
            state=state,
        )
        self.dimension_assessments.create(assessment)
        self.db.commit()

    def _run_subject_list_dimension(
        self,
        run: AssessmentRun,
        dimension: str,
        dimension_facts: dict[str, Any],
        rule_versions: list,
    ) -> None:
        """
        Claims/Label shape: the caller enumerates the complete subject
        list, and every active rule for the dimension runs against every
        subject. Subject-collection key stays dimension-specific
        ("claims" vs "label_fields") rather than a unified "items" key -
        confirmed explicitly rather than touching the already-shipped
        Claims contract.
        """

        product_facts = dimension_facts.get("product", {})
        if dimension == "LABEL":
            subjects = [
                self._build_label_field_facts(item)
                for item in dimension_facts.get("label_fields", [])
            ]
            subject_key_field = "field_key"
        else:
            subjects = dimension_facts.get("claims", [])
            subject_key_field = "claim_id"

        for subject in subjects:
            subject_key = subject.get(subject_key_field)
            subject_facts = {"product": product_facts, **subject}

            for rule_version in rule_versions:
                self._run_step(run, dimension, rule_version, subject_key, subject_facts)

    def _run_documents_dimension(
        self,
        run: AssessmentRun,
        dimension_facts: dict[str, Any],
        rule_versions: list,
    ) -> None:
        """
        Documents' checklist is regulatory-basis-driven, not
        caller-driven (FR-08: "Checklist is generated from applicable
        Requirement Versions... users cannot remove a mandatory item";
        AC-FR-08-01) - unlike Claims/Label, where the caller enumerates
        the full subject list. A required document_type the caller never
        submitted is still evaluated (as empty facts), so a missing
        mandatory document is actually detected rather than silently
        skipped.

        Active rules are split by their linked RequirementVersion's
        subject_kind (see RequirementVersionSubjectKind) into two
        independently-evaluated subject pools - a per-document rule
        (e.g. checking expiry_date) has no meaningful facts to compare
        against a consistency-check subject and vice versa, so running
        the wrong pool against the wrong subject would silently produce
        bogus UNKNOWN/FAIL_CLOSED results for rules never meant to apply
        there.
        """

        product_facts = dimension_facts.get("product", {})
        submitted_documents = {
            item.get("document_type"): item
            for item in dimension_facts.get("documents", [])
        }

        document_rules = [
            rule_version
            for rule_version in rule_versions
            if rule_version.requirement_version.subject_kind
            != RequirementVersionSubjectKind.CONSISTENCY_CHECK.value
        ]
        consistency_rules = [
            rule_version
            for rule_version in rule_versions
            if rule_version.requirement_version.subject_kind
            == RequirementVersionSubjectKind.CONSISTENCY_CHECK.value
        ]

        document_types: list[str] = []
        seen: set[str] = set()
        for rule_version in document_rules:
            document_type = rule_version.requirement_version.obligation_type
            if document_type not in seen:
                seen.add(document_type)
                document_types.append(document_type)

        for document_type in document_types:
            submitted = submitted_documents.get(document_type)
            subject_facts = {
                "product": product_facts,
                **self._build_document_facts(document_type, submitted, run.started_at),
            }

            for rule_version in document_rules:
                if rule_version.requirement_version.obligation_type != document_type:
                    continue
                self._run_step(run, "DOCUMENTS", rule_version, document_type, subject_facts)

        for check in dimension_facts.get("consistency_checks", []):
            check_key = check.get("check_key")
            subject_facts = {
                "product": product_facts,
                **self._build_consistency_check_facts(check),
            }

            for rule_version in consistency_rules:
                self._run_step(run, "DOCUMENTS", rule_version, check_key, subject_facts)

    def _build_document_facts(
        self,
        document_type: str,
        item: dict[str, Any] | None,
        run_started_at: datetime | None,
    ) -> dict[str, Any]:
        """
        item is None when the caller never submitted anything for this
        checklist document_type at all - facts then carry only
        document_type, so a not_exists check on "status" (always present
        whenever anything was genuinely uploaded) correctly detects
        "missing entirely". This is the same null-value-omission
        convention Label's _build_label_field_facts established: a field
        whose value is None is omitted from facts rather than built as a
        null-valued wrapper, which would make it structurally "exist".

        Each extracted business field (manufacturer, expiry_date, ...)
        arrives already {"value", "confidence"}-wrapped from the caller,
        unlike Label's single flat value/confidence pair - a document has
        several independently-extracted fields at once, so each gets its
        own wrapper directly rather than one shared indirection key.

        expiry_date additionally yields a derived days_until_expiry fact,
        computed here (not in the engine, which must stay a pure function
        of condition+facts to keep StepRun replay deterministic - see
        CLAUDE.md) from the run's own started_at, not wall-clock now().
        It inherits expiry_date's own confidence: the day-count arithmetic
        itself adds no uncertainty beyond what the OCR read already carries.
        """

        if item is None:
            return {"document_type": document_type}

        facts: dict[str, Any] = {"document_type": document_type}

        if item.get("status") is not None:
            facts["status"] = item["status"]

        for field_key, field_value in item.items():
            if field_key in ("document_type", "status"):
                continue
            if not isinstance(field_value, dict) or field_value.get("value") is None:
                continue
            facts[field_key] = {
                "value": field_value.get("value"),
                "confidence": field_value.get("confidence"),
            }

        if "expiry_date" in facts and run_started_at is not None:
            days = self._compute_days_until_expiry(facts["expiry_date"]["value"], run_started_at)
            if days is not None:
                facts["days_until_expiry"] = {
                    "value": days,
                    "confidence": facts["expiry_date"]["confidence"],
                }

        return facts

    def _compute_days_until_expiry(
        self,
        expiry_date_value: Any,
        run_started_at: datetime,
    ) -> int | None:
        try:
            expiry = date.fromisoformat(expiry_date_value)
        except (TypeError, ValueError):
            return None

        return (expiry - run_started_at.date()).days

    def _build_consistency_check_facts(self, check: dict[str, Any]) -> dict[str, Any]:
        """
        The comparison itself (does "Acme Corp" mean the same manufacturer
        as "Acme Corporation") is out of scope here - per C8's own
        "Consistency Check" entity ("Pair/set of normalized fields |
        Compared values, match policy, outcome, confidence and resulting
        finding"), that computation belongs to a real Consistency Check
        mechanism, unbuilt. The caller supplies the already-computed
        outcome as a fact, confidence-wrapped like any other
        extraction-derived value, same null-value-omission convention as
        documents/label fields.
        """

        facts: dict[str, Any] = {
            "check_key": check.get("check_key"),
            "compared_field": check.get("compared_field"),
            "value_a": check.get("value_a"),
            "value_b": check.get("value_b"),
            "document_types": check.get("document_types"),
        }

        outcome = check.get("outcome")
        if isinstance(outcome, dict) and outcome.get("value") is not None:
            facts["outcome"] = {
                "value": outcome.get("value"),
                "confidence": outcome.get("confidence"),
            }

        return facts

    def _build_label_field_facts(self, item: dict[str, Any]) -> dict[str, Any]:
        """
        A caller-supplied label_fields[] item is {field_key, value,
        confidence, location} - flat, matching how the request payload
        is documented. The engine's confidence gate only fires when a
        condition leaf resolves directly onto a {"value", "confidence"}
        wrapper (see app.engine.condition_evaluator), so value/confidence
        get nested under a fixed "extracted" key here - Label rule
        conditions reference "extracted" as the field to get confidence
        gating; "field_key"/"location" stay top-level for subject_key
        and Finding.observed_location respectively. This nesting is an
        internal wire-format detail, not part of the request payload.

        A null value (nothing extracted for this field at all) omits
        "extracted" entirely rather than building a wrapper around a
        null - otherwise the field would always structurally "exist"
        (as a null-valued wrapper) even when the mandatory check is
        exactly that nothing was found, making not_exists/missing-field
        UNKNOWN handling unreachable for the one case Label needs them
        most.
        """

        facts: dict[str, Any] = {
            "field_key": item.get("field_key"),
            "location": item.get("location"),
        }

        if item.get("value") is not None:
            facts["extracted"] = {"value": item.get("value"), "confidence": item.get("confidence")}

        return facts

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
        step.unknown_reason = result.unknown_reason
        step.trace = result.trace
        self.step_runs.create(step)
        self.db.commit()

        self._apply_output(run, rule_version, step, result, facts)

    def _effective_unknown_behavior(self, result, rule_version) -> str:
        if result.unknown_reason == "low_confidence":
            # Hard-pinned per AC-FR-06-02 - low-confidence OCR must never
            # silently pass a mandatory check, regardless of what this
            # rule's own unknown_behavior declares. Confirmed explicitly
            # rather than leaving it rule-configurable.
            return UnknownBehavior.HUMAN_REVIEW.value
        return rule_version.unknown_behavior

    def _apply_output(self, run, rule_version, step, result, facts) -> None:
        output_type = rule_version.output_type
        effective_unknown_behavior = self._effective_unknown_behavior(result, rule_version)

        if output_type == RuleOutputType.APPLICABILITY.value:
            outcome = self._resolve_applicability_outcome(result, effective_unknown_behavior)
            self._create_requirement_result(run, rule_version, step, output_type, outcome, facts)

        elif output_type == RuleOutputType.REQUIREMENT_RESULT.value:
            outcome = self._resolve_satisfaction_outcome(result, effective_unknown_behavior)
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
        if result.outcome == "MATCH":
            rationale = f"Condition matched: {self._trace_summary(result.trace)}"
        elif result.outcome == "UNKNOWN":
            if result.unknown_reason == "low_confidence":
                # Hard-pinned per AC-FR-06-02, regardless of what this
                # rule's own unknown_behavior declares - see
                # _effective_unknown_behavior. Internal/RA-facing text,
                # not customer-facing (same split as RequirementVersion's
                # canonical_statement/customer_safe_explanation).
                rationale = (
                    f"{self._low_confidence_summary(result.trace)} - routed to "
                    "human review per AC-FR-06-02 (low-confidence OCR must "
                    "never silently pass a mandatory check), overriding this "
                    f"rule's own unknown_behavior ({rule_version.unknown_behavior})."
                )
            elif rule_version.unknown_behavior == UnknownBehavior.FAIL_CLOSED.value:
                rationale = (
                    "Required input missing; proposed under fail-closed "
                    "unknown-behavior policy rather than silently passing."
                )
            elif rule_version.unknown_behavior == UnknownBehavior.HUMAN_REVIEW.value:
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
            observed_location=facts.get("location"),
            severity=severity,
            hard_gate_effect=hard_gate_effect,
            rationale=rationale,
        )
        self.db.commit()

    def _observed_value(self, facts: dict[str, Any]) -> str:
        wording = facts.get("wording")
        if isinstance(wording, str):
            return wording

        extracted = facts.get("extracted")
        if isinstance(extracted, dict) and "value" in extracted:
            return json.dumps(extracted["value"], default=str)

        return json.dumps(facts, sort_keys=True, default=str)

    def _low_confidence_summary(self, trace: list[dict]) -> str:
        entries = [entry for entry in trace if entry.get("reason") == "low_confidence"]
        if not entries:
            return "Extraction confidence below required threshold"

        return "; ".join(
            f"{entry['field']} confidence {entry['confidence']:.2f} below required threshold"
            for entry in entries
        )

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

        # low_confidence is hard-pinned to HUMAN_REVIEW_REQUIRED (AC-FR-06-02)
        # regardless of what the step's own rule declares - checked
        # directly on the step, not via a rule-lookup, since the rule's
        # declared unknown_behavior might say something else entirely
        # (FAIL_CLOSED/REQUEST_INPUT) and still be overridden here.
        human_review = engine_errored or any(
            s.unknown_reason == "low_confidence"
            or self._unknown_reason_for_rule(s.rule_version_id) == UnknownBehavior.HUMAN_REVIEW.value
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
