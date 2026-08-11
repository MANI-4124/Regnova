from __future__ import annotations

from sqlalchemy.orm import relationship

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

    versions = relationship(
        "SourceVersion",
        back_populates="source",
        cascade="all, delete-orphan",
    )
