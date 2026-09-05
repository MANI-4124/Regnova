"""
One-time bootstrap script that stands up the very first RegNova-internal
account so the internal role model isn't a chicken-and-egg problem: there
is no HR actor-type and no second internal user yet to propose/approve a
grant for anyone, including the person setting this codebase up.

This script:
  1. Finds or creates the tenant-zero Organization (Organization.is_internal).
  2. Finds or creates one User inside it, identified by --email.
  3. Marks that user User.is_permanent_admin (the "CEO" seat).
  4. Grants that same user an APPROVED REGULATORY_KNOWLEDGE_LEAD
     InternalRoleAssignment, so Source/Requirement/Rule/RegulatoryBasisRelease
     writes work end-to-end through the running API.

Every assignment this script creates is self-proposed and self-decided (the
one account acting as its own "HR" and "CEO") and carries a rationale that
says so explicitly - see _INTERIM_RATIONALE below. This is NOT the real
HR-propose/CEO-approve workflow; it exists only because there is exactly one
internal operator right now. See CLAUDE.md's "Internal role model" known
limitations for what unblocks reassigning this properly.

No identity is hardcoded here - every identifying value is a required CLI
argument. Uses the service layer directly (bypasses HTTP/RBAC entirely),
same convention as scripts/seed_regulatory_sources.py.

Convention this script deliberately does NOT follow, and why: the CEO seat
this script bootstraps is tied to a real person's identity on purpose -
User.is_permanent_admin has no succession path (see CLAUDE.md), so a
placeholder could never legitimately hold it. For every other
InternalRoleCode (RA, SENIOR_REVIEWER, SUBMISSION_OPERATIONS,
PLATFORM_ADMIN, REGULATORY_CONTENT_ADVISOR - REGULATORY_KNOWLEDGE_LEAD is
covered by this script's own interim dual-hat grant above), the intended
convention once they're first needed is the OPPOSITE: a role-named
placeholder account (e.g. regulatory_advisor, senior_reviewer,
submission_ops, platform_admin, regulatory_content_advisor), never a real
person's identity. regulatory_advisor (RA, assessment-side Finding review)
and regulatory_content_advisor (REGULATORY_CONTENT_ADVISOR, content
drafting - see CLAUDE.md "Regulatory content approval workflow") are
deliberately spelled differently despite the name overlap, for the same
reason those two role codes stayed distinct rather than being merged. When
a real hire joins, they get a NEW account with the role granted through
the normal propose/approve flow, and the placeholder is deactivated -
never renamed into the real person, since that would retroactively
attribute the placeholder's prior actions to someone who wasn't there. No
script creates these placeholder accounts
yet; recorded here (see also CLAUDE.md's "Internal role model") as the
decided convention, not a design still open.

Idempotent: safe to re-run. Refuses (does not silently override) if the
permanent-admin seat or the tenant-zero organization already belongs to a
different identity than the one you pass in - see the error messages.

Run against a real (non-SQLite) database once DATABASE_URL points to one,
from the backend/ directory:

    python scripts/bootstrap_interim_operator.py \\
        --email you@example.com \\
        --password 'a-real-password' \\
        --first-name Jane \\
        --last-name Doe

Optional: --org-name (default "RegNova"), --org-industry (default
"Regulatory Technology"), --org-country (default "US") - only used the
first time, when the tenant-zero organization doesn't exist yet.
"""

from __future__ import annotations

import argparse

from app.core.database import build_database
from app.core.settings import get_settings
from app.modules.auth.security import hash_password
from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.internal_role_assignment.service import InternalRoleAssignmentService
from app.modules.organization.models import Organization
from app.modules.organization.repository import OrganizationRepository
from app.modules.role.models import Role
from app.modules.user.models import User
from app.modules.user.repository import UserRepository

_INTERIM_RATIONALE = (
    "INTERIM SINGLE-OPERATOR ARRANGEMENT, not a considered regulatory-"
    "authority grant: this account was bootstrapped as RegNova's tenant-"
    "zero permanent admin and REGULATORY_KNOWLEDGE_LEAD via "
    "scripts/bootstrap_interim_operator.py because no HR actor-type and no "
    "second internal operator exist yet to run the real propose/approve "
    "workflow. Reassign through that real workflow once one does - see "
    "CLAUDE.md 'Internal role model' known limitations."
)


