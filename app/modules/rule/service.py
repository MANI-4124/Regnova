from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from .exceptions import RuleNotFound
from .models import Rule
from .repository import RuleRepository
from .schemas import (
    RuleCreate,
    RuleResponse,
    RuleUpdate,
)


class RuleService:
    """
    Business logic for Rule.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = RuleRepository(db)

    def get_all(self) -> list[RuleResponse]:
        rules = self.repository.get_all()

        return [
            RuleResponse.model_validate(rule)
            for rule in rules
        ]

    def get_by_id(self, rule_id: UUID) -> RuleResponse:
        rule = self.repository.get_by_id(rule_id)

        if rule is None:
            raise RuleNotFound()

        return RuleResponse.model_validate(rule)

    def create(self, payload: RuleCreate) -> RuleResponse:
        rule = Rule(
            human_reference=payload.human_reference,
        )

        self.repository.create(rule)
        self.db.commit()

        return RuleResponse.model_validate(rule)

    def update(
        self,
        rule_id: UUID,
        payload: RuleUpdate,
    ) -> RuleResponse:
        rule = self.repository.get_by_id(rule_id)

        if rule is None:
            raise RuleNotFound()

        data = payload.model_dump(exclude_unset=True)

        for field, value in data.items():
            setattr(rule, field, value)

        self.repository.update(rule)
        self.db.commit()

        return RuleResponse.model_validate(rule)
