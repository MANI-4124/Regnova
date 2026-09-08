from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.audit.repository import OutboxRepository
from app.modules.organization.repository import OrganizationRepository
from app.modules.user.exceptions import UserNotFound
from app.modules.user.models import User
from app.modules.user.repository import UserRepository

from .exceptions import (
    AssignmentNotActive,
    AssignmentNotPending,
    InternalRoleAssignmentNotFound,
    InvalidInternalRoleCode,
    NoRevocationPending,
    RevocationAlreadyPending,
    ScopeNotAllowedForRole,
    TargetUserNotInternal,
    TenantZeroNotConfigured,
)
from .models import InternalRoleAssignment, InternalRoleAssignmentStatus, InternalRoleCode
from .repository import InternalRoleAssignmentRepository

_VALID_ROLE_CODES = frozenset(code.value for code in InternalRoleCode)


class InternalRoleAssignmentService:
    """
    HR proposes (person + role + scope as one package, with why);
    only the CEO decides. See CLAUDE.md "Internal role model" for the
    full design reasoning.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = InternalRoleAssignmentRepository(db)
        self.users = UserRepository(db)
        self.organizations = OrganizationRepository(db)
        self.outbox = OutboxRepository(db)

    def _publish_changed(
        self,
        assignment: InternalRoleAssignment,
        *,
        action: str,
        from_status: str | None,
        to_status: str,
        actor_user_id: UUID,
        rationale: str | None,
        correlation_id: str | None,
    ) -> None:
        """
        One parameterized event for all 5 write methods - see CLAUDE.md
        "Internal role model" for why action/from_status/to_status live
        in the payload rather than 5 separate event names, and "Audit
        log" for the TECHNICAL_SECURITY tier decision. Same tenant-zero
        organization_id fix as RegulatoryBasisActivated/
        ContentVersionTransitioned - InternalRoleAssignment has no
        organization of its own (its user_id always belongs to
        tenant-zero per _require_internal_user).
        """
        internal_org = self._get_tenant_zero_or_error()

        self.outbox.append(
            organization_id=internal_org.id,
            event_type="InternalRoleAssignmentChanged",
            schema_version=1,
            payload={
                "assignment_id": str(assignment.id),
                "user_id": str(assignment.user_id),
                "role_code": assignment.role_code,
                "scope": assignment.scope,
                "action": action,
                "from_status": from_status,
                "to_status": to_status,
                "rationale": rationale,
            },
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )

    def _get_tenant_zero_or_error(self):
        organization = self.organizations.get_internal()

        if organization is None:
            raise TenantZeroNotConfigured()

        return organization

    def _require_internal_user(self, user_id: UUID) -> User:
        user = self.users.get_by_id_only(user_id)

        if user is None:
            raise UserNotFound()

        tenant_zero = self._get_tenant_zero_or_error()

        if user.organization_id != tenant_zero.id:
            raise TargetUserNotInternal()

        return user

    def _compute_content_hash(self, user_id: UUID, role_code: str, scope: list[Any] | None) -> str:
        payload = {"user_id": str(user_id), "role_code": role_code, "scope": scope}

        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        ).hexdigest()

    def get_all(self) -> list[InternalRoleAssignment]:
        return self.repository.get_all()

    def get_by_id(self, assignment_id: UUID) -> InternalRoleAssignment:
        assignment = self.repository.get_by_id(assignment_id)

        if assignment is None:
            raise InternalRoleAssignmentNotFound()

        return assignment

    def propose(
        self,
        *,
        user_id: UUID,
        role_code: str,
        scope: list[Any] | None,
        proposed_by_user_id: UUID,
        rationale: str,
        correlation_id: str | None = None,
    ) -> InternalRoleAssignment:
        # The proposer must themselves be tenant-zero staff - "HR" is an
        # internal function, not something a customer-org admin can
        # invoke just because require_admin (the placeholder gate on
        # this endpoint - no HR actor-type exists in RBAC yet) happens
        # to pass for their own organization.
        self._require_internal_user(proposed_by_user_id)

        # AC: no customer-side account can ever hold an internal role -
        # enforced here, the one write path that creates these rows.
        self._require_internal_user(user_id)

        if role_code not in _VALID_ROLE_CODES:
            raise InvalidInternalRoleCode(role_code, _VALID_ROLE_CODES)

        if scope and role_code != InternalRoleCode.PLATFORM_ADMIN.value:
            raise ScopeNotAllowedForRole(role_code)

        assignment = InternalRoleAssignment(
            user_id=user_id,
            role_code=role_code,
            scope=scope,
            status=InternalRoleAssignmentStatus.PROPOSED.value,
            proposed_by_user_id=proposed_by_user_id,
            proposed_at=datetime.now(timezone.utc),
            rationale=rationale,
            content_hash=self._compute_content_hash(user_id, role_code, scope),
        )
        self.repository.create(assignment)

        self._publish_changed(
            assignment,
            action="propose",
            from_status=None,
            to_status=assignment.status,
            actor_user_id=proposed_by_user_id,
            rationale=rationale,
            correlation_id=correlation_id,
        )

        self.db.commit()

        return assignment

    def decide(
        self,
        *,
        assignment_id: UUID,
        approver_user_id: UUID,
        approve: bool,
        decision_rationale: str | None,
        correlation_id: str | None = None,
    ) -> InternalRoleAssignment:
        assignment = self.get_by_id(assignment_id)
        from_status = assignment.status

        if assignment.status != InternalRoleAssignmentStatus.PROPOSED.value:
            raise AssignmentNotPending(assignment.status)

        assignment.approver_user_id = approver_user_id
        assignment.decided_at = datetime.now(timezone.utc)
        assignment.decision_rationale = decision_rationale

        if approve:
            assignment.status = InternalRoleAssignmentStatus.APPROVED.value
            self._supersede_prior_approved(assignment)
        else:
            assignment.status = InternalRoleAssignmentStatus.REJECTED.value

        self.repository.update(assignment)

        self._publish_changed(
            assignment,
            action="decide",
            from_status=from_status,
            to_status=assignment.status,
            actor_user_id=approver_user_id,
            rationale=decision_rationale,
            correlation_id=correlation_id,
        )

        self.db.commit()

        return assignment

    def _supersede_prior_approved(self, new_assignment: InternalRoleAssignment) -> None:
        """
        A scope/role change is always a new row (propose() again), never
        an edit to the existing one - "proposing must never suspend
        existing access" means the old row stays APPROVED for the
        entire PROPOSED window of the new one. Only once the new one is
        actually approved does the old one get superseded, so there is
        never a moment with either zero or two simultaneously-APPROVED
        rows for the same (user, role_code).
        """

        prior = self.repository.get_active_for_user_role(
            new_assignment.user_id, new_assignment.role_code,
        )

        if prior is not None and prior.id != new_assignment.id:
            prior.status = InternalRoleAssignmentStatus.SUPERSEDED.value
            prior.superseded_by_id = new_assignment.id
            self.repository.update(prior)

    def propose_revocation(
        self,
        *,
        assignment_id: UUID,
        proposed_by_user_id: UUID,
        rationale: str,
        correlation_id: str | None = None,
    ) -> InternalRoleAssignment:
        assignment = self.get_by_id(assignment_id)
        self._require_internal_user(proposed_by_user_id)

        if assignment.status != InternalRoleAssignmentStatus.APPROVED.value:
            raise AssignmentNotActive(assignment.status)

        if assignment.revocation_proposed_at is not None:
            raise RevocationAlreadyPending()

        assignment.revocation_proposed_by_user_id = proposed_by_user_id
        assignment.revocation_proposed_at = datetime.now(timezone.utc)
        assignment.revocation_rationale = rationale
        # status stays APPROVED - same "proposing never suspends
        # existing access" principle as a scope-change proposal.

        self.repository.update(assignment)

        self._publish_changed(
            assignment,
            action="propose_revocation",
            from_status=assignment.status,
            to_status=assignment.status,
            actor_user_id=proposed_by_user_id,
            rationale=rationale,
            correlation_id=correlation_id,
        )

        self.db.commit()

        return assignment

    def decide_revocation(
        self,
        *,
        assignment_id: UUID,
        approver_user_id: UUID,
        approve: bool,
        decision_rationale: str | None,
        correlation_id: str | None = None,
    ) -> InternalRoleAssignment:
        assignment = self.get_by_id(assignment_id)
        from_status = assignment.status

        if assignment.revocation_proposed_at is None:
            raise NoRevocationPending()

        if approve:
            assignment.status = InternalRoleAssignmentStatus.REVOKED.value
            assignment.revoked_by_user_id = approver_user_id
            assignment.revoked_at = datetime.now(timezone.utc)
            assignment.revocation_reason = decision_rationale or assignment.revocation_rationale
        else:
            assignment.revocation_proposed_by_user_id = None
            assignment.revocation_proposed_at = None
            assignment.revocation_rationale = None

        self.repository.update(assignment)

        self._publish_changed(
            assignment,
            action="decide_revocation",
            from_status=from_status,
            to_status=assignment.status,
            actor_user_id=approver_user_id,
            rationale=decision_rationale,
            correlation_id=correlation_id,
        )

        self.db.commit()

        return assignment

    def revoke(
        self,
        *,
        assignment_id: UUID,
        actor_user_id: UUID,
        reason: str,
        correlation_id: str | None = None,
    ) -> InternalRoleAssignment:
        """
        CEO-only unilateral revocation (require_ceo gates this at the
        router) - bypasses propose_revocation/decide_revocation
        entirely, per "the same propose/approve flow, except the CEO
        who may revoke unilaterally".
        """

        assignment = self.get_by_id(assignment_id)
        from_status = assignment.status

        if assignment.status != InternalRoleAssignmentStatus.APPROVED.value:
            raise AssignmentNotActive(assignment.status)

        assignment.status = InternalRoleAssignmentStatus.REVOKED.value
        assignment.revoked_by_user_id = actor_user_id
        assignment.revoked_at = datetime.now(timezone.utc)
        assignment.revocation_reason = reason

        self.repository.update(assignment)

        self._publish_changed(
            assignment,
            action="revoke",
            from_status=from_status,
            to_status=assignment.status,
            actor_user_id=actor_user_id,
            rationale=reason,
            correlation_id=correlation_id,
        )

        self.db.commit()

        return assignment
