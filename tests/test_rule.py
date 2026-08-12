from __future__ import annotations

from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.role.models import Role
from app.modules.user.models import User


def _non_admin_headers(db, tenant):
    """
    Same pattern as test_source.py/test_requirement.py - a role that
    passes require_employee but fails require_admin, used to confirm
    the write-authorization placeholder is actually enforced.
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


def _create_rule(client, tenant, **overrides):
    payload = {}
    payload.update(overrides)
    response = client.post(
        "/rules",
        json=payload,
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _simple_condition():
    return {
        "op": "lte",
        "field": "ingredient.concentration_pct",
        "value": 0.01,
    }


def _create_rule_version(client, tenant, rule_id, **overrides):
    payload = {
        "condition": _simple_condition(),
        "output_type": "REQUIREMENT_RESULT",
    }
    payload.update(overrides)
    response = client.post(
        f"/rules/{rule_id}/versions",
        json=payload,
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_requirement_version(client, tenant):
    req_resp = client.post("/requirements", json={}, headers=tenant["headers"])
    assert req_resp.status_code == 200
    requirement = req_resp.json()

    version_resp = client.post(
        f"/requirements/{requirement['id']}/versions",
        json={
            "jurisdiction": "Malaysia",
            "market": "Malaysia",
            "authority": "NPRA",
            "category": "Ingredients",
            "dimension": "INGREDIENTS",
            "obligation_type": "INGREDIENT_CONCENTRATION_LIMIT",
            "canonical_statement": "Mercury and its compounds must not form part of the composition.",
            "default_severity": "CRITICAL",
            "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
        },
        headers=tenant["headers"],
    )
    assert version_resp.status_code == 200
    return version_resp.json()


def _create_source_location(client, tenant):
    source_resp = client.post("/sources", headers=tenant["headers"])
    assert source_resp.status_code == 200
    source = source_resp.json()

    version_resp = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "Test Source",
            "issuing_authority": "Test Authority",
            "jurisdiction": "Malaysia",
            "tier": 2,
            "source_type": "REGIONAL_DIRECTIVE",
        },
        headers=tenant["headers"],
    )
    assert version_resp.status_code == 200
    source_version = version_resp.json()

    location_resp = client.post(
        "/source-locations",
        json={"source_version_id": source_version["id"], "section": "Annex II"},
        headers=tenant["headers"],
    )
    assert location_resp.status_code == 200
    return location_resp.json()


def test_create_and_get_rule(client, tenant_a):
    rule = _create_rule(client, tenant_a, human_reference="RULE-MY-COS-0001")

    assert rule["human_reference"] == "RULE-MY-COS-0001"

    response = client.get(
        f"/rules/{rule['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["id"] == rule["id"]


def test_update_rule(client, tenant_a):
    rule = _create_rule(client, tenant_a)

    response = client.put(
        f"/rules/{rule['id']}",
        json={"human_reference": "RULE-MY-COS-0002"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["human_reference"] == "RULE-MY-COS-0002"


def test_create_and_get_rule_version(client, tenant_a):
    rule = _create_rule(client, tenant_a)
    version = _create_rule_version(client, tenant_a, rule["id"])

    assert version["rule_id"] == rule["id"]
    assert version["status"] == "DRAFT"
    assert version["unknown_behavior"] == "HUMAN_REVIEW"
    assert version["output_type"] == "REQUIREMENT_RESULT"
    assert version["condition"] == _simple_condition()
    assert version["requirement_version_id"] is None
    assert version["source_location_ids"] == []

    response = client.get(
        f"/rules/{rule['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["id"] == version["id"]


def test_update_rule_version(client, tenant_a):
    rule = _create_rule(client, tenant_a)
    version = _create_rule_version(client, tenant_a, rule["id"])

    response = client.put(
        f"/rules/{rule['id']}/versions/{version['id']}",
        json={"status": "IN_REVIEW", "notes": "under review"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IN_REVIEW"
    assert response.json()["notes"] == "under review"


def test_get_version_through_wrong_rule_returns_404(client, tenant_a):
    rule_1 = _create_rule(client, tenant_a)
    rule_2 = _create_rule(client, tenant_a)
    version = _create_rule_version(client, tenant_a, rule_1["id"])

    response = client.get(
        f"/rules/{rule_2['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404


def test_create_version_for_nonexistent_rule_returns_404(client, tenant_a):
    import uuid

    response = client.post(
        f"/rules/{uuid.uuid4()}/versions",
        json={
            "condition": _simple_condition(),
            "output_type": "REQUIREMENT_RESULT",
        },
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404


def test_create_version_with_requirement_version_id(client, tenant_a):
    rule = _create_rule(client, tenant_a)
    requirement_version = _create_requirement_version(client, tenant_a)

    version = _create_rule_version(
        client,
        tenant_a,
        rule["id"],
        requirement_version_id=requirement_version["id"],
    )

    assert version["requirement_version_id"] == requirement_version["id"]


def test_create_version_with_nonexistent_requirement_version_id_returns_404(client, tenant_a):
    import uuid

    rule = _create_rule(client, tenant_a)

    response = client.post(
        f"/rules/{rule['id']}/versions",
        json={
            "condition": _simple_condition(),
            "output_type": "REQUIREMENT_RESULT",
            "requirement_version_id": str(uuid.uuid4()),
        },
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404


def test_create_version_with_source_location_ids(client, tenant_a):
    rule = _create_rule(client, tenant_a)
    location = _create_source_location(client, tenant_a)

    version = _create_rule_version(
        client,
        tenant_a,
        rule["id"],
        source_location_ids=[location["id"]],
    )

    assert version["source_location_ids"] == [location["id"]]


def test_create_version_with_nonexistent_source_location_id_returns_404(client, tenant_a):
    import uuid

    rule = _create_rule(client, tenant_a)

    response = client.post(
        f"/rules/{rule['id']}/versions",
        json={
            "condition": _simple_condition(),
            "output_type": "REQUIREMENT_RESULT",
            "source_location_ids": [str(uuid.uuid4())],
        },
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404


def test_update_replaces_source_location_ids(client, tenant_a):
    rule = _create_rule(client, tenant_a)
    location_1 = _create_source_location(client, tenant_a)
    location_2 = _create_source_location(client, tenant_a)

    version = _create_rule_version(
        client,
        tenant_a,
        rule["id"],
        source_location_ids=[location_1["id"]],
    )

    response = client.put(
        f"/rules/{rule['id']}/versions/{version['id']}",
        json={"source_location_ids": [location_2["id"]]},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["source_location_ids"] == [location_2["id"]]


def test_rules_are_readable_across_organizations(client, tenant_a, tenant_b):
    """
    Rule is platform reference data, not customer-owned data - it has
    no organization_id, same as Source/Requirement.
    """
    rule = _create_rule(client, tenant_a, human_reference="RULE-SHARED")

    response = client.get(
        f"/rules/{rule['id']}",
        headers=tenant_b["headers"],
    )
    assert response.status_code == 200

    list_response = client.get(
        "/rules",
        headers=tenant_b["headers"],
    )
    assert list_response.status_code == 200
    assert any(r["id"] == rule["id"] for r in list_response.json())


def test_create_rule_rejects_non_admin(client, db, tenant_a):
    headers = _non_admin_headers(db, tenant_a)

    response = client.post(
        "/rules",
        json={},
        headers=headers,
    )
    assert response.status_code == 403


def test_create_rule_version_rejects_non_admin(client, db, tenant_a):
    rule = _create_rule(client, tenant_a)
    headers = _non_admin_headers(db, tenant_a)

    response = client.post(
        f"/rules/{rule['id']}/versions",
        json={
            "condition": _simple_condition(),
            "output_type": "REQUIREMENT_RESULT",
        },
        headers=headers,
    )
    assert response.status_code == 403
