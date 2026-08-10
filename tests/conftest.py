from __future__ import annotations

from collections.abc import Iterator

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
