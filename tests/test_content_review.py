from __future__ import annotations

from app.modules.audit.repository import OutboxRepository
from app.modules.audit.worker import dispatch_pending_events
from app.modules.content_review.repository import ContentVersionTransitionRepository
from app.modules.role.models import Role
from app.modules.user.models import User


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


def _create_rule_version(client, writer, requirement_version_id, **overrides):
    rule = client.post("/rules", json={}, headers=writer["headers"]).json()

    payload = {
        "requirement_version_id": requirement_version_id,
        "condition": {"op": "exists", "field": "wording"},
        "output_type": "REQUIREMENT_RESULT",
    }
    payload.update(overrides)

    response = client.post(
        f"/rules/{rule['id']}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return rule, response.json()


def _create_source_version(client, writer, **overrides):
    source = client.post("/sources", headers=writer["headers"]).json()

    payload = {
        "title": "Test Source",
        "issuing_authority": "Test Authority",
        "jurisdiction": "Malaysia",
        "tier": 1,
        "source_type": "OFFICIAL_GUIDELINE",
    }
    payload.update(overrides)

    response = client.post(
        f"/sources/{source['id']}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return source, response.json()


def _non_regulatory_headers(db, tenant):
    """A plain customer-org user - holds no InternalRoleAssignment at all."""
    from app.modules.auth.jwt import create_access_token
    from app.modules.auth.security import hash_password

    role = Role(organization_id=tenant["organization"].id, code="EMPLOYEE", name="Employee")
    db.add(role)
    db.flush()

    user = User(
        organization_id=tenant["organization"].id,
        role_id=role.id,
        first_name="Plain",
        last_name="User",
        email="plain.user@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        subject=str(user.id),
        additional_claims={"organization_id": str(tenant["organization"].id), "role_id": str(role.id)},
    )
    return {"Authorization": f"Bearer {token}"}


# --- authority split (point 1) ------------------------------------------


def test_non_regulatory_user_cannot_draft_requirement_version(client, db, tenant_a):
    headers = _non_regulatory_headers(db, tenant_a)

    response = client.post("/requirements", json={}, headers=headers)
    assert response.status_code == 403


def test_advisor_can_draft_and_submit_but_not_verify(client, regulatory_content_advisor):
    requirement, version = _create_requirement_version(client, regulatory_content_advisor)
    assert version["status"] == "DRAFT"
    assert version["author_user_id"] == str(regulatory_content_advisor["user"].id)

    path = f"/requirements/{requirement['id']}/versions/{version['id']}"

    submit = client.post(f"{path}/submit-for-review", headers=regulatory_content_advisor["headers"])
    assert submit.status_code == 200
    assert submit.json()["status"] == "IN_REVIEW"

    verify = client.post(
        f"{path}/verify",
        json={"rationale": "Self-approving my own draft."},
        headers=regulatory_content_advisor["headers"],
    )
    assert verify.status_code == 403


def test_advisor_cannot_activate_or_reject_either(client, regulatory_content_advisor, regulatory_content_writer):
    """
    An advisor can't skip straight to activate()/reject() either - both
    are REGULATORY_KNOWLEDGE_LEAD-only, same as verify().
    """
    requirement, version = _create_requirement_version(client, regulatory_content_advisor)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"

    client.post(f"{path}/submit-for-review", headers=regulatory_content_advisor["headers"])

    activate = client.post(
        f"{path}/activate",
        json={"rationale": "Approving my own draft."},
        headers=regulatory_content_advisor["headers"],
    )
    assert activate.status_code == 403

    reject = client.post(
        f"{path}/reject",
        json={"rationale": "Rejecting my own draft."},
        headers=regulatory_content_advisor["headers"],
    )
    assert reject.status_code == 403


def test_service_layer_rejects_advisor_verify_even_bypassing_the_router(
    client, db, regulatory_content_advisor,
):
    """
    Defense-in-depth: ContentReviewWorkflow re-checks verifier authority
    itself rather than trusting the router dependency alone - the HTTP
    tests above never actually reach this code path, since
    require_regulatory_content_writer already blocks an advisor before
    the service is called. Exercised here via a direct service call
    (the same way a script bypassing HTTP, e.g. scripts/seed_regulatory_
    sources.py's convention, would reach it).
    """
    from app.modules.content_review.exceptions import ContentVersionTransitionNotAuthorized
    from app.modules.requirement_version.service import RequirementVersionService

    requirement, version = _create_requirement_version(client, regulatory_content_advisor)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"
    client.post(f"{path}/submit-for-review", headers=regulatory_content_advisor["headers"])

    import uuid

    service = RequirementVersionService(db)
    try:
        service.verify(
            uuid.UUID(requirement["id"]), uuid.UUID(version["id"]),
            actor_user_id=regulatory_content_advisor["user"].id,
            rationale="Self-approving directly through the service.",
        )
        assert False, "expected ContentVersionTransitionNotAuthorized"
    except ContentVersionTransitionNotAuthorized:
        pass


def test_knowledge_lead_can_run_the_whole_pipeline_alone(client, regulatory_content_writer):
    """Knowledge Lead is a strict superset - can draft, submit, verify, and activate without an advisor."""
    requirement, version = _create_requirement_version(client, regulatory_content_writer)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"

    assert client.post(f"{path}/submit-for-review", headers=regulatory_content_writer["headers"]).status_code == 200
    verify = client.post(
        f"{path}/verify",
        json={"rationale": "Verified."},
        headers=regulatory_content_writer["headers"],
    )
    assert verify.status_code == 200
    activate = client.post(
        f"{path}/activate",
        json={"rationale": "Activated."},
        headers=regulatory_content_writer["headers"],
    )
    assert activate.status_code == 200
    assert activate.json()["status"] == "ACTIVE"


# --- transition order + audit trail (point 2) ----------------------------


def test_out_of_order_verify_is_rejected(client, regulatory_content_writer):
    """verify() only accepts IN_REVIEW - calling it on a still-DRAFT version is an illegal jump."""
    requirement, version = _create_requirement_version(client, regulatory_content_writer)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"

    response = client.post(
        f"{path}/verify",
        json={"rationale": "Skipping submission."},
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTENT_VERSION_TRANSITION_NOT_ALLOWED"


def test_out_of_order_activate_is_rejected(client, regulatory_content_writer):
    """activate() only accepts VERIFIED - calling it while still IN_REVIEW (never verified) is illegal."""
    requirement, version = _create_requirement_version(client, regulatory_content_writer)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"

    client.post(f"{path}/submit-for-review", headers=regulatory_content_writer["headers"])

    response = client.post(
        f"{path}/activate",
        json={"rationale": "Skipping verification."},
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTENT_VERSION_TRANSITION_NOT_ALLOWED"


def test_update_rejected_once_submitted_for_review(client, regulatory_content_writer):
    """Content is only editable while DRAFT - once submitted, edits must go through reject() first."""
    requirement, version = _create_requirement_version(client, regulatory_content_writer)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"

    client.post(f"{path}/submit-for-review", headers=regulatory_content_writer["headers"])

    response = client.put(
        path,
        json={"notes": "sneaking in an edit"},
        headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 409


def test_reject_returns_version_to_draft_and_makes_it_editable_again(client, regulatory_content_writer):
    requirement, version = _create_requirement_version(client, regulatory_content_writer)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"

    client.post(f"{path}/submit-for-review", headers=regulatory_content_writer["headers"])

    reject = client.post(
        f"{path}/reject",
        json={"rationale": "Statement needs rework."},
        headers=regulatory_content_writer["headers"],
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "DRAFT"

    edit = client.put(
        path,
        json={"notes": "reworked"},
        headers=regulatory_content_writer["headers"],
    )
    assert edit.status_code == 200
    assert edit.json()["notes"] == "reworked"


def test_full_lifecycle_records_transition_history_and_publishes_events(client, db, regulatory_content_writer):
    requirement, version = _create_requirement_version(client, regulatory_content_writer)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"

    client.post(f"{path}/submit-for-review", headers=regulatory_content_writer["headers"])
    client.post(
        f"{path}/verify",
        json={"rationale": "Matches the primary source text."},
        headers=regulatory_content_writer["headers"],
    )
    activated = client.post(
        f"{path}/activate",
        json={"rationale": "Cleared for release inclusion."},
        headers=regulatory_content_writer["headers"],
    ).json()

    assert activated["status"] == "ACTIVE"
    assert activated["verified_at"] is not None
    assert activated["reviewer_user_id"] == str(regulatory_content_writer["user"].id)

    import uuid

    transitions = ContentVersionTransitionRepository(db).get_for_content(
        "requirement_version", uuid.UUID(version["id"]),
    )
    hops = [(t.from_status, t.to_status) for t in transitions]
    assert hops == [
        (None, "DRAFT"),
        ("DRAFT", "IN_REVIEW"),
        ("IN_REVIEW", "VERIFIED"),
        ("VERIFIED", "ACTIVE"),
    ]
    assert transitions[2].rationale == "Matches the primary source text."
    assert transitions[3].rationale == "Cleared for release inclusion."
    assert transitions[0].rationale is None  # draft - nothing to justify yet

    events = [
        e for e in OutboxRepository(db).get_all()
        if e.event_type == "ContentVersionTransitioned"
        and e.payload.get("content_version_id") == version["id"]
    ]
    assert [e.payload["to_status"] for e in events] == ["IN_REVIEW", "VERIFIED", "ACTIVE"]
    for event in events:
        assert event.payload["content_type"] == "requirement_version"


# --- shared across all three content types --------------------------------


def test_workflow_shared_by_rule_version_and_source_version(client, regulatory_content_writer):
    requirement, requirement_version = _create_requirement_version(client, regulatory_content_writer)
    rule, rule_version = _create_rule_version(client, regulatory_content_writer, requirement_version["id"])
    source, source_version = _create_source_version(client, regulatory_content_writer)

    for path in (
        f"/rules/{rule['id']}/versions/{rule_version['id']}",
        f"/sources/{source['id']}/versions/{source_version['id']}",
    ):
        assert client.post(f"{path}/submit-for-review", headers=regulatory_content_writer["headers"]).status_code == 200
        assert client.post(
            f"{path}/verify",
            json={"rationale": "Verified."},
            headers=regulatory_content_writer["headers"],
        ).status_code == 200
        activate = client.post(
            f"{path}/activate",
            json={"rationale": "Activated."},
            headers=regulatory_content_writer["headers"],
        )
        assert activate.status_code == 200
        assert activate.json()["status"] == "ACTIVE"


# --- notification consumer (point 3) --------------------------------------


def test_submitted_for_review_notifies_active_knowledge_leads(
    client, db, regulatory_content_advisor, regulatory_content_writer,
):
    """
    Integration with the shared notification mechanism (see
    tests/test_notification.py for that mechanism's own contract):
    dispatching a SubmittedForReview ContentVersionTransitioned event
    creates a real Notification row for the active
    REGULATORY_KNOWLEDGE_LEAD holder - here, regulatory_content_writer.
    """
    from app.modules.notification.repository import NotificationRepository

    requirement, version = _create_requirement_version(client, regulatory_content_advisor)
    path = f"/requirements/{requirement['id']}/versions/{version['id']}"
    client.post(f"{path}/submit-for-review", headers=regulatory_content_advisor["headers"])

    dispatched = dispatch_pending_events(db)
    assert dispatched >= 1

    notifications = NotificationRepository(db).get_all_for_recipient(
        regulatory_content_writer["user"].id,
    )
    assert len(notifications) == 1
    assert notifications[0].type == "ContentVersionTransitioned"
    assert notifications[0].payload["content_version_id"] == version["id"]
    assert notifications[0].payload["to_status"] == "IN_REVIEW"


def test_draft_creation_does_not_notify_anyone(client, db, regulatory_content_advisor, regulatory_content_writer):
    """Drafting is 'visible but inert' - only submission-for-review needs a reviewer notified."""
    from app.modules.notification.repository import NotificationRepository

    _create_requirement_version(client, regulatory_content_advisor)
    dispatch_pending_events(db)

    notifications = NotificationRepository(db).get_all_for_recipient(
        regulatory_content_writer["user"].id,
    )
    assert notifications == []
