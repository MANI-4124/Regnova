from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    """
    The customer-tier shape - deliberately has NO internal_payload
    field at all, not just one that happens to be null, so a row that
    somehow carries internal-only detail can never leak through this
    schema's serialization regardless of what the service returns.
    """

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    event_type: str
    schema_version: int
    occurred_at: datetime
    actor_user_id: UUID | None
    correlation_id: str | None
    product_id: UUID | None
    product_market_state_id: UUID | None
    visibility_tier: str
    payload: dict[str, Any]


class AuditEventInternalResponse(AuditEventResponse):
    """
    The internal-regulatory/technical-security/auditor shape - the only
    one that ever includes internal_payload.
    """

    internal_payload: dict[str, Any] | None
