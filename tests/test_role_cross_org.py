from __future__ import annotations


def _create_role(client, tenant, code="MANAGER", name="Manager"):
    response = client.post(
        "/roles",
        json={"code": code, "name": name},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def test_get_role_across_orgs_returns_404(client, tenant_a, tenant_b):
    role = _create_role(client, tenant_b)

    response = client.get(
        f"/roles/{role['id']}",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404


def test_update_role_across_orgs_returns_404_and_leaves_data_untouched(
    client, tenant_a, tenant_b
):
    role = _create_role(client, tenant_b)

    response = client.put(
        f"/roles/{role['id']}",
        json={"name": "Hijacked"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404

    check = client.get(
        f"/roles/{role['id']}",
        headers=tenant_b["headers"],
    )
    assert check.status_code == 200
    assert check.json()["name"] == "Manager"


def test_delete_role_across_orgs_returns_404_and_leaves_data_untouched(
    client, tenant_a, tenant_b
):
    role = _create_role(client, tenant_b)

    response = client.delete(
        f"/roles/{role['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404

    check = client.get(
        f"/roles/{role['id']}",
        headers=tenant_b["headers"],
    )
    assert check.status_code == 200


def test_list_roles_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    _create_role(client, tenant_b, code="B_ROLE", name="B Role")
    _create_role(client, tenant_a, code="A_ROLE", name="A Role")

    response = client.get(
        "/roles",
        params={"organization_id": str(tenant_b["organization"].id)},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    codes = [r["code"] for r in response.json()]
    assert "B_ROLE" not in codes
    assert "A_ROLE" in codes


def test_create_role_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    response = client.post(
        "/roles",
        params={"organization_id": str(tenant_b["organization"].id)},
        json={"code": "SNEAKY", "name": "Sneaky"},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["organization_id"] == str(tenant_a["organization"].id)
    assert body["organization_id"] != str(tenant_b["organization"].id)
