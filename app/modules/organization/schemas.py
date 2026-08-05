from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OrganizationBase(BaseModel):
    name: str
    industry: str
    country: str


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    country: str | None = None
    is_active: bool | None = None


class OrganizationResponse(OrganizationBase):
    id: UUID
    is_active: bool

    model_config = ConfigDict(from_attributes=True)