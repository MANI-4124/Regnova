from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class MarketReadinessRunCreate(BaseModel):

    product_market_state_id: UUID

    # Same dimension-keyed shape as AssessmentRunCreate.input_facts, but
    # every key is optional here (Market Readiness attempts all eight
    # canonical dimensions regardless of what's supplied). Including a
    # dimension's key at all - even with an empty facts dict - is an
    # explicit signal to (re)run that dimension this call rather than
    # reuse a prior result; see CLAUDE.md "Market readiness".
    input_facts: dict[str, Any] = {}
