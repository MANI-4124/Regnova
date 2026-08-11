from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class Requirement(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Stable identity of a regulatory obligation concept (C5). No
    organization_id - requirement content is RegNova-owned platform
    content, same as Source. Descriptive/substantive fields live on
    RequirementVersion, mirroring the Source/SourceVersion split.
    """

    __tablename__ = "requirements"

    human_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
    )

    versions = relationship(
        "RequirementVersion",
        back_populates="requirement",
        cascade="all, delete-orphan",
    )
