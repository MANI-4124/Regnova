from __future__ import annotations

import uuid


def _create_requirement_version(client, writer, **overrides):
    requirement = client.post("/requirements", json={}, headers=writer["headers"]).json()

    payload = {
        "jurisdiction": "Malaysia",
        "market": "Malaysia",
        "authority": "NPRA",
        "category": "Documents",
        "dimension": "DOCUMENTS",
        "obligation_type": "gmp_certificate",
        "canonical_statement": "A current GMP certificate must be on file.",
        "default_severity": "MAJOR",
        "is_hard_gate": True,
        "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
    }
    payload.update(overrides)

    response = client.post(
        f"/requirements/{requirement['id']}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return requirement, response.json()


def _create_rule(client, writer):
    response = client.post("/rules", json={}, headers=writer["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _create_rule_version(client, writer, rule_id, **overrides):
    payload = {
        "condition": {"op": "not_exists", "field": "status"},
        "output_type": "FINDING_PROPOSAL",
    }
    payload.update(overrides)
    response = client.post(
        f"/rules/{rule_id}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_source(client, writer):
    response = client.post("/sources", headers=writer["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _create_source_version(client, writer, source_id):
    response = client.post(
        f"/sources/{source_id}/versions",
        json={
            "title": "Test Guideline",
            "issuing_authority": "Test Authority",
            "jurisdiction": "Malaysia",
            "tier": 1,
            "source_type": "OFFICIAL_GUIDELINE",
        },
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- Point 0 fix: unscoped version-lookup routes (CLAUDE.md "Ask RegNova") ---
# The exact gap: a Finding only ever carries the bare
# requirement_version_id/rule_version_id, never the parent id the nested
# /requirements/{requirement_id}/versions/{id} route needs.


def test_get_requirement_version_unscoped(client, tenant_a, regulatory_content_writer):
    requirement, version = _create_requirement_version(client, regulatory_content_writer)

    response = client.get(
        f"/requirement-versions/{version['id']}", headers=tenant_a["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == version["id"]
    # The parent id nothing calling this route needs to already know -
    # this IS the fix.
    assert body["requirement_id"] == requirement["id"]
    assert body["canonical_statement"] == "A current GMP certificate must be on file."


def test_get_requirement_version_unscoped_404_for_unknown_id(client, tenant_a):
    response = client.get(
        f"/requirement-versions/{uuid.uuid4()}", headers=tenant_a["headers"],
    )
    assert response.status_code == 404


def test_get_rule_version_unscoped(client, tenant_a, regulatory_content_writer):
    rule = _create_rule(client, regulatory_content_writer)
    version = _create_rule_version(client, regulatory_content_writer, rule["id"])

    response = client.get(f"/rule-versions/{version['id']}", headers=tenant_a["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == version["id"]
    assert body["rule_id"] == rule["id"]
    assert body["condition"] == {"op": "not_exists", "field": "status"}


def test_get_rule_version_unscoped_404_for_unknown_id(client, tenant_a):
    response = client.get(f"/rule-versions/{uuid.uuid4()}", headers=tenant_a["headers"])
    assert response.status_code == 404


def test_get_source_version_unscoped(client, tenant_a, regulatory_content_writer):
    source = _create_source(client, regulatory_content_writer)
    version = _create_source_version(client, regulatory_content_writer, source["id"])

    response = client.get(f"/source-versions/{version['id']}", headers=tenant_a["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == version["id"]
    assert body["source_id"] == source["id"]
    assert body["title"] == "Test Guideline"
    assert body["tier"] == 1


def test_get_source_version_unscoped_404_for_unknown_id(client, tenant_a):
    response = client.get(f"/source-versions/{uuid.uuid4()}", headers=tenant_a["headers"])
    assert response.status_code == 404


def test_unscoped_version_routes_require_authentication(client):
    """
    require_employee, same as every other Source/Requirement/Rule read -
    reachable by any authenticated user, not by no one at all.
    """
    response = client.get(f"/requirement-versions/{uuid.uuid4()}")
    assert response.status_code in (401, 403)
