from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .exceptions import (
    OrganizationAlreadyExists,
    OrganizationNotFound,
)
from .models import Organization
from .repository import OrganizationRepository
from .schemas import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)


class OrganizationService:
    """
    Business logic for Organization.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = OrganizationRepository(db)

    def get_all(self) -> list[OrganizationResponse]:
        organizations = self.repository.get_all()

        return [
            OrganizationResponse.model_validate(org)
            for org in organizations
        ]

    def get_by_id(
        self,
        organization_id: UUID,
    ) -> OrganizationResponse:

        organization = self.repository.get_by_id(organization_id)

        if organization is None:
            raise OrganizationNotFound()

        return OrganizationResponse.model_validate(organization)

    def create(
        self,
        payload: OrganizationCreate,
    ) -> OrganizationResponse:

        organization = Organization(
            name=payload.name,
            industry=payload.industry,
            country=payload.country,
        )

        try:
            organization = self.repository.create(organization)
            self.db.commit()

        except IntegrityError:
            self.db.rollback()
            raise OrganizationAlreadyExists()

        self.repository.refresh(organization)

        return OrganizationResponse.model_validate(organization)

    def update(
        self,
        organization_id: UUID,
        payload: OrganizationUpdate,
    ) -> OrganizationResponse:

        organization = self.repository.get_by_id(organization_id)

        if organization is None:
            raise OrganizationNotFound()

        update_data = payload.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(organization, field, value)

        try:
            self.db.commit()

        except IntegrityError:
            self.db.rollback()
            raise OrganizationAlreadyExists()

        self.repository.refresh(organization)

        return OrganizationResponse.model_validate(organization)

    def delete(
        self,
        organization_id: UUID,
    ) -> None:

        organization = self.repository.get_by_id(organization_id)

        if organization is None:
            raise OrganizationNotFound()

        try:
            self.repository.delete(organization)
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise