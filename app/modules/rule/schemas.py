from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RuleCreate(BaseModel):

    human_reference: str | None = None


class RuleUpdate(BaseModel):

    human_reference: str | None = None


class RuleResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    human_reference: str | None
    created_at: datetime
