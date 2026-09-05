from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository

from .exceptions import NotificationNotFound
from .models import Notification
from .repository import NotificationRepository


def _resolve_content_version_transitioned_recipients(
    db: Session,
    payload: dict,
) -> list[UUID]:
    """
    Relocated from app.modules.audit.worker's previous log-only
    consumer, unchanged in behavior: only the DRAFT -> IN_REVIEW hop
    needs anyone notified (an advisor drafting silently, or a Knowledge
    Lead's own verify/activate/reject, doesn't). Internal-role
    resolution, not organization-membership - this axis was never about
    tenancy, see CLAUDE.md "Internal role model".
    """

    if payload.get("to_status") != "IN_REVIEW":
        return []

    holders = InternalRoleAssignmentRepository(db).get_active_holders(
        InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
    )
    return [holder.user_id for holder in holders]


# event_type -> resolver(db, event.payload) -> recipient user ids.
# Extensibility point: a new OutboxEvent type becomes notifiable by
# registering a resolver here, not by touching the dispatch loop in
# app.modules.audit.worker. No resolver registered for a given
# event_type means no notifications are produced for it - silent, not
# an error - see CLAUDE.md "Notifications" for which existing event
# types deliberately have no resolver yet (WorkspaceActivated/
# MembershipChanged/ProductVersionPublished - the organization-
# membership resolver shape those would need is designed, not built).
RESOLVERS: dict[str, Callable[[Session, dict], list[UUID]]] = {
    "ContentVersionTransitioned": _resolve_content_version_transitioned_recipients,
}


class NotificationService:
    """
    Notification service - produced from existing OutboxEvents (see
    record_for_event(), called by app.modules.audit.worker's dispatch
    loop), never written any other way. See CLAUDE.md "Notifications".
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = NotificationRepository(db)

    def get_all(
        self,
        recipient_user_id: UUID,
        *,
        unread_only: bool = False,
    ) -> list[Notification]:
        return self.repository.get_all_for_recipient(
            recipient_user_id, unread_only=unread_only,
        )

    def get_unread_count(self, recipient_user_id: UUID) -> int:
        return self.repository.get_unread_count(recipient_user_id)

    def mark_read(
        self,
        recipient_user_id: UUID,
        notification_id: UUID,
    ) -> Notification:
        notification = self.repository.get_by_id_for_recipient(
            recipient_user_id, notification_id,
        )

        if notification is None:
            raise NotificationNotFound()

        self.repository.mark_read(notification)
        self.db.commit()

        return notification

    def record_for_event(self, event) -> list[Notification]:
        """
        Turns one OutboxEvent into zero or more Notification rows via
        RESOLVERS. Idempotent against outbox at-least-once redelivery -
        checks per recipient before inserting (exists_for_event_and_
        recipient), backed by the table's own UNIQUE(source_event_id,
        recipient_user_id) as the authoritative constraint. Does not
        commit - the caller (app.modules.audit.worker.dispatch_pending_
        events) commits this alongside marking the event published, the
        same transactional-outbox discipline as everywhere else in this
        codebase.
        """

        resolver = RESOLVERS.get(event.event_type)
        if resolver is None:
            return []

        recipient_ids = resolver(self.db, event.payload or {})

        created = []
        for recipient_user_id in recipient_ids:
            if self.repository.exists_for_event_and_recipient(event.id, recipient_user_id):
                continue

            created.append(
                self.repository.create_for_event(
                    recipient_user_id=recipient_user_id,
                    type=event.event_type,
                    payload=event.payload,
                    source_event_id=event.id,
                ),
            )

        return created
