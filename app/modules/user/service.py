from __future__ import annotations
from app.modules.auth.security import hash_password
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .exceptions import (
    UserAlreadyExists,
    UserNotFound,
)
from .models import User
from .repository import UserRepository
from .schemas import (
    UserCreate,
    UserResponse,
    UserUpdate,
)


class UserService:

    def __init__(
        self,
        db: Session,
    ):
        self.db = db
        self.repository = UserRepository(db)

    def get_all(
        self,
        organization_id: UUID,
    ) -> list[UserResponse]:

        users = self.repository.get_all(
            organization_id,
        )

        return [
            UserResponse.model_validate(user)
            for user in users
        ]

    def get_by_id(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> UserResponse:

        user = self.repository.get_by_id(
            organization_id,
            user_id,
        )

        if user is None:
            raise UserNotFound()

        return UserResponse.model_validate(user)

    def create(
        self,
        organization_id: UUID,
        payload: UserCreate,
    ) -> UserResponse:

        if self.repository.get_by_email(
            organization_id,
            payload.email,
        ):
            raise UserAlreadyExists()

        user = User(
            organization_id=organization_id,
            role_id=payload.role_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            # Hash password before storing
password_hash=hash_password(payload.password),
            phone=payload.phone,
        )

        try:
            user = self.repository.create(user)
            self.db.commit()

        except IntegrityError:
            self.db.rollback()
            raise UserAlreadyExists()

        self.repository.refresh(user)

        return UserResponse.model_validate(user)

    def update(
        self,
        organization_id: UUID,
        user_id: UUID,
        payload: UserUpdate,
    ) -> UserResponse:

        user = self.repository.get_by_id(
            organization_id,
            user_id,
        )

        if user is None:
            raise UserNotFound()

        update_data = payload.model_dump(
            exclude_unset=True,
        )

        for field, value in update_data.items():
            setattr(user, field, value)

        self.db.commit()

        self.repository.refresh(user)

        return UserResponse.model_validate(user)

    def delete(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> None:

        user = self.repository.get_by_id(
            organization_id,
            user_id,
        )

        if user is None:
            raise UserNotFound()

        self.repository.delete(user)

        self.db.commit()