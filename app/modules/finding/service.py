from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.audit.repository import OutboxRepository
from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.rbac.exceptions import PermissionDenied
from app.modules.rbac.service import RBACService
from app.modules.requirement_version.models import RequirementSeverity
from app.modules.user.exceptions import UserNotFound
from app.modules.user.models import User
from app.modules.user.repository import UserRepository

from .exceptions import (
    FindingNotFound,
    FindingTransitionNotAllowed,
    FindingTransitionNotAuthorized,
)
from .models import (
    Finding,
    FindingRevision,
    FindingStatus,
    NON_TERMINAL_FINDING_STATUSES,
    TERMINAL_FINDING_STATUSES,
)
from .repository import FindingRepository, FindingRevisionRepository

# Customer-side "Resolve findings" authority (B2: Organisation admin
# Yes, Customer regulatory lead Yes) maps onto this codebase's own
# ADMIN/MANAGER role tier - the same tier the existing GET endpoints on
# this router already require. "Assigned" (Contributor) isn't modeled -
# there's no per-finding assignment mechanism in this codebase yet, so
# Contributor-level access isn't distinguished from Viewer here.
_CUSTOMER_MANAGER_ROLE_CODES = ("ADMIN", "MANAGER")


class FindingService:
    """
    Finding/FindingRevision service. propose() is the engine's entry
    point (called from AssessmentRunService). The transition methods
    below (accept/reject/mark_not_applicable/respond/reopen/resolve/
    accept_with_rationale) are the review workflow's entry points,
    called from the router - each appends a new FindingRevision rather
    than mutating one (C7: never updated in place), and each checks
    both transition legality (is the finding's current status allowed
    to become this one) and actor authorization (does this specific
    actor have authority for this specific transition) before writing
    anything. See CLAUDE.md "Finding review workflow" for the full
    transition/actor table and the reasoning behind it - in particular,
    why authorization happens here and not as a router-level require_*
    dependency: RA/Senior Reviewer authority is a completely different
    axis (InternalRoleAssignment) from the customer-side role tier
    check, and severity itself (which the router never sees) decides
    which axis a RESOLVED transition actually needs.
    """

    def __init__(self, db: Session):
        self.db = db
        self.findings = FindingRepository(db)
        self.revisions = FindingRevisionRepository(db)
        self.users = UserRepository(db)
        self.internal_role_assignments = InternalRoleAssignmentRepository(db)
        self.outbox = OutboxRepository(db)

    def get_all(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> list[Finding]:
        return self.findings.get_all(organization_id, product_market_state_id)

    def get_by_id(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
    ) -> Finding:
        finding = self.findings.get_by_id(
            organization_id,
            product_market_state_id,
            finding_id,
        )

        if finding is None:
            raise FindingNotFound()

        return finding

    def has_open_finding(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        dimension: str,
    ) -> bool:
        """
        Live, run-independent check: does a currently-open Finding
        exist for this (product_market_state, dimension), regardless of
        which AssessmentRun originally proposed it. Exists specifically
        for AssessmentRunService._derive_dimension_state, whose own
        findings_proposed signal only sees revisions created during the
        one run being scored - a Finding that's moved past PROPOSED
        (OPEN, CUSTOMER_RESPONDED) correctly gets no new revision on a
        fresh rerun (propose()'s own idempotent-reuse guard), so
        without this, a still-open Finding could go uncounted. See
        CLAUDE.md "Assessment engine" and "Known limitations" for what
        this does and does not close (in particular: nothing here helps
        a REUSED DimensionAssessment, which never calls
        _derive_dimension_state at all).

        Deliberately severity-blind, matching findings_proposed's own
        behavior - any open Finding counts, not just Critical/Major/
        hard-gated ones. Whether dimension-level state should become
        severity/hard-gate-aware the way the gate now is is a separate,
        open question - not decided here.
        """

        return any(
            latest.status not in TERMINAL_FINDING_STATUSES
            for latest in (
                self.revisions.get_latest(finding.id)
                for finding in self.findings.get_all_for_dimension(
                    organization_id, product_market_state_id, dimension,
                )
            )
            if latest is not None
        )

    def get_revisions(self, finding_id: UUID) -> list[FindingRevision]:
        return self.revisions.get_all(finding_id)

    def propose(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        dimension: str,
        assessment_run_id: UUID,
        requirement_version_id: UUID | None,
        rule_version_id: UUID | None,
        subject_key: str | None,
        issue_type: str,
        observed_value: str,
        severity: str,
        hard_gate_effect: bool,
        rationale: str,
        normalized_value: str | None = None,
        observed_location: dict[str, Any] | None = None,
        analysis_method: str | None = None,
        ai_model_identifier: str | None = None,
        ai_prompt_version: str | None = None,
        correlation_id: str | None = None,
    ) -> Finding | None:
        """
        Idempotent re-proposal: the same (product_market_state,
        dimension, requirement_version, subject_key) tuple reuses its
        existing Finding rather than spawning a duplicate on every
        re-run. If a human has already acted on it (status moved past
        PROPOSED), a fresh automated detection defers to that - no new
        revision is written, and this returns None. If it's still
        PROPOSED (never reviewed), a fresh revision is appended so the
        latest evidence is current.

        Publishes FindingProposed whenever a revision is actually
        written (both the new-Finding and the reused-still-PROPOSED
        branches) - not on the early-return no-op above, which
        correctly produces no event. No actor_user_id: this is an
        engine-only action, no human actor exists at this call site
        (see FindingRevision's own lack of a human-lineage field for
        engine-driven revisions). The caller (AssessmentRunService)
        commits - propose() itself never has, and still doesn't.
        """

        existing = self.findings.find_open_match(
            product_market_state_id,
            dimension,
            requirement_version_id,
            subject_key,
        )

        if existing is not None:
            latest = self.revisions.get_latest(existing.id)
            if latest is not None and latest.status != FindingStatus.PROPOSED.value:
                return None

            next_revision_number = (latest.revision_number + 1) if latest else 1
            finding = existing
        else:
            finding = Finding(
                organization_id=organization_id,
                product_market_state_id=product_market_state_id,
                dimension=dimension,
                requirement_version_id=requirement_version_id,
                rule_version_id=rule_version_id,
                subject_key=subject_key,
            )
            self.findings.create(finding)
            next_revision_number = 1

        revision = FindingRevision(
            finding_id=finding.id,
            revision_number=next_revision_number,
            assessment_run_id=assessment_run_id,
            issue_type=issue_type,
            observed_value=observed_value,
            normalized_value=normalized_value,
            observed_location=observed_location,
            severity=severity,
            status=FindingStatus.PROPOSED.value,
            hard_gate_effect=hard_gate_effect,
            rationale=rationale,
            analysis_method=analysis_method,
            ai_model_identifier=ai_model_identifier,
            ai_prompt_version=ai_prompt_version,
        )
        self.revisions.create(revision)

        self.outbox.append(
            organization_id=organization_id,
            event_type="FindingProposed",
            schema_version=1,
            payload={
                "finding_id": str(finding.id),
                "product_market_state_id": str(product_market_state_id),
                "dimension": dimension,
                "subject_key": subject_key,
                "assessment_run_id": str(assessment_run_id),
                "requirement_version_id": (
                    str(requirement_version_id) if requirement_version_id else None
                ),
                "rule_version_id": str(rule_version_id) if rule_version_id else None,
                "severity": severity,
                "hard_gate_effect": hard_gate_effect,
                "issue_type": issue_type,
                "observed_value": observed_value,
                "observed_location": observed_location,
                "rationale": rationale,
                # AI lineage - None for every deterministic proposal; set only
                # when the Claims semantic analysis hop raised this Finding.
                # AuditService._build_finding_proposed routes these into
                # internal_payload (RA-facing), never the customer payload.
                "analysis_method": analysis_method,
                "ai_model_identifier": ai_model_identifier,
                "ai_prompt_version": ai_prompt_version,
            },
            correlation_id=correlation_id,
        )

        return finding

    # --- Transition internals ------------------------------------------

    def _latest_or_404(self, finding_id: UUID) -> FindingRevision:
        latest = self.revisions.get_latest(finding_id)

        if latest is None:
            # Structurally shouldn't happen - propose() always writes a
            # first revision - but a Finding with no revisions is at
            # least as broken as one that doesn't exist.
            raise FindingNotFound()

        return latest

    def _require_status(self, latest: FindingRevision, *allowed: str) -> None:
        if latest.status not in allowed:
            raise FindingTransitionNotAllowed(latest.status, frozenset(allowed))

    def _load_actor_or_404(self, actor_user_id: UUID) -> User:
        actor = self.users.get_by_id_only(actor_user_id)

        if actor is None:
            raise UserNotFound()

        return actor

    def _is_customer_manager(self, actor: User) -> bool:
        """
        True only if actor holds ADMIN/MANAGER tier *within the org
        this finding belongs to* - RBACService.require_role looks the
        role up scoped to actor.organization_id, which by the time this
        is called already equals the finding's own organization_id
        (get_by_id is org-scoped to the caller). An RA/Senior Reviewer
        actor (tenant-zero) can never satisfy this, by construction -
        not because of a check here, but because get_by_id would have
        already 404'd them before this method is ever reached through
        the router.
        """

        try:
            RBACService.require_role(self.db, actor, *_CUSTOMER_MANAGER_ROLE_CODES)
            return True
        except PermissionDenied:
            return False

    def _has_internal_role(self, actor_user_id: UUID, role_code: str) -> bool:
        return self.internal_role_assignments.get_active_for_user_role(
            actor_user_id, role_code,
        ) is not None

    def _append_revision(
        self,
        finding: Finding,
        latest: FindingRevision,
        *,
        status: str,
        actor_user_id: UUID,
        rationale: str,
        disposition: str | None = None,
        resolution_decision: str | None = None,
    ) -> FindingRevision:
        """
        Copies the prior revision's observation fields forward unchanged
        (issue_type/observed_value are NOT NULL - a transition-only
        revision has no new observation to write, so it carries the
        existing one) and its source_location citations, writing only
        the new decision. Never mutates `latest` - C7's immutability
        contract applies to a human-driven transition exactly as much
        as to an engine re-proposal.
        """

        revision = FindingRevision(
            finding_id=finding.id,
            revision_number=latest.revision_number + 1,
            assessment_run_id=latest.assessment_run_id,
            issue_type=latest.issue_type,
            observed_value=latest.observed_value,
            normalized_value=latest.normalized_value,
            observed_location=latest.observed_location,
            severity=latest.severity,
            status=status,
            disposition=disposition,
            hard_gate_effect=latest.hard_gate_effect,
            rationale=rationale,
            decided_by_user_id=actor_user_id,
            resolution_decision=resolution_decision,
            resolved_at=datetime.now(timezone.utc) if status == FindingStatus.RESOLVED.value else None,
        )
        revision.source_locations = list(latest.source_locations)

        self.revisions.create(revision)

        return revision

    def _publish_decision_changed(
        self,
        finding: Finding,
        *,
        organization_id: UUID,
        from_status: str,
        to_status: str,
        actor_user_id: UUID,
        rationale: str,
        disposition: str | None,
        correlation_id: str | None,
    ) -> None:
        """
        FindingDecisionChanged (Appendix 2) - one parameterized event
        covering all seven transition methods, not seven names, matching
        C14's own singular naming ("RA/customer resolution decision
        revision") and the ContentVersionTransitioned precedent. `to_status`
        distinguishes which transition actually fired.

        rationale is included in full here, unlike FindingProposed's own
        engine-driven event - see AuditService's builder for why: a
        human transition's rationale is the customer-facing "why" FR-14
        itself names, not an RA-only note. Tier/redaction assignment
        happens entirely downstream, in the audit consumer - this
        method's job is only to publish the complete fact.
        """
        self.outbox.append(
            organization_id=organization_id,
            event_type="FindingDecisionChanged",
            schema_version=1,
            payload={
                "finding_id": str(finding.id),
                "product_market_state_id": str(finding.product_market_state_id),
                "dimension": finding.dimension,
                "from_status": from_status,
                "to_status": to_status,
                "rationale": rationale,
                "disposition": disposition,
            },
            correlation_id=correlation_id,
            actor_user_id=actor_user_id,
        )

    # --- Transitions -----------------------------------------------------
    # Each: resolve the finding (org-scoped - this is the tenant
    # boundary RA/Senior actors cannot cross this pass), check the
    # FROM status is legal for this transition, check the actor is
    # authorized for it, append a revision, commit. See CLAUDE.md
    # "Finding review workflow" for the transition table these mirror.

    def accept(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
        actor_user_id: UUID,
        rationale: str,
        disposition: str | None = None,
        correlation_id: str | None = None,
    ) -> Finding:
        """PROPOSED -> OPEN. Customer manager or RA/Senior triage."""

        finding = self.get_by_id(organization_id, product_market_state_id, finding_id)
        latest = self._latest_or_404(finding.id)
        self._require_status(latest, FindingStatus.PROPOSED.value)

        actor = self._load_actor_or_404(actor_user_id)
        authorized = (
            self._is_customer_manager(actor)
            or self._has_internal_role(actor.id, InternalRoleCode.RA.value)
            or self._has_internal_role(actor.id, InternalRoleCode.SENIOR_REVIEWER.value)
        )
        if not authorized:
            raise FindingTransitionNotAuthorized()

        self._append_revision(
            finding, latest,
            status=FindingStatus.OPEN.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
        )
        self._publish_decision_changed(
            finding,
            organization_id=organization_id,
            from_status=latest.status,
            to_status=FindingStatus.OPEN.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
            correlation_id=correlation_id,
        )
        self.db.commit()

        return finding

    def reject(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
        actor_user_id: UUID,
        rationale: str,
        disposition: str | None = None,
        correlation_id: str | None = None,
    ) -> Finding:
        """
        PROPOSED -> REJECTED. RA/Senior only - B4 frames rejection as
        correcting the engine's own proposal ("becomes evaluation
        data", D10.3), not a customer dispute mechanism. A customer who
        disagrees uses respond(), for RA to adjudicate.
        """

        finding = self.get_by_id(organization_id, product_market_state_id, finding_id)
        latest = self._latest_or_404(finding.id)
        self._require_status(latest, FindingStatus.PROPOSED.value)

        actor = self._load_actor_or_404(actor_user_id)
        authorized = (
            self._has_internal_role(actor.id, InternalRoleCode.RA.value)
            or self._has_internal_role(actor.id, InternalRoleCode.SENIOR_REVIEWER.value)
        )
        if not authorized:
            raise FindingTransitionNotAuthorized()

        self._append_revision(
            finding, latest,
            status=FindingStatus.REJECTED.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
        )
        self._publish_decision_changed(
            finding,
            organization_id=organization_id,
            from_status=latest.status,
            to_status=FindingStatus.REJECTED.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
            correlation_id=correlation_id,
        )
        self.db.commit()

        return finding

    def mark_not_applicable(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
        actor_user_id: UUID,
        rationale: str,
        disposition: str | None = None,
        correlation_id: str | None = None,
    ) -> Finding:
        """PROPOSED -> NOT_APPLICABLE. RA/Senior only - a regulatory-
        applicability judgment, same weight as C5.1's Does Not Apply."""

        finding = self.get_by_id(organization_id, product_market_state_id, finding_id)
        latest = self._latest_or_404(finding.id)
        self._require_status(latest, FindingStatus.PROPOSED.value)

        actor = self._load_actor_or_404(actor_user_id)
        authorized = (
            self._has_internal_role(actor.id, InternalRoleCode.RA.value)
            or self._has_internal_role(actor.id, InternalRoleCode.SENIOR_REVIEWER.value)
        )
        if not authorized:
            raise FindingTransitionNotAuthorized()

        self._append_revision(
            finding, latest,
            status=FindingStatus.NOT_APPLICABLE.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
        )
        self._publish_decision_changed(
            finding,
            organization_id=organization_id,
            from_status=latest.status,
            to_status=FindingStatus.NOT_APPLICABLE.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
            correlation_id=correlation_id,
        )
        self.db.commit()

        return finding

    def respond(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
        actor_user_id: UUID,
        rationale: str,
        correlation_id: str | None = None,
    ) -> Finding:
        """OPEN -> CUSTOMER_RESPONDED. Customer manager only - this is
        literally the customer's own action B4 names."""

        finding = self.get_by_id(organization_id, product_market_state_id, finding_id)
        latest = self._latest_or_404(finding.id)
        self._require_status(latest, FindingStatus.OPEN.value)

        actor = self._load_actor_or_404(actor_user_id)
        if not self._is_customer_manager(actor):
            raise FindingTransitionNotAuthorized()

        self._append_revision(
            finding, latest,
            status=FindingStatus.CUSTOMER_RESPONDED.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )
        self._publish_decision_changed(
            finding,
            organization_id=organization_id,
            from_status=latest.status,
            to_status=FindingStatus.CUSTOMER_RESPONDED.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=None,
            correlation_id=correlation_id,
        )
        self.db.commit()

        return finding

    def reopen(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
        actor_user_id: UUID,
        rationale: str,
        correlation_id: str | None = None,
    ) -> Finding:
        """CUSTOMER_RESPONDED -> OPEN. RA/Senior only - the response was
        reviewed and judged insufficient; still needs the customer's
        further action, unlike accept()'s initial triage."""

        finding = self.get_by_id(organization_id, product_market_state_id, finding_id)
        latest = self._latest_or_404(finding.id)
        self._require_status(latest, FindingStatus.CUSTOMER_RESPONDED.value)

        actor = self._load_actor_or_404(actor_user_id)
        authorized = (
            self._has_internal_role(actor.id, InternalRoleCode.RA.value)
            or self._has_internal_role(actor.id, InternalRoleCode.SENIOR_REVIEWER.value)
        )
        if not authorized:
            raise FindingTransitionNotAuthorized()

        self._append_revision(
            finding, latest,
            status=FindingStatus.OPEN.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )
        self._publish_decision_changed(
            finding,
            organization_id=organization_id,
            from_status=latest.status,
            to_status=FindingStatus.OPEN.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=None,
            correlation_id=correlation_id,
        )
        self.db.commit()

        return finding

    def resolve(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
        actor_user_id: UUID,
        rationale: str,
        disposition: str | None = None,
        resolution_decision: str | None = None,
        correlation_id: str | None = None,
    ) -> Finding:
        """
        PROPOSED/OPEN/CUSTOMER_RESPONDED -> RESOLVED. Authority is
        gated by the finding's own CURRENT severity, checked here
        against the latest revision - never at the router, which has
        no way to know severity before loading the finding. Critical
        requires Senior Reviewer unconditionally (B4/D6: "Always
        blocks... senior RA review required"); Major requires RA or
        Senior ("RA; senior by policy"); everything else is customer-
        manager self-service, matching B2's own "Resolve findings"
        grant to customer roles.
        """

        finding = self.get_by_id(organization_id, product_market_state_id, finding_id)
        latest = self._latest_or_404(finding.id)
        self._require_status(latest, *NON_TERMINAL_FINDING_STATUSES)

        actor = self._load_actor_or_404(actor_user_id)
        is_ra = self._has_internal_role(actor.id, InternalRoleCode.RA.value)
        is_senior = self._has_internal_role(actor.id, InternalRoleCode.SENIOR_REVIEWER.value)

        if latest.severity == RequirementSeverity.CRITICAL.value:
            authorized = is_senior
        elif latest.severity == RequirementSeverity.MAJOR.value:
            authorized = is_ra or is_senior
        else:
            authorized = self._is_customer_manager(actor) or is_ra or is_senior

        if not authorized:
            raise FindingTransitionNotAuthorized()

        self._append_revision(
            finding, latest,
            status=FindingStatus.RESOLVED.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
            resolution_decision=resolution_decision,
        )
        self._publish_decision_changed(
            finding,
            organization_id=organization_id,
            from_status=latest.status,
            to_status=FindingStatus.RESOLVED.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
            correlation_id=correlation_id,
        )
        self.db.commit()

        return finding

    def accept_with_rationale(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
        actor_user_id: UUID,
        rationale: str,
        disposition: str | None = None,
        correlation_id: str | None = None,
    ) -> Finding:
        """
        PROPOSED/OPEN/CUSTOMER_RESPONDED -> ACCEPTED_WITH_RATIONALE.
        RA/Senior only, regardless of severity - B4 says "approved by
        authorized RA" without a severity carve-out the way RESOLVED
        gets one, so ordinary RA authority suffices even for a Critical
        finding's non-blocking-exception disposition.
        """

        finding = self.get_by_id(organization_id, product_market_state_id, finding_id)
        latest = self._latest_or_404(finding.id)
        self._require_status(latest, *NON_TERMINAL_FINDING_STATUSES)

        actor = self._load_actor_or_404(actor_user_id)
        authorized = (
            self._has_internal_role(actor.id, InternalRoleCode.RA.value)
            or self._has_internal_role(actor.id, InternalRoleCode.SENIOR_REVIEWER.value)
        )
        if not authorized:
            raise FindingTransitionNotAuthorized()

        self._append_revision(
            finding, latest,
            status=FindingStatus.ACCEPTED_WITH_RATIONALE.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
        )
        self._publish_decision_changed(
            finding,
            organization_id=organization_id,
            from_status=latest.status,
            to_status=FindingStatus.ACCEPTED_WITH_RATIONALE.value,
            actor_user_id=actor_user_id,
            rationale=rationale,
            disposition=disposition,
            correlation_id=correlation_id,
        )
        self.db.commit()

        return finding
