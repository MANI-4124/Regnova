from __future__ import annotations

from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.role.models import Role
from app.modules.user.models import User


def _non_admin_headers(db, tenant):
    """
    Same pattern as test_source.py - a customer-org user, used to
    confirm require_regulatory_content_writer rejects any customer-org
    account outright.
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


def _create_requirement(client, writer, **overrides):
    payload = {}
    payload.update(overrides)
    response = client.post(
        "/requirements",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_version(client, writer, requirement_id, **overrides):
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
    response = client.post(
        f"/requirements/{requirement_id}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_source_location(client, writer):
    source_resp = client.post("/sources", headers=writer["headers"])
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
        headers=writer["headers"],
    )
    assert version_resp.status_code == 200
    source_version = version_resp.json()

    location_resp = client.post(
        "/source-locations",
        json={"source_version_id": source_version["id"], "section": "Annex II"},
        headers=writer["headers"],
    )
    assert location_resp.status_code == 200
    return location_resp.json()


def test_create_and_get_requirement(client, tenant_a, regulatory_content_writer):
    requirement = _create_requirement(client, regulatory_content_writer, human_reference="REQ-MY-COS-0001")

    assert requirement["human_reference"] == "REQ-MY-COS-0001"

    response = client.get(
        f"/requirements/{requirement['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["id"] == requirement["id"]


def test_update_requirement(client, regulatory_content_writer):
    requirement = _create_requirement(client, regulatory_content_writer)

    response = client.put(
        f"/requirements/{requirement['id']}",
        json={"human_reference": "REQ-MY-COS-0002"},
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 200
    assert response.json()["human_reference"] == "REQ-MY-COS-0002"


def test_create_and_get_requirement_version(client, tenant_a, regulatory_content_writer):
    requirement = _create_requirement(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, requirement["id"])

    assert version["requirement_id"] == requirement["id"]
    assert version["status"] == "DRAFT"
    assert version["unknown_behavior"] == "HUMAN_REVIEW"
    assert version["is_hard_gate"] is False
    assert version["source_location_ids"] == []

    response = client.get(
        f"/requirements/{requirement['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["id"] == version["id"]


def test_update_requirement_version(client, regulatory_content_writer):
    """
    status is no longer settable through this generic PUT - it's
    managed exclusively by the submit-for-review/verify/activate/reject
    transition endpoints (see tests/test_content_review.py).
    """
    requirement = _create_requirement(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, requirement["id"])

    response = client.put(
        f"/requirements/{requirement['id']}/versions/{version['id']}",
        json={"notes": "under review"},
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "DRAFT"
    assert response.json()["notes"] == "under review"


def test_get_version_through_wrong_requirement_returns_404(client, tenant_a, regulatory_content_writer):
    requirement_1 = _create_requirement(client, regulatory_content_writer)
    requirement_2 = _create_requirement(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, requirement_1["id"])

    response = client.get(
        f"/requirements/{requirement_2['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404


def test_create_version_for_nonexistent_requirement_returns_404(client, regulatory_content_writer):
    import uuid

    response = client.post(
        f"/requirements/{uuid.uuid4()}/versions",
        json={
            "jurisdiction": "Malaysia",
            "market": "Malaysia",
            "authority": "NPRA",
            "category": "Ingredients",
            "dimension": "INGREDIENTS",
            "obligation_type": "X",
            "canonical_statement": "X",
            "default_severity": "MINOR",
            "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
        },
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 404


def test_create_version_with_source_location_ids(client, regulatory_content_writer):
    requirement = _create_requirement(client, regulatory_content_writer)
    location = _create_source_location(client, regulatory_content_writer)

    version = _create_version(
        client,
        regulatory_content_writer,
        requirement["id"],
        source_location_ids=[location["id"]],
    )

    assert version["source_location_ids"] == [location["id"]]


def test_create_version_with_nonexistent_source_location_id_returns_404(client, regulatory_content_writer):
    import uuid

    requirement = _create_requirement(client, regulatory_content_writer)

    response = client.post(
        f"/requirements/{requirement['id']}/versions",
        json={
            "jurisdiction": "Malaysia",
            "market": "Malaysia",
            "authority": "NPRA",
            "category": "Ingredients",
            "dimension": "INGREDIENTS",
            "obligation_type": "X",
            "canonical_statement": "X",
            "default_severity": "MINOR",
            "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
            "source_location_ids": [str(uuid.uuid4())],
        },
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 404


def test_update_replaces_source_location_ids(client, regulatory_content_writer):
    requirement = _create_requirement(client, regulatory_content_writer)
    location_1 = _create_source_location(client, regulatory_content_writer)
    location_2 = _create_source_location(client, regulatory_content_writer)

    version = _create_version(
        client,
        regulatory_content_writer,
        requirement["id"],
        source_location_ids=[location_1["id"]],
    )

    response = client.put(
        f"/requirements/{requirement['id']}/versions/{version['id']}",
        json={"source_location_ids": [location_2["id"]]},
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 200
    assert response.json()["source_location_ids"] == [location_2["id"]]


def test_requirements_are_readable_across_organizations(client, tenant_a, tenant_b, regulatory_content_writer):
    """
    Requirement is platform reference data, not customer-owned data - it
    has no organization_id, same as Source.
    """
    requirement = _create_requirement(client, regulatory_content_writer, human_reference="REQ-SHARED")

    response = client.get(
        f"/requirements/{requirement['id']}",
        headers=tenant_b["headers"],
    )
    assert response.status_code == 200

    list_response = client.get(
        "/requirements",
        headers=tenant_b["headers"],
    )
    assert list_response.status_code == 200
    assert any(r["id"] == requirement["id"] for r in list_response.json())


def test_create_requirement_rejects_non_admin(client, db, tenant_a):
    headers = _non_admin_headers(db, tenant_a)

    response = client.post(
        "/requirements",
        json={},
        headers=headers,
    )
    assert response.status_code == 403


def test_create_requirement_version_rejects_non_admin(client, db, tenant_a, regulatory_content_writer):
    requirement = _create_requirement(client, regulatory_content_writer)
    headers = _non_admin_headers(db, tenant_a)

    response = client.post(
        f"/requirements/{requirement['id']}/versions",
        json={
            "jurisdiction": "Malaysia",
            "market": "Malaysia",
            "authority": "NPRA",
            "category": "Ingredients",
            "dimension": "INGREDIENTS",
            "obligation_type": "X",
            "canonical_statement": "X",
            "default_severity": "MINOR",
            "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
        },
        headers=headers,
    )
    assert response.status_code == 403
