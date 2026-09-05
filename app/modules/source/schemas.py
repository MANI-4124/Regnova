from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SourceCreate(BaseModel):
    """
    human_reference is Source's only settable field (see models.py) -
    optional, since most callers still don't need one; the file-based
    regulatory content pipeline is the first caller that always sets it.
    """

    human_reference: str | None = None


class SourceUpdate(BaseModel):

    human_reference: str | None = None


class SourceResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    human_reference: str | None
    created_at: datetime
