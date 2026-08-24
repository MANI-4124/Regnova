from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.product_market_state.models import ProductMarketState
from app.modules.product_market_state.schemas import ProductMarketStateCreate
from app.modules.product_market_state.service import ProductMarketStateService
from app.modules.role.models import Role
from app.modules.user.models import User


def _manager_headers(db, tenant):
    """
    A role that passes require_manager (used by the GET routes) but fails
    require_admin (used by POST/PUT) - for the non-admin permission test.
    """

    role = Role(
        organization_id=tenant["organization"].id,
        code="MANAGER",
        name="Manager",
    )
    db.add(role)
    db.flush()

    user = User(
        organization_id=tenant["organization"].id,
        role_id=role.id,
        first_name="Man",
        last_name="Ager",
        email="manager@example.com",
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


def _create_product(client, tenant, name="Widget"):
    response = client.post(
        "/products",
        json={"name": name},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_version(client, tenant, product_id, version="1.0.0"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version, "notes": "initial"},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_state(client, tenant, product_id, product_version_id, market="Malaysia"):
    return client.post(
        f"/products/{product_id}/market-states",
        json={"product_version_id": product_version_id, "market": market},
        headers=tenant["headers"],
    )


def _create_active_release(client, writer, jurisdiction="Malaysia", market="Malaysia"):
    source = client.post("/sources", headers=writer["headers"]).json()
    source_version = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "Test Source",
            "issuing_authority": "Test Authority",
            "jurisdiction": jurisdiction,
            "tier": 1,
            "source_type": "OFFICIAL_GUIDELINE",
        },
        headers=writer["headers"],
    ).json()
    activated = client.put(
        f"/sources/{source['id']}/versions/{source_version['id']}",
        json={"status": "ACTIVE", "verified_at": "2026-01-01T00:00:00Z"},
        headers=writer["headers"],
    ).json()

    release = client.post(
        "/regulatory-basis-releases",
        json={
            "jurisdiction": jurisdiction,
            "market": market,
            "source_version_ids": [activated["id"]],
        },
        headers=writer["headers"],
    )
    assert release.status_code == 200
    return release.json()


def test_create_and_get_state(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    response = _create_state(client, tenant_a, product["id"], version["id"])
    assert response.status_code == 200
    state = response.json()

    assert state["product_id"] == product["id"]
    assert state["product_version_id"] == version["id"]
    assert state["market"] == "Malaysia"
    assert state["gate"] == "G0"
    assert state["status"] == "ACTIVE"
    assert state["regulatory_basis_release_id"] is None

    get_resp = client.get(
        f"/products/{product['id']}/market-states/{state['id']}",
        headers=tenant_a["headers"],
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == state["id"]


def test_create_resolves_active_release_for_market(client, tenant_a, regulatory_content_writer):
    release = _create_active_release(client, regulatory_content_writer)

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    state = _create_state(client, tenant_a, product["id"], version["id"]).json()

    assert state["regulatory_basis_release_id"] == release["id"]


def test_create_with_no_active_release_leaves_release_id_null(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    state = _create_state(
        client, tenant_a, product["id"], version["id"], market="Freedonia",
    ).json()

    assert state["regulatory_basis_release_id"] is None


def test_create_is_idempotent(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    first = _create_state(client, tenant_a, product["id"], version["id"]).json()
    second = _create_state(client, tenant_a, product["id"], version["id"]).json()

    assert second["id"] == first["id"]


def test_create_idempotent_does_not_repoint_to_different_version(client, tenant_a):
    product = _create_product(client, tenant_a)
    v1 = _create_version(client, tenant_a, product["id"], version="1.0.0")

    first = _create_state(client, tenant_a, product["id"], v1["id"]).json()
    assert first["product_version_id"] == v1["id"]

    v2 = _create_version(client, tenant_a, product["id"], version="2.0.0")

    repeated = _create_state(client, tenant_a, product["id"], v2["id"]).json()

    assert repeated["id"] == first["id"]
    assert repeated["product_version_id"] == v1["id"]


def test_create_rejects_withdrawn_product_version(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    withdraw = client.put(
        f"/products/{product['id']}/versions/{version['id']}",
        json={"is_active": False},
        headers=tenant_a["headers"],
    )
    assert withdraw.status_code == 200

    response = _create_state(client, tenant_a, product["id"], version["id"])
    assert response.status_code == 409


def test_create_nonexistent_product_version_returns_404(client, tenant_a):
    product = _create_product(client, tenant_a)

    response = _create_state(client, tenant_a, product["id"], str(uuid.uuid4()))
    assert response.status_code == 404


def test_create_nonexistent_product_returns_404(client, tenant_a):
    response = _create_state(
        client, tenant_a, str(uuid.uuid4()), str(uuid.uuid4()),
    )
    assert response.status_code == 404


def test_list_filtered_by_market(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    _create_state(client, tenant_a, product["id"], version["id"], market="Malaysia")
    _create_state(client, tenant_a, product["id"], version["id"], market="Singapore")

    response = client.get(
        f"/products/{product['id']}/market-states",
        params={"market": "Malaysia"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    markets = [s["market"] for s in response.json()]
    assert markets == ["Malaysia"]


def test_update_state(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"]).json()

    response = client.put(
        f"/products/{product['id']}/market-states/{state['id']}",
        json={"gate": "G2"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["gate"] == "G2"


def test_states_are_isolated_across_organizations(client, tenant_a, tenant_b):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"]).json()

    response = client.get(
        f"/products/{product['id']}/market-states/{state['id']}",
        headers=tenant_b["headers"],
    )
    assert response.status_code == 404

    list_response = client.get(
        f"/products/{product['id']}/market-states",
        headers=tenant_b["headers"],
    )
    assert list_response.status_code == 404


def test_create_state_rejects_non_admin(client, db, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    headers = _manager_headers(db, tenant_a)

    response = client.post(
        f"/products/{product['id']}/market-states",
        json={"product_version_id": version["id"], "market": "Malaysia"},
        headers=headers,
    )
    assert response.status_code == 403


def test_partial_unique_index_rejects_duplicate_active_rows(client, db, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    organization_id = tenant_a["organization"].id
    product_id = UUID(product["id"])
    product_version_id = UUID(version["id"])

    first = ProductMarketState(
        organization_id=organization_id,
        product_id=product_id,
        product_version_id=product_version_id,
        market="Malaysia",
    )
    db.add(first)
    db.commit()

    second = ProductMarketState(
        organization_id=organization_id,
        product_id=product_id,
        product_version_id=product_version_id,
        market="Malaysia",
    )
    db.add(second)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # The index is partial (status = 'ACTIVE' only) - an ARCHIVED duplicate
    # for the same (organization_id, product_id, market) must still succeed.
    first.status = "ARCHIVED"
    db.add(first)
    db.commit()

    archived_duplicate = ProductMarketState(
        organization_id=organization_id,
        product_id=product_id,
        product_version_id=product_version_id,
        market="Malaysia",
        status="ARCHIVED",
    )
    db.add(archived_duplicate)
    db.commit()


def test_create_handles_race_by_returning_existing_active_state(
    client, db, tenant_a, monkeypatch,
):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])

    organization_id = tenant_a["organization"].id
    product_id = UUID(product["id"])
    product_version_id = UUID(version["id"])
    market = "Malaysia"

    service = ProductMarketStateService(db)
    payload = ProductMarketStateCreate(
        product_version_id=product_version_id,
        market=market,
    )

    original_lookup = service.repository.get_active_for_product_market
    calls = {"count": 0}

    def flaky_lookup(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            # The service's own idempotent pre-check, racing against a
            # concurrent request that hasn't committed yet - nothing found.
            return None
        return original_lookup(*args, **kwargs)

    monkeypatch.setattr(
        service.repository, "get_active_for_product_market", flaky_lookup,
    )

    # The concurrent request wins the race and commits first.
    winner = ProductMarketState(
        organization_id=organization_id,
        product_id=product_id,
        product_version_id=product_version_id,
        market=market,
    )
    db.add(winner)
    db.commit()

    result = service.create(organization_id, product_id, payload)

    assert result.id == winner.id
    assert calls["count"] == 2
