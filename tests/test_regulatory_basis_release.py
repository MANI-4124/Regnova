from __future__ import annotations

import uuid

from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.role.models import Role
from app.modules.user.models import User


def _non_admin_headers(db, tenant):
    """
    Same pattern as test_source.py/test_requirement.py/test_rule.py - a
    role that passes require_employee but fails require_admin.
    """
    role = Role(
        organization_id=tenant["organization"].id,
        code="EMPLOYEE",
        name="Employee",
    )
    db.add(role)
    db.flush()

    user = User(
        organization_id=tenant["organization"].id,
        role_id=role.id,
        first_name="Non",
        last_name="Admin",
        email="non.admin@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(tenant["organization"].id),
            "role_id": str(role.id),
        },
    )

    return {"Authorization": f"Bearer {token}"}


def _create_source_version(client, tenant, **overrides):
    source_resp = client.post("/sources", headers=tenant["headers"])
    assert source_resp.status_code == 200
    source = source_resp.json()

    payload = {
        "title": "Test Source",
        "issuing_authority": "Test Authority",
        "jurisdiction": "Malaysia",
        "tier": 1,
        "source_type": "OFFICIAL_GUIDELINE",
    }
    payload.update(overrides)

    version_resp = client.post(
        f"/sources/{source['id']}/versions",
        json=payload,
        headers=tenant["headers"],
    )
    assert version_resp.status_code == 200
    return source, version_resp.json()


def _create_requirement_version(client, tenant, **overrides):
    req_resp = client.post("/requirements", json={}, headers=tenant["headers"])
    assert req_resp.status_code == 200
    requirement = req_resp.json()

    payload = {
        "jurisdiction": "Malaysia",
        "market": "Malaysia",
        "authority": "NPRA",
        "category": "Ingredients",
        "dimension": "INGREDIENTS",
        "obligation_type": "INGREDIENT_CONCENTRATION_LIMIT",
        "canonical_statement": "Mercury and its compounds must not form part of the composition.",
        "default_severity": "CRITICAL",
        "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
    }
    payload.update(overrides)

    version_resp = client.post(
        f"/requirements/{requirement['id']}/versions",
        json=payload,
        headers=tenant["headers"],
    )
    assert version_resp.status_code == 200
    return requirement, version_resp.json()


def _create_rule_version(client, tenant, **overrides):
    rule_resp = client.post("/rules", json={}, headers=tenant["headers"])
    assert rule_resp.status_code == 200
    rule = rule_resp.json()

    payload = {
        "condition": {"op": "lte", "field": "ingredient.concentration_pct", "value": 0.01},
        "output_type": "REQUIREMENT_RESULT",
    }
    payload.update(overrides)

    version_resp = client.post(
        f"/rules/{rule['id']}/versions",
        json=payload,
        headers=tenant["headers"],
    )
    assert version_resp.status_code == 200
    return rule, version_resp.json()


def _activate_source_version(client, tenant, source, version, verified=True):
    body = {"status": "ACTIVE"}
    if verified:
        body["verified_at"] = "2026-01-01T00:00:00Z"
    resp = client.put(
        f"/sources/{source['id']}/versions/{version['id']}",
        json=body,
        headers=tenant["headers"],
    )
    assert resp.status_code == 200
    return resp.json()


def _activate_requirement_version(client, tenant, requirement, version, verified=True):
    body = {"status": "ACTIVE"}
    if verified:
        body["verified_at"] = "2026-01-01T00:00:00Z"
    resp = client.put(
        f"/requirements/{requirement['id']}/versions/{version['id']}",
        json=body,
        headers=tenant["headers"],
    )
    assert resp.status_code == 200
    return resp.json()


def _activate_rule_version(client, tenant, rule, version, verified=True):
    body = {"status": "ACTIVE"}
    if verified:
        body["verified_at"] = "2026-01-01T00:00:00Z"
    resp = client.put(
        f"/rules/{rule['id']}/versions/{version['id']}",
        json=body,
        headers=tenant["headers"],
    )
    assert resp.status_code == 200
    return resp.json()