class BootstrapConflict(Exception):
    """Raised when this script would have to silently override an
    existing, different identity's grant - refused on purpose."""


def bootstrap(
    db,
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    org_name: str,
    org_industry: str,
    org_country: str,
) -> User:
    organizations = OrganizationRepository(db)

    organization = organizations.get_internal()
    if organization is None:
        organization = Organization(
            name=org_name,
            industry=org_industry,
            country=org_country,
            is_internal=True,
        )
        db.add(organization)
        db.flush()
        print(f"created tenant-zero organization {organization.id} ({organization.name!r})")
    else:
        print(f"reusing existing tenant-zero organization {organization.id} ({organization.name!r})")

    role = (
        db.query(Role)
        .filter(Role.organization_id == organization.id, Role.code == "ADMIN")
        .first()
    )
    if role is None:
        role = Role(organization_id=organization.id, code="ADMIN", name="Admin")
        db.add(role)
        db.flush()

    users = UserRepository(db)
    existing_by_email = users.get_by_email_global(email)

    if existing_by_email is not None and existing_by_email.organization_id != organization.id:
        raise BootstrapConflict(
            f"A user with email {email!r} already exists in a different, "
            f"non-tenant-zero organization ({existing_by_email.organization_id}). "
            "An internal role can never be granted to a customer-org account "
            "(see InternalRoleAssignmentService._require_internal_user) - use "
            "a different email for the internal account, or resolve the "
            "collision manually."
        )

    if existing_by_email is not None:
        user = existing_by_email
        print(f"reusing existing tenant-zero user {user.id} ({user.email})")
    else:
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.flush()
        print(f"created tenant-zero user {user.id} ({user.email})")

    existing_ceo = db.query(User).filter(User.is_permanent_admin.is_(True)).first()
    if existing_ceo is not None and existing_ceo.id != user.id:
        raise BootstrapConflict(
            f"User {existing_ceo.id} ({existing_ceo.email}) already holds the "
            "permanent-admin seat. uq_users_single_permanent_admin allows at "
            "most one; this script will not silently move it. If this is a "
            "genuine handover, that's a manual DB operation, not something "
            "this script does implicitly (see CLAUDE.md - no API/script "
            "succession path exists on purpose)."
        )

    if not user.is_permanent_admin:
        user.is_permanent_admin = True
        db.add(user)
        print(f"marked {user.email} as permanent admin")
    else:
        print(f"{user.email} is already the permanent admin")

    db.commit()
    db.refresh(user)

    assignments = InternalRoleAssignmentRepository(db)
    active = assignments.get_active_for_user_role(
        user.id, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
    )
    if active is not None:
        print(f"{user.email} already holds an active REGULATORY_KNOWLEDGE_LEAD assignment ({active.id})")
        return user

    service = InternalRoleAssignmentService(db)
    proposal = service.propose(
        user_id=user.id,
        role_code=InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
        scope=None,
        proposed_by_user_id=user.id,
        rationale=_INTERIM_RATIONALE,
    )
    decision = service.decide(
        assignment_id=proposal.id,
        approver_user_id=user.id,
        approve=True,
        decision_rationale=_INTERIM_RATIONALE,
    )
    print(f"granted REGULATORY_KNOWLEDGE_LEAD to {user.email} ({decision.id}, status={decision.status})")

    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--org-name", default="RegNova")
    parser.add_argument("--org-industry", default="Regulatory Technology")
    parser.add_argument("--org-country", default="US")
    args = parser.parse_args()

    settings = get_settings()
    database = build_database(settings)
    session = database.session_factory()

    try:
        bootstrap(
            session,
            email=args.email,
            password=args.password,
            first_name=args.first_name,
            last_name=args.last_name,
            org_name=args.org_name,
            org_industry=args.org_industry,
            org_country=args.org_country,
        )
    except BootstrapConflict as exc:
        session.rollback()
        raise SystemExit(f"refusing to proceed: {exc}") from None
    finally:
        session.close()


if __name__ == "__main__":
    main()
