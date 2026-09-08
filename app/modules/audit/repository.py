from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import AuditEvent, OutboxEvent


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


class AuditEventRepository(BaseRepository[AuditEvent]):
    """
    Repository for the audit log. No update/delete methods - see
    AuditEvent's own docstring for why.
    """

    def __init__(self, db: Session):
        super().__init__(db, AuditEvent)

    def exists_for_source_event(self, source_event_id: UUID) -> bool:
        """
        Idempotency check against outbox at-least-once redelivery - the
        same shape as NotificationRepository.exists_for_event_and_
        recipient, just keyed on source_event_id alone since there is no
        per-recipient fan-out here (one OutboxEvent -> at most one
        AuditEvent). Backed by the table's own UNIQUE(source_event_id)
        as the authoritative constraint for the genuine-race case.
        """
        statement = select(AuditEvent.id).where(
            AuditEvent.source_event_id == source_event_id,
        )
        return self.db.scalar(statement) is not None

    def exists_for_organization(self, organization_id: UUID) -> bool:
        """
        Backs the RESTRICT-on-delete check in OrganizationService.delete()
        - see AuditEvent.organization_id's own docstring for why this
        can't be left to the DB constraint alone in this test suite.
        """
        statement = select(AuditEvent.id).where(
            AuditEvent.organization_id == organization_id,
        )
        return self.db.scalar(statement) is not None

    def create_from_event(
        self,
        *,
        organization_id: UUID,
        source_event_id: UUID,
        event_type: str,
        schema_version: int,
        occurred_at: datetime,
        actor_user_id: UUID | None,
        correlation_id: str | None,
        product_id: UUID | None,
        product_market_state_id: UUID | None,
        visibility_tier: str,
        payload: dict[str, Any],
        internal_payload: dict[str, Any] | None,
    ) -> AuditEvent:
        event = AuditEvent(
            organization_id=organization_id,
            source_event_id=source_event_id,
            event_type=event_type,
            schema_version=schema_version,
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            product_id=product_id,
            product_market_state_id=product_market_state_id,
            visibility_tier=visibility_tier,
            payload=payload,
            internal_payload=internal_payload,
        )

        self.db.add(event)
        self.db.flush()

        return event

    def create_direct(
        self,
        *,
        organization_id: UUID,
        event_type: str,
        schema_version: int,
        occurred_at: datetime,
        actor_user_id: UUID | None,
        correlation_id: str | None,
        product_id: UUID | None,
        product_market_state_id: UUID | None,
        visibility_tier: str,
        payload: dict[str, Any],
        internal_payload: dict[str, Any] | None,
    ) -> AuditEvent:
        """
        For meta audit entries with no corresponding OutboxEvent at all
        (see AuditService._record_cross_org_query) - the audit system
        recording a fact about its own reader activity, not consuming a
        domain event through the outbox. source_event_id stays null.
        """
        event = AuditEvent(
            organization_id=organization_id,
            source_event_id=None,
            event_type=event_type,
            schema_version=schema_version,
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            product_id=product_id,
            product_market_state_id=product_market_state_id,
            visibility_tier=visibility_tier,
            payload=payload,
            internal_payload=internal_payload,
        )

        self.db.add(event)
        self.db.flush()

        return event

    def get_all(
        self,
        *,
        organization_id: UUID,
        visibility_tiers: Iterable[str],
        product_id: UUID | None = None,
        product_market_state_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        event_type: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> list[AuditEvent]:
        """
        `visibility_tiers` is never client-supplied as an unrestricted
        filter - the caller (AuditService) computes exactly which tiers
        this specific reader is cleared for and passes that set in; a
        caller asking for a tier they don't hold simply sees fewer rows,
        never an error and never a partial/redacted view of a row they
        aren't cleared for at all.
        """
        statement = select(AuditEvent).where(
            AuditEvent.organization_id == organization_id,
            AuditEvent.visibility_tier.in_(list(visibility_tiers)),
        )

        if product_id is not None:
            statement = statement.where(AuditEvent.product_id == product_id)
        if product_market_state_id is not None:
            statement = statement.where(
                AuditEvent.product_market_state_id == product_market_state_id,
            )
        if actor_user_id is not None:
            statement = statement.where(AuditEvent.actor_user_id == actor_user_id)
        if event_type is not None:
            statement = statement.where(AuditEvent.event_type == event_type)
        if occurred_from is not None:
            statement = statement.where(AuditEvent.occurred_at >= occurred_from)
        if occurred_to is not None:
            statement = statement.where(AuditEvent.occurred_at <= occurred_to)

        statement = statement.order_by(AuditEvent.occurred_at.desc())

        return list(self.db.scalars(statement))
