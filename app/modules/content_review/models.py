from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class ContentVersionTransition(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Append-only audit trail for the DRAFT -> IN_REVIEW -> VERIFIED ->
    ACTIVE lifecycle (or IN_REVIEW -> DRAFT on reject) shared by
    RequirementVersion/RuleVersion/SourceVersion - one polymorphic table
    rather than three near-identical ones, written by
    app.modules.content_review.service.ContentReviewWorkflow, never
    directly. See CLAUDE.md "Regulatory content approval workflow".

    content_version_id deliberately carries no ForeignKey: which table
    it points into depends on content_type (it can be a
    requirement_versions/rule_versions/source_versions row), and a
    single FK column can't express "one of three possible parents".
    Integrity is app-level, the same trust boundary every other write
    in this codebase already places on going through the service layer
    rather than raw inserts.
    """

    __tablename__ = "content_version_transitions"

    __table_args__ = (
        Index(
            "ix_content_version_transitions_content",
            "content_type",
            "content_version_id",
        ),
        Index(
            "ix_content_version_transitions_actor_user_id",
            "actor_user_id",
        ),
    )

    content_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    content_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        nullable=False,
    )

    # Null only for the initial DRAFT row written at creation - there is
    # no "from" status before a version exists.
    from_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    to_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # Required by ContentReviewWorkflow for verify/activate/reject
    # (D6.1's "rationale" vocabulary); null for the no-rationale-needed
    # draft/submit-for-review hops, and for the migration-time
    # "pre-workflow" backfill's own explanatory text (see the migration
    # that creates this table).
    rationale: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
