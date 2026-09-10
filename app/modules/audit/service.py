from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.product_market_state.repository import ProductMarketStateRepository

from .exceptions import AuditReaderNotAuthorized
from .models import AuditEvent, AuditVisibilityTier
from .repository import AuditEventRepository


@dataclass
class AuditEventDraft:
    """
    What a builder decides for one OutboxEvent - the tier/redaction
    split (see AuditEvent's own docstring) plus whatever product/state
    scoping this event_type can resolve. OutboxEvent itself carries no
    product_id column, so builders that need one look it up.
    """

    visibility_tier: str
    payload: dict[str, Any]
    internal_payload: dict[str, Any] | None = None
    product_id: UUID | None = None
    product_market_state_id: UUID | None = None


def _default_builder(db: Session, event) -> AuditEventDraft:
    """
    Fail-closed default for any event_type with no registered builder
    below - INTERNAL_REGULATORY, full raw payload, no internal_payload
    split, no product scoping. A new or forgotten event_type is never
    accidentally customer-visible; widening it to CUSTOMER_VISIBLE (or
    splitting its payload) is a deliberate, reviewable addition to
    AUDIT_BUILDERS, not something that falls out of doing nothing. The
    four event types that predate this module (WorkspaceActivated,
    MembershipChanged, ProductVersionPublished, ContentVersionTransitioned)
    all fall through to this today - deliberately not tuned in this
    pass, see CLAUDE.md "Audit log" for why.
    """
    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.INTERNAL_REGULATORY.value,
        payload=dict(event.payload or {}),
    )


def _resolve_product_market_state_scope(
    db: Session,
    organization_id: UUID,
    payload: dict[str, Any],
) -> tuple[UUID | None, UUID | None]:
    """
    Finding events carry product_market_state_id but not product_id
    (Finding itself doesn't store one) - one cheap lookup at ingestion
    resolves both, so the audit log can be queried by product directly
    rather than only by product_market_state. organization_id is the
    event's own (Finding.organization_id == its ProductMarketState's),
    so the existing org-scoped lookup is used as-is - no new, unscoped
    repository method needed just for this.
    """
    raw_state_id = payload.get("product_market_state_id")
    if raw_state_id is None:
        return None, None

    state_id = UUID(raw_state_id)
    state = ProductMarketStateRepository(db).get_by_id_only(organization_id, state_id)

    return (state.product_id if state else None), state_id


def _build_finding_proposed(db: Session, event) -> AuditEventDraft:
    """
    Customer-visible: a customer needs to know a new issue was flagged
    against their product. `rationale`/`issue_type`/`observed_value`/
    `observed_location` stay internal-only - FindingRevision's own
    rationale for an engine-proposed Finding is RA-facing text (see
    AssessmentRunService._maybe_propose_finding's own docstring: "same
    split as RequirementVersion's canonical_statement/
    customer_safe_explanation"), not something this pass invents a new
    distinction to enforce.
    """
    payload = event.payload or {}
    product_id, product_market_state_id = _resolve_product_market_state_scope(
        db, event.organization_id, payload,
    )

    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.CUSTOMER_VISIBLE.value,
        payload={
            "finding_id": payload.get("finding_id"),
            "product_market_state_id": payload.get("product_market_state_id"),
            "dimension": payload.get("dimension"),
            "subject_key": payload.get("subject_key"),
            "severity": payload.get("severity"),
            "hard_gate_effect": payload.get("hard_gate_effect"),
            "status": "PROPOSED",
            # Lineage - FR-14's own "reconstructing the inputs, rules
            # and evidence behind a state snapshot" story. All three
            # already travel with propose()'s own params, no new
            # plumbing needed to surface them here.
            "assessment_run_id": payload.get("assessment_run_id"),
            "requirement_version_id": payload.get("requirement_version_id"),
            "rule_version_id": payload.get("rule_version_id"),
        },
        internal_payload={
            "issue_type": payload.get("issue_type"),
            "observed_value": payload.get("observed_value"),
            "observed_location": payload.get("observed_location"),
            "rationale": payload.get("rationale"),
            # AI lineage - only set when the Claims semantic analysis hop
            # raised this Finding; None for every deterministic proposal.
            # Internal-only, same as rationale: which model and prompt version
            # produced an AI proposal is RA-facing reproducibility detail, not
            # something a customer needs on the finding notification.
            "analysis_method": payload.get("analysis_method"),
            "ai_model_identifier": payload.get("ai_model_identifier"),
            "ai_prompt_version": payload.get("ai_prompt_version"),
        },
        product_id=product_id,
        product_market_state_id=product_market_state_id,
    )


