from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class Source(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Stable identity of a regulatory source (authority publication,
    standard, RegNova interpretation, or secondary reference).

    Deliberately minimal - no organization_id (Source is shared platform
    reference data, not customer-owned data - see CLAUDE.md "Regulatory
    content ownership"). Descriptive fields (title, jurisdiction, tier,
    etc.) live on SourceVersion per C4.1, not here, since they can
    legitimately change between versions of the same source (e.g. a
    consolidated re-issue with a different title).
    """

    __tablename__ = "sources"

    # Added for parity with Requirement.human_reference/Rule.human_reference
    # - "stable identity... across versions", same docstring language,
    # same unique constraint. Added specifically so the file-based
    # regulatory content pipeline's idempotency key (a file's own
    # human-authored `key`) has somewhere to live for Source the same
    # way it already does for Requirement/Rule - see CLAUDE.md
    # "File-based regulatory content pipeline".
    human_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
    )

    versions = relationship(
        "SourceVersion",
        back_populates="source",
        cascade="all, delete-orphan",
    )
