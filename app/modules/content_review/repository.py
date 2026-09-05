from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import ContentVersionTransition


class ContentVersionTransitionRepository(BaseRepository[ContentVersionTransition]):
    """
    Repository for the shared content-version transition history table.
    """

    def __init__(self, db: Session):
        super().__init__(db, ContentVersionTransition)

    def record(
        self,
        *,
        content_type: str,
        content_version_id: UUID,
        from_status: str | None,
        to_status: str,
        actor_user_id: UUID | None,
        rationale: str | None,
    ) -> ContentVersionTransition:
        transition = ContentVersionTransition(
            content_type=content_type,
            content_version_id=content_version_id,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            rationale=rationale,
        )

        self.db.add(transition)
        self.db.flush()

        return transition

    def get_for_content(
        self,
        content_type: str,
        content_version_id: UUID,
    ) -> list[ContentVersionTransition]:
        statement = (
            select(ContentVersionTransition)
            .where(
                ContentVersionTransition.content_type == content_type,
                ContentVersionTransition.content_version_id == content_version_id,
            )
            .order_by(ContentVersionTransition.created_at.asc())
        )

        return list(self.db.scalars(statement))
