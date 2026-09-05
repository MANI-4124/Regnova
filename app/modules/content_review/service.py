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

from .exceptions import (
    ContentVersionTransitionNotAllowed,
    ContentVersionTransitionNotAuthorized,
    UnknownContentType,
)
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


def _content_type_registry() -> dict[str, tuple[type, type]]:
    """
    content_type -> (repository class, status enum) - the same pair each
    *VersionService's own __init__ already builds a ContentReviewWorkflow
    from, just keyed by string so BulkContentReviewService can resolve an
    arbitrary mix of the three content types in one request without
    three near-identical bulk endpoints.

    Built lazily inside a function, not as a module-level constant -
    RequirementVersionService/RuleVersionService/SourceVersionService
    all import ContentReviewWorkflow from this same module at import
    time, so importing their repositories/status enums back at THIS
    module's top level would be a real circular import (each module's
    own __init__.py eagerly imports its router -> service -> this
    module, before this module has finished defining itself). Deferring
    the import to call time, long after every module has finished
    loading, sidesteps that entirely.
    """

    from app.modules.requirement_version.models import RequirementVersionStatus
    from app.modules.requirement_version.repository import RequirementVersionRepository
    from app.modules.rule_version.models import RuleVersionStatus
    from app.modules.rule_version.repository import RuleVersionRepository
    from app.modules.source_version.models import SourceVersionStatus
    from app.modules.source_version.repository import SourceVersionRepository

    return {
        "requirement_version": (RequirementVersionRepository, RequirementVersionStatus),
        "rule_version": (RuleVersionRepository, RuleVersionStatus),
        "source_version": (SourceVersionRepository, SourceVersionStatus),
    }


_PAST_TENSE = {"verify": "verified", "activate": "activated"}


class BulkContentReviewService:
    """
    Bulk-verify/bulk-activate - the practical-at-volume counterpart to
    the one-at-a-time verify()/activate() endpoints, for when a file-
    based load produces hundreds of DRAFT/IN_REVIEW rows at once (see
    CLAUDE.md "File-based regulatory content pipeline"). Does NOT
    bypass per-row authority or status checks - each item still goes
    through the exact same ContentReviewWorkflow.verify()/.activate()
    real single-row authority+status guards a lone verify() call would.
    One bad item fails that item alone and never blocks the rest of the
    batch - same "commit per success, continue on failure" discipline
    app.modules.audit.worker.dispatch_pending_events already uses for
    exactly this reason.
    """

    def __init__(self, db: Session):
        self.db = db

    def _resolve(self, content_type: str, content_id: UUID):
        entry = _content_type_registry().get(content_type)
        if entry is None:
            raise UnknownContentType(content_type, content_id)

        repository_cls, status_enum = entry
        version = repository_cls(self.db).get_by_id_only(content_id)
        if version is None:
            raise UnknownContentType(content_type, content_id)

        workflow = ContentReviewWorkflow(self.db, content_type=content_type, status_enum=status_enum)
        return version, workflow

    def _apply(self, items, *, action: str, actor_user_id: UUID, rationale: str):
        from .schemas import BulkContentReviewItemResult

        results = []

        for item in items:
            try:
                version, workflow = self._resolve(item.content_type, item.content_id)
                getattr(workflow, action)(version, actor_user_id=actor_user_id, rationale=rationale)
                self.db.commit()
                results.append(
                    BulkContentReviewItemResult(
                        content_type=item.content_type,
                        content_id=item.content_id,
                        status=_PAST_TENSE[action],
                    ),
                )
            except Exception as exc:
                self.db.rollback()
                results.append(
                    BulkContentReviewItemResult(
                        content_type=item.content_type,
                        content_id=item.content_id,
                        status="failed",
                        error=str(exc),
                    ),
                )

        return results

    def bulk_verify(self, items, *, actor_user_id: UUID, rationale: str):
        return self._apply(items, action="verify", actor_user_id=actor_user_id, rationale=rationale)

    def bulk_activate(self, items, *, actor_user_id: UUID, rationale: str):
        return self._apply(items, action="activate", actor_user_id=actor_user_id, rationale=rationale)
