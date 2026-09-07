from __future__ import annotations

import uuid

import pytest

from app.core.dependencies import get_document_storage
from app.main import app
from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.role.models import Role
from app.modules.user.models import User
from app.storage import LocalFilesystemStorage

PDF_BYTES = b"%PDF-1.4\n%mock gmp certificate content\n%%EOF"
PDF_BYTES_V2 = b"%PDF-1.4\n%mock gmp certificate content, corrected expiry\n%%EOF"


@pytest.fixture()
def storage(tmp_path):
    backend = LocalFilesystemStorage(tmp_path)
    app.dependency_overrides[get_document_storage] = lambda: backend
    yield backend
    app.dependency_overrides.pop(get_document_storage, None)


def _employee_headers(db, tenant):
    role = Role(organization_id=tenant["organization"].id, code="EMPLOYEE", name="Employee")
    db.add(role)
    db.flush()

    user = User(
        organization_id=tenant["organization"].id,
        role_id=role.id,
        first_name="Rank",
        last_name="File",
        email="employee-evidence@example.com",
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
    response = client.post("/products", json={"name": name}, headers=tenant["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _create_document(client, tenant, document_type="GMP_CERTIFICATE"):
    response = client.post(
        "/documents", json={"document_type": document_type}, headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_version(client, tenant, document_id, content=PDF_BYTES, filename="cert.pdf"):
    files = {"file": (filename, content, "application/pdf")}
    response = client.post(
        f"/documents/{document_id}/versions", files=files, headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _verify_version(client, tenant, document_id, version_id):
    response = client.post(
        f"/documents/{document_id}/versions/{version_id}/verify",
        json={},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_verified_document_version(client, tenant, content=PDF_BYTES):
    document = _create_document(client, tenant)
    version = _upload_version(client, tenant, document["id"], content=content)
    return document, _verify_version(client, tenant, document["id"], version["id"])


def _create_evidence(client, tenant, *, document_version_id, product_id, requirement_version_id=None):
    return client.post(
        "/evidence",
        json={
            "document_version_id": document_version_id,
            "product_id": product_id,
            "requirement_version_id": requirement_version_id,
        },
        headers=tenant["headers"],
    )


# --- The explicitly required guarantee ------------------------------------


def test_evidence_cannot_link_a_non_verified_document_version(client, tenant_a, storage):
    """
    Explicitly required: AC-FR-04-01's compensating control (no
    scanner exists, so a human clearing the file to VERIFIED is what
    stands in for a passed scan). A REVIEW_REQUIRED document version
    must be rejected, not silently allowed through.
    """
    product = _create_product(client, tenant_a)
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"])  # still REVIEW_REQUIRED

    response = _create_evidence(
        client, tenant_a, document_version_id=version["id"], product_id=product["id"],
    )

    assert response.status_code == 409


def test_evidence_cannot_link_a_rejected_document_version(client, tenant_a, storage):
    product = _create_product(client, tenant_a)
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"])
    client.post(
        f"/documents/{document['id']}/versions/{version['id']}/reject",
        json={"note": "wrong file"},
        headers=tenant_a["headers"],
    )

    response = _create_evidence(
        client, tenant_a, document_version_id=version["id"], product_id=product["id"],
    )

    assert response.status_code == 409


# --- Happy path and validation ---------------------------------------------


def test_create_evidence_succeeds_once_verified(client, tenant_a, storage):
    product = _create_product(client, tenant_a)
    _, version = _create_verified_document_version(client, tenant_a)

    response = _create_evidence(
        client, tenant_a, document_version_id=version["id"], product_id=product["id"],
    )

    assert response.status_code == 200, response.text
    evidence = response.json()
    assert evidence["document_version_id"] == version["id"]
    assert evidence["product_id"] == product["id"]
    assert evidence["is_current"] is True
    assert evidence["stale_reason"] is None


def test_create_evidence_duplicate_link_rejected(client, tenant_a, storage):
    product = _create_product(client, tenant_a)
    _, version = _create_verified_document_version(client, tenant_a)

    first = _create_evidence(
        client, tenant_a, document_version_id=version["id"], product_id=product["id"],
    )
    second = _create_evidence(
        client, tenant_a, document_version_id=version["id"], product_id=product["id"],
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_create_evidence_nonexistent_product_returns_404(client, tenant_a, storage):
    _, version = _create_verified_document_version(client, tenant_a)

    response = _create_evidence(
        client, tenant_a, document_version_id=version["id"], product_id=str(uuid.uuid4()),
    )

    assert response.status_code == 404


def test_create_evidence_nonexistent_requirement_version_returns_404(client, tenant_a, storage):
    product = _create_product(client, tenant_a)
    _, version = _create_verified_document_version(client, tenant_a)

    response = _create_evidence(
        client, tenant_a,
        document_version_id=version["id"], product_id=product["id"],
        requirement_version_id=str(uuid.uuid4()),
    )

    assert response.status_code == 404


def test_create_evidence_requires_manager_not_just_employee(client, db, tenant_a, storage):
    product = _create_product(client, tenant_a)
    _, version = _create_verified_document_version(client, tenant_a)

    headers = _employee_headers(db, tenant_a)
    response = client.post(
        "/evidence",
        json={"document_version_id": version["id"], "product_id": product["id"]},
        headers=headers,
    )

    assert response.status_code == 403


# --- Staleness --------------------------------------------------------------


def test_evidence_marked_stale_when_document_version_superseded(client, tenant_a, storage):
    product = _create_product(client, tenant_a)
    document, version_v1 = _create_verified_document_version(client, tenant_a, content=PDF_BYTES)

    evidence = _create_evidence(
        client, tenant_a, document_version_id=version_v1["id"], product_id=product["id"],
    ).json()
    assert evidence["is_current"] is True

    # Replacement upload - a genuinely different file for the same
    # logical document.
    _upload_version(client, tenant_a, document["id"], content=PDF_BYTES_V2)

    refetched = client.get(f"/evidence/{evidence['id']}", headers=tenant_a["headers"]).json()
    assert refetched["is_current"] is False
    assert refetched["stale_reason"] == "DOCUMENT_VERSION_SUPERSEDED"


def test_evidence_isolated_across_organizations(client, tenant_a, tenant_b, storage):
    product = _create_product(client, tenant_a)
    _, version = _create_verified_document_version(client, tenant_a)
    evidence = _create_evidence(
        client, tenant_a, document_version_id=version["id"], product_id=product["id"],
    ).json()

    response = client.get(f"/evidence/{evidence['id']}", headers=tenant_b["headers"])
    assert response.status_code == 404


def test_delete_evidence(client, tenant_a, storage):
    product = _create_product(client, tenant_a)
    _, version = _create_verified_document_version(client, tenant_a)
    evidence = _create_evidence(
        client, tenant_a, document_version_id=version["id"], product_id=product["id"],
    ).json()

    response = client.delete(f"/evidence/{evidence['id']}", headers=tenant_a["headers"])
    assert response.status_code == 200

    get_response = client.get(f"/evidence/{evidence['id']}", headers=tenant_a["headers"])
    assert get_response.status_code == 404
