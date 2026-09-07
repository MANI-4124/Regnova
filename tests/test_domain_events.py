from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import OutboxEvent


def _events_for(db, organization_id, event_type):
    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.organization_id == UUID(str(organization_id)),
            OutboxEvent.event_type == event_type,
        )
        .order_by(OutboxEvent.created_at.asc())
    )
    return list(db.scalars(statement))


def test_organization_create_emits_workspace_activated(client, db, tenant_a):
    response = client.post(
        "/organizations",
        json={
            "name": "New Workspace Co",
            "industry": "Cosmetics",
            "country": "MY",
        },
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    new_org_id = response.json()["id"]

    events = _events_for(db, new_org_id, "WorkspaceActivated")

    assert len(events) == 1
    assert events[0].schema_version == 1
    assert events[0].payload["organization_id"] == new_org_id
    assert events[0].actor_user_id == tenant_a["user"].id
    assert events[0].published_at is None


def test_user_create_emits_membership_changed(client, db, tenant_a):
    response = client.post(
        "/users",
        json={
            "role_id": str(tenant_a["role"].id),
            "first_name": "New",
            "last_name": "Hire",
            "email": "new.hire@example.com",
            "password": "Password123!",
        },
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    new_user_id = response.json()["id"]

    events = _events_for(db, tenant_a["organization"].id, "MembershipChanged")
    matching = [e for e in events if e.payload.get("user_id") == new_user_id]

    assert len(matching) == 1
    assert matching[0].payload["change"] == "created"


def test_user_role_change_emits_membership_changed(client, db, tenant_a):
    create = client.post(
        "/users",
        json={
            "role_id": str(tenant_a["role"].id),
            "first_name": "Existing",
            "last_name": "User",
            "email": "existing.user@example.com",
            "password": "Password123!",
        },
        headers=tenant_a["headers"],
    )
    user_id = create.json()["id"]

    response = client.put(
        f"/users/{user_id}",
        json={"is_active": False},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200

    events = _events_for(db, tenant_a["organization"].id, "MembershipChanged")
    matching = [
        e for e in events
        if e.payload.get("user_id") == user_id and e.payload.get("change") == "updated"
    ]

    assert len(matching) == 1
    assert matching[0].payload["is_active"] is False


def test_user_non_membership_update_does_not_emit_event(client, db, tenant_a):
    create = client.post(
        "/users",
        json={
            "role_id": str(tenant_a["role"].id),
            "first_name": "Existing",
            "last_name": "User",
            "email": "rename.only@example.com",
            "password": "Password123!",
        },
        headers=tenant_a["headers"],
    )
    user_id = create.json()["id"]

    before = len(_events_for(db, tenant_a["organization"].id, "MembershipChanged"))

    response = client.put(
        f"/users/{user_id}",
        json={"first_name": "Renamed"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200

    after = len(_events_for(db, tenant_a["organization"].id, "MembershipChanged"))
    assert after == before


def test_user_delete_emits_membership_changed(client, db, tenant_a):
    create = client.post(
        "/users",
        json={
            "role_id": str(tenant_a["role"].id),
            "first_name": "To",
            "last_name": "Delete",
            "email": "to.delete@example.com",
            "password": "Password123!",
        },
        headers=tenant_a["headers"],
    )
    user_id = create.json()["id"]

    response = client.delete(
        f"/users/{user_id}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200

    events = _events_for(db, tenant_a["organization"].id, "MembershipChanged")
    matching = [
        e for e in events
        if e.payload.get("user_id") == user_id and e.payload.get("change") == "revoked"
    ]

    assert len(matching) == 1


def _create_product(client, tenant, name="Widget"):
    response = client.post(
        "/products",
        json={"name": name},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_version(client, tenant, product_id, version="1.0.0", category="Beauty"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version, "category": category},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def test_publish_product_version_emits_event_and_sets_released_at(client, db, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    assert version["released_at"] is None

    response = client.post(
        f"/products/{product['id']}/versions/{version['id']}/publish",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    assert response.json()["released_at"] is not None

    events = _events_for(db, tenant_a["organization"].id, "ProductVersionPublished")
    matching = [e for e in events if e.payload.get("product_version_id") == version["id"]]

    assert len(matching) == 1
    assert matching[0].payload["product_id"] == product["id"]
    assert matching[0].payload["version"] == "1.0.0"


def test_publish_product_version_twice_conflicts(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    first = client.post(
        f"/products/{product['id']}/versions/{version['id']}/publish",
        headers=tenant_a["headers"],
    )
    assert first.status_code == 200

    second = client.post(
        f"/products/{product['id']}/versions/{version['id']}/publish",
        headers=tenant_a["headers"],
    )
    assert second.status_code == 409


def test_publish_product_version_across_orgs_returns_404(client, tenant_a, tenant_b):
    product = _create_product(client, tenant_b)
    version = _create_version(client, tenant_b, product["id"])

    response = client.post(
        f"/products/{product['id']}/versions/{version['id']}/publish",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404
