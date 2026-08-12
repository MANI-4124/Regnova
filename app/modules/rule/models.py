from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class Rule(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Stable identity of executable regulatory logic (C6). No
    organization_id - Rule is RegNova-owned platform content, same as
    Source/Requirement. Confirmed as a distinct entity from RuleVersion
    via C2's entity catalog and Appendix 1's glossary, even though C6's
    own prose only ever says "A Rule Version is..." without separately
    defining "Rule". Descriptive/substantive fields live on
    RuleVersion, mirroring the Requirement/RequirementVersion split -
    not independently confirmed by C6's own text, consistent with
    precedent rather than a certainty.
    """

    __tablename__ = "rules"

    human_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
    )

    versions = relationship(
        "RuleVersion",
        back_populates="rule",
        cascade="all, delete-orphan",
    )
