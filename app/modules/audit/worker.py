from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.user.repository import UserRepository

from .repository import OutboxRepository

logger = logging.getLogger(__name__)

_CONTENT_VERSION_TRANSITIONED = "ContentVersionTransitioned"


def dispatch_pending_events(db: Session, limit: int = 100) -> int:
    """
    Poll for unpublished outbox events and dispatch them, committing each
    one's published/failed state individually so a failure on one event
    doesn't roll back the successful dispatch of the others. Returns the
    number of events successfully dispatched.

    Intended to be invoked by a scheduler/worker process (cron, a
    separate dyno, etc.) - not started automatically by the web app. The
    dispatch transport itself (queue/bus/log) is left open pending the
    durable-work architecture spike A5.1 calls for; V1 logs the event.
    """

    repository = OutboxRepository(db)
    events = repository.get_unpublished(limit)

    dispatched = 0

    for event in events:
        try:
            _publish(db, event)
        except Exception as exc:
            repository.mark_failed(event.id, str(exc))
            db.commit()
            continue

        repository.mark_published(event.id)
        db.commit()
        dispatched += 1

    return dispatched


def _publish(db: Session, event) -> None:
    logger.info(
        "outbox_event_dispatched",
        extra={
            "event_id": str(event.id),
            "event_type": event.event_type,
            "organization_id": str(event.organization_id),
            "correlation_id": event.correlation_id,
        },
    )

    if event.event_type == _CONTENT_VERSION_TRANSITIONED:
        _notify_on_submitted_for_review(db, event)


def _notify_on_submitted_for_review(db: Session, event) -> None:
    """
    Minimal notification consumer - the smallest thing that works, not
    the full spec'd M5 notification system (no email/Slack/in-app
    delivery channel exists yet to send to). Logs one line per active
    REGULATORY_KNOWLEDGE_LEAD holder naming them and the content
    awaiting their review, only when this transition is the one that
    actually needs a reviewer's attention (DRAFT -> IN_REVIEW) - an
    advisor drafting silently, or a Knowledge Lead's own verify/
    activate/reject, doesn't need to notify anyone. See CLAUDE.md
    "Regulatory content approval workflow".
    """

    payload = event.payload or {}
    if payload.get("to_status") != "IN_REVIEW":
        return

    holders = InternalRoleAssignmentRepository(db).get_active_holders(
        InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
    )
    users = UserRepository(db)

    for holder in holders:
        recipient = users.get_by_id_only(holder.user_id)
        logger.info(
            "content_version_submitted_for_review_notification",
            extra={
                "event_id": str(event.id),
                "recipient_user_id": str(holder.user_id),
                "recipient_email": recipient.email if recipient else None,
                "content_type": payload.get("content_type"),
                "content_version_id": payload.get("content_version_id"),
            },
        )
