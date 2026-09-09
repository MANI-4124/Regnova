from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.dependencies import get_document_storage
from app.main import app
from app.modules.audit.models import AuditVisibilityTier
from app.modules.audit.repository import AuditEventRepository, OutboxRepository
from app.modules.audit.worker import dispatch_pending_events
from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.finding.repository import FindingRevisionRepository
from app.modules.internal_role_assignment.models import (
    InternalRoleAssignment,
    InternalRoleAssignmentStatus,
    InternalRoleCode,
)
from app.modules.organization.models import Organization
from app.modules.role.models import Role
from app.modules.user.models import User
from app.storage import LocalFilesystemStorage


@pytest.fixture()
def storage(tmp_path):
    backend = LocalFilesystemStorage(tmp_path)
    app.dependency_overrides[get_document_storage] = lambda: backend
    yield backend
    app.dependency_overrides.pop(get_document_storage, None)


# --- Shared helpers (duplicated per this codebase's own test-file convention) ---


def _create_product(client, tenant, name="Widget"):
    response = client.post("/products", json={"name": name}, headers=tenant["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _create_version(client, tenant, product_id, version="1.0.0", category="Claims"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version, "category": category},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _publish_version(client, tenant, product_id, version_id):
    response = client.post(
        f"/products/{product_id}/versions/{version_id}/publish", headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_state(client, tenant, product_id, product_version_id, jurisdiction="Malaysia"):
    response = client.post(
        f"/products/{product_id}/market-states",
        json={
            "product_version_id": product_version_id,
            "market": jurisdiction,
            "jurisdiction": jurisdiction,
        },
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _submit_verify_activate(client, writer, path):
    response = client.post(f"{path}/submit-for-review", headers=writer["headers"])
    assert response.status_code == 200, response.text
    response = client.post(
        f"{path}/verify", json={"rationale": "Verified."}, headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"{path}/activate", json={"rationale": "Approved."}, headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_requirement_version(client, writer, **overrides):
    requirement = client.post("/requirements", json={}, headers=writer["headers"]).json()
    payload = {
        "jurisdiction": "Malaysia",
        "market": "Malaysia",
        "authority": "NPRA",
        "category": "Claims",
        "dimension": "CLAIMS",
        "obligation_type": "PROHIBITED_THERAPEUTIC_CLAIM",
        "canonical_statement": "Claims must not be therapeutic.",
        "default_severity": "MAJOR",
        "is_hard_gate": True,
        "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
    }
    payload.update(overrides)
    response = client.post(
        f"/requirements/{requirement['id']}/versions", json=payload, headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return requirement, response.json()


def _create_rule_version(client, writer, requirement_version_id, **overrides):
    rule = client.post("/rules", json={}, headers=writer["headers"]).json()
    payload = {
        "requirement_version_id": requirement_version_id,
        "condition": {"op": "equals", "field": "wording", "value": "cures acne"},
        "output_type": "FINDING_PROPOSAL",
        "unknown_behavior": "HUMAN_REVIEW",
    }
    payload.update(overrides)
    response = client.post(
        f"/rules/{rule['id']}/versions", json=payload, headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return rule, response.json()


def _create_active_release(client, writer, rule_version_ids, requirement_version_ids, jurisdiction="Malaysia"):
    source = client.post("/sources", headers=writer["headers"]).json()
    source_version = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "Test Source", "issuing_authority": "Test Authority",
            "jurisdiction": jurisdiction, "tier": 1, "source_type": "OFFICIAL_GUIDELINE",
        },
        headers=writer["headers"],
    ).json()
    activated_source = _submit_verify_activate(
        client, writer, f"/sources/{source['id']}/versions/{source_version['id']}",
    )
    response = client.post(
        "/regulatory-basis-releases",
        json={
            "jurisdiction": jurisdiction, "market": jurisdiction, "category": "Claims",
            "source_version_ids": [activated_source["id"]],
            "requirement_version_ids": requirement_version_ids,
            "rule_version_ids": rule_version_ids,
        },
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _setup_finding_proposal_state(client, tenant, writer):
    """
    One CLAIMS FINDING_PROPOSAL rule matching wording=="cures acne",
    published product version, active release, state - a market
    readiness run with a matching claim proposes exactly one Finding.
    """
    requirement, requirement_version = _create_requirement_version(client, writer)
    requirement_version = _submit_verify_activate(
        client, writer, f"/requirements/{requirement['id']}/versions/{requirement_version['id']}",
    )
    rule, rule_version = _create_rule_version(client, writer, requirement_version["id"])
    rule_version = _submit_verify_activate(
        client, writer, f"/rules/{rule['id']}/versions/{rule_version['id']}",
    )
    _create_active_release(
        client, writer, rule_version_ids=[rule_version["id"]], requirement_version_ids=[requirement_version["id"]],
    )

    product = _create_product(client, tenant)
    version = _create_version(client, tenant, product["id"])
    _publish_version(client, tenant, product["id"], version["id"])
    state = _create_state(client, tenant, product["id"], version["id"])

    return product, version, state


def _run_market_readiness(client, tenant, state_id, input_facts=None):
    response = client.post(
        "/market-readiness-runs",
        json={"product_market_state_id": state_id, "input_facts": input_facts or {}},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_or_create_tenant_zero(db):
    organization = db.query(Organization).filter(Organization.is_internal.is_(True)).first()
    if organization is None:
        organization = Organization(
            name="RegNova", industry="Regulatory Technology", country="US", is_internal=True,
        )
        db.add(organization)
        db.flush()
    return organization


def _headers_for(user, organization_id, role_id):
    token = create_access_token(
        subject=str(user.id),
        additional_claims={"organization_id": str(organization_id), "role_id": str(role_id)},
    )
    return {"Authorization": f"Bearer {token}"}


def _grant_internal_role(db, role_code, label):
    organization = _get_or_create_tenant_zero(db)

    role = (
        db.query(Role)
        .filter(Role.organization_id == organization.id, Role.code == "EMPLOYEE")
        .first()
    )
    if role is None:
        role = Role(organization_id=organization.id, code="EMPLOYEE", name="Internal Staff")
        db.add(role)
        db.flush()

    user = User(
        organization_id=organization.id,
        role_id=role.id,
        first_name="Internal",
        last_name=label,
        email=f"internal-{label.lower()}-{uuid.uuid4()}@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(user)
    db.flush()

    payload = {"user_id": str(user.id), "role_code": role_code, "scope": None}
    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
    ).hexdigest()
    assignment = InternalRoleAssignment(
        user_id=user.id,
        role_code=role_code,
        status=InternalRoleAssignmentStatus.APPROVED.value,
        proposed_by_user_id=user.id,
        proposed_at=datetime.now(timezone.utc),
        rationale="test setup",
        approver_user_id=user.id,
        decided_at=datetime.now(timezone.utc),
        content_hash=content_hash,
    )
    db.add(assignment)
    db.commit()

    return {
        "user": user,
        "organization": organization,
        "role": role,
        "headers": _headers_for(user, organization.id, role.id),
    }


def _matching_claim_facts():
    return {"CLAIMS": {"product": {}, "claims": [{"claim_id": "c1", "wording": "cures acne"}]}}


# --- (1) FINDINGS_CSV: generate, download, redaction reuse ----------------


def test_customer_generates_and_downloads_findings_csv(client, db, tenant_a, regulatory_content_writer, storage):
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)
    _run_market_readiness(client, tenant_a, state["id"], _matching_claim_facts())

    create_resp = client.post(
        "/exports", json={"product_market_state_id": state["id"]}, headers=tenant_a["headers"],
    )
    assert create_resp.status_code == 200, create_resp.text
    export = create_resp.json()
    assert export["status"] == "READY"
    assert export["export_type"] == "FINDINGS_CSV"
    assert export["content_type"] == "text/csv"

    download_resp = client.get(f"/exports/{export['id']}/download", headers=tenant_a["headers"])
    assert download_resp.status_code == 200
    assert download_resp.headers["content-type"].startswith("text/csv")
    assert f'export_{export["id"]}.csv' in download_resp.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(download_resp.text)))
    assert len(rows) == 1
    assert rows[0]["dimension"] == "CLAIMS"
    assert rows[0]["status"] == "PROPOSED"
    # Still-unreviewed engine proposal - rationale stays internal-only,
    # blank in the customer-facing CSV. Reuses AUDIT_BUILDERS'
    # FindingProposed split, not a separately-maintained redaction rule.
    assert rows[0]["rationale"] == ""


def test_findings_csv_rationale_populates_after_human_decision(client, db, tenant_a, regulatory_content_writer, storage):
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)
    run_result = _run_market_readiness(client, tenant_a, state["id"], _matching_claim_facts())

    findings_resp = client.get(
        "/findings", params={"product_market_state_id": state["id"]}, headers=tenant_a["headers"],
    )
    finding_id = findings_resp.json()[0]["id"]

    client.post(
        f"/findings/{finding_id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "Acknowledged, remediating label copy."},
        headers=tenant_a["headers"],
    )

    create_resp = client.post(
        "/exports", json={"product_market_state_id": state["id"]}, headers=tenant_a["headers"],
    )
    export = create_resp.json()
    download_resp = client.get(f"/exports/{export['id']}/download", headers=tenant_a["headers"])
    rows = list(csv.DictReader(io.StringIO(download_resp.text)))

    assert rows[0]["status"] == "OPEN"
    assert rows[0]["rationale"] == "Acknowledged, remediating label copy."


def test_findings_csv_export_is_customer_scoped_cross_org_404(client, db, tenant_a, tenant_b, regulatory_content_writer, storage):
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)
    create_resp = client.post(
        "/exports", json={"product_market_state_id": state["id"]}, headers=tenant_a["headers"],
    )
    export = create_resp.json()

    cross_org = client.get(f"/exports/{export['id']}/download", headers=tenant_b["headers"])
    assert cross_org.status_code == 404


# --- (2) EVIDENCE_PACK_JSON: internal-only clearance ------------------


def test_evidence_pack_generation_requires_internal_regulatory_clearance(client, db, tenant_a, regulatory_content_writer):
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)
    _run_market_readiness(client, tenant_a, state["id"], _matching_claim_facts())

    response = client.post(
        "/exports/internal",
        json={
            "organization_id": str(tenant_a["organization"].id),
            "product_market_state_id": state["id"],
        },
        headers=tenant_a["headers"],  # a customer manager, not internal staff
    )
    assert response.status_code == 403


def test_evidence_pack_generation_and_download_by_ra(client, db, tenant_a, regulatory_content_writer, storage):
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)
    run_result = _run_market_readiness(client, tenant_a, state["id"], _matching_claim_facts())
    ra = _grant_internal_role(db, InternalRoleCode.RA.value, "Reader")

    create_resp = client.post(
        "/exports/internal",
        json={
            "organization_id": str(tenant_a["organization"].id),
            "product_market_state_id": state["id"],
        },
        headers=ra["headers"],
    )
    assert create_resp.status_code == 200, create_resp.text
    export = create_resp.json()
    assert export["status"] == "READY"
    assert export["export_type"] == "EVIDENCE_PACK_JSON"
    assert export["state_snapshot_id"] == run_result["id"]

    download_resp = client.get(f"/exports/{export['id']}/download", headers=ra["headers"])
    assert download_resp.status_code == 200
    pack = download_resp.json()
    assert pack["header"]["state_snapshot_id"] == run_result["id"]
    assert "reconstruction_note" in pack["header"]
    assert len(pack["findings"]) == 1
    assert pack["findings"][0]["rationale"]  # internal audience - unredacted
    assert pack["omitted"]["approvals"]

    dispatch_pending_events(db)

    # ExportGenerated at INTERNAL_REGULATORY tier.
    generated = AuditEventRepository(db).get_all(
        organization_id=tenant_a["organization"].id,
        visibility_tiers=[AuditVisibilityTier.INTERNAL_REGULATORY.value],
        event_type="ExportGenerated",
    )
    assert len(generated) == 1
    assert generated[0].payload["export_type"] == "EVIDENCE_PACK_JSON"

    # Self-audited exactly like AuditLogQueried - one for generate, one
    # for download, both filed under the CUSTOMER org, TECHNICAL_SECURITY.
    accessed = AuditEventRepository(db).get_all(
        organization_id=tenant_a["organization"].id,
        visibility_tiers=[AuditVisibilityTier.TECHNICAL_SECURITY.value],
        event_type="EvidencePackAccessed",
    )
    assert len(accessed) == 2
    actions = sorted(e.payload["action"] for e in accessed)
    assert actions == ["download", "generate"]
    assert all(e.actor_user_id == ra["user"].id for e in accessed)


