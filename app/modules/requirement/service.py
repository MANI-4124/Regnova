from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from .exceptions import RequirementNotFound
from .models import Requirement
from .repository import RequirementRepository
from .schemas import (
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate,
)


class RequirementService:
    """
    Business logic for Requirement.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = RequirementRepository(db)

    def get_all(self) -> list[RequirementResponse]:
        requirements = self.repository.get_all()

        return [
            RequirementResponse.model_validate(requirement)
            for requirement in requirements
        ]

    def get_by_id(self, requirement_id: UUID) -> RequirementResponse:
        requirement = self.repository.get_by_id(requirement_id)

        if requirement is None:
            raise RequirementNotFound()

        return RequirementResponse.model_validate(requirement)

    def create(self, payload: RequirementCreate) -> RequirementResponse:
        requirement = Requirement(
            human_reference=payload.human_reference,
        )

        self.repository.create(requirement)
        self.db.commit()

        return RequirementResponse.model_validate(requirement)

    def update(
        self,
        requirement_id: UUID,
        payload: RequirementUpdate,
    ) -> RequirementResponse:
        requirement = self.repository.get_by_id(requirement_id)

        if requirement is None:
            raise RequirementNotFound()

        data = payload.model_dump(exclude_unset=True)

        for field, value in data.items():
            setattr(requirement, field, value)

        self.repository.update(requirement)
        self.db.commit()

        return RequirementResponse.model_validate(requirement)
