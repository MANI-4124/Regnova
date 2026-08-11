from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class OutboxEvent(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Transactional outbox row: one schema-versioned domain event fact,
    written in the same transaction as the domain change that caused it.
    """

    __tablename__ = "outbox_events"

    __table_args__ = (
        Index(
            "ix_outbox_events_dispatch",
            "published_at",
            "created_at",
        ),
        Index(
            "ix_outbox_events_organization_id",
            "organization_id",
        ),
        Index(
            "ix_outbox_events_event_type",
            "event_type",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
