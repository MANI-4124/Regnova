from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):

    role_id: UUID

    first_name: str

    last_name: str

    email: EmailStr

    password: str

    phone: str | None = None


class UserUpdate(BaseModel):

    role_id: UUID | None = None

    first_name: str | None = None

    last_name: str | None = None

    phone: str | None = None

    is_active: bool | None = None


class UserResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID

    organization_id: UUID

    role_id: UUID

    first_name: str

    last_name: str

    email: EmailStr

    phone: str | None

    is_active: bool

    is_verified: bool

    last_login: datetime | None