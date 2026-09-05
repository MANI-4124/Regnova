from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.audit.repository import OutboxRepository
from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.organization.repository import OrganizationRepository
from app.modules.user.exceptions import UserNotFound
from app.modules.user.repository import UserRepository

from .exceptions import ContentVersionTransitionNotAllowed, ContentVersionTransitionNotAuthorized
from .repository import ContentVersionTransitionRepository

# One event type, content_type carried in the payload, rather than 15
# concrete names (3 content types x 5 transitions) - see CLAUDE.md
# "Regulatory content approval workflow".
CONTENT_VERSION_TRANSITIONED = "ContentVersionTransitioned"


class ContentReviewWorkflow:
    """
    Shared draft -> submit_for_review -> verify -> activate (or
    IN_REVIEW -> DRAFT via reject) transition logic for
    RequirementVersion/RuleVersion/SourceVersion - one implementation
    composed into each content type's own *VersionService, rather than
    three near-identical copies. Formalizes the DRAFT/IN_REVIEW/
    VERIFIED/ACTIVE status vocabulary those models already declared but
    never enforced transition order or authority on. See CLAUDE.md
    "Regulatory content approval workflow" for the full design.

    `version` here is any ORM instance with `.id`/`.status` and (for
    verify()) a `.verified_at`/`.reviewer_user_id` pair - i.e. a
    RequirementVersion, RuleVersion, or SourceVersion row. Callers pass
    their own already-loaded row; this class never queries for it.
    """

    def __init__(self, db: Session, *, content_type: str, status_enum):
        self.db = db
        self.content_type = content_type
        self.status_enum = status_enum
        self.transitions = ContentVersionTransitionRepository(db)
        self.internal_role_assignments = InternalRoleAssignmentRepository(db)
        self.users = UserRepository(db)
        self.organizations = OrganizationRepository(db)
        self.outbox = OutboxRepository(db)

    # --- guards ---

    def _require_status(self, version, *allowed: str) -> None:
        if version.status not in allowed:
            raise ContentVersionTransitionNotAllowed(version.status, frozenset(allowed))

    def _load_actor_or_404(self, actor_user_id: UUID):
        actor = self.users.get_by_id_only(actor_user_id)

        if actor is None:
            raise UserNotFound()

        return actor

    def _has_internal_role(self, actor_user_id: UUID, role_code: str) -> bool:
        return self.internal_role_assignments.get_active_for_user_role(
            actor_user_id, role_code,
        ) is not None

    def _require_author(self, actor_user_id: UUID) -> None:
        """
        Drafting/submitting-for-review: REGULATORY_CONTENT_ADVISOR or
        REGULATORY_KNOWLEDGE_LEAD (Knowledge Lead is a strict superset -
        they can still do everything themselves, same shape as
        require_manager including ADMIN).
        """

        self._load_actor_or_404(actor_user_id)

        authorized = (
            self._has_internal_role(actor_user_id, InternalRoleCode.REGULATORY_CONTENT_ADVISOR.value)
            or self._has_internal_role(actor_user_id, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value)
        )
        if not authorized:
            raise ContentVersionTransitionNotAuthorized()

    def _require_verifier(self, actor_user_id: UUID) -> None:
        """
        verify()/activate()/reject(): REGULATORY_KNOWLEDGE_LEAD only -
        an advisor can draft and submit but never self-verify.
        """

        self._load_actor_or_404(actor_user_id)

        if not self._has_internal_role(actor_user_id, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value):
            raise ContentVersionTransitionNotAuthorized()

    # --- audit trail + notification ---

    def _record_transition(
        self,
        version,
        *,
        from_status: str | None,
        to_status: str,
        actor_user_id: UUID | None,
        rationale: str | None,
    ) -> None:
        self.transitions.record(
            content_type=self.content_type,
            content_version_id=version.id,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )

    def _publish_event(
        self,
        version,
        *,
        from_status: str | None,
        to_status: str,
        actor_user_id: UUID | None,
        rationale: str | None,
    ) -> None:
        """
        OutboxEvent.organization_id is a NOT NULL FK to organizations.id
        - but this content has no organization_id of its own (same
        ownership model as RegulatoryBasisRelease). Regulatory content
        is authored and reviewed exclusively by tenant-zero staff, so
        tying these events to the tenant-zero Organization is the
        smallest correct fit, not a real per-customer attribution - see
        CLAUDE.md "Regulatory content approval workflow" for the
        alternative (making the column nullable) this deliberately
        avoids.
        """

        internal_org = self.organizations.get_internal()
        if internal_org is None:
            # Regulatory content authoring must not fail because the
            # tenant-zero organization doesn't exist yet in this
            # environment - just skip the event.
            return

        self.outbox.append(
            organization_id=internal_org.id,
            event_type=CONTENT_VERSION_TRANSITIONED,
            schema_version=1,
            payload={
                "content_type": self.content_type,
                "content_version_id": str(version.id),
                "from_status": from_status,
                "to_status": to_status,
                "rationale": rationale,
            },
            actor_user_id=actor_user_id,
        )

    # --- transitions ---

    def require_editable(self, version) -> None:
        """
        Guard for the owning service's own field-level update() -
        content is only editable while DRAFT; once submitted for
        review, changes must go through reject() back to DRAFT first
        rather than being silently rewritten mid-review.
        """

        self._require_status(version, self.status_enum.DRAFT.value)

    def draft(self, version, *, actor_user_id: UUID) -> None:
        """
        Records the initial DRAFT transition for a newly created
        version. No event published - nothing needs notifying yet, an
        advisor drafting silently is the whole point of this stage
        being "visible but inert".
        """

        self._record_transition(
            version,
            from_status=None,
            to_status=self.status_enum.DRAFT.value,
            actor_user_id=actor_user_id,
            rationale=None,
        )

    def submit_for_review(self, version, *, actor_user_id: UUID) -> None:
        self._require_status(version, self.status_enum.DRAFT.value)
        self._require_author(actor_user_id)

        from_status = version.status
        version.status = self.status_enum.IN_REVIEW.value

        self._record_transition(
            version,
            from_status=from_status,
            to_status=version.status,
            actor_user_id=actor_user_id,
            rationale=None,
        )
        self._publish_event(
            version,
            from_status=from_status,
            to_status=version.status,
            actor_user_id=actor_user_id,
            rationale=None,
        )

    def verify(self, version, *, actor_user_id: UUID, rationale: str) -> None:
        self._require_status(version, self.status_enum.IN_REVIEW.value)
        self._require_verifier(actor_user_id)

        from_status = version.status
        version.status = self.status_enum.VERIFIED.value
        version.verified_at = datetime.now(timezone.utc)
        # reviewer_user_id now means "who formally verified this
        # version" - previously a freely self-settable field with no
        # enforced meaning at all.
        version.reviewer_user_id = actor_user_id

        self._record_transition(
            version,
            from_status=from_status,
            to_status=version.status,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )
        self._publish_event(
            version,
            from_status=from_status,
            to_status=version.status,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )

    def activate(self, version, *, actor_user_id: UUID, rationale: str) -> None:
        """
        Same actor authority as verify() (REGULATORY_KNOWLEDGE_LEAD) -
        for now. See CLAUDE.md "Known limitations": material content
        may need a distinct second approver for activation specifically,
        per D6.1's fuller approval-matrix vocabulary; not implemented.
        """

        self._require_status(version, self.status_enum.VERIFIED.value)
        self._require_verifier(actor_user_id)

        from_status = version.status
        version.status = self.status_enum.ACTIVE.value
        if hasattr(version, "activated_at"):
            # Only SourceVersion has this column today (RequirementVersion/
            # RuleVersion don't) - the transition-history row is the
            # authoritative "when activated" record for all three either
            # way; this just fills an existing, previously-dead column
            # where it exists.
            version.activated_at = datetime.now(timezone.utc)

        self._record_transition(
            version,
            from_status=from_status,
            to_status=version.status,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )
        self._publish_event(
            version,
            from_status=from_status,
            to_status=version.status,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )

    def reject(self, version, *, actor_user_id: UUID, rationale: str) -> None:
        self._require_status(version, self.status_enum.IN_REVIEW.value)
        self._require_verifier(actor_user_id)

        from_status = version.status
        version.status = self.status_enum.DRAFT.value

        self._record_transition(
            version,
            from_status=from_status,
            to_status=version.status,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )
        self._publish_event(
            version,
            from_status=from_status,
            to_status=version.status,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )
