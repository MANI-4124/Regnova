from __future__ import annotations

from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.role.models import Role
from app.modules.user.models import User


def _non_admin_headers(db, tenant):
    """
    A user in the same org as `tenant` - a customer org, not RegNova's
    own tenant-zero. Used to confirm require_regulatory_content_writer
    (which only ever grants a tenant-zero REGULATORY_KNOWLEDGE_LEAD
    InternalRoleAssignment) rejects any customer-org account outright,
    admin role or not - not just non-admin roles within a customer org.
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


def _create_source(client, writer):
    response = client.post(
        "/sources",
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_version(client, writer, source_id, title="Test Guideline"):
    response = client.post(
        f"/sources/{source_id}/versions",
        json={
            "title": title,
            "issuing_authority": "Test Authority",
            "jurisdiction": "Malaysia",
            "tier": 1,
            "source_type": "OFFICIAL_GUIDELINE",
        },
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_location(client, writer, source_version_id, **overrides):
    payload = {"source_version_id": source_version_id, "section": "5", "page": "12"}
    payload.update(overrides)
    response = client.post(
        "/source-locations",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def test_create_and_get_source(client, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)

    response = client.get(
        f"/sources/{source['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["id"] == source["id"]


def test_create_and_get_source_version(client, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, source["id"])

    assert version["source_id"] == source["id"]
    assert version["status"] == "DRAFT"
    assert version["tier"] == 1
    assert version["is_full_text_displayable"] is False

    response = client.get(
        f"/sources/{source['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["id"] == version["id"]


def test_update_source_version(client, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, source["id"])

    response = client.put(
        f"/sources/{source['id']}/versions/{version['id']}",
        json={"status": "IN_REVIEW", "notes": "under review"},
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IN_REVIEW"
    assert response.json()["notes"] == "under review"


def test_get_version_through_wrong_source_returns_404(client, tenant_a, regulatory_content_writer):
    source_1 = _create_source(client, regulatory_content_writer)
    source_2 = _create_source(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, source_1["id"])

    response = client.get(
        f"/sources/{source_2['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404


def test_create_version_for_nonexistent_source_returns_404(client, regulatory_content_writer):
    import uuid

    response = client.post(
        f"/sources/{uuid.uuid4()}/versions",
        json={
            "title": "X",
            "issuing_authority": "X",
            "jurisdiction": "Malaysia",
            "tier": 1,
            "source_type": "LEGISLATION",
        },
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 404


def test_create_and_get_source_location(client, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, source["id"])
    location = _create_location(
        client,
        regulatory_content_writer,
        version["id"],
        section="5(2)",
        schedule="Second Schedule",
        page="47",
    )

    assert location["source_version_id"] == version["id"]
    assert location["section"] == "5(2)"
    assert location["schedule"] == "Second Schedule"
    assert location["page"] == "47"

    response = client.get(
        f"/source-locations/{location['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["id"] == location["id"]


def test_create_location_with_no_coordinate_fields_is_rejected(client, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, source["id"])

    response = client.post(
        "/source-locations",
        json={
            "source_version_id": version["id"],
            "normalized_text": "some text with no coordinate at all",
        },
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 422


def test_create_location_for_nonexistent_source_version_returns_404(client, regulatory_content_writer):
    import uuid

    response = client.post(
        "/source-locations",
        json={
            "source_version_id": str(uuid.uuid4()),
            "section": "5",
        },
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 404


def test_list_locations_filtered_by_source_version_id(client, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    version_1 = _create_version(client, regulatory_content_writer, source["id"], title="V1")
    version_2 = _create_version(client, regulatory_content_writer, source["id"], title="V2")

    location_1 = _create_location(client, regulatory_content_writer, version_1["id"], section="1")
    _create_location(client, regulatory_content_writer, version_2["id"], section="2")

    response = client.get(
        "/source-locations",
        params={"source_version_id": version_1["id"]},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    ids = [loc["id"] for loc in response.json()]
    assert ids == [location_1["id"]]


def test_list_locations_without_filter_returns_all(client, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, source["id"])

    _create_location(client, regulatory_content_writer, version["id"], section="1")
    _create_location(client, regulatory_content_writer, version["id"], section="2")

    response = client.get(
        "/source-locations",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_create_source_rejects_non_admin(client, db, tenant_a):
    headers = _non_admin_headers(db, tenant_a)

    response = client.post(
        "/sources",
        headers=headers,
    )
    assert response.status_code == 403


def test_create_source_version_rejects_non_admin(client, db, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    headers = _non_admin_headers(db, tenant_a)

    response = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "X",
            "issuing_authority": "X",
            "jurisdiction": "Malaysia",
            "tier": 1,
            "source_type": "LEGISLATION",
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_create_source_location_rejects_non_admin(client, db, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    version = _create_version(client, regulatory_content_writer, source["id"])
    headers = _non_admin_headers(db, tenant_a)

    response = client.post(
        "/source-locations",
        json={
            "source_version_id": version["id"],
            "section": "5",
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_sources_are_readable_across_organizations(client, tenant_a, tenant_b, regulatory_content_writer):
    """
    Source is platform reference data, not customer-owned data - it has
    no organization_id. A source created (from either org's perspective,
    since there's no ownership) must be visible to every authenticated
    user regardless of which org their token belongs to.
    """
    source = _create_source(client, regulatory_content_writer)
    _create_version(client, regulatory_content_writer, source["id"], title="Shared Guideline")

    response = client.get(
        f"/sources/{source['id']}",
        headers=tenant_b["headers"],
    )
    assert response.status_code == 200

    list_response = client.get(
        "/sources",
        headers=tenant_b["headers"],
    )
    assert list_response.status_code == 200
    assert any(s["id"] == source["id"] for s in list_response.json())
