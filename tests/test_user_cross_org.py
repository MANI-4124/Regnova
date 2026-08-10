from __future__ import annotations


def _create_user(client, tenant, email, first_name="Jane"):
    response = client.post(
        "/users",
        json={
            "role_id": str(tenant["role"].id),
            "first_name": first_name,
            "last_name": "Doe",
            "email": email,
            "password": "Password123!",
        },
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def test_get_user_across_orgs_returns_404(client, tenant_a, tenant_b):
    user = _create_user(client, tenant_b, "orgb.get@example.com")

    response = client.get(
        f"/users/{user['id']}",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404


def test_update_user_across_orgs_returns_404_and_leaves_data_untouched(
    client, tenant_a, tenant_b
):
    user = _create_user(client, tenant_b, "orgb.update@example.com")

    response = client.put(
        f"/users/{user['id']}",
        json={"first_name": "Hijacked"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404

    check = client.get(
        f"/users/{user['id']}",
        headers=tenant_b["headers"],
    )
    assert check.status_code == 200
    assert check.json()["first_name"] == "Jane"


def test_delete_user_across_orgs_returns_404_and_leaves_data_untouched(
    client, tenant_a, tenant_b
):
    user = _create_user(client, tenant_b, "orgb.delete@example.com")

    response = client.delete(
        f"/users/{user['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404

    check = client.get(
        f"/users/{user['id']}",
        headers=tenant_b["headers"],
    )
    assert check.status_code == 200


def test_list_users_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    _create_user(client, tenant_b, "orgb.list@example.com")
    _create_user(client, tenant_a, "orga.list@example.com")

    response = client.get(
        "/users",
        params={"organization_id": str(tenant_b["organization"].id)},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert "orgb.list@example.com" not in emails
    assert "orga.list@example.com" in emails


def test_create_user_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    response = client.post(
        "/users",
        params={"organization_id": str(tenant_b["organization"].id)},
        json={
            "role_id": str(tenant_a["role"].id),
            "first_name": "Sneaky",
            "last_name": "User",
            "email": "sneaky@example.com",
            "password": "Password123!",
        },
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["organization_id"] == str(tenant_a["organization"].id)
    assert body["organization_id"] != str(tenant_b["organization"].id)
