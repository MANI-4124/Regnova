from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.enums import UnknownBehavior
from app.engine import evaluate_condition
from app.modules.document_version.models import DocumentVersionStatus
from app.modules.document_version.repository import (
    DocumentFieldRepository,
    DocumentFieldRevisionRepository,
)
from app.modules.evidence.repository import EvidenceRepository
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

# Excluded when hashing DOCUMENTS facts for reuse comparison (see
# AssessmentRunService._facts_for_hashing) - derived/lineage data, not
# content. days_until_expiry is a function of run.started_at, not of
# anything that changed on the document itself; _evidence_id/
# _document_version_id are identifiers, not values, so a document being
# re-linked under a new Evidence row with byte-identical field content
# must not force a rerun on its own.
_HASH_IRRELEVANT_FACT_KEYS = frozenset({
    "days_until_expiry",
    "_evidence_id",
    "_document_version_id",
})


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
        self.evidence = EvidenceRepository(db)
        self.document_fields = DocumentFieldRepository(db)
        self.document_field_revisions = DocumentFieldRevisionRepository(db)

    def hash_facts(self, facts: dict[str, Any]) -> str:
        """
        SHA-256 over facts, sort_keys=True so nested dict key order
        never affects the result - the one hashing convention this
        service uses everywhere it needs a stable content fingerprint
        (StepRun.input_hash and DimensionAssessment.submitted_facts_hash
        both call this). Deliberately NOT list-order-insensitive and
        NOT float-rounded: a reordered list or a different float
        representation hashes differently, which only ever causes an
        unnecessary rerun, never a wrongly-skipped one - see CLAUDE.md
        "Market readiness" for why that's the accepted tradeoff.
        """

        return hashlib.sha256(
            json.dumps(facts, sort_keys=True, default=str).encode("utf-8"),
        ).hexdigest()

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
        correlation_id: str | None = None,
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
                self._run_dimension(
                    run, dimension, payload.input_facts.get(dimension, {}),
                    correlation_id=correlation_id,
                )
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
        correlation_id: str | None = None,
    ) -> None:
        """
        Public entrypoint for orchestrators (MarketReadinessService) that
        already own an AssessmentRun and need to execute a single
        dimension against it directly - bypasses SUPPORTED_DIMENSIONS
        validation, which is `create_and_run`'s guardrail for direct
        single-dimension callers via POST /assessment-runs. Market
        Readiness deliberately attempts all eight canonical dimensions
        every time; a dimension with no rule content at all naturally
        settles at DimensionAssessmentState.UNKNOWN (no rules -> no
        StepRuns -> `_derive_dimension_state`'s own
        `if not steps: return UNKNOWN`), which is exactly the signal
        G0's "required dimension Unknown" gate condition needs - not a
        reason to special-case anything here. A dimension that DOES have
        rule content but resolves zero subjects from the submitted facts
        is a different, explicit state - see
        DimensionAssessmentState.NO_SUBJECTS_RESOLVED in `_run_dimension`.
        """

        self._run_dimension(run, dimension, dimension_facts, correlation_id=correlation_id)

    def _run_dimension(
        self,
        run: AssessmentRun,
        dimension: str,
        dimension_facts: dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        release = self.releases.get_by_id(run.regulatory_basis_release_id)
        rule_versions = self.rule_versions.get_verified_active_for_dimension(
            dimension,
            release.rule_version_ids if release else [],
        )

        if dimension == "DOCUMENTS":
            product_id = self._resolve_product_id(run.organization_id, run.product_market_state_id)
            assembled = self._assemble_documents_dimension_facts(
                run.organization_id, product_id, dimension_facts, rule_versions, run.started_at,
            )
            self._run_documents_dimension(
                run, dimension_facts, rule_versions, assembled,
                correlation_id=correlation_id,
            )
            state = self._derive_dimension_state(
                run.id, dimension, run.organization_id, run.product_market_state_id,
            )
            # Hash the assembled real-facts snapshot, not the caller's
            # raw submission - see compute_documents_reuse_hash, which
            # MUST build this exact same quantity before a run even
            # happens, or MarketReadinessService's reuse comparison
            # would compare against a hash nothing else ever produces.
            facts_for_hash = assembled["hash_snapshot"]
        else:
            resolved_subject_count = self._run_subject_list_dimension(
                run, dimension, dimension_facts, rule_versions,
                correlation_id=correlation_id,
            )
            if rule_versions and resolved_subject_count == 0:
                # Active rules exist for this dimension, but nothing
                # resolved to a subject to run them against - distinct
                # from "nothing built here yet" (see
                # DimensionAssessmentState.NO_SUBJECTS_RESOLVED). Bypasses
                # _derive_dimension_state entirely: with zero StepRuns
                # either way, its own `if not steps: return UNKNOWN`
                # would otherwise silently produce the same UNKNOWN as
                # the no-rules-at-all case.
                state = DimensionAssessmentState.NO_SUBJECTS_RESOLVED.value
            else:
                state = self._derive_dimension_state(
                    run.id, dimension, run.organization_id, run.product_market_state_id,
                )
            facts_for_hash = dimension_facts

        assessment = DimensionAssessment(
            assessment_run_id=run.id,
            dimension=dimension,
            state=state,
            submitted_facts_hash=self.hash_facts(facts_for_hash),
        )
        self.dimension_assessments.create(assessment)
        self.db.commit()

    def compute_documents_reuse_hash(
        self,
        organization_id: UUID,
        product_id: UUID,
        regulatory_basis_release_id: UUID | None,
        dimension_facts: dict[str, Any],
        run_started_at: datetime | None,
    ) -> str:
        """
        Lets MarketReadinessService decide DOCUMENTS reuse against real,
        DB-resolved facts rather than the caller's raw submission - a
        deliberate deviation from Claims/Label's own two reuse checks
        (see CLAUDE.md "Assessment engine" and "Market readiness"):
        DOCUMENTS is always hash-checked, never reused on pins alone,
        because the ground truth it reads can change (a new document
        gets uploaded and linked) without the caller submitting
        anything at all this run. Builds the exact same hash_snapshot
        _run_dimension itself writes when it actually runs this
        dimension - the two must never drift apart, or reuse would
        compare against a hash nothing else ever produces.
        """
        release = self.releases.get_by_id(regulatory_basis_release_id)
        rule_versions = self.rule_versions.get_verified_active_for_dimension(
            "DOCUMENTS",
            release.rule_version_ids if release else [],
        )
        assembled = self._assemble_documents_dimension_facts(
            organization_id, product_id, dimension_facts, rule_versions, run_started_at,
        )
        return self.hash_facts(assembled["hash_snapshot"])

    def _run_subject_list_dimension(
        self,
        run: AssessmentRun,
        dimension: str,
        dimension_facts: dict[str, Any],
        rule_versions: list,
        correlation_id: str | None = None,
    ) -> int:
        """
        Claims/Label shape: the caller enumerates the complete subject
        list, and every active rule for the dimension runs against every
        subject. Subject-collection key stays dimension-specific
        ("claims" vs "label_fields") rather than a unified "items" key -
        confirmed explicitly rather than touching the already-shipped
        Claims contract.

        Any other dimension (INGREDIENTS, CLASSIFICATION_ELIGIBILITY,
        TESTING, ...) has no dedicated list shape of its own. If the
        caller submits a "claims" key anyway, it's honored exactly like
        Claims (a dimension whose rules genuinely want to iterate a list
        of items - e.g. one dosage-limit check per ingredient - can use
        it). Otherwise, whatever the caller submitted (everything except
        "product") is treated as ONE implicit subject, so a flat,
        non-list fact set (a single risk-class value, a single dosage
        reading) still gets exactly one evaluation with subject_key=None,
        rather than being silently unreachable through this method.
        Returns the number of subjects resolved, so the caller can tell
        "zero subjects because nothing was submitted/matched" apart from
        "zero subjects because this dimension has no rules at all" - see
        DimensionAssessmentState.NO_SUBJECTS_RESOLVED.
        """

        product_facts = dimension_facts.get("product", {})
        if dimension == "LABEL":
            subjects = [
                self._build_label_field_facts(item)
                for item in dimension_facts.get("label_fields", [])
            ]
            subject_key_field = "field_key"
        elif "claims" in dimension_facts:
            subjects = dimension_facts["claims"]
            subject_key_field = "claim_id"
        elif dimension_facts:
            subjects = [{k: v for k, v in dimension_facts.items() if k != "product"}]
            subject_key_field = None
        else:
            subjects = []
            subject_key_field = None

        for subject in subjects:
            subject_key = subject.get(subject_key_field) if subject_key_field else None
            subject_facts = {"product": product_facts, **subject}

            for rule_version in rule_versions:
                self._run_step(
                    run, dimension, rule_version, subject_key, subject_facts,
                    correlation_id=correlation_id,
                )

        return len(subjects)

    def _run_documents_dimension(
        self,
        run: AssessmentRun,
        dimension_facts: dict[str, Any],
        rule_versions: list,
        assembled: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """
        Documents' checklist is regulatory-basis-driven, not
        caller-driven (FR-08: "Checklist is generated from applicable
        Requirement Versions... users cannot remove a mandatory item";
        AC-FR-08-01) - unlike Claims/Label, where the caller enumerates
        the full subject list. A required document_type with no
        resolved subject at all (no linked Evidence, no caller fallback)
        is still evaluated (as empty facts), so a missing mandatory
        document is actually detected rather than silently skipped.

        Real data first, caller-supplied JSON as a per-document_type
        fallback - see _assemble_documents_dimension_facts, which does
        the actual resolution/fallback decision and (when a checklist
        item resolves more than one currently-linked document, e.g. two
        COAs) the per-document subject expansion. `assembled` lets
        _run_dimension pass in a resolution it already computed, so a
        real run and its own reuse-hash never redo (or disagree about)
        the same work twice in one call.

        Active rules are split by their linked RequirementVersion's
        subject_kind (see RequirementVersionSubjectKind) into two
        independently-evaluated subject pools - a per-document rule
        (e.g. checking expiry_date) has no meaningful facts to compare
        against a consistency-check subject and vice versa, so running
        the wrong pool against the wrong subject would silently produce
        bogus UNKNOWN/FAIL_CLOSED results for rules never meant to apply
        there. Consistency checks stay entirely caller-supplied - no
        Consistency Check mechanism exists yet (C8, unbuilt) - unaffected
        by any of this.
        """

        product_facts = dimension_facts.get("product", {})

        if assembled is None:
            product_id = self._resolve_product_id(run.organization_id, run.product_market_state_id)
            assembled = self._assemble_documents_dimension_facts(
                run.organization_id, product_id, dimension_facts, rule_versions, run.started_at,
            )

        document_rules = assembled["document_rules"]
        consistency_rules = [
            rule_version
            for rule_version in rule_versions
            if rule_version.requirement_version.subject_kind
            == RequirementVersionSubjectKind.CONSISTENCY_CHECK.value
        ]

        for document_type, subjects in assembled["resolved_subjects"].items():
            for subject_key, facts in subjects:
                subject_facts = {"product": product_facts, **facts}

                for rule_version in document_rules:
                    if rule_version.requirement_version.obligation_type != document_type:
                        continue
                    self._run_step(
                        run, "DOCUMENTS", rule_version, subject_key, subject_facts,
                        correlation_id=correlation_id,
                    )

        for check in dimension_facts.get("consistency_checks", []):
            check_key = check.get("check_key")
            subject_facts = {
                "product": product_facts,
                **self._build_consistency_check_facts(check),
            }

            for rule_version in consistency_rules:
                self._run_step(
                    run, "DOCUMENTS", rule_version, check_key, subject_facts,
                    correlation_id=correlation_id,
                )

    def _resolve_product_id(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> UUID | None:
        state = self.product_market_states.get_by_id_only(organization_id, product_market_state_id)
        return state.product_id if state else None

    def _assemble_documents_dimension_facts(
        self,
        organization_id: UUID,
        product_id: UUID | None,
        dimension_facts: dict[str, Any],
        rule_versions: list,
        run_started_at: datetime | None,
    ) -> dict[str, Any]:
        """
        Single source of truth for what the DOCUMENTS dimension actually
        sees per checklist item - called both to actually run rules
        (_run_documents_dimension) and, before that, to decide whether a
        rerun is even needed (compute_documents_reuse_hash). The two
        calls MUST stay in agreement: MarketReadinessService compares a
        hash computed here (pre-run) against a hash stored from a real
        run of this same method, so any divergence between the two call
        sites would make reuse silently wrong. See CLAUDE.md "Assessment
        engine".

        Real Evidence-backed data wins per document_type, whole-hog -
        never merged with caller-supplied fields for the same checklist
        item. Only a document_type with ZERO currently-linked, VERIFIED
        Evidence falls back to the caller's documents[] JSON, preserving
        every existing test/TESTLAND fixture unchanged (neither has any
        real Evidence rows to resolve, so they always hit the fallback).

        Multiple currently-linked documents for one document_type (e.g.
        two COAs) are each evaluated as their own subject, not merged or
        arbitrarily reduced to one - dropping either would hide a real
        compliance issue. subject_key stays exactly document_type when
        exactly one document resolves (preserving Finding continuity/
        dedup for the overwhelmingly common case), and becomes
        f"{document_type}#{evidence_id}" only when there's more than
        one - stable per link, not per position, so re-running doesn't
        spuriously create new Findings unless the link itself changes.
        """

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

        document_types: list[str] = []
        seen: set[str] = set()
        for rule_version in document_rules:
            document_type = rule_version.requirement_version.obligation_type
            if document_type not in seen:
                seen.add(document_type)
                document_types.append(document_type)

        resolved_subjects: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        hash_snapshot: dict[str, Any] = {}

        for document_type in document_types:
            relevant_requirement_version_ids = {
                rule_version.requirement_version_id
                for rule_version in document_rules
                if rule_version.requirement_version.obligation_type == document_type
            }

            evidence_list = (
                self._resolve_document_evidence(
                    organization_id, product_id, document_type, relevant_requirement_version_ids,
                )
                if product_id is not None
                else []
            )

            if evidence_list:
                subjects = []
                for evidence in evidence_list:
                    subject_key = (
                        document_type if len(evidence_list) == 1
                        else f"{document_type}#{evidence.id}"
                    )
                    facts = self._build_document_facts_from_evidence(document_type, evidence)
                    facts = self._maybe_add_days_until_expiry(facts, run_started_at)
                    subjects.append((subject_key, facts))
            else:
                submitted = submitted_documents.get(document_type)
                facts = self._build_document_facts(document_type, submitted, run_started_at)
                subjects = [(document_type, facts)]

            resolved_subjects[document_type] = subjects
            hash_snapshot[document_type] = [
                self._facts_for_hashing(facts) for _subject_key, facts in subjects
            ]

        return {
            "document_rules": document_rules,
            "resolved_subjects": resolved_subjects,
            "hash_snapshot": {
                "documents": hash_snapshot,
                "consistency_checks": dimension_facts.get("consistency_checks", []),
                "product": dimension_facts.get("product", {}),
            },
        }

    def _resolve_document_evidence(
        self,
        organization_id: UUID,
        product_id: UUID,
        document_type: str,
        relevant_requirement_version_ids: set[UUID | None],
    ) -> list:
        """
        Two-tier match (see CLAUDE.md "Assessment engine"): Evidence
        explicitly scoped to one of this checklist item's own
        requirement_version_ids wins outright; otherwise product-wide
        Evidence (requirement_version_id IS NULL) is the fallback.
        Evidence scoped to a DIFFERENT requirement is excluded entirely,
        even if the document_type matches - it was deliberately linked
        elsewhere and shouldn't leak into an unrelated checklist item
        just because the two share a document type.
        """

        candidates = self.evidence.get_current_verified_for_product_and_document_type(
            organization_id, product_id, document_type,
        )
        if not candidates:
            return []

        exact = [
            evidence for evidence in candidates
            if evidence.requirement_version_id in relevant_requirement_version_ids
        ]
        if exact:
            return exact

        return [evidence for evidence in candidates if evidence.requirement_version_id is None]

    def _build_document_facts_from_evidence(
        self,
        document_type: str,
        evidence,
    ) -> dict[str, Any]:
        """
        Mirrors _build_document_facts' shape exactly (same document_type/
        status/per-field {"value","confidence"} convention) so a
        checklist item's rules never need to know or care which source
        backed it. status is the DocumentVersion's own real status
        (always VERIFIED - Evidence only ever links a VERIFIED version),
        replacing the old synthetic "uploaded" marker; every rule
        condition in this codebase only ever checks status via exists/
        not_exists, never its literal value, so this is a strict
        improvement, not a behavior change. _evidence_id/
        _document_version_id are lineage-only - never referenced by any
        rule condition, stripped before hashing (see
        _facts_for_hashing) - kept in the real facts so a Finding/
        StepRun stemming from this subject can be traced back to the
        exact file.
        """

        facts: dict[str, Any] = {
            "document_type": document_type,
            "status": DocumentVersionStatus.VERIFIED.value,
            "_evidence_id": str(evidence.id),
            "_document_version_id": str(evidence.document_version_id),
        }

        location = None
        for document_field in self.document_fields.get_all_for_version(evidence.document_version_id):
            revision = self.document_field_revisions.get_latest(document_field.id)
            if revision is None or revision.value is None:
                continue
            facts[document_field.field_key] = self._wrap_confidence_value(
                revision.value, revision.confidence,
            )
            if location is None and revision.location is not None:
                location = revision.location

        if location is not None:
            facts["location"] = location

        return facts

    def _wrap_confidence_value(self, value: Any, confidence: float | None) -> Any:
        """
        A value with no recorded confidence is a plain, unwrapped scalar -
        not gated, treated the same as any fact with no confidence
        semantics at all (Claims' plain facts). Only a value with an
        EXPLICIT confidence is wrapped, and therefore confidence-gated by
        the engine exactly like OCR output. Null must never reach the
        engine inside a {"value","confidence"} dict -
        condition_evaluator.py's own "malformed input" fail-safe would
        silently force it to 0.0 (maximally untrustworthy), a materially
        different claim than "nobody has recorded a confidence for this
        yet" - manual entry's whole premise (see CLAUDE.md "Document
        storage and versioning"). See CLAUDE.md "Assessment engine".
        """
        if confidence is None:
            return value
        return {"value": value, "confidence": confidence}

    def _unwrap_confidence_value(self, raw: Any) -> tuple[Any, float | None]:
        if isinstance(raw, dict) and "value" in raw and "confidence" in raw:
            return raw.get("value"), raw.get("confidence")
        return raw, None

    def _facts_for_hashing(self, facts: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in facts.items()
            if key not in _HASH_IRRELEVANT_FACT_KEYS
        }

    def _build_document_facts(
        self,
        document_type: str,
        item: dict[str, Any] | None,
        run_started_at: datetime | None,
    ) -> dict[str, Any]:
        """
        The caller-supplied fallback path - only reached for a
        document_type with no currently-linked, VERIFIED Evidence (see
        _assemble_documents_dimension_facts). item is None when the
        caller never submitted anything for this checklist document_type
        at all - facts then carry only document_type, so a not_exists
        check on "status" (always present whenever anything was
        genuinely on file) correctly detects "missing entirely". Same
        null-value-omission convention Label's _build_label_field_facts
        established: a field whose value is None is omitted from facts
        rather than built as a null-valued wrapper, which would make it
        structurally "exist".

        Each extracted business field (manufacturer, expiry_date, ...)
        arrives {"value", "confidence"}-shaped from the caller, unlike
        Label's single flat value/confidence pair - a document has
        several independently-extracted fields at once, so each gets its
        own wrapper directly rather than one shared indirection key. A
        null/absent confidence unwraps to a plain value - see
        _wrap_confidence_value - the same rule the real-evidence path
        uses, so the two stay behaviorally consistent for callers who
        happen to submit confidence: null themselves.

        expiry_date additionally yields a derived days_until_expiry fact
        (see _maybe_add_days_until_expiry) - computed here, not in the
        engine, which must stay a pure function of condition+facts to
        keep StepRun replay deterministic (see CLAUDE.md), from the
        run's own started_at, not wall-clock now().
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
            facts[field_key] = self._wrap_confidence_value(
                field_value.get("value"), field_value.get("confidence"),
            )

        return self._maybe_add_days_until_expiry(facts, run_started_at)

    def _maybe_add_days_until_expiry(
        self,
        facts: dict[str, Any],
        run_started_at: datetime | None,
    ) -> dict[str, Any]:
        """
        Shared by both the real-evidence and caller-fallback paths, so
        expiry banding (FR-08's 90/60/30/7-day rules) works identically
        regardless of source. Mirrors expiry_date's own wrapped-or-plain
        shape - inherits its confidence when it has one, stays a plain
        int when expiry_date itself was unwrapped (null confidence).
        """
        if "expiry_date" not in facts or run_started_at is None:
            return facts

        expiry_value, expiry_confidence = self._unwrap_confidence_value(facts["expiry_date"])
        days = self._compute_days_until_expiry(expiry_value, run_started_at)
        if days is not None:
            facts["days_until_expiry"] = self._wrap_confidence_value(days, expiry_confidence)

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
        correlation_id: str | None = None,
    ) -> None:
        input_hash = self.hash_facts(facts)

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

        self._apply_output(run, rule_version, step, result, facts, correlation_id=correlation_id)

    def _effective_unknown_behavior(self, result, rule_version) -> str:
        if result.unknown_reason == "low_confidence":
            # Hard-pinned per AC-FR-06-02 - low-confidence OCR must never
            # silently pass a mandatory check, regardless of what this
            # rule's own unknown_behavior declares. Confirmed explicitly
            # rather than leaving it rule-configurable.
            return UnknownBehavior.HUMAN_REVIEW.value
        return rule_version.unknown_behavior

    def _apply_output(
        self, run, rule_version, step, result, facts, correlation_id: str | None = None,
    ) -> None:
        output_type = rule_version.output_type
        effective_unknown_behavior = self._effective_unknown_behavior(result, rule_version)

        if output_type == RuleOutputType.APPLICABILITY.value:
            outcome = self._resolve_applicability_outcome(result, effective_unknown_behavior)
            self._create_requirement_result(run, rule_version, step, output_type, outcome, facts)

        elif output_type == RuleOutputType.REQUIREMENT_RESULT.value:
            outcome = self._resolve_satisfaction_outcome(result, effective_unknown_behavior)
            self._create_requirement_result(run, rule_version, step, output_type, outcome, facts)

        elif output_type == RuleOutputType.FINDING_PROPOSAL.value:
            self._maybe_propose_finding(
                run, rule_version, step, result, facts, correlation_id=correlation_id,
            )

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

    def _maybe_propose_finding(
        self, run, rule_version, step, result, facts, correlation_id: str | None = None,
    ) -> None:
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
            correlation_id=correlation_id,
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

    def _derive_dimension_state(
        self,
        assessment_run_id: UUID,
        dimension: str,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> str:
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

        # findings_proposed only sees revisions created during THIS run -
        # a Finding that's moved past PROPOSED (OPEN, CUSTOMER_RESPONDED)
        # correctly gets no new revision from propose() on a fresh
        # rerun, so it would go uncounted without this third,
        # run-independent check. Additive to, not a replacement for,
        # the two existing signals - same "OR another signal in" shape
        # as the hard_gate_effect fix at the gate level. Only helps a
        # FRESH (non-reused) computation - see CLAUDE.md "Known
        # limitations" for the reuse gap this does not close.
        non_compliant = (
            findings_proposed > 0
            or any(r.outcome == "NOT_SATISFIED" for r in results)
            or self.findings.has_open_finding(organization_id, product_market_state_id, dimension)
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
