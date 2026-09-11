from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AskRegnovaAskRequest(BaseModel):

    question: str = Field(min_length=1, max_length=500)


class AskRegnovaQueryResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    question: str
    question_class: str
    intent: str
    params: dict[str, Any]
    confidence: float
    model_identifier: str
    prompt_version: str

    # structured_result is the ground truth for the shipped intents -
    # see CLAUDE.md "Ask RegNova" point 2. narrative is code-templated
    # prose describing it, never independently computed.
    structured_result: dict[str, Any] | None
    sources: list[Any]
    narrative: str

    degraded: bool
    degraded_reason: str | None

    created_at: datetime
