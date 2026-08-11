from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import OutboxEvent


class OutboxRepository(BaseRepository[OutboxEvent]):
    """
    Repository for the transactional outbox.
    """

    def __init__(self, db: Session):
        super().__init__(db, OutboxEvent)

    def append(
        self,
        organization_id: UUID,
        event_type: str,
        schema_version: int,
        payload: dict[str, Any],
        correlation_id: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> OutboxEvent:
        """
        Add an event row to the current transaction. Does not commit -
        the caller commits this alongside its own domain write, which is
        what makes the outbox transactional.
        """

        event = OutboxEvent(
            organization_id=organization_id,
            event_type=event_type,
            schema_version=schema_version,
            payload=payload,
            correlation_id=correlation_id,
            actor_user_id=actor_user_id,
        )

        self.db.add(event)
        self.db.flush()

        return event

    def get_unpublished(
        self,
        limit: int = 100,
    ) -> list[OutboxEvent]:
        statement = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )

        if self.db.get_bind().dialect.name == "postgresql":
            # SKIP LOCKED is what makes concurrent dispatcher workers safe
            # to run in parallel - it's a Postgres-only guarantee. SQLite
            # has no equivalent concurrent-claim model, so this is scoped
            # to Postgres explicitly rather than relying on SQLite's
            # silent no-op of with_for_update().
            statement = statement.with_for_update(skip_locked=True)

        return list(self.db.scalars(statement))

    def mark_published(self, event_id: UUID) -> None:
        event = self.get_by_id(event_id)

        if event is None:
            return

        event.published_at = datetime.now(timezone.utc)
        self.db.flush()

    def mark_failed(self, event_id: UUID, error: str) -> None:
        event = self.get_by_id(event_id)

        if event is None:
            return

        event.attempts += 1
        event.last_error = error
        self.db.flush()
