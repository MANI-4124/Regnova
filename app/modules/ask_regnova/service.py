from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.modules.document_version.repository import (
    DocumentFieldRepository,
    DocumentFieldRevisionRepository,
    DocumentVersionRepository,
)
from app.modules.finding.repository import FindingRepository, FindingRevisionRepository
from app.modules.organization.service import require_organization_synthetic
from app.modules.product_market_state.repository import ProductMarketStateRepository
from app.modules.rbac.exceptions import PermissionDenied
from app.modules.rbac.service import RBACService
from app.modules.requirement_version.exceptions import RequirementVersionNotFound
from app.modules.requirement_version.models import RequirementVersionStatus
from app.modules.requirement_version.service import RequirementVersionService
from app.modules.rule_version.exceptions import RuleVersionNotFound
from app.modules.rule_version.service import RuleVersionService
from app.modules.source_version.exceptions import SourceVersionNotFound
from app.modules.source_version.service import SourceVersionService
from app.modules.state_snapshot.repository import StateSnapshotRepository
from app.modules.user.models import User
from app.query_classification import (
    AskRegnovaQuestionClass,
    GeminiQueryClassifier,
    QueryClassificationUnavailable,
    QueryClassifier,
    VALID_INTENTS_BY_CLASS,
)

from .exceptions import AskRegnovaQuestionEmpty
from .models import AskRegnovaQuery
from .repository import AskRegnovaQueryRepository

MAX_WITHIN_DAYS = 365


class AskRegnovaService:
    """
    FR-11's query router. Orchestrates: (1) classify the question into a
    class+intent+bounded-params selection via QueryClassifier - a
    technical-layer dependency that NEVER touches the database itself;
    (2) dispatch to one of a fixed set of hand-written, parameterized
    handlers, keyed by (class, intent) - the model's output selects
    WHICH handler runs, never what it does; (3) record the full
    classification + answer on an AskRegnovaQuery ledger row, win or
    degrade. See CLAUDE.md "Ask RegNova" for the full design.

    Every handler receives organization_id from THIS service's own
    caller (current_user.organization_id, via the router) - never from
    the classifier's params, which structurally cannot carry it (see
    app/query_classification/__init__.py's fixed _PARAM_KEYS, none of
    which is an org id). This is what makes tenant scoping hold even
    though the model is choosing which query runs.
    """

    def __init__(self, db: Session, classifier: QueryClassifier, settings: Settings | None = None):
        self.db = db
        self.classifier = classifier
        self.settings = settings or get_settings()
        self.queries = AskRegnovaQueryRepository(db)
        self.product_market_states = ProductMarketStateRepository(db)
        self.document_versions = DocumentVersionRepository(db)
        self.document_fields = DocumentFieldRepository(db)
        self.document_field_revisions = DocumentFieldRevisionRepository(db)
        self.findings = FindingRepository(db)
        self.finding_revisions = FindingRevisionRepository(db)
        self.requirement_versions = RequirementVersionService(db)
        self.rule_versions = RuleVersionService(db)
        self.source_versions = SourceVersionService(db)
        self.state_snapshots = StateSnapshotRepository(db)

    def get_all(self, organization_id: UUID) -> list[AskRegnovaQuery]:
        return self.queries.get_all(organization_id)

    def _requirement_citation(self, requirement_version) -> dict[str, Any]:
        """
        Assembled entirely from real rows already loaded - never from
        anything the model said. See CLAUDE.md "Ask RegNova" point 3.
        Closes the traceability gap named there: source_version_id is
        already on SourceLocation, and RequirementVersionService/
        RuleVersionService/SourceVersionService's new get_by_id_only
        (see CLAUDE.md "Ask RegNova" point 0) is what makes the last hop
        (SourceLocation -> SourceVersion) resolvable at all.
        """
        sources = []
        for location in requirement_version.source_locations:
            try:
                source_version = self.source_versions.get_by_id_only(location.source_version_id)
            except SourceVersionNotFound:
                source_version = None
            coords = {
                field: getattr(location, field)
                for field in ("section", "article", "schedule", "page", "table_ref", "paragraph")
                if getattr(location, field)
            }
            sources.append({
                "source_location_id": str(location.id),
                "coordinates": coords,
                "normalized_text": location.normalized_text,
                "source_version_id": str(location.source_version_id),
                "source_title": source_version.title if source_version else None,
                "issuing_authority": source_version.issuing_authority if source_version else None,
                "tier": source_version.tier if source_version else None,
            })

        return {
            "requirement_version_id": str(requirement_version.id),
            "obligation_type": requirement_version.obligation_type,
            "canonical_statement": requirement_version.canonical_statement,
            "authority_interpretation_label": requirement_version.authority_interpretation_label,
            "status": requirement_version.status,
            "sources": sources,
        }

    def ask(
        self,
        organization_id: UUID,
        question: str,
        *,
        current_user: User,
    ) -> AskRegnovaQuery:
        question = question.strip()
        if not question:
            raise AskRegnovaQuestionEmpty()

        try:
            # Organization.is_synthetic gate (see CLAUDE.md "Ask
            # RegNova") - checked against the INJECTED classifier's own
            # type, not a settings string - see AssessmentRunService's
            # identical guard for the full reasoning.
            if (
                isinstance(self.classifier, GeminiQueryClassifier)
                and not require_organization_synthetic(self.db, organization_id)
            ):
                raise QueryClassificationUnavailable(
                    "organization_not_synthetic",
                    "Organization.is_synthetic is not set - the Gemini free tier "
                    "must only ever see confirmed-synthetic organizations' data.",
                )
            result = self.classifier.classify(question=question)
        except QueryClassificationUnavailable as exc:
            # Graceful degradation: Ask RegNova's whole function IS the
            # classification step, so there is no deterministic-rules-
            # alone fallback the way the assessment engine has one.
            # Failure must be visible and honest, never a lesser guessed
            # answer - see CLAUDE.md "Ask RegNova". degraded_reason
            # records exc.reason VERBATIM (not a generic bucket) - e.g.
            # "organization_not_synthetic" vs. "timeout" vs. "http_error"
            # are diagnostically different and this is the one place
            # that distinction survives into the ledger.
            return self._save(
                organization_id, current_user.id, question,
                question_class=AskRegnovaQuestionClass.UNSUPPORTED.value,
                intent="", params={}, confidence=0.0,
                model_identifier="unavailable", prompt_version="unavailable",
                structured_result=None, sources=[],
                narrative=(
                    "Ask RegNova is temporarily unavailable. Please use the "
                    "dashboard directly for now."
                ),
                degraded=True, degraded_reason=exc.reason,
            )

        handler = _INTENT_HANDLERS.get((result.question_class, result.intent))

        # Confidence only gates a class/intent that WOULD otherwise
        # dispatch - a genuinely UNSUPPORTED classification (no handler
        # exists for it at any confidence) reports "unsupported", not
        # "low_confidence"; the two are different situations (see
        # CLAUDE.md "Ask RegNova" point 1) and the classifier's own
        # StubQueryClassifier default (UNSUPPORTED, confidence 0.0)
        # would otherwise always read as "low_confidence" instead, which
        # is the wrong diagnosis.
        if handler is not None and result.confidence < self.settings.ask_regnova_classification_confidence_threshold:
            return self._save(
                organization_id, current_user.id, question,
                question_class=result.question_class, intent=result.intent,
                params=result.params, confidence=result.confidence,
                model_identifier=result.model_identifier, prompt_version=result.prompt_version,
                structured_result=None, sources=[],
                narrative="I'm not confident I understood that question - could you rephrase it?",
                degraded=True, degraded_reason="low_confidence",
            )

        if handler is None:
            narrative, reason = _not_dispatchable_response(result.question_class)
            return self._save(
                organization_id, current_user.id, question,
                question_class=result.question_class, intent=result.intent,
                params=result.params, confidence=result.confidence,
                model_identifier=result.model_identifier, prompt_version=result.prompt_version,
                structured_result=None, sources=[], narrative=narrative,
                degraded=True, degraded_reason=reason,
            )

        try:
            structured_result, sources, narrative = handler(self, organization_id, result.params, current_user)
        except PermissionDenied:
            # Per-intent RBAC, re-checked in the handler, not once at the
            # router - see CLAUDE.md "Ask RegNova" point 5. A low-tier
            # user cannot use natural language to reach data their own
            # role would be refused on the direct endpoint.
            raise

        return self._save(
            organization_id, current_user.id, question,
            question_class=result.question_class, intent=result.intent,
            params=result.params, confidence=result.confidence,
            model_identifier=result.model_identifier, prompt_version=result.prompt_version,
            structured_result=structured_result, sources=sources, narrative=narrative,
            degraded=False, degraded_reason=None,
        )

    def _save(
        self, organization_id, actor_user_id, question, *,
        question_class, intent, params, confidence, model_identifier, prompt_version,
        structured_result, sources, narrative, degraded, degraded_reason,
    ) -> AskRegnovaQuery:
        record = AskRegnovaQuery(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            question=question,
            question_class=question_class,
            intent=intent,
            params=params,
            confidence=confidence,
            model_identifier=model_identifier,
            prompt_version=prompt_version,
            structured_result=structured_result,
            sources=sources,
            narrative=narrative,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )
        self.queries.create(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    # --- Shipped intent handlers -----------------------------------
    # Each returns (structured_result, sources, narrative). narrative is
    # code-templated from structured_result directly - no second,
    # narration-generating LLM call in this pass (see CLAUDE.md
    # "Ask RegNova"). organization_id always comes from this service's
    # own caller, never from `params`.

    def _handle_products_by_gate(self, organization_id, params, current_user):
        RBACService.require_role(self.db, current_user, "ADMIN", "MANAGER")

        gate = (params.get("gate") or "").strip().upper() or None
        states = self.product_market_states.get_all_for_organization(organization_id, gate=gate)

        structured_result = {
            "gate": gate,
            "count": len(states),
            "product_market_state_ids": [str(s.id) for s in states],
        }
        if gate:
            narrative = f"{len(states)} product market state(s) are currently at gate {gate}."
        else:
            narrative = f"{len(states)} product market state(s) total in your portfolio."
        return structured_result, [], narrative

    def _handle_documents_expiring_within(self, organization_id, params, current_user):
        RBACService.require_role(self.db, current_user, "ADMIN", "MANAGER")

        try:
            within_days = int(params.get("within_days") or "90")
        except ValueError:
            within_days = 90
        within_days = max(1, min(within_days, MAX_WITHIN_DAYS))

        # Wall-clock now(), deliberately NOT AssessmentRun.started_at -
        # unlike the engine's own days_until_expiry, Ask RegNova writes
        # no replayable StepRun, so there is no determinism constraint
        # pinning "now" to anything but the real current time. See
        # CLAUDE.md "Ask RegNova" point 2.
        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=within_days)

        expiring: list[dict[str, Any]] = []
        for version in self.document_versions.get_all_verified_for_organization(organization_id):
            field = self.document_fields.get_by_key(version.id, "expiry_date")
            if field is None:
                continue
            revision = self.document_field_revisions.get_latest(field.id)
            if revision is None or not revision.value:
                continue
            try:
                expiry = date.fromisoformat(str(revision.value)[:10])
            except ValueError:
                continue
            if expiry <= cutoff:
                expiring.append({
                    "document_version_id": str(version.id),
                    "document_id": str(version.document_id),
                    "expiry_date": expiry.isoformat(),
                })

        expiring.sort(key=lambda item: item["expiry_date"])
        structured_result = {"within_days": within_days, "count": len(expiring), "documents": expiring}
        narrative = f"{len(expiring)} verified document(s) expire within {within_days} day(s)."
        return structured_result, [], narrative

    def _handle_requirement_detail(self, organization_id, params, current_user):
        # require_employee-level data (Source/Requirement/Rule reads are
        # open to any authenticated user - see CLAUDE.md "Regulatory
        # content"), so no stricter RBACService.require_role call here -
        # the router's own require_employee gate already covers it.
        requirement_version_id = params.get("requirement_version_id") or ""
        try:
            requirement_version = self.requirement_versions.get_by_id_only(UUID(requirement_version_id))
        except (ValueError, RequirementVersionNotFound):
            return (
                {"requirement_version_id": requirement_version_id, "found": False},
                [],
                "I couldn't find a requirement with that id.",
            )

        # Only quotable, reviewed content - see CLAUDE.md "Ask RegNova"
        # point 3: a DRAFT/IN_REVIEW version must never be presented as
        # an authoritative answer.
        if requirement_version.status not in (
            RequirementVersionStatus.VERIFIED.value, RequirementVersionStatus.ACTIVE.value,
        ):
            return (
                {"requirement_version_id": requirement_version_id, "found": True, "quotable": False},
                [],
                "That requirement exists but hasn't been verified yet, so I can't quote it as authoritative.",
            )

        citation = self._requirement_citation(requirement_version)
        narrative = (
            f"{requirement_version.canonical_statement} "
            f"(source classification: {requirement_version.authority_interpretation_label})"
        )
        return citation, citation["sources"], narrative

    def _handle_explain_gate(self, organization_id, params, current_user):
        RBACService.require_role(self.db, current_user, "ADMIN", "MANAGER")

        state_id = params.get("product_market_state_id") or ""
        try:
            snapshot = self.state_snapshots.get_current(UUID(state_id))
        except ValueError:
            snapshot = None

        if snapshot is None or snapshot.organization_id != organization_id:
            return (
                {"product_market_state_id": state_id, "found": False}, [],
                "I couldn't find a current state snapshot for that product market state.",
            )

        reasons = snapshot.readiness_reason_codes or []
        # float(), not the raw Decimal - Numeric(5,2) columns come back
        # as Decimal, which is not JSON-serializable into structured_result.
        displayed_progress = float(snapshot.displayed_progress)
        structured_result = {
            "product_market_state_id": state_id,
            "overall_gate": snapshot.overall_gate,
            "displayed_progress": displayed_progress,
            "readiness_reason_codes": reasons,
            "dimension_summary": snapshot.dimension_summary,
        }
        if reasons:
            narrative = (
                f"Gate {snapshot.overall_gate}, {displayed_progress:.1f}% progress. "
                f"Blocking reasons: {', '.join(reasons)}."
            )
        else:
            narrative = f"Gate {snapshot.overall_gate}, {displayed_progress:.1f}% progress. No blocking reasons."
        return structured_result, [], narrative

    def _handle_explain_finding(self, organization_id, params, current_user):
        RBACService.require_role(self.db, current_user, "ADMIN", "MANAGER")

        finding_id = params.get("finding_id") or ""
        try:
            finding = self.findings.get_by_id_only(organization_id, UUID(finding_id))
        except ValueError:
            finding = None

        if finding is None:
            return (
                {"finding_id": finding_id, "found": False}, [],
                "I couldn't find a finding with that id in your organization.",
            )

        latest = self.finding_revisions.get_latest(finding.id)
        sources: list[dict[str, Any]] = []
        requirement_detail = None

        if finding.requirement_version_id is not None:
            try:
                requirement_version = self.requirement_versions.get_by_id_only(finding.requirement_version_id)
                requirement_detail = self._requirement_citation(requirement_version)
                sources = requirement_detail["sources"]
            except RequirementVersionNotFound:
                requirement_detail = None

        rule_detail = None
        if finding.rule_version_id is not None:
            try:
                rule_version = self.rule_versions.get_by_id_only(finding.rule_version_id)
                rule_detail = {
                    "rule_version_id": str(rule_version.id),
                    "output_type": rule_version.output_type,
                    "condition": rule_version.condition,
                }
            except RuleVersionNotFound:
                rule_detail = None

        structured_result = {
            "finding_id": str(finding.id),
            "dimension": finding.dimension,
            "status": latest.status if latest else None,
            "severity": latest.severity if latest else None,
            "rationale": latest.rationale if latest else None,
            "requirement": requirement_detail,
            "rule": rule_detail,
        }
        narrative = (
            f"This {latest.severity if latest else 'unknown-severity'} finding on "
            f"{finding.dimension} is currently {latest.status if latest else 'unknown'}. "
            f"{latest.rationale if latest else ''}"
        ).strip()
        return structured_result, sources, narrative


