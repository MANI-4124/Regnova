from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):

    name: str

    brand: str | None = None

    description: str | None = None


class ProductUpdate(BaseModel):

    name: str | None = None

    brand: str | None = None

    description: str | None = None

    status: str | None = None

    is_active: bool | None = None


class ProductResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID

    organization_id: UUID

    name: str

    brand: str | None

    description: str | None

    status: str

    is_active: bool