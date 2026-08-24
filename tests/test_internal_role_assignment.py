from __future__ import annotations

from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.organization.models import Organization
from app.modules.role.models import Role
from app.modules.user.models import User


def _get_or_create_tenant_zero(db):
    organization = (
        db.query(Organization).filter(Organization.is_internal.is_(True)).first()
    )
    if organization is None:
        organization = Organization(
            name="RegNova",
            industry="Regulatory Technology",
            country="US",
            is_internal=True,
        )
        db.add(organization)
        db.flush()
    return organization


def _make_org_user(db, organization, role_code, label):
    """
    Plain org-scoped User + Role, no InternalRoleAssignment - the axis
    require_admin/require_manager/require_employee check, independent
    of the internal-role-code axis this module adds. Reuses an existing
    Role for this (org, code) rather than inserting a duplicate - Role
    has a uq_role_code_per_org constraint, and some tests call this
    against an org (e.g. tenant_a) that already has one.
    """
    role = (
        db.query(Role)
        .filter(Role.organization_id == organization.id, Role.code == role_code)
        .first()
    )
    if role is None:
        role = Role(organization_id=organization.id, code=role_code, name=f"{role_code} {label}")
        db.add(role)
        db.flush()

    user = User(
        organization_id=organization.id,
        role_id=role.id,
        first_name="Test",
        last_name=label,
        email=f"{label.lower()}-{role_code.lower()}@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(organization.id),
            "role_id": str(role.id),
        },
    )
    return {
        "organization": organization,
        "role": role,
        "user": user,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _tenant_zero_admin(db, label="HR"):
    """
    An ADMIN-role user inside tenant-zero - passes require_admin AND the
    service layer's tenant-zero check, so it can act as the "HR"
    proposer this module's require_admin placeholder stands in for.
    """
    organization = _get_or_create_tenant_zero(db)
    return _make_org_user(db, organization, "ADMIN", label)


def _tenant_zero_staff(db, label="Staff"):
    """A plain (non-ADMIN) tenant-zero user - a valid propose target."""
    organization = _get_or_create_tenant_zero(db)
    return _make_org_user(db, organization, "EMPLOYEE", label)


def _second_admin_same_org(db, tenant, label="Other"):
    """
    A second ADMIN in tenant's own org, reusing its existing ADMIN role
    (uq_role_code_per_org forbids a second ADMIN Role row per org).
    """
    user = User(
        organization_id=tenant["organization"].id,
        role_id=tenant["role"].id,
        first_name="Test",
        last_name=label,
        email=f"{label.lower()}-admin@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(tenant["organization"].id),
            "role_id": str(tenant["role"].id),
        },
    )
    return {"user": user, "headers": {"Authorization": f"Bearer {token}"}}


def _make_ceo(db, tenant, label="CEO"):
    """
    Marks an existing tenant's own user as the permanent admin
    (is_permanent_admin is DB-only settable - no API path, by design).
    Reuses `tenant`'s own user/org/headers so the CEO and "another
    admin" tests below can share one organization.
    """
    tenant["user"].is_permanent_admin = True
    db.add(tenant["user"])
    db.commit()
    return tenant


