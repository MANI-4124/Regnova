from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """
    Base repository providing common CRUD operations.
    """

    def __init__(
        self,
        db: Session,
        model: type[ModelType],
    ):
        self.db = db
        self.model = model

    def get_all(self) -> list[ModelType]:
        statement = select(self.model)
        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        entity_id,
    ) -> ModelType | None:
        return self.db.get(
            self.model,
            entity_id,
        )

    def create(
        self,
        entity: ModelType,
    ) -> ModelType:
        self.db.add(entity)
        self.db.flush()
        self.db.refresh(entity)
        return entity

    def update(
        self,
        entity: ModelType,
    ) -> ModelType:
        self.db.flush()
        self.db.refresh(entity)
        return entity

    def refresh(
        self,
        entity: ModelType,
    ) -> None:
        self.db.refresh(entity)

    def delete(
        self,
        entity: ModelType,
    ) -> None:
        self.db.delete(entity)