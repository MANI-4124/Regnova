from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Float, ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins import TimestampMixin, UUIDMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class AskRegnovaQuery(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    One row per question asked - the "universal execution ledger" for
    Ask RegNova, the same role StepRun plays for the assessment engine
    (CLAUDE.md "Assessment engine"). Not an OutboxEvent/AuditEvent: those
    are for domain STATE CHANGES, and answering a question changes
    nothing - this is a request/response record, immutable once written
    (never updated in place, same as FindingRevision/AuditEvent).

    Records the full classification, not just the final answer, so a
    misrouted or degraded question is diagnosable after the fact without
    re-asking it: question_class/intent/confidence/model_identifier/
    prompt_version are what the classifier ACTUALLY returned, even when
    `degraded` is true because the confidence was too low to act on or
    the intent isn't built yet - see CLAUDE.md "Ask RegNova".
    """

    __tablename__ = "ask_regnova_queries"

    __table_args__ = (
        Index("ix_ask_regnova_queries_organization_id", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # As classified, verbatim - see the class docstring above for why
    # this is recorded even on a degraded answer.
    question_class: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    intent: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="",
    )

    params: Mapped[dict[str, Any]] = mapped_column(
        _JSON,
        nullable=False,
        default=dict,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # "stub"/"noop"-shaped defaults when the classifier never ran for
    # real, same convention as StubSemanticAnalyzer/StubQueryClassifier's
    # own canned model_identifier="stub".
    model_identifier: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    prompt_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # The real, code-computed answer for a shipped intent - e.g.
    # {"count": 3, "products": [...]}. Null for a degraded response
    # (nothing was computed). This, not `narrative`, is what any
    # consuming UI should treat as ground truth - see CLAUDE.md
    # "Ask RegNova" point 2.
    structured_result: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    # Source citations assembled server-side from real rows a handler
    # fetched (RequirementVersion.authority_interpretation_label,
    # SourceLocation coordinates, SourceVersion tier/title) - never
    # composed by the model. Empty list when the answer cites nothing
    # (e.g. a pure count).
    sources: Mapped[list[Any]] = mapped_column(
        _JSON,
        nullable=False,
        default=list,
    )

    # Code-templated from structured_result for every shipped intent in
    # this pass (see CLAUDE.md "Ask RegNova" - no second, narration-
    # generating LLM call is built here). Kept as a plain string column
    # rather than re-derived at read time so a historical query's
    # rendered answer never silently changes if a template's wording
    # changes later.
    narrative: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    degraded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # One of: low_confidence, unsupported, not_yet_supported, or a
    # QueryClassificationUnavailable reason verbatim (not_configured,
    # organization_not_synthetic, question_too_long, timeout,
    # http_error, unparseable_response, schema_invalid) - see
    # service.py. Null when degraded is False.
    degraded_reason: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
