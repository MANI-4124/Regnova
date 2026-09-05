from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Notification


class NotificationRepository(BaseRepository[Notification]):
    """
    Repository for Notification - scoped by recipient_user_id alone,
    not organization_id. See models.py for why.
    """

    def __init__(self, db: Session):
        super().__init__(db, Notification)

    def get_by_id_for_recipient(
        self,
        recipient_user_id: UUID,
        notification_id: UUID,
    ) -> Notification | None:
        statement = select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == recipient_user_id,
        )

        return self.db.scalar(statement)

    def get_all_for_recipient(
        self,
        recipient_user_id: UUID,
        *,
        unread_only: bool = False,
    ) -> list[Notification]:
        statement = select(Notification).where(
            Notification.recipient_user_id == recipient_user_id,
        )

        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))

        statement = statement.order_by(Notification.created_at.desc())

        return list(self.db.scalars(statement))

    def get_unread_count(self, recipient_user_id: UUID) -> int:
        statement = select(func.count()).select_from(Notification).where(
            Notification.recipient_user_id == recipient_user_id,
            Notification.read_at.is_(None),
        )

        return self.db.scalar(statement) or 0

    def exists_for_event_and_recipient(
        self,
        source_event_id: UUID,
        recipient_user_id: UUID,
    ) -> bool:
        """
        Idempotency check used by record_for_event() before inserting -
        at-least-once outbox delivery means the same event can be
        reprocessed, and this is what makes that a no-op rather than a
        duplicate row. The UNIQUE(source_event_id, recipient_user_id)
        constraint on the table is the authoritative backstop (a race
        between two dispatcher workers), not the primary mechanism -
        this check is what avoids relying on catching an IntegrityError
        in the normal reprocessing path.
        """

        statement = select(Notification.id).where(
            Notification.source_event_id == source_event_id,
            Notification.recipient_user_id == recipient_user_id,
        )

        return self.db.scalar(statement) is not None

    def create_for_event(
        self,
        *,
        recipient_user_id: UUID,
        type: str,
        payload: dict[str, Any],
        source_event_id: UUID | None,
    ) -> Notification:
        notification = Notification(
            recipient_user_id=recipient_user_id,
            type=type,
            payload=payload,
            source_event_id=source_event_id,
        )

        self.db.add(notification)
        self.db.flush()

        return notification

    def mark_read(self, notification: Notification) -> Notification:
        notification.read_at = datetime.now(timezone.utc)
        self.db.flush()

        return notification
