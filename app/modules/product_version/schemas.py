from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductVersionCreate(BaseModel):

    version: str

    status: str | None = None

    notes: str | None = None


class ProductVersionUpdate(BaseModel):

    status: str | None = None

    notes: str | None = None

    is_active: bool | None = None


class ProductVersionResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID

    organization_id: UUID

    product_id: UUID

    version: str

    status: str

    notes: str | None

    is_active: bool

    released_at: datetime | None
