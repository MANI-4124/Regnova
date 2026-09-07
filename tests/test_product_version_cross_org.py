from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from app.modules.product_version.models import ProductVersion


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
        json={"version": version, "notes": "initial", "category": category},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def test_get_version_across_orgs_returns_404(client, tenant_a, tenant_b):
    product = _create_product(client, tenant_b)
    version = _create_version(client, tenant_b, product["id"])

    response = client.get(
        f"/products/{product['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404


def test_create_version_for_product_in_another_org_returns_404(client, tenant_a, tenant_b):
    """
    The product_id in the URL must be resolved against the caller's own
    org before anything version-related happens - a product_id belonging
    to another org must 404, not silently attach a version to it.
    """
    product = _create_product(client, tenant_b)

    response = client.post(
        f"/products/{product['id']}/versions",
        json={"version": "1.0.0", "category": "Beauty"},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404


def test_get_version_wrong_product_in_same_org_returns_404(client, tenant_a):
    """
    A version fetched through the wrong product's URL - even within the
    caller's own org - must 404, not silently return it. This is what the
    3-arg (organization_id, product_id, version_id) repository lookup buys
    over the 2-arg shape used elsewhere.
    """
    product_1 = _create_product(client, tenant_a, name="Product One")
    product_2 = _create_product(client, tenant_a, name="Product Two")
    version = _create_version(client, tenant_a, product_1["id"])

    response = client.get(
        f"/products/{product_2['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404


def test_update_version_across_orgs_returns_404_and_leaves_data_untouched(
    client, tenant_a, tenant_b
):
    product = _create_product(client, tenant_b)
    version = _create_version(client, tenant_b, product["id"])

    response = client.put(
        f"/products/{product['id']}/versions/{version['id']}",
        json={"notes": "Hijacked"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404

    check = client.get(
        f"/products/{product['id']}/versions/{version['id']}",
        headers=tenant_b["headers"],
    )
    assert check.status_code == 200
    assert check.json()["notes"] == "initial"


def test_delete_version_across_orgs_returns_404_and_leaves_data_untouched(
    client, tenant_a, tenant_b
):
    product = _create_product(client, tenant_b)
    version = _create_version(client, tenant_b, product["id"])

    response = client.delete(
        f"/products/{product['id']}/versions/{version['id']}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 404

    check = client.get(
        f"/products/{product['id']}/versions/{version['id']}",
        headers=tenant_b["headers"],
    )
    assert check.status_code == 200
    assert check.json()["is_active"] is True


def test_list_versions_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    product_a = _create_product(client, tenant_a, name="OrgA Product")
    _create_version(client, tenant_a, product_a["id"], version="A-1.0.0")

    product_b = _create_product(client, tenant_b, name="OrgB Product")
    _create_version(client, tenant_b, product_b["id"], version="B-1.0.0")

    response = client.get(
        f"/products/{product_a['id']}/versions",
        params={"organization_id": str(tenant_b["organization"].id)},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    versions = [v["version"] for v in response.json()]
    assert versions == ["A-1.0.0"]


def test_create_version_ignores_organization_id_query_param(client, tenant_a, tenant_b):
    product = _create_product(client, tenant_a)

    response = client.post(
        f"/products/{product['id']}/versions",
        params={"organization_id": str(tenant_b["organization"].id)},
        json={"version": "1.0.0", "category": "Beauty"},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["organization_id"] == str(tenant_a["organization"].id)
    assert body["organization_id"] != str(tenant_b["organization"].id)


def test_get_current_version_returns_most_recent_approved(client, db, tenant_a):
    product = _create_product(client, tenant_a)

    v1 = _create_version(client, tenant_a, product["id"], version="1.0.0")
    client.put(
        f"/products/{product['id']}/versions/{v1['id']}",
        json={"status": "APPROVED"},
        headers=tenant_a["headers"],
    )

    # SQLite's CURRENT_TIMESTAMP (what func.now() compiles to there) only
    # has second-level resolution, so two rows created back-to-back in the
    # same test can tie on created_at. Backdate v1 so "most recent" has an
    # unambiguous answer to assert against, instead of depending on
    # wall-clock granularity.
    row = db.get(ProductVersion, UUID(v1["id"]))
    row.created_at = row.created_at - timedelta(hours=1)
    db.commit()

    v2 = _create_version(client, tenant_a, product["id"], version="2.0.0")
    client.put(
        f"/products/{product['id']}/versions/{v2['id']}",
        json={"status": "APPROVED"},
        headers=tenant_a["headers"],
    )

    response = client.get(
        f"/products/{product['id']}/versions/current",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    assert response.json()["id"] == v2["id"]


def test_get_current_version_across_orgs_returns_404(client, tenant_a, tenant_b):
    product = _create_product(client, tenant_b)
    version = _create_version(client, tenant_b, product["id"])
    client.put(
        f"/products/{product['id']}/versions/{version['id']}",
        json={"status": "APPROVED"},
        headers=tenant_b["headers"],
    )

    response = client.get(
        f"/products/{product['id']}/versions/current",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 404
