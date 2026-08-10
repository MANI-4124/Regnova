from __future__ import annotations


def _create_product(client, tenant, name="Widget"):
    response = client.post(
        "/products",
        json={"name": name, "brand": "Acme", "description": "test product"},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def test_get_product_across_orgs_returns_404(client, tenant_a, tenant_b):
    product = _create_product(client, tenant_b)

    response = client.get(
        f"/products/{product['id']}",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404


def test_get_product_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    """
    Passing the victim org's id in the query string must not let org A
    reach org B's product - organization_id now comes only from the token.
    """
    product = _create_product(client, tenant_b)

    response = client.get(
        f"/products/{product['id']}",
        params={"organization_id": str(tenant_b["organization"].id)},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404


def test_update_product_across_orgs_returns_404_and_leaves_data_untouched(
    client, tenant_a, tenant_b
):
    product = _create_product(client, tenant_b)

    response = client.put(
        f"/products/{product['id']}",
        json={"name": "Hijacked"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404

    check = client.get(
        f"/products/{product['id']}",
        headers=tenant_b["headers"],
    )
    assert check.status_code == 200
    assert check.json()["name"] == "Widget"


def test_delete_product_across_orgs_returns_404_and_leaves_data_untouched(
    client, tenant_a, tenant_b
):
    product = _create_product(client, tenant_b)

    response = client.delete(
        f"/products/{product['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404

    check = client.get(
        f"/products/{product['id']}",
        headers=tenant_b["headers"],
    )
    assert check.status_code == 200
    assert check.json()["is_active"] is True


def test_list_products_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    _create_product(client, tenant_b, name="OrgB Product")
    _create_product(client, tenant_a, name="OrgA Product")

    response = client.get(
        "/products",
        params={"organization_id": str(tenant_b["organization"].id)},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert names == ["OrgA Product"]


def test_create_product_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    """
    organization_id used to be a required query param read straight into
    the service call. Even if a client still sends it, the product must be
    created under the caller's own org, not the org named in the request.
    """
    response = client.post(
        "/products",
        params={"organization_id": str(tenant_b["organization"].id)},
        json={"name": "Sneaky"},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["organization_id"] == str(tenant_a["organization"].id)
    assert body["organization_id"] != str(tenant_b["organization"].id)
