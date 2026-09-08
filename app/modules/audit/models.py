from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class OutboxEvent(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    Transactional outbox row: one schema-versioned domain event fact,
    written in the same transaction as the domain change that caused it.
    """

    __tablename__ = "outbox_events"

    __table_args__ = (
        Index(
            "ix_outbox_events_dispatch",
            "published_at",
            "created_at",
        ),
        Index(
            "ix_outbox_events_organization_id",
            "organization_id",
        ),
        Index(
            "ix_outbox_events_event_type",
            "event_type",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


class AuditVisibilityTier(str, Enum):
    """
    FR-14's three tiers. CUSTOMER_VISIBLE and INTERNAL_REGULATORY nest
    (an internal-regulatory reader sees both); TECHNICAL_SECURITY is a
    deliberately separate, non-nested category, not "above" the other
    two - a security/ops event isn't more-privileged regulatory
    content, it's a different kind of content a Regulatory Knowledge
    Lead has no reason to see bundled into their queue. See CLAUDE.md
    "Audit log" for the reasoning and the flagged alternative (a strict
    three-level hierarchy) this rejected.
    """

    CUSTOMER_VISIBLE = "CUSTOMER_VISIBLE"
    INTERNAL_REGULATORY = "INTERNAL_REGULATORY"
    TECHNICAL_SECURITY = "TECHNICAL_SECURITY"


class AuditEvent(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    FR-14's append-only, queryable compliance record - the durable
    read-side of the outbox, not the outbox itself (C14's "Consumers
    store processed event IDs for idempotency" applies here exactly the
    way it already does for `notification`). See CLAUDE.md "Audit log"
    for the full reasoning: why this is a consumer rather than a
    parallel write or a projection over OutboxEvent, why it needs its
    own retention story, and the tier/redaction design.

    Never updated or deleted by any service method - immutable by
    construction, the second entity in this codebase for which that's
    true (the first is FindingRevision). This is the weaker,
    "no code path mutates it" guarantee, not literal cryptographic
    tamper-evidence (a hash chain, WORM storage) - C15's "tamper-evident
    retention" language reads as wanting the stronger claim, which this
    pass does not build; named as a deferred enhancement, not silently
    assumed satisfied.

    Copies everything it needs from the source OutboxEvent at ingestion
    time rather than reading through source_event_id later - the outbox
    is prunable delivery plumbing (see CLAUDE.md "Known limitations"),
    the audit record is the compliance record and must survive that
    pruning intact.
    """

    __tablename__ = "audit_events"

    __table_args__ = (
        Index("ix_audit_events_organization_id", "organization_id"),
        Index("ix_audit_events_product_id", "product_id"),
        Index("ix_audit_events_product_market_state_id", "product_market_state_id"),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_visibility_tier", "visibility_tier"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )

    # RESTRICT, not CASCADE like OutboxEvent - a deliberate divergence.
    # Organization deletion is a real, existing endpoint
    # (DELETE /organizations/{id}) that already hard-deletes and already
    # cascades OutboxEvent; letting it also cascade AuditEvent would
    # silently destroy a customer's entire compliance history on
    # offboarding, directly against C15's "audit/security records...
    # may outlive user accounts". Enforced at the DB level (Postgres)
    # AND at the service layer (OrganizationService.delete(), via
    # AuditEventRepository.exists_for_organization) - SQLite in this
    # test suite does not enforce foreign keys at all, so the DB-level
    # constraint alone would be untestable here; the service-layer
    # pre-check is what actually makes this real and verified in this
    # codebase's own test suite, not just documented intent.
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    # Nullable + SET NULL + UNIQUE: the dedup key for at-least-once
    # outbox redelivery (see AuditService.record_for_event), but never
    # required to still resolve - null for the direct-write "someone
    # queried the audit log" meta-entries (see AuditService._record_
    # cross_org_query), which have no corresponding OutboxEvent at all.
    source_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "outbox_events.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        unique=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    # The domain-write moment (copied from OutboxEvent.created_at at
    # ingestion), deliberately NOT this row's own created_at - dispatch
    # is asynchronous in principle (even though nothing currently runs
    # it on a schedule), so the two can legitimately differ. AC-FR-14-01
    # reconstruction needs the real moment the change occurred.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # Extracted per event_type by the builder registry (see
    # AUDIT_BUILDERS) - OutboxEvent itself carries no product_id column,
    # only organization_id. Nullable: plenty of audited facts (workspace/
    # membership/content-review events) aren't product-scoped at all.
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "products.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    product_market_state_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "product_market_states.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    visibility_tier: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    # Redaction-safe for `visibility_tier` and any broader-clearance
    # reader - always returned to whoever is allowed to see this row at
    # all.
    payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON,
        nullable=False,
    )

    # Additional detail visible ONLY to internal-regulatory/technical-
    # security readers, regardless of this row's own visibility_tier -
    # the per-FIELD half of the tier design (see CLAUDE.md "Audit log").
    # A static split decided once by the builder at ingestion, not a
    # redaction function computed per request - easier to verify once
    # and keep verified than logic re-audited on every read.
    internal_payload: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON,
        nullable=True,
    )

    # Inert in V1 - no job reads or enforces this yet, matching this
    # codebase's own repeated "add the column a future mechanism will
    # need now, without pretending to enforce it" precedent
    # (InternalRoleAssignment.expires_at is the direct one). C15 calls
    # for "configurable retention classes", not a hard-coded period;
    # this is the field a real retention-enforcement job would key off,
    # whenever one exists.
    retention_class: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="STANDARD",
    )
