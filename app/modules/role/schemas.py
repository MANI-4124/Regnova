from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RoleCreate(BaseModel):

    code: str
    name: str
    description: str | None = None


class RoleUpdate(BaseModel):

    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class RoleResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: UUID

    organization_id: UUID

    code: str

    name: str

    description: str | None

    is_system: bool

    is_active: bool