from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    recipient_user_id: UUID
    type: str
    payload: dict[str, Any]
    source_event_id: UUID | None
    read_at: datetime | None
    created_at: datetime


class UnreadCountResponse(BaseModel):

    unread_count: int
