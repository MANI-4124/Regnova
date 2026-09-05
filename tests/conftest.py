from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers all mapped models on Base.metadata)
from app.core.database import Base
from app.core.dependencies import get_db_session
from app.main import app
from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.internal_role_assignment.models import (
    InternalRoleAssignment,
    InternalRoleAssignmentStatus,
    InternalRoleCode,
)
from app.modules.organization.models import Organization
from app.modules.role.models import Role
from app.modules.user.models import User


@pytest.fixture()
def engine():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


@pytest.fixture()
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(session_factory) -> Iterator[TestClient]:
    def override_get_db_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def make_tenant(db: Session, label: str) -> dict:
    """
    Create an Organization with one ADMIN role and one active user,
    and return everything a test needs to act as that tenant.
    """

    organization = Organization(
        name=f"Org {label}",
        industry="Software",
        country="US",
    )
    db.add(organization)
    db.flush()

    role = Role(
        organization_id=organization.id,
        code="ADMIN",
        name=f"Admin {label}",
    )
    db.add(role)
    db.flush()

    user = User(
        organization_id=organization.id,
        role_id=role.id,
        first_name="Test",
        last_name=label,
        email=f"admin-{label.lower()}@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(user)
    db.flush()
    db.commit()

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(organization.id),
            "role_id": str(role.id),
        },
    )

    return {
        "organization": organization,
        "role": role,
        "user": user,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture()
def tenant_a(db: Session) -> dict:
    return make_tenant(db, "A")


@pytest.fixture()
def tenant_b(db: Session) -> dict:
    return make_tenant(db, "B")


def make_internal_user(db: Session, role_code: str | None, label: str) -> dict:
    """
    Create a User inside the tenant-zero (RegNova-internal) Organization,
    creating that org if this test hasn't already, and optionally grant
    it an already-APPROVED InternalRoleAssignment for role_code. Returns
    the same shape as make_tenant, so callers can use ["headers"] the
    same way. Direct ORM inserts (not an HTTP propose/decide round trip)
    for the same reason _non_admin_headers builds its user directly -
    there's no bootstrap CEO/HR account to drive that flow through yet.
    """
    organization = (
        db.query(Organization).filter(Organization.is_internal.is_(True)).first()
    )
    if organization is None:
        organization = Organization(
            name="RegNova",
            industry="Regulatory Technology",
            country="US",
            is_internal=True,
        )
        db.add(organization)
        db.flush()

    # Reused across calls, not recreated per call - a test requesting two
    # internal-role fixtures at once (e.g. regulatory_content_advisor AND
    # regulatory_content_writer) would otherwise insert a second EMPLOYEE
    # role into the same tenant-zero org and violate its own (organization_id,
    # code) uniqueness, the same reuse-or-create shape as the organization
    # lookup just above.
    role = (
        db.query(Role)
        .filter(Role.organization_id == organization.id, Role.code == "EMPLOYEE")
        .first()
    )
    if role is None:
        role = Role(
            organization_id=organization.id,
            code="EMPLOYEE",
            name="Internal",
        )
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

    if role_code is not None:
        payload = {"user_id": str(user.id), "role_code": role_code, "scope": None}
        content_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        ).hexdigest()
        assignment = InternalRoleAssignment(
            user_id=user.id,
            role_code=role_code,
            scope=None,
            status=InternalRoleAssignmentStatus.APPROVED.value,
            proposed_by_user_id=user.id,
            proposed_at=datetime.now(timezone.utc),
            rationale="test setup",
            approver_user_id=user.id,
            decided_at=datetime.now(timezone.utc),
            content_hash=content_hash,
        )
        db.add(assignment)
        db.flush()

    db.commit()

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(organization.id),
            "role_id": str(role.id),
        },
    )

    return {
        "organization": organization,
        "role": role,
        "user": user,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture()
def regulatory_content_writer(db: Session) -> dict:
    """
    A RegNova-internal user holding an APPROVED REGULATORY_KNOWLEDGE_LEAD
    InternalRoleAssignment - satisfies require_regulatory_content_writer,
    the replacement for the old require_admin placeholder on Source/
    Requirement/Rule/RegulatoryBasisRelease writes.
    """
    return make_internal_user(
        db, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value, "KnowledgeLead",
    )


@pytest.fixture()
def regulatory_content_advisor(db: Session) -> dict:
    """
    A RegNova-internal user holding an APPROVED REGULATORY_CONTENT_ADVISOR
    InternalRoleAssignment - satisfies require_regulatory_content_author
    but NOT require_regulatory_content_writer: can draft/edit/submit-for-
    review, cannot verify/activate/reject. See CLAUDE.md "Regulatory
    content approval workflow".
    """
    return make_internal_user(
        db, InternalRoleCode.REGULATORY_CONTENT_ADVISOR.value, "ContentAdvisor",
    )