def _build_finding_decision_changed(db: Session, event) -> AuditEventDraft:
    """
    Customer-visible, no internal_payload split - FR-14's own literal
    example ("I can see who changed a finding and why"). Unlike
    FindingProposed, a human transition's rationale IS the field FR-14
    wants the customer to see; there's only one rationale field per
    revision in this codebase, and for a human-driven transition it's
    the customer-facing one by construction, not an RA-only note.
    """
    payload = event.payload or {}
    product_id, product_market_state_id = _resolve_product_market_state_scope(
        db, event.organization_id, payload,
    )

    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.CUSTOMER_VISIBLE.value,
        payload=dict(payload),
        product_id=product_id,
        product_market_state_id=product_market_state_id,
    )


def _build_document_customer_visible(db: Session, event) -> AuditEventDraft:
    """
    Shared by every DocumentVersion/DocumentField event - Document is
    organization-scoped customer data with no internal-actor authority
    over it at all (see CLAUDE.md "Document storage and versioning":
    "No internal-role gating anywhere in this module"), so there is no
    internal/customer line to draw within this payload - the whole
    thing is the customer's own action on their own data.
    """
    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.CUSTOMER_VISIBLE.value,
        payload=dict(event.payload or {}),
    )


def _build_evidence_customer_visible(db: Session, event) -> AuditEventDraft:
    """
    Shared by EvidenceLinked/EvidenceUnlinked - same reasoning as
    _build_document_customer_visible: Evidence is organization-scoped
    customer data (a link row over the customer's own document and
    product/requirement), no internal-actor authority to carve a split
    around. product_id/requirement_version_id/notes travel verbatim,
    same precedent as DocumentFieldRevised carrying its field value
    verbatim.
    """
    payload = event.payload or {}

    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.CUSTOMER_VISIBLE.value,
        payload=dict(payload),
        product_id=UUID(payload["product_id"]) if payload.get("product_id") else None,
    )


def _build_regulatory_basis_activated(db: Session, event) -> AuditEventDraft:
    """
    INTERNAL_REGULATORY, no split - same tier as ContentVersionTransitioned
    and for the same reason: RegulatoryBasisRelease has no organization
    of its own (OutboxRepository.append is called with the tenant-zero
    org id - see RegulatoryBasisReleaseService), so there's no customer
    to carve a CUSTOMER_VISIBLE half out for. C14's own minimum payload
    ("release/old-new/effective time") travels through unsplit.
    """
    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.INTERNAL_REGULATORY.value,
        payload=dict(event.payload or {}),
    )


def _build_assessment_completed(db: Session, event) -> AuditEventDraft:
    """
    CUSTOMER_VISIBLE, no split - a customer's own product reaching a
    new readiness state is squarely their own data, same reasoning as
    FindingDecisionChanged. product_id resolved the same way
    FindingProposed's is - AssessmentCompleted's payload carries
    product_market_state_id but not product_id directly.
    """
    payload = event.payload or {}
    product_id, product_market_state_id = _resolve_product_market_state_scope(
        db, event.organization_id, payload,
    )

    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.CUSTOMER_VISIBLE.value,
        payload=dict(payload),
        product_id=product_id,
        product_market_state_id=product_market_state_id,
    )


def _build_state_current_changed(db: Session, event) -> AuditEventDraft:
    """
    CUSTOMER_VISIBLE, no split - same reasoning as AssessmentCompleted.
    Fires from two distinct sites (MarketReadinessService._build_snapshot,
    a new snapshot becoming current; ProductMarketStateService.update,
    the current snapshot going stale with no replacement yet) - see
    CLAUDE.md "Market readiness" for why both are C14's single
    "New snapshot becomes current or prior becomes stale" definition,
    not two different events.
    """
    payload = event.payload or {}
    product_id, product_market_state_id = _resolve_product_market_state_scope(
        db, event.organization_id, payload,
    )

    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.CUSTOMER_VISIBLE.value,
        payload=dict(payload),
        product_id=product_id,
        product_market_state_id=product_market_state_id,
    )


