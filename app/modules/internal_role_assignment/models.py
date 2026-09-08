from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.mixins.timestamp import TimestampMixin
from app.shared.mixins.uuid import UUIDMixin


class InternalRoleCode(str, Enum):
    """
    RegNova's four operational internal roles (B2) plus
    REGULATORY_KNOWLEDGE_LEAD as its own fifth code (FR-13 treats it as
    a distinct actor from Platform Admin, not a scoped variant of it -
    putting the most sensitive capability, regulatory content authoring,
    on the most restricted role would invert A4's own intent that
    Platform Admin "cannot alter regulatory decisions without a
    regulated role"). A different axis of authority from Role/role_id's
    Employee/Manager/Admin tenant-zero hierarchy - not orderable, not
    reused from that model.
    """

    RA = "RA"
    SENIOR_REVIEWER = "SENIOR_REVIEWER"
    SUBMISSION_OPERATIONS = "SUBMISSION_OPERATIONS"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    REGULATORY_KNOWLEDGE_LEAD = "REGULATORY_KNOWLEDGE_LEAD"
    # Drafts Source/Requirement/Rule content (visible but inert) but
    # cannot verify or activate it - that stays REGULATORY_KNOWLEDGE_LEAD
    # only. Deliberately NOT `RA`, despite the superficial name overlap:
    # RA's authority is assessment-side (Finding review), never content
    # authoring - see require_regulatory_content_writer's own docstring.
    # A new code, not a scope on PLATFORM_ADMIN or REGULATORY_KNOWLEDGE_LEAD,
    # for the same reason REGULATORY_KNOWLEDGE_LEAD itself got its own
    # code rather than riding on PLATFORM_ADMIN's scope list. See
    # CLAUDE.md "Regulatory content approval workflow".
    REGULATORY_CONTENT_ADVISOR = "REGULATORY_CONTENT_ADVISOR"
    # Strictly read-only - grants no write/decision authority anywhere
    # in this codebase, unlike every other internal role. Added for
    # FR-14's own "auditor" actor, which had no home in this model:
    # every other code grants some action authority (content authoring,
    # finding review, technical operations); AUDITOR grants only
    # cross-tier, cross-organization READ access to the audit log (see
    # AuditService._resolve_internal_tier_grants) - see CLAUDE.md
    # "Audit log: audit_event, tier/redaction, query surface".
    AUDITOR = "AUDITOR"


class InternalRoleAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    # A newer assignment for the same (user, role_code) - a scope or
    # role change - was approved, replacing this one. Not the same as
    # REJECTED (this one WAS in force) or REVOKED (this one wasn't
    # withdrawn, it was superseded by a fresh grant).
    SUPERSEDED = "SUPERSEDED"


_JSON = JSON().with_variant(JSONB(), "postgresql")


class InternalRoleAssignment(
    UUIDMixin,
    TimestampMixin,
    Base,
):
    """
    HR proposes a role assignment (person + scope as one package); only
    the CEO (User.is_permanent_admin) approves - two distinct persisted
    steps on one row's lifecycle (PROPOSED -> APPROVED/REJECTED), not
    one atomic action, matching this codebase's own established
    versioned-entity pattern (RequirementVersion/RuleVersion/
    SourceVersion: created in one state, transitioned by a separate
    later write). Field shape reuses D6.1's Approval object vocabulary
    narrowly (approver identity, decision, rationale, timestamp,
    expiry/revocation behavior, content hash) rather than building a
    generic polymorphic Approval entity for all of D6's approval
    matrix - that's separate, larger, future scope.

    See CLAUDE.md "Internal role model" for the full reasoning behind
    every field/decision here, including what's deliberately deferred.
    """

    __tablename__ = "internal_role_assignments"

    __table_args__ = (
        Index("ix_internal_role_assignments_user_id", "user_id"),
        Index("ix_internal_role_assignments_role_code", "role_code"),
        Index("ix_internal_role_assignments_status", "status"),
    )

    # Structurally required to be a tenant-zero User (enforced in
    # InternalRoleAssignmentService, not here - see CLAUDE.md) - RESTRICT
    # rather than CASCADE/SET NULL, since a User with assignment history
    # shouldn't be deletable out from under that governance record.
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    role_code: Mapped[str] = mapped_column(String(50), nullable=False)

    # Only meaningful for PLATFORM_ADMIN - a technical qualifier
    # (infrastructure/security/config areas), never a regulatory-
    # authority elevation; REGULATORY_KNOWLEDGE_LEAD exists as its own
    # role_code precisely so that capability never rides on this list.
    # Extensible list, not a hardcoded two-value enum - open string
    # values inside, same "needs real definition before constraining"
    # precedent as obligation_type/verification_level. No concrete
    # scope value is exercised by any check in this pass; the attribute
    # exists so PLATFORM_ADMIN can be subdivided later without a
    # migration.
    scope: Mapped[list[Any] | None] = mapped_column(_JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=InternalRoleAssignmentStatus.PROPOSED.value,
    )

    # --- Proposal ("HR" - see CLAUDE.md for the require_admin
    # placeholder framing; no HR actor-type exists in RBAC yet) ---

    proposed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Decision (CEO only - User.is_permanent_admin) ---

    approver_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    decision_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SHA-256 over {user_id, role_code, scope} at proposal time (D6.1:
    # "content hash... editing approved content invalidates or
    # supersedes the approval; it does not silently carry forward") -
    # there is no edit path for those three fields after creation in
    # this pass (a scope/role change always creates a new row, see
    # superseded_by_id), so this is currently an integrity marker with
    # no exercised edit-detection path yet, not a placeholder - it's
    # real, computed, and stored every time.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- Revocation proposal (same propose/approve shape as the grant
    # itself) - except the CEO, who may call revoke() directly and
    # bypass this pair entirely. ---

    revocation_proposed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    revocation_proposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    revocation_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Revocation decision (terminal) ---

    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # D6.1's "expiry... behavior" - column exists, nothing sets or
    # checks it this pass. Flagged deferred, not silently absent.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("internal_role_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