def test_evidence_pack_requires_existing_snapshot(client, db, tenant_a, regulatory_content_writer):
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)
    ra = _grant_internal_role(db, InternalRoleCode.RA.value, "Reader2")

    response = client.post(
        "/exports/internal",
        json={
            "organization_id": str(tenant_a["organization"].id),
            "product_market_state_id": state["id"],
        },
        headers=ra["headers"],
    )
    assert response.status_code == 409


def test_export_generated_customer_visible_for_findings_csv(client, db, tenant_a, regulatory_content_writer, storage):
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)
    client.post("/exports", json={"product_market_state_id": state["id"]}, headers=tenant_a["headers"])
    dispatch_pending_events(db)

    events = client.get(
        "/audit-events", params={"event_type": "ExportGenerated"}, headers=tenant_a["headers"],
    ).json()
    assert len(events) == 1
    assert events[0]["payload"]["export_type"] == "FINDINGS_CSV"


# --- (3) AC-FR-14-01: resolves findings as-of the pinned snapshot ----------


def test_evidence_pack_resolves_findings_as_of_snapshot_not_current(client, db, tenant_a, regulatory_content_writer, storage):
    """
    The one behavior AC-FR-14-01 actually demands: a Finding proposed
    under snapshot A, then transitioned by a human AFTER that snapshot
    was taken, must still read as it stood AT snapshot A's own time
    when the evidence pack is explicitly pinned to snapshot A - not
    today's current, human-decided state.
    """
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)
    snapshot_a = _run_market_readiness(client, tenant_a, state["id"], _matching_claim_facts())

    findings_resp = client.get(
        "/findings", params={"product_market_state_id": state["id"]}, headers=tenant_a["headers"],
    )
    finding_id = findings_resp.json()[0]["id"]

    # Human transition happens AFTER snapshot A.
    accept_resp = client.post(
        f"/findings/{finding_id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "Acknowledged after the fact."},
        headers=tenant_a["headers"],
    )
    assert accept_resp.status_code == 200
    # confirms the live finding really did move on
    assert accept_resp.json()["revisions"][-1]["status"] == "OPEN"

    # TimestampMixin.created_at is server_default=func.now(), which on
    # SQLite is CURRENT_TIMESTAMP - second precision only. This whole
    # sequence runs well under a second, so the snapshot's created_at
    # and the accept()-produced revision's created_at can land in the
    # SAME second, making them genuinely indistinguishable by value
    # alone. Backdating the later revision explicitly (a legitimate,
    # common technique for testing point-in-time logic) makes the test
    # deterministic rather than depending on real elapsed wall-clock
    # time separating two fast in-process calls.
    latest_revision = FindingRevisionRepository(db).get_latest(uuid.UUID(finding_id))
    latest_revision.created_at = latest_revision.created_at + timedelta(seconds=10)
    db.add(latest_revision)
    db.commit()

    ra = _grant_internal_role(db, InternalRoleCode.RA.value, "AsOfReader")
    create_resp = client.post(
        "/exports/internal",
        json={
            "organization_id": str(tenant_a["organization"].id),
            "product_market_state_id": state["id"],
            "state_snapshot_id": snapshot_a["id"],  # explicit - the OLD snapshot
        },
        headers=ra["headers"],
    )
    export = create_resp.json()
    assert export["status"] == "READY"

    pack = client.get(f"/exports/{export['id']}/download", headers=ra["headers"]).json()

    assert len(pack["findings"]) == 1
    entry = pack["findings"][0]
    assert entry["finding_id"] == finding_id
    # Engine-authored shape (status="PROPOSED") is what get_latest_as_of
    # must resolve here - the human-decided shape ("to_status": "OPEN")
    # would only appear if this incorrectly read the CURRENT revision
    # instead of the one current as of snapshot_a's own created_at.
    assert entry.get("status") == "PROPOSED"
    assert "to_status" not in entry


# --- (4) AC-FR-14-02: deactivated user cannot download ---------------------


def test_deactivated_user_cannot_download_previously_generated_export(client, db, tenant_a, regulatory_content_writer, storage):
    product, version, state = _setup_finding_proposal_state(client, tenant_a, regulatory_content_writer)

    create_resp = client.post(
        "/exports", json={"product_market_state_id": state["id"]}, headers=tenant_a["headers"],
    )
    export = create_resp.json()

    # Confirm the SAME credentials work before deactivation.
    ok = client.get(f"/exports/{export['id']}/download", headers=tenant_a["headers"])
    assert ok.status_code == 200

    tenant_a["user"].is_active = False
    db.add(tenant_a["user"])
    db.commit()

    blocked = client.get(f"/exports/{export['id']}/download", headers=tenant_a["headers"])
    assert blocked.status_code == 401
