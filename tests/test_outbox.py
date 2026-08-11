from __future__ import annotations

from app.modules.audit.repository import OutboxRepository


def test_append_creates_unpublished_event(db, tenant_a):
    repository = OutboxRepository(db)

    event = repository.append(
        organization_id=tenant_a["organization"].id,
        event_type="TestEvent",
        schema_version=1,
        payload={"foo": "bar"},
    )
    db.commit()

    assert event.id is not None
    assert event.published_at is None
    assert event.attempts == 0
    assert event.payload == {"foo": "bar"}


def test_get_unpublished_returns_only_unpublished_ordered_by_created_at(db, tenant_a):
    repository = OutboxRepository(db)

    first = repository.append(
        organization_id=tenant_a["organization"].id,
        event_type="First",
        schema_version=1,
        payload={},
    )
    second = repository.append(
        organization_id=tenant_a["organization"].id,
        event_type="Second",
        schema_version=1,
        payload={},
    )
    db.commit()

    repository.mark_published(first.id)
    db.commit()

    pending = repository.get_unpublished()

    assert [e.id for e in pending] == [second.id]


def test_mark_published_sets_timestamp_and_excludes_from_unpublished(db, tenant_a):
    repository = OutboxRepository(db)

    event = repository.append(
        organization_id=tenant_a["organization"].id,
        event_type="TestEvent",
        schema_version=1,
        payload={},
    )
    db.commit()

    repository.mark_published(event.id)
    db.commit()

    assert event.published_at is not None
    assert repository.get_unpublished() == []


def test_mark_failed_records_attempt_and_error_but_stays_pending(db, tenant_a):
    repository = OutboxRepository(db)

    event = repository.append(
        organization_id=tenant_a["organization"].id,
        event_type="TestEvent",
        schema_version=1,
        payload={},
    )
    db.commit()

    repository.mark_failed(event.id, "boom")
    db.commit()

    assert event.attempts == 1
    assert event.last_error == "boom"
    assert event.published_at is None
    assert [e.id for e in repository.get_unpublished()] == [event.id]


def test_get_unpublished_respects_limit(db, tenant_a):
    repository = OutboxRepository(db)

    for i in range(3):
        repository.append(
            organization_id=tenant_a["organization"].id,
            event_type=f"Event{i}",
            schema_version=1,
            payload={},
        )
    db.commit()

    assert len(repository.get_unpublished(limit=2)) == 2


def test_get_unpublished_runs_cleanly_on_sqlite(db, tenant_a):
    """
    get_unpublished() applies FOR UPDATE SKIP LOCKED only against
    Postgres - a real concurrent-claim guarantee that can't be
    meaningfully exercised on SQLite (single connection, no MVCC row
    locking to contend over). This just proves the query itself runs
    end-to-end on the SQLite dialect these tests use, not that
    concurrent claims are safe here.
    """
    repository = OutboxRepository(db)

    repository.append(
        organization_id=tenant_a["organization"].id,
        event_type="TestEvent",
        schema_version=1,
        payload={},
    )
    db.commit()

    assert repository.db.get_bind().dialect.name == "sqlite"
    assert len(repository.get_unpublished()) == 1
