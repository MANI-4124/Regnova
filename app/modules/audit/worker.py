from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .repository import OutboxRepository

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
            _publish(event)
        except Exception as exc:
            repository.mark_failed(event.id, str(exc))
            db.commit()
            continue

        repository.mark_published(event.id)
        db.commit()
        dispatched += 1

    return dispatched


def _publish(event) -> None:
    logger.info(
        "outbox_event_dispatched",
        extra={
            "event_id": str(event.id),
            "event_type": event.event_type,
            "organization_id": str(event.organization_id),
            "correlation_id": event.correlation_id,
        },
    )
