from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EvidenceCreate(BaseModel):

    document_version_id: UUID
    product_id: UUID
    requirement_version_id: UUID | None = None
    notes: str | None = None


class EvidenceResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    document_version_id: UUID
    product_id: UUID
    requirement_version_id: UUID | None
    notes: str | None
    created_by_user_id: UUID | None
    is_current: bool
    stale_reason: str | None
    created_at: datetime
    updated_at: datetime
