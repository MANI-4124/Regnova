from __future__ import annotations

import pytest

from app.core.dependencies import get_document_storage
from app.core.settings import get_settings
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
    """
    Overrides get_document_storage the same way the `client` fixture
    overrides get_db_session - a real LocalFilesystemStorage under a
    throwaway tmp_path, not the app's configured (relative-path)
    storage root.
    """
    backend = LocalFilesystemStorage(tmp_path)
    app.dependency_overrides[get_document_storage] = lambda: backend
    yield backend
    app.dependency_overrides.pop(get_document_storage, None)


def _employee_headers(db, tenant):
    """
    A role that passes require_employee (upload/field-entry) but fails
    require_manager (verify/reject/quarantine) - for the RBAC tier test.
    """
    role = Role(organization_id=tenant["organization"].id, code="EMPLOYEE", name="Employee")
    db.add(role)
    db.flush()

    user = User(
        organization_id=tenant["organization"].id,
        role_id=role.id,
        first_name="Rank",
        last_name="File",
        email="employee-doc@example.com",
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


def _create_document(client, tenant, document_type="GMP_CERTIFICATE"):
    response = client.post(
        "/documents",
        json={"document_type": document_type},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_version(
    client, tenant, document_id, *,
    content=PDF_BYTES, filename="cert.pdf", content_type="application/pdf", notes=None, headers=None,
):
    files = {"file": (filename, content, content_type)}
    data = {"notes": notes} if notes is not None else {}
    return client.post(
        f"/documents/{document_id}/versions",
        files=files,
        data=data,
        headers=headers or tenant["headers"],
    )


def _verify_version(client, tenant, document_id, version_id, note=None):
    return client.post(
        f"/documents/{document_id}/versions/{version_id}/verify",
        json={"note": note},
        headers=tenant["headers"],
    )


# --- Document ----------------------------------------------------------


def test_create_document(client, tenant_a):
    document = _create_document(client, tenant_a, document_type="COA")
    assert document["document_type"] == "COA"
    assert document["organization_id"] == str(tenant_a["organization"].id)


def test_create_document_rejects_unknown_type(client, tenant_a):
    response = client.post(
        "/documents",
        json={"document_type": "NOT_A_REAL_TYPE"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 422


def test_documents_isolated_across_organizations(client, tenant_a, tenant_b):
    document = _create_document(client, tenant_a)

    response = client.get(f"/documents/{document['id']}", headers=tenant_b["headers"])
    assert response.status_code == 404


# --- DocumentVersion: upload, checksum dedup, supersession --------------


def test_upload_creates_version_in_review_required(client, tenant_a, storage):
    document = _create_document(client, tenant_a)

    response = _upload_version(client, tenant_a, document["id"])
    assert response.status_code == 200, response.text
    version = response.json()

    assert version["status"] == "REVIEW_REQUIRED"
    assert version["version_number"] == 1
    assert version["supersedes_id"] is None
    assert version["superseded_by_id"] is None
    assert len(version["checksum"]) == 64  # sha256 hex
    assert storage.exists(version["checksum"])


def test_reuploading_identical_bytes_creates_no_new_version(client, tenant_a, storage):
    """
    Explicitly required: checksum-based dedup means a byte-identical
    re-upload for the SAME document is a true no-op, matching the
    file-loader's own "unchanged content is a no-op" precedent - not a
    second version, not an error.
    """
    document = _create_document(client, tenant_a)

    first = _upload_version(client, tenant_a, document["id"]).json()
    second = _upload_version(client, tenant_a, document["id"]).json()

    assert second["id"] == first["id"]
    assert second["version_number"] == 1

    versions = client.get(
        f"/documents/{document['id']}/versions", headers=tenant_a["headers"],
    ).json()
    assert len(versions) == 1


def test_reuploading_different_bytes_creates_new_version_and_supersedes(client, tenant_a, storage):
    document = _create_document(client, tenant_a)

    first = _upload_version(client, tenant_a, document["id"], content=PDF_BYTES).json()
    second = _upload_version(client, tenant_a, document["id"], content=PDF_BYTES_V2).json()

    assert second["version_number"] == 2
    assert second["supersedes_id"] == first["id"]
    assert second["superseded_by_id"] is None

    first_refetched = client.get(
        f"/documents/{document['id']}/versions/{first['id']}", headers=tenant_a["headers"],
    ).json()
    assert first_refetched["superseded_by_id"] == second["id"]

    versions = client.get(
        f"/documents/{document['id']}/versions", headers=tenant_a["headers"],
    ).json()
    assert len(versions) == 2


def test_same_bytes_across_different_documents_is_not_blocked(client, tenant_a, storage):
    """
    Dedup is storage-level (don't write the same blob twice), not an
    application-level "reject duplicate content" rule - the same LOA
    genuinely can back two different logical documents.
    """
    document_1 = _create_document(client, tenant_a, document_type="LOA")
    document_2 = _create_document(client, tenant_a, document_type="LOA")

    response_1 = _upload_version(client, tenant_a, document_1["id"], content=PDF_BYTES)
    response_2 = _upload_version(client, tenant_a, document_2["id"], content=PDF_BYTES)

    assert response_1.status_code == 200
    assert response_2.status_code == 200
    assert response_1.json()["id"] != response_2.json()["id"]
    assert response_1.json()["checksum"] == response_2.json()["checksum"]


def test_upload_rejects_oversized_file(client, tenant_a, storage, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "document_max_size_bytes", 10)

    document = _create_document(client, tenant_a)
    response = _upload_version(client, tenant_a, document["id"], content=b"x" * 100)

    assert response.status_code == 400


def test_upload_rejects_content_not_matching_declared_type(client, tenant_a, storage):
    document = _create_document(client, tenant_a)

    response = _upload_version(
        client, tenant_a, document["id"],
        content=b"this is plainly not a pdf", filename="fake.pdf", content_type="application/pdf",
    )

    assert response.status_code == 400


def test_upload_accepts_csv_by_declared_type_and_decodable_text(client, tenant_a, storage):
    document = _create_document(client, tenant_a, document_type="FORMULA_INCI")

    response = _upload_version(
        client, tenant_a, document["id"],
        content=b"ingredient,pct\nAqua,80.0\n", filename="formula.csv", content_type="text/csv",
    )

    assert response.status_code == 200, response.text
    assert response.json()["content_type"] == "text/csv"


# --- Review transitions --------------------------------------------------


def test_verify_document_version(client, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    response = _verify_version(client, tenant_a, document["id"], version["id"], note="looks correct")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "VERIFIED"
    assert body["reviewed_by_user_id"] == str(tenant_a["user"].id)
    assert body["review_note"] == "looks correct"


def test_verify_requires_manager_not_just_employee(client, db, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    headers = _employee_headers(db, tenant_a)
    response = client.post(
        f"/documents/{document['id']}/versions/{version['id']}/verify",
        json={},
        headers=headers,
    )
    assert response.status_code == 403


def test_reject_requires_nonempty_note(client, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    response = client.post(
        f"/documents/{document['id']}/versions/{version['id']}/reject",
        json={"note": ""},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 422


def test_reject_document_version(client, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    response = client.post(
        f"/documents/{document['id']}/versions/{version['id']}/reject",
        json={"note": "wrong document type entirely"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_transition_not_allowed_once_already_decided(client, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    first = _verify_version(client, tenant_a, document["id"], version["id"])
    assert first.status_code == 200

    second = _verify_version(client, tenant_a, document["id"], version["id"])
    assert second.status_code == 409


# --- Manual field entry ---------------------------------------------------


def test_set_field_defaults_confidence_to_null(client, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    response = client.put(
        f"/documents/{document['id']}/versions/{version['id']}/fields/expiry_date",
        json={"value": "2027-06-30"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    field = response.json()
    assert len(field["revisions"]) == 1
    assert field["revisions"][0]["value"] == "2027-06-30"
    assert field["revisions"][0]["confidence"] is None
    assert field["revisions"][0]["method"] == "MANUAL"


def test_set_field_can_record_an_explicit_confidence(client, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    response = client.put(
        f"/documents/{document['id']}/versions/{version['id']}/fields/manufacturer",
        json={"value": "Acme Labs", "confidence": 0.8},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200
    assert response.json()["revisions"][0]["confidence"] == 0.8


def test_correcting_a_field_creates_a_new_revision_not_an_overwrite(client, tenant_a, storage):
    """
    AC-FR-04-02: corrections create a revision and an audit event -
    never a silent overwrite, even for manual-only entry.
    """
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    client.put(
        f"/documents/{document['id']}/versions/{version['id']}/fields/expiry_date",
        json={"value": "2027-06-30"},
        headers=tenant_a["headers"],
    )
    response = client.put(
        f"/documents/{document['id']}/versions/{version['id']}/fields/expiry_date",
        json={"value": "2027-07-15"},
        headers=tenant_a["headers"],
    )

    assert response.status_code == 200
    field = response.json()
    assert len(field["revisions"]) == 2
    assert field["revisions"][0]["value"] == "2027-06-30"
    assert field["revisions"][0]["revision_number"] == 1
    assert field["revisions"][1]["value"] == "2027-07-15"
    assert field["revisions"][1]["revision_number"] == 2


def test_fields_locked_once_document_version_verified(client, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_version(client, tenant_a, document["id"]).json()

    _verify_version(client, tenant_a, document["id"], version["id"])

    response = client.put(
        f"/documents/{document['id']}/versions/{version['id']}/fields/expiry_date",
        json={"value": "2027-06-30"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 409