def _not_dispatchable_response(question_class: str) -> tuple[str, str]:
    if question_class in (
        AskRegnovaQuestionClass.SEMANTIC_DOCUMENT_SEARCH.value,
        AskRegnovaQuestionClass.WORKFLOW_COMMANDS.value,
    ):
        return (
            "That kind of question isn't supported yet, even though I recognize what "
            "you're asking - please use the dashboard directly for now.",
            "not_yet_supported",
        )
    return (
        "I can't help with that - Ask RegNova only answers questions about your own "
        "regulatory and compliance data.",
        "unsupported",
    )


# (question_class, intent) -> bound-method-shaped handler. A closed
# dispatch table, not a dynamic lookup by string the model could widen -
# every key here is one of VALID_INTENTS_BY_CLASS's own entries. See
# CLAUDE.md "Ask RegNova" point 2.
_INTENT_HANDLERS = {
    (AskRegnovaQuestionClass.STRUCTURED_PORTFOLIO.value, "PRODUCTS_BY_GATE"): AskRegnovaService._handle_products_by_gate,
    (AskRegnovaQuestionClass.STRUCTURED_PORTFOLIO.value, "DOCUMENTS_EXPIRING_WITHIN"): AskRegnovaService._handle_documents_expiring_within,
    (AskRegnovaQuestionClass.REGULATORY_GRAPH.value, "REQUIREMENT_DETAIL"): AskRegnovaService._handle_requirement_detail,
    (AskRegnovaQuestionClass.STATE_EXPLANATION.value, "EXPLAIN_GATE"): AskRegnovaService._handle_explain_gate,
    (AskRegnovaQuestionClass.STATE_EXPLANATION.value, "EXPLAIN_FINDING"): AskRegnovaService._handle_explain_finding,
}

# Sanity check at import time, not just by convention: every handler key
# must be a real (class, intent) pair the classifier is actually allowed
# to emit - catches a typo the moment this module loads, not the first
# time that intent is asked about.
for _cls, _intent in _INTENT_HANDLERS:
    assert _intent in VALID_INTENTS_BY_CLASS.get(_cls, ()), (
        f"_INTENT_HANDLERS has a handler for ({_cls!r}, {_intent!r}), which is not "
        f"in VALID_INTENTS_BY_CLASS - these two must stay in sync."
    )