def _build_export_generated(db: Session, event) -> AuditEventDraft:
    """
    Tier decided by export_type inside the payload itself - the same
    dynamic-resolution shape _build_finding_proposed already uses for
    product-scoping. FINDINGS_CSV is CUSTOMER_VISIBLE (a customer's own
    record of their own export); EVIDENCE_PACK_JSON is
    INTERNAL_REGULATORY - regulatory-side reconstruction activity, not
    access-governance, deliberately not TECHNICAL_SECURITY the way
    InternalRoleAssignmentChanged is (RA/Auditor colleagues plausibly
    want visibility into who pulled evidence packs for which
    snapshots). No split either way - nothing here is more sensitive
    than the tier itself already gates. See CLAUDE.md "Exports".
    """
    payload = event.payload or {}
    product_id, product_market_state_id = _resolve_product_market_state_scope(
        db, event.organization_id, payload,
    )

    tier = (
        AuditVisibilityTier.CUSTOMER_VISIBLE.value
        if payload.get("export_type") == "FINDINGS_CSV"
        else AuditVisibilityTier.INTERNAL_REGULATORY.value
    )

    return AuditEventDraft(
        visibility_tier=tier,
        payload=dict(payload),
        product_id=product_id,
        product_market_state_id=product_market_state_id,
    )


def _build_internal_role_assignment_changed(db: Session, event) -> AuditEventDraft:
    """
    TECHNICAL_SECURITY, no split - the most audit-critical surface in
    this codebase (who gains/loses regulatory or assessment authority),
    but a governance/access-control concern, not a regulatory-content or
    assessment decision: INTERNAL_REGULATORY holders (RA/Senior/
    Knowledge Lead/Content Advisor) have no natural need to see who else
    was granted a role, and this sidesteps the awkward question of
    whether one advisor should see another's own grant. Only Platform
    Admin/Auditor ever see this event at all, so there's no lower tier
    to protect a split from - the whole payload is already
    access-restricted by tier alone.
    """
    return AuditEventDraft(
        visibility_tier=AuditVisibilityTier.TECHNICAL_SECURITY.value,
        payload=dict(event.payload or {}),
    )


# event_type -> builder(db, OutboxEvent) -> AuditEventDraft. The
# extensibility point for tier/redaction assignment - a new event_type
# becomes properly classified by registering a builder here, not by
# touching record_for_event. No entry means _default_builder (fail
# closed to INTERNAL_REGULATORY) - see CLAUDE.md "Audit log".
AUDIT_BUILDERS: dict[str, Callable[[Session, Any], AuditEventDraft]] = {
    "FindingProposed": _build_finding_proposed,
    "FindingDecisionChanged": _build_finding_decision_changed,
    "DocumentVersionUploaded": _build_document_customer_visible,
    "DocumentVersionVerified": _build_document_customer_visible,
    "DocumentVersionRejected": _build_document_customer_visible,
    "DocumentVersionQuarantined": _build_document_customer_visible,
    "DocumentVersionScanFailed": _build_document_customer_visible,
    "DocumentFieldRevised": _build_document_customer_visible,
    "EvidenceLinked": _build_evidence_customer_visible,
    "EvidenceUnlinked": _build_evidence_customer_visible,
    "RegulatoryBasisActivated": _build_regulatory_basis_activated,
    "AssessmentCompleted": _build_assessment_completed,
    "StateCurrentChanged": _build_state_current_changed,
    "InternalRoleAssignmentChanged": _build_internal_role_assignment_changed,
    "ExportGenerated": _build_export_generated,
}


# Internal roles that grant CUSTOMER_VISIBLE + INTERNAL_REGULATORY - the
# same "regulatory-side" grouping already used for
# require_regulatory_content_author, extended here to reading, not
# authoring.
_INTERNAL_REGULATORY_ROLE_CODES = (
    InternalRoleCode.RA.value,
    InternalRoleCode.SENIOR_REVIEWER.value,
    InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
    InternalRoleCode.REGULATORY_CONTENT_ADVISOR.value,
)


