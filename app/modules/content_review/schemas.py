from __future__ import annotations

from pydantic import BaseModel, Field


class ContentVersionTransitionRequest(BaseModel):
    """
    Body for verify/activate/reject - D6.1's rationale requirement,
    enforced as a required, non-empty field rather than the freely
    optional `notes` the old generic PATCH allowed.
    """

    rationale: str = Field(min_length=1)