def _propose(client, proposer, user_id, role_code, scope=None, rationale="test"):
    response = client.post(
        "/internal-role-assignments",
        json={"user_id": str(user_id), "role_code": role_code, "scope": scope, "rationale": rationale},
        headers=proposer["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _decide(client, ceo, assignment_id, approve, rationale="approved"):
    response = client.post(
        f"/internal-role-assignments/{assignment_id}/decide",
        json={"approve": approve, "decision_rationale": rationale},
        headers=ceo["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_assignment(client, reader, assignment_id):
    response = client.get(
        f"/internal-role-assignments/{assignment_id}",
        headers=reader["headers"],
    )
    assert response.status_code == 200
    return response.json()


# --- (a) Customer-org accounts can never hold an internal role -------------


def test_propose_rejects_customer_org_proposer(client, db, tenant_a):
    """
    tenant_a's admin passes require_admin (the router-level placeholder)
    but is not tenant-zero staff - the service layer must still reject it.
    """
    staff = _tenant_zero_staff(db)

    response = client.post(
        "/internal-role-assignments",
        json={
            "user_id": str(staff["user"].id),
            "role_code": "RA",
            "scope": None,
            "rationale": "attempted by a customer-org admin",
        },
        headers=tenant_a["headers"],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TARGET_USER_NOT_INTERNAL"


def test_propose_rejects_customer_org_target(client, db, tenant_a):
    """
    Even a genuine tenant-zero HR proposer cannot grant an internal role
    to a customer-org user_id.
    """
    hr = _tenant_zero_admin(db)

    response = client.post(
        "/internal-role-assignments",
        json={
            "user_id": str(tenant_a["user"].id),
            "role_code": "RA",
            "scope": None,
            "rationale": "attempted target is a customer-org user",
        },
        headers=hr["headers"],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TARGET_USER_NOT_INTERNAL"


# --- (b) The CEO seat structurally resists mutation, even by another admin -


def test_ceo_resists_role_change_from_another_admin(client, db, tenant_a):
    ceo = _make_ceo(db, tenant_a)
    other_admin = _second_admin_same_org(db, tenant_a)
    other_role = Role(organization_id=tenant_a["organization"].id, code="MANAGER", name="Manager")
    db.add(other_role)
    db.commit()

    response = client.put(
        f"/users/{ceo['user'].id}",
        json={"role_id": str(other_role.id)},
        headers=other_admin["headers"],
    )
    assert response.status_code == 409
    assert "permanently protected" in response.json()["error"]["message"]


def test_ceo_resists_deactivation_from_another_admin(client, db, tenant_a):
    ceo = _make_ceo(db, tenant_a)
    other_admin = _second_admin_same_org(db, tenant_a)

    response = client.put(
        f"/users/{ceo['user'].id}",
        json={"is_active": False},
        headers=other_admin["headers"],
    )
    assert response.status_code == 409
    assert "permanently protected" in response.json()["error"]["message"]


def test_ceo_resists_deletion_from_another_admin(client, db, tenant_a):
    ceo = _make_ceo(db, tenant_a)
    other_admin = _second_admin_same_org(db, tenant_a)

    response = client.delete(
        f"/users/{ceo['user'].id}",
        headers=other_admin["headers"],
    )
    assert response.status_code == 409
    assert "permanently protected" in response.json()["error"]["message"]


# --- (c) Proposing never suspends an existing grant -------------------------


def test_pending_scope_change_proposal_does_not_suspend_existing_grant(client, db, tenant_a):
    hr = _tenant_zero_admin(db)
    ceo = _make_ceo(db, tenant_a)
    target = _tenant_zero_staff(db, "PlatformAdmin")

    first = _propose(client, hr, target["user"].id, "PLATFORM_ADMIN", scope=["infra"])
    first = _decide(client, ceo, first["id"], approve=True)
    assert first["status"] == "APPROVED"

    second = _propose(client, hr, target["user"].id, "PLATFORM_ADMIN", scope=["infra", "security"])
    assert second["status"] == "PROPOSED"

    # The original grant must still be in force while the scope-change
    # proposal is merely pending - proposing must never suspend access.
    still_first = _get_assignment(client, tenant_a, first["id"])
    assert still_first["status"] == "APPROVED"
    assert still_first["superseded_by_id"] is None


def test_approving_scope_change_supersedes_prior_grant(client, db, tenant_a):
    hr = _tenant_zero_admin(db)
    ceo = _make_ceo(db, tenant_a)
    target = _tenant_zero_staff(db, "PlatformAdmin2")

    first = _propose(client, hr, target["user"].id, "PLATFORM_ADMIN", scope=["infra"])
    first = _decide(client, ceo, first["id"], approve=True)

    second = _propose(client, hr, target["user"].id, "PLATFORM_ADMIN", scope=["infra", "security"])
    second = _decide(client, ceo, second["id"], approve=True)
    assert second["status"] == "APPROVED"

    superseded_first = _get_assignment(client, tenant_a, first["id"])
    assert superseded_first["status"] == "SUPERSEDED"
    assert superseded_first["superseded_by_id"] == second["id"]


def test_propose_revocation_does_not_suspend_existing_grant(client, db, tenant_a):
    hr = _tenant_zero_admin(db)
    ceo = _make_ceo(db, tenant_a)
    target = _tenant_zero_staff(db, "RaReviewer")

    assignment = _propose(client, hr, target["user"].id, "RA")
    assignment = _decide(client, ceo, assignment["id"], approve=True)

    response = client.post(
        f"/internal-role-assignments/{assignment['id']}/propose-revocation",
        json={"rationale": "role no longer needed"},
        headers=hr["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"

    still_active = _get_assignment(client, tenant_a, assignment["id"])
    assert still_active["status"] == "APPROVED"


# --- CEO-only unilateral revocation -----------------------------------------


def test_revoke_requires_ceo(client, db, tenant_a):
    hr = _tenant_zero_admin(db)
    ceo = _make_ceo(db, tenant_a)
    target = _tenant_zero_staff(db, "RaReviewer2")

    assignment = _propose(client, hr, target["user"].id, "RA")
    assignment = _decide(client, ceo, assignment["id"], approve=True)

    response = client.post(
        f"/internal-role-assignments/{assignment['id']}/revoke",
        json={"reason": "not the CEO"},
        headers=hr["headers"],
    )
    assert response.status_code == 403


def test_ceo_can_revoke_unilaterally(client, db, tenant_a):
    hr = _tenant_zero_admin(db)
    ceo = _make_ceo(db, tenant_a)
    target = _tenant_zero_staff(db, "RaReviewer3")

    assignment = _propose(client, hr, target["user"].id, "RA")
    assignment = _decide(client, ceo, assignment["id"], approve=True)

    response = client.post(
        f"/internal-role-assignments/{assignment['id']}/revoke",
        json={"reason": "role no longer needed"},
        headers=ceo["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REVOKED"


# --- (d) require_regulatory_content_writer actually gates content writes ---


def test_require_regulatory_content_writer_rejects_non_writer(client, db, tenant_a):
    hr = _tenant_zero_admin(db)  # tenant-zero, but no REGULATORY_KNOWLEDGE_LEAD grant

    response = client.post("/sources", headers=hr["headers"])
    assert response.status_code == 403

    response = client.post("/requirements", json={}, headers=hr["headers"])
    assert response.status_code == 403

    response = client.post("/rules", json={}, headers=hr["headers"])
    assert response.status_code == 403

    response = client.post(
        "/regulatory-basis-releases",
        json={"jurisdiction": "Malaysia", "market": "Malaysia"},
        headers=hr["headers"],
    )
    assert response.status_code == 403


def test_require_regulatory_content_writer_allows_assigned_writer(client, regulatory_content_writer):
    response = client.post("/sources", headers=regulatory_content_writer["headers"])
    assert response.status_code == 200

    response = client.post("/requirements", json={}, headers=regulatory_content_writer["headers"])
    assert response.status_code == 200

    response = client.post("/rules", json={}, headers=regulatory_content_writer["headers"])
    assert response.status_code == 200
