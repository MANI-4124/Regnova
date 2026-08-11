from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SourceResponse(BaseModel):
    """
    Source has no settable fields of its own (see models.py) - there is
    no SourceCreate/SourceUpdate schema, only a response shape.
    """

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    created_at: datetime