class AuditService:
    """
    Consumes OutboxEvents into the durable, tiered audit log (see
    AuditEvent's own docstring), and serves the two-endpoint query
    surface: the zero-exception customer path and the deliberately
    narrow, audited cross-organization internal path. See CLAUDE.md
    "Audit log" for the full design.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = AuditEventRepository(db)
        self.internal_role_assignments = InternalRoleAssignmentRepository(db)

    def record_for_event(self, event) -> AuditEvent | None:
        """
        Called from audit.worker._publish() for EVERY outbox event -
        unlike NotificationService.record_for_event, there is no "no
        resolver -> skip" path: the audit log's whole point is
        completeness, not selectivity (see _default_builder). Idempotent
        against at-least-once redelivery via exists_for_source_event,
        backed by the table's own UNIQUE(source_event_id). Does not
        commit - the caller (dispatch_pending_events) commits this
        alongside marking the event published, the same transactional-
        outbox discipline as everywhere else in this codebase.
        """
        if self.repository.exists_for_source_event(event.id):
            return None

        builder = AUDIT_BUILDERS.get(event.event_type, _default_builder)
        draft = builder(self.db, event)

        return self.repository.create_from_event(
            organization_id=event.organization_id,
            source_event_id=event.id,
            event_type=event.event_type,
            schema_version=event.schema_version,
            occurred_at=event.created_at,
            actor_user_id=event.actor_user_id,
            correlation_id=event.correlation_id,
            product_id=draft.product_id,
            product_market_state_id=draft.product_market_state_id,
            visibility_tier=draft.visibility_tier,
            payload=draft.payload,
            internal_payload=draft.internal_payload,
        )

    # --- Query surface ----------------------------------------------------

    def get_customer_visible(
        self,
        organization_id: UUID,
        **filters: Any,
    ) -> list[AuditEvent]:
        """
        The zero-exception path - organization_id is always the
        caller's own, exactly like every other org-scoped read in this
        codebase. No new mechanism.
        """
        return self.repository.get_all(
            organization_id=organization_id,
            visibility_tiers=[AuditVisibilityTier.CUSTOMER_VISIBLE.value],
            **filters,
        )

    def resolve_internal_tier_grants(self, caller_user_id: UUID) -> set[str]:
        """
        Public (not `_`-prefixed) precisely because it's now a genuine
        cross-module utility, not an AuditService-internal helper: the
        export module's own INTERNAL_REGULATORY gate on evidence-pack
        generation/download (see CLAUDE.md "Exports") calls this exact
        method rather than re-deriving "does this caller hold a
        qualifying internal role" a second time. Renamed when that
        reuse was added - was `_resolve_internal_tier_grants`.

        AUDITOR is strictly read-only and grants all three tiers - the
        whole point of the role (see InternalRoleCode.AUDITOR). RA/
        Senior Reviewer/Knowledge Lead/Content Advisor grant customer-
        visible+internal-regulatory (the nested pair). Platform Admin
        grants technical-security only, deliberately not the regulatory
        tiers too - A4's own framing ("Platform administrator... cannot
        alter regulatory decisions without a regulated role") extended
        here to reading, not just writing. A caller holding more than
        one internal role gets the union of whatever each grants.
        """
        if self.internal_role_assignments.get_active_for_user_role(
            caller_user_id, InternalRoleCode.AUDITOR.value,
        ) is not None:
            return {
                AuditVisibilityTier.CUSTOMER_VISIBLE.value,
                AuditVisibilityTier.INTERNAL_REGULATORY.value,
                AuditVisibilityTier.TECHNICAL_SECURITY.value,
            }

        granted: set[str] = set()

        if any(
            self.internal_role_assignments.get_active_for_user_role(caller_user_id, code) is not None
            for code in _INTERNAL_REGULATORY_ROLE_CODES
        ):
            granted |= {
                AuditVisibilityTier.CUSTOMER_VISIBLE.value,
                AuditVisibilityTier.INTERNAL_REGULATORY.value,
            }

        if self.internal_role_assignments.get_active_for_user_role(
            caller_user_id, InternalRoleCode.PLATFORM_ADMIN.value,
        ) is not None:
            granted.add(AuditVisibilityTier.TECHNICAL_SECURITY.value)

        return granted

    def get_internal(
        self,
        *,
        caller_user_id: UUID,
        organization_id: UUID,
        correlation_id: str | None = None,
        requested_tiers: list[str] | None = None,
        **filters: Any,
    ) -> list[AuditEvent]:
        """
        The deliberate, narrow exception to "organization_id is always
        derived from current_user" - see CLAUDE.md "Audit log" for why
        this is the first place in this codebase that exception is made,
        and why it is NOT precedent for the still-unbuilt RA Workbench
        (acting-as-a-customer-organization for writes). This path:
        - is read-only (no write method exists on this service at all
          that accepts an explicit organization_id);
        - is role-validated per tier (_resolve_internal_tier_grants,
          not "any internal role at all");
        - is scoped to this one endpoint (GET /audit-events/internal),
          not a general relaxation of the org-scoping convention;
        - unconditionally logs itself (_record_cross_org_query) every
          time it's called, including when granted_tiers ends up empty
          for filtering purposes below (the attempt itself is still
          audited) - "every cross-org query is itself audited" is not
          conditional on whether the caller's own org happens to match
          (for every internal actor, whose own org is always
          tenant-zero, it structurally never does).

        `filters` (product_id/product_market_state_id/actor_user_id/
        event_type/occurred_from/occurred_to) are the SAME filter kwargs
        AuditEventRepository.get_all accepts - `actor_user_id` here
        means "show me events performed by this actor", a different
        thing from `caller_user_id` (who is asking); kept as two
        distinctly-named parameters specifically so they can never be
        confused with each other.
        """
        granted = self.resolve_internal_tier_grants(caller_user_id)
        if not granted:
            raise AuditReaderNotAuthorized()

        tiers = granted if requested_tiers is None else granted & set(requested_tiers)

        results = self.repository.get_all(
            organization_id=organization_id,
            visibility_tiers=tiers,
            **filters,
        )

        self._record_cross_org_query(
            caller_user_id=caller_user_id,
            organization_id=organization_id,
            correlation_id=correlation_id,
            granted_tiers=tiers,
            filters=filters,
            result_count=len(results),
        )

        return results

    def _record_cross_org_query(
        self,
        *,
        caller_user_id: UUID,
        organization_id: UUID,
        correlation_id: str | None,
        granted_tiers: set[str],
        filters: dict[str, Any],
        result_count: int,
    ) -> None:
        self.record_cross_org_access(
            caller_user_id=caller_user_id,
            organization_id=organization_id,
            event_type="AuditLogQueried",
            payload={
                "queried_organization_id": str(organization_id),
                "granted_tiers": sorted(granted_tiers),
                "filters": {
                    key: (str(value) if value is not None else None)
                    for key, value in filters.items()
                },
                "result_count": result_count,
            },
            correlation_id=correlation_id,
        )

    def record_cross_org_access(
        self,
        *,
        caller_user_id: UUID,
        organization_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        """
        The generalized self-audit mechanism every deliberate
        organization_id exception must use - see CLAUDE.md "Deliberate
        organization_id exceptions" for the maintained list of callers.
        Generalized from what was `_record_cross_org_query`'s own
        inline body (that method is now a thin wrapper over this) when
        the export module's evidence-pack generation/download needed
        the exact same mechanism for a second exception, not a copy of
        it - see CLAUDE.md "Exports".

        A direct write, not an outbox-consumed one - there is no domain
        change here to publish for other consumers, this is the audit
        system recording a fact about its own reader/accessor activity.
        Always TECHNICAL_SECURITY, always filed under the QUERIED/
        ACCESSED organization (never the caller's own tenant-zero org) -
        same "whose data this is about" convention AuditEvent.organization_id
        uses everywhere else. Commits immediately: unlike most domain
        writes in this codebase, several call sites of this method are
        a GET with no other domain-write transaction to piggyback its
        commit onto - and even where one exists (a POST), keeping this
        commit uniform across every caller matters more than an
        occasional saved round trip.
        """
        self.repository.create_direct(
            organization_id=organization_id,
            event_type=event_type,
            schema_version=1,
            occurred_at=datetime.now(timezone.utc),
            actor_user_id=caller_user_id,
            correlation_id=correlation_id,
            product_id=None,
            product_market_state_id=None,
            visibility_tier=AuditVisibilityTier.TECHNICAL_SECURITY.value,
            payload=payload,
            internal_payload=None,
        )
        self.db.commit()
