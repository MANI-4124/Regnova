from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class Notification(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    A minimal notification system, produced from existing OutboxEvents
    rather than a parallel path - see CLAUDE.md "Notifications" and
    app.modules.notification.service.RESOLVERS. Deliberately scoped by
    recipient_user_id alone, with NO organization_id column: every
    recipient (internal staff or customer-org user) is a concrete User
    row, and User.organization_id already answers "which tenant" when
    it matters - repeating that here would recreate the exact friction
    OutboxEvent.organization_id's NOT NULL FK already caused for
    ContentVersionTransitioned (no real organization to point at,
    borrowed tenant-zero's id instead). This also means Organization
    deletion cleans up its users' notifications for free via
    User.organization_id's own CASCADE, with no extra cleanup path
    needed here.
    """

    __tablename__ = "notifications"

    __table_args__ = (
        UniqueConstraint(
            "source_event_id",
            "recipient_user_id",
            name="uq_notifications_source_event_recipient",
        ),
        Index(
            "ix_notifications_recipient_read",
            "recipient_user_id",
            "read_at",
        ),
    )

    recipient_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    # Reuses OutboxEvent.event_type verbatim - not a second vocabulary
    # to keep in sync. New event types become notifiable by registering
    # a recipient resolver (see service.py's RESOLVERS), not by
    # registering a new "notification type" too.
    type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # The source event's own payload, copied as-is - no rendered
    # title/body. Deliberately not a template system: a consumer
    # renders `type` + `payload` into human text itself.
    payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON,
        nullable=False,
    )

    # SET NULL (not CASCADE) so an OutboxEvent can later be purged
    # without orphaning notification history. Nullable also so a
    # future non-event-sourced notification isn't structurally
    # impossible - the uniqueness constraint below only meaningfully
    # dedups event-sourced rows (multiple NULLs never collide).
    source_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "outbox_events.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
