from __future__ import annotations

from app.modules.audit.repository import OutboxRepository
from app.modules.audit.worker import dispatch_pending_events
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService


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


def _submit_for_review(client, advisor, requirement, version):
    path = f"/requirements/{requirement['id']}/versions/{version['id']}/submit-for-review"
    response = client.post(path, headers=advisor["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _produce_one_notification(client, db, advisor):
    """
    The only notification-producing event wired up so far (see CLAUDE.md
    "Notifications" - customer-org resolvers aren't wired yet) is
    ContentVersionTransitioned's DRAFT -> IN_REVIEW hop. Used here purely
    as a vehicle to get a real Notification row into existence; these
    tests are about the notification mechanism's own contract, not
    content review.
    """
    requirement, version = _create_requirement_version(client, advisor)
    _submit_for_review(client, advisor, requirement, version)
    dispatch_pending_events(db)
    return version


# --- list / unread-count / mark-read --------------------------------------


def test_list_returns_only_the_callers_own_notifications(
    client, db, regulatory_content_advisor, regulatory_content_writer,
):
    _produce_one_notification(client, db, regulatory_content_advisor)

    mine = client.get("/notifications", headers=regulatory_content_writer["headers"])
    assert mine.status_code == 200
    assert len(mine.json()) == 1

    someone_elses = client.get("/notifications", headers=regulatory_content_advisor["headers"])
    assert someone_elses.status_code == 200
    assert someone_elses.json() == []


def test_unread_only_filter(client, db, regulatory_content_advisor, regulatory_content_writer):
    _produce_one_notification(client, db, regulatory_content_advisor)

    unread = client.get(
        "/notifications", params={"unread_only": True}, headers=regulatory_content_writer["headers"],
    ).json()
    assert len(unread) == 1

    client.post(f"/notifications/{unread[0]['id']}/read", headers=regulatory_content_writer["headers"])

    unread_after = client.get(
        "/notifications", params={"unread_only": True}, headers=regulatory_content_writer["headers"],
    ).json()
    assert unread_after == []

    all_after = client.get("/notifications", headers=regulatory_content_writer["headers"]).json()
    assert len(all_after) == 1
    assert all_after[0]["read_at"] is not None


def test_unread_count(client, db, regulatory_content_advisor, regulatory_content_writer):
    _produce_one_notification(client, db, regulatory_content_advisor)

    response = client.get("/notifications/unread-count", headers=regulatory_content_writer["headers"])
    assert response.status_code == 200
    assert response.json()["unread_count"] == 1

    notifications = client.get("/notifications", headers=regulatory_content_writer["headers"]).json()
    client.post(f"/notifications/{notifications[0]['id']}/read", headers=regulatory_content_writer["headers"])

    response = client.get("/notifications/unread-count", headers=regulatory_content_writer["headers"])
    assert response.json()["unread_count"] == 0


def test_mark_read_is_idempotent(client, db, regulatory_content_advisor, regulatory_content_writer):
    _produce_one_notification(client, db, regulatory_content_advisor)
    notifications = client.get("/notifications", headers=regulatory_content_writer["headers"]).json()
    notification_id = notifications[0]["id"]

    first = client.post(f"/notifications/{notification_id}/read", headers=regulatory_content_writer["headers"])
    assert first.status_code == 200
    first_read_at = first.json()["read_at"]

    second = client.post(f"/notifications/{notification_id}/read", headers=regulatory_content_writer["headers"])
    assert second.status_code == 200
    assert second.json()["read_at"] >= first_read_at


# --- cross-recipient isolation (explicitly requested) ---------------------


def test_cannot_read_or_mark_another_users_notification(
    client, db, regulatory_content_advisor, regulatory_content_writer,
):
    """
    A notification belongs to exactly one recipient - there is no
    organization_id to scope by (see models.py), so cross-recipient
    access must be blocked entirely, and reported as 404 (not 403) so a
    caller can't distinguish "not yours" from "doesn't exist" - the same
    information-hiding convention this codebase uses for cross-org 404s
    elsewhere.
    """
    _produce_one_notification(client, db, regulatory_content_advisor)
    notification_id = client.get(
        "/notifications", headers=regulatory_content_writer["headers"],
    ).json()[0]["id"]

    read_attempt = client.get("/notifications", headers=regulatory_content_advisor["headers"])
    assert read_attempt.json() == []  # confirms it's genuinely invisible to the wrong recipient, not just unlisted

    mark_read_attempt = client.post(
        f"/notifications/{notification_id}/read", headers=regulatory_content_advisor["headers"],
    )
    assert mark_read_attempt.status_code == 404
    assert mark_read_attempt.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"


def test_marking_nonexistent_notification_read_is_also_404(client, regulatory_content_writer):
    import uuid

    response = client.post(
        f"/notifications/{uuid.uuid4()}/read", headers=regulatory_content_writer["headers"],
    )
    assert response.status_code == 404


# --- production mechanism: dedup + resolver registry (explicitly requested) ---


def test_reprocessing_same_event_does_not_duplicate_notifications(
    client, db, regulatory_content_advisor, regulatory_content_writer,
):
    """
    Outbox delivery is at-least-once (dispatch_pending_events retries
    the same event on failure) - reprocessing an already-dispatched
    event must not create a second Notification for the same recipient.
    Exercised by calling record_for_event() directly a second time with
    the SAME OutboxEvent row, simulating exactly that redelivery.
    """
    requirement, version = _create_requirement_version(client, regulatory_content_advisor)
    _submit_for_review(client, regulatory_content_advisor, requirement, version)

    events = [
        e for e in OutboxRepository(db).get_unpublished()
        if e.event_type == "ContentVersionTransitioned"
    ]
    assert len(events) == 1
    event = events[0]

    service = NotificationService(db)
    first_pass = service.record_for_event(event)
    db.commit()
    second_pass = service.record_for_event(event)
    db.commit()

    assert len(first_pass) == 1
    assert second_pass == []  # the dedup check short-circuited before inserting

    stored = NotificationRepository(db).get_all_for_recipient(regulatory_content_writer["user"].id)
    assert len(stored) == 1


def test_event_type_with_no_registered_resolver_produces_no_notifications(db, tenant_a):
    """
    No resolver registered for a given event_type means no notifications
    produced for it - silent, not an error. WorkspaceActivated/
    MembershipChanged/ProductVersionPublished are exactly this case
    today - see CLAUDE.md "Notifications".
    """
    event = OutboxRepository(db).append(
        organization_id=tenant_a["organization"].id,
        event_type="WorkspaceActivated",
        schema_version=1,
        payload={"organization_id": str(tenant_a["organization"].id)},
    )
    db.commit()

    created = NotificationService(db).record_for_event(event)
    assert created == []
