from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.modules.notification.service import NotificationService

from .repository import OutboxRepository
from .service import AuditService

logger = logging.getLogger(__name__)


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
    """
    V1's own dispatch transport is just this log line (see
    dispatch_pending_events' docstring) - independent of whether any
    real notification/audit record gets produced below. Turning an
    event into Notification rows is a separate, generic step:
    NotificationService.record_for_event() looks up a recipient
    resolver for event.event_type (see
    app.modules.notification.service.RESOLVERS) and creates zero or
    more rows - there is no per-event-type branching in this function
    itself, that lives entirely in the resolver registry. See CLAUDE.md
    "Notifications".

    AuditService.record_for_event() is the same shape but NOT selective
    - every event produces exactly one AuditEvent row (see CLAUDE.md
    "Audit log": the audit log's whole point is completeness, unlike
    notifications' deliberate narrowness).
    """

    logger.info(
        "outbox_event_dispatched",
        extra={
            "event_id": str(event.id),
            "event_type": event.event_type,
            "organization_id": str(event.organization_id),
            "correlation_id": event.correlation_id,
        },
    )

    AuditService(db).record_for_event(event)

    notifications = NotificationService(db).record_for_event(event)

    for notification in notifications:
        logger.info(
            "notification_created",
            extra={
                "event_id": str(event.id),
                "notification_id": str(notification.id),
                "recipient_user_id": str(notification.recipient_user_id),
                "type": notification.type,
            },
        )
