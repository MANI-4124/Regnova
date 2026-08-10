from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .exceptions import (
    RoleAlreadyExists,
    RoleNotFound,
)
from .models import Role
from .repository import RoleRepository
from .schemas import (
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)


class RoleService:

    def __init__(self, db: Session):
        self.db = db
        self.repository = RoleRepository(db)

    def get_all(
    self,
    organization_id: UUID,
) -> list[RoleResponse]:

        roles = self.repository.get_all(
    organization_id,
)

        return [
            RoleResponse.model_validate(role)
            for role in roles
        ]

    def get_by_id(
    self,
    organization_id: UUID,
    role_id: UUID,
) -> RoleResponse:

        role = self.repository.get_by_id(
    organization_id,
    role_id,
)

        if role is None:
            raise RoleNotFound()

        return RoleResponse.model_validate(role)

    def create(
        self,
        organization_id: UUID,
        payload: RoleCreate,
    ) -> RoleResponse:

        if self.repository.get_by_code(
            organization_id,
            payload.code,
        ):
            raise RoleAlreadyExists()

        role = Role(
            organization_id=organization_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            is_system=False,
        )

        try:
            role = self.repository.create(role)
            self.db.commit()

        except IntegrityError:
            self.db.rollback()
            raise RoleAlreadyExists()

        self.repository.refresh(role)

        return RoleResponse.model_validate(role)

    def update(
        self,
        organization_id: UUID,
        role_id: UUID,
        payload: RoleUpdate,
    ) -> RoleResponse:

        role = self.repository.get_by_id(organization_id, role_id)

        if role is None:
            raise RoleNotFound()
        if role.is_system:
         raise ValueError(
        "System roles cannot be modified."
    )

        update_data = payload.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(role, field, value)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise RoleAlreadyExists()

        self.repository.refresh(role)

        return RoleResponse.model_validate(role)

    def delete(
        self,
        organization_id: UUID,
        role_id: UUID,
    ) -> None:

        role = self.repository.get_by_id(organization_id, role_id)

        if role is None:
            raise RoleNotFound()
        if role.is_system:
         raise ValueError(
        "System roles cannot be deleted."
    )

        self.repository.delete(role)

        self.db.commit()