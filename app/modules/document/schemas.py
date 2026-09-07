from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .models import DocumentType


class DocumentCreate(BaseModel):

    document_type: DocumentType

    notes: str | None = None


class DocumentResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    document_type: str
    notes: str | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
