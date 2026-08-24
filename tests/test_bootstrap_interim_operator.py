from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bootstrap_interim_operator import (  # noqa: E402
    BootstrapConflict,
    _INTERIM_RATIONALE,
    bootstrap,
)

from app.modules.auth.jwt import create_access_token  # noqa: E402
from app.modules.internal_role_assignment.models import InternalRoleCode  # noqa: E402
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository  # noqa: E402

# Synthetic test-only identity - never the real operator's email/password.
# This file is exactly the fixture-independence check the script's own
# CLAUDE.md entry promises: no test anywhere depends on any real account.
_EMAIL = "interim-operator@example.test"
_PASSWORD = "TestPassword123!"


def _run(db, email=_EMAIL, password=_PASSWORD, first_name="Interim", last_name="Operator"):
    return bootstrap(
        db,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        org_name="RegNova",
        org_industry="Regulatory Technology",
        org_country="US",
    )


def test_bootstrap_creates_org_ceo_and_grant(db):
    user = _run(db)

    assert user.is_permanent_admin is True
    assert user.email == _EMAIL

    assignment = InternalRoleAssignmentRepository(db).get_active_for_user_role(
        user.id, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
    )
    assert assignment is not None
    assert assignment.status == "APPROVED"
    assert assignment.rationale == _INTERIM_RATIONALE
    assert "INTERIM SINGLE-OPERATOR ARRANGEMENT" in assignment.rationale
    assert assignment.decision_rationale == _INTERIM_RATIONALE
    # Self-proposed, self-decided - the one account acting as its own
    # "HR" and "CEO", exactly because there is no one else yet.
    assert assignment.proposed_by_user_id == user.id
    assert assignment.approver_user_id == user.id


def test_bootstrap_is_idempotent(db):
    first = _run(db)
    second = _run(db)

    assert second.id == first.id

    assignments = InternalRoleAssignmentRepository(db).get_all()
    grants = [
        a for a in assignments
        if a.user_id == first.id and a.role_code == InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value
    ]
    assert len(grants) == 1


def test_bootstrap_refuses_to_move_permanent_admin_to_a_different_email(db):
    _run(db, email=_EMAIL)

    with pytest.raises(BootstrapConflict):
        _run(db, email="someone-else@example.test")


def test_bootstrap_refuses_email_collision_with_a_customer_org_user(db, tenant_a):
    with pytest.raises(BootstrapConflict):
        _run(db, email=tenant_a["user"].email)


def test_bootstrapped_account_can_create_a_source_via_the_api(client, db):
    """
    End-to-end sanity check, mirroring
    test_seed_regulatory_sources.py::test_seeded_versions_are_readable_via_the_api -
    the bootstrapped account must actually be able to exercise
    require_regulatory_content_writer through the real HTTP path, not
    just satisfy the service-layer checks in isolation.
    """
    user = _run(db)

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(user.organization_id),
            "role_id": str(user.role_id),
        },
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post("/sources", headers=headers)
    assert response.status_code == 200
