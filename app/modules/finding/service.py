from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

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
from .models import Finding, FindingRevision, FindingStatus, NON_TERMINAL_FINDING_STATUSES
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
        )
        self.revisions.create(revision)

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
        self.db.commit()

        return finding
