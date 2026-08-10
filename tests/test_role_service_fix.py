"""
Regression tests for the RoleRepository.get_by_id arity bug: update_role,
delete_role, and get_role used to call the (organization_id, role_id)
repository method with only role_id, which raised a TypeError before a
response was ever produced.
"""

from __future__ import annotations


def _create_role(client, tenant, code="MANAGER", name="Manager"):
    response = client.post(
        "/roles",
        json={"code": code, "name": name},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def test_get_role_does_not_raise_type_error(client, tenant_a):
    role = _create_role(client, tenant_a, code="AUDITOR", name="Auditor")

    response = client.get(
        f"/roles/{role['id']}",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    assert response.json()["id"] == role["id"]


def test_update_role_does_not_raise_type_error(client, tenant_a):
    role = _create_role(client, tenant_a)

    response = client.put(
        f"/roles/{role['id']}",
        json={"name": "Manager Updated"},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Manager Updated"


def test_delete_role_does_not_raise_type_error(client, tenant_a):
    role = _create_role(client, tenant_a, code="VIEWER", name="Viewer")

    response = client.delete(
        f"/roles/{role['id']}",
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200

    follow_up = client.get(
        f"/roles/{role['id']}",
        headers=tenant_a["headers"],
    )
    assert follow_up.status_code == 404
