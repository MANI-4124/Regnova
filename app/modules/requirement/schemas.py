from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RequirementCreate(BaseModel):

    human_reference: str | None = None


class RequirementUpdate(BaseModel):

    human_reference: str | None = None


class RequirementResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    human_reference: str | None
    created_at: datetime