def _create_eligible_source_version(client, tenant, **overrides):
    source, version = _create_source_version(client, tenant, **overrides)
    return _activate_source_version(client, tenant, source, version)


def _create_release(client, tenant, **overrides):
    payload = {"jurisdiction": "Malaysia", "market": "Malaysia"}
    payload.update(overrides)
    return client.post(
        "/regulatory-basis-releases",
        json=payload,
        headers=tenant["headers"],
    )


def test_create_and_get_release(client, tenant_a):
    source_version = _create_eligible_source_version(client, tenant_a)

    response = _create_release(
        client, tenant_a,
        source_version_ids=[source_version["id"]],
    )
    assert response.status_code == 200
    release = response.json()

    assert release["jurisdiction"] == "Malaysia"
    assert release["status"] == "ACTIVE"
    assert release["source_version_ids"] == [source_version["id"]]
    assert release["content_hash"]

    get_resp = client.get(
        f"/regulatory-basis-releases/{release['id']}",
        headers=tenant_a["headers"],
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == release["id"]


def test_create_release_with_all_three_version_types(client, tenant_a):
    source_version = _create_eligible_source_version(client, tenant_a)

    requirement, requirement_version = _create_requirement_version(client, tenant_a)
    requirement_version = _activate_requirement_version(
        client, tenant_a, requirement, requirement_version,
    )

    rule, rule_version = _create_rule_version(client, tenant_a)
    rule_version = _activate_rule_version(client, tenant_a, rule, rule_version)

    response = _create_release(
        client, tenant_a,
        source_version_ids=[source_version["id"]],
        requirement_version_ids=[requirement_version["id"]],
        rule_version_ids=[rule_version["id"]],
    )
    assert response.status_code == 200
    release = response.json()

    assert release["source_version_ids"] == [source_version["id"]]
    assert release["requirement_version_ids"] == [requirement_version["id"]]
    assert release["rule_version_ids"] == [rule_version["id"]]


def test_create_release_with_ineligible_requirement_version_is_rejected(client, tenant_a):
    requirement, version = _create_requirement_version(client, tenant_a)
    # left in DRAFT

    response = _create_release(
        client, tenant_a,
        requirement_version_ids=[version["id"]],
    )
    assert response.status_code == 409


def test_create_release_with_ineligible_rule_version_is_rejected(client, tenant_a):
    rule, version = _create_rule_version(client, tenant_a)
    # left in DRAFT

    response = _create_release(
        client, tenant_a,
        rule_version_ids=[version["id"]],
    )
    assert response.status_code == 409


def test_update_release_narrow_fields_only(client, tenant_a):
    source_version = _create_eligible_source_version(client, tenant_a)
    release = _create_release(
        client, tenant_a,
        source_version_ids=[source_version["id"]],
    ).json()

    response = client.put(
        f"/regulatory-basis-releases/{release['id']}",
        json={"notes": "reviewed"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["notes"] == "reviewed"


def test_create_release_with_draft_version_is_rejected(client, tenant_a):
    source, version = _create_source_version(client, tenant_a)
    # left in DRAFT - never activated

    response = _create_release(
        client, tenant_a,
        source_version_ids=[version["id"]],
    )
    assert response.status_code == 409


def test_create_release_with_active_but_unverified_version_is_rejected(client, tenant_a):
    """
    The specific gap the verified_at check exists to catch: a version
    PATCHed directly to ACTIVE without ever going through verification
    (nothing currently enforces that ordering - see CLAUDE.md). status
    alone being ACTIVE must not be sufficient for inclusion.
    """
    source, version = _create_source_version(client, tenant_a)
    active_unverified = _activate_source_version(
        client, tenant_a, source, version, verified=False,
    )
    assert active_unverified["status"] == "ACTIVE"
    assert active_unverified["verified_at"] is None

    response = _create_release(
        client, tenant_a,
        source_version_ids=[active_unverified["id"]],
    )
    assert response.status_code == 409


def test_create_release_with_nonexistent_version_id_returns_404(client, tenant_a):
    response = _create_release(
        client, tenant_a,
        source_version_ids=[str(uuid.uuid4())],
    )
    assert response.status_code == 404


def test_create_release_with_bogus_supersedes_id_returns_404(client, tenant_a):
    source_version = _create_eligible_source_version(client, tenant_a)

    response = _create_release(
        client, tenant_a,
        source_version_ids=[source_version["id"]],
        supersedes_id=str(uuid.uuid4()),
    )
    assert response.status_code == 404


def test_second_active_release_for_same_jurisdiction_is_rejected(client, tenant_a):
    version_a = _create_eligible_source_version(client, tenant_a, title="Source A")
    response_a = _create_release(client, tenant_a, source_version_ids=[version_a["id"]])
    assert response_a.status_code == 200

    version_b = _create_eligible_source_version(client, tenant_a, title="Source B")
    response_b = _create_release(client, tenant_a, source_version_ids=[version_b["id"]])
    assert response_b.status_code == 409


def test_supersede_existing_active_release_atomically(client, tenant_a):
    version_a = _create_eligible_source_version(client, tenant_a, title="Source A")
    release_a = _create_release(client, tenant_a, source_version_ids=[version_a["id"]]).json()

    version_b = _create_eligible_source_version(client, tenant_a, title="Source B")
    response_b = _create_release(
        client, tenant_a,
        source_version_ids=[version_b["id"]],
        supersedes_id=release_a["id"],
    )
    assert response_b.status_code == 200
    release_b = response_b.json()

    assert release_b["status"] == "ACTIVE"

    check_a = client.get(
        f"/regulatory-basis-releases/{release_a['id']}",
        headers=tenant_a["headers"],
    )
    assert check_a.status_code == 200
    assert check_a.json()["status"] == "SUPERSEDED"
    assert check_a.json()["superseded_by_id"] == release_b["id"]


def test_active_release_for_different_jurisdiction_succeeds(client, tenant_a):
    version_a = _create_eligible_source_version(client, tenant_a, title="Source MY")
    response_a = _create_release(
        client, tenant_a,
        jurisdiction="Malaysia", market="Malaysia",
        source_version_ids=[version_a["id"]],
    )
    assert response_a.status_code == 200

    version_b = _create_eligible_source_version(client, tenant_a, title="Source SG")
    response_b = _create_release(
        client, tenant_a,
        jurisdiction="Singapore", market="Singapore",
        source_version_ids=[version_b["id"]],
    )
    assert response_b.status_code == 200


def test_duplicate_content_hash_is_rejected(client, tenant_a):
    version = _create_eligible_source_version(client, tenant_a)

    first = _create_release(
        client, tenant_a,
        jurisdiction="Malaysia", market="Malaysia",
        source_version_ids=[version["id"]],
    )
    assert first.status_code == 200

    # different jurisdiction so it doesn't hit the active-conflict check -
    # isolates the content_hash uniqueness check specifically
    second = _create_release(
        client, tenant_a,
        jurisdiction="Singapore", market="Singapore",
        source_version_ids=[version["id"]],
    )
    assert second.status_code == 409


def test_releases_are_readable_across_organizations(client, tenant_a, tenant_b):
    version = _create_eligible_source_version(client, tenant_a)
    release = _create_release(
        client, tenant_a,
        source_version_ids=[version["id"]],
    ).json()

    response = client.get(
        f"/regulatory-basis-releases/{release['id']}",
        headers=tenant_b["headers"],
    )
    assert response.status_code == 200

    list_response = client.get(
        "/regulatory-basis-releases",
        headers=tenant_b["headers"],
    )
    assert list_response.status_code == 200
    assert any(r["id"] == release["id"] for r in list_response.json())


def test_create_release_rejects_non_admin(client, db, tenant_a):
    headers = _non_admin_headers(db, tenant_a)

    response = client.post(
        "/regulatory-basis-releases",
        json={"jurisdiction": "Malaysia", "market": "Malaysia"},
        headers=headers,
    )
    assert response.status_code == 403
