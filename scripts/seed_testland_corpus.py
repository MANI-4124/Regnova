"""
Seeds the TESTLAND synthetic corpus (see tests/testland/README.md) into a
real, running backend - the same content tests/test_testland_corpus.py
exercises against an in-memory SQLite DB, but persisted so it can be
browsed/demoed through the actual API against Postgres.

Reuses tests/testland/fixtures.py's own content builders unchanged, driven
through TestClient(app) against the app's REAL configured database (no
get_db_session override, unlike the test suite's `client` fixture) - so
this creates real, permanent rows. Every row it creates carries TESTLAND's
synthetic-provenance markers (see fixtures.py's module docstring) and is
removable in one step via scripts/delete_testland_corpus.py.

Requires an existing RegNova-internal account holding an APPROVED
REGULATORY_KNOWLEDGE_LEAD InternalRoleAssignment - i.e. this only works
after scripts/bootstrap_interim_operator.py has been run at least once.
This script does not create that account itself; it authenticates AS it,
the same way a real regulatory-content author would through the UI.

Run against a real (non-SQLite) database once DATABASE_URL points to one,
from the backend/ directory:

    python scripts/seed_testland_corpus.py --email you@example.com

Idempotent only in the sense that re-running creates a SECOND copy of the
corpus (fresh Requirements/Rules/Release) - fixtures.py's builders don't
check for an existing TESTLAND release before creating one. If you're
re-seeding, delete the old corpus first with delete_testland_corpus.py.
"""

from __future__ import annotations

import argparse
import sys

from fastapi.testclient import TestClient

from app.core.database import build_database
from app.core.settings import get_settings
from app.main import app
from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.organization.models import Organization
from app.modules.role.models import Role
from app.modules.user.models import User
from app.modules.user.repository import UserRepository

sys.path.insert(0, ".")
from tests.testland import fixtures as tl  # noqa: E402

DEMO_ORG_NAME = tl.DEMO_ORG_NAME


def build_writer(db, email: str) -> dict:
    users = UserRepository(db)
    user = users.get_by_email_global(email)
    if user is None:
        raise SystemExit(
            f"no user found with email {email!r} - this script authenticates AS an "
            "existing RegNova-internal account, it does not create one. Run "
            "scripts/bootstrap_interim_operator.py first.",
        )

    assignments = InternalRoleAssignmentRepository(db)
    active = assignments.get_active_for_user_role(
        user.id, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
    )
    if active is None:
        raise SystemExit(
            f"{email} has no APPROVED REGULATORY_KNOWLEDGE_LEAD InternalRoleAssignment - "
            "required for require_regulatory_content_writer. Run "
            "scripts/bootstrap_interim_operator.py first.",
        )

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(user.organization_id),
            "role_id": str(user.role_id),
        },
    )
    return {"headers": {"Authorization": f"Bearer {token}"}}


def build_demo_tenant(db) -> dict:
    """
    One dedicated, obviously-named Organization owning every golden-case
    Product/ProductVersion/ProductMarketState/AssessmentRun/Finding this
    script creates - the "customer-side" half of the corpus's deletion
    key (see fixtures.py's module docstring). Never reused for anything
    real; found-or-created by DEMO_ORG_NAME so re-running this script
    doesn't create a second one.
    """

    organization = db.query(Organization).filter(Organization.name == DEMO_ORG_NAME).first()
    if organization is None:
        # is_synthetic=True - TESTLAND is exactly the confirmed-synthetic
        # data Organization.is_synthetic exists to permit reaching a real
        # Gemini backend for (see CLAUDE.md "Ask RegNova"). Direct ORM
        # write, not the Create API - is_synthetic is deliberately not
        # exposed there, same as is_internal.
        organization = Organization(
            name=DEMO_ORG_NAME, industry="Synthetic Test Fixture", country="US", is_synthetic=True,
        )
        db.add(organization)
        db.flush()
    elif not organization.is_synthetic:
        # Backfill for a demo org created before Organization.is_synthetic
        # existed - re-running this script (without a fresh delete first)
        # must not leave a stale TESTLAND org ineligible for the real
        # Gemini backend.
        organization.is_synthetic = True
        db.add(organization)
        db.flush()

    role = (
        db.query(Role)
        .filter(Role.organization_id == organization.id, Role.code == "ADMIN")
        .first()
    )
    if role is None:
        role = Role(organization_id=organization.id, code="ADMIN", name="TESTLAND Demo Admin")
        db.add(role)
        db.flush()

    user = (
        db.query(User)
        .filter(User.organization_id == organization.id, User.email == "testland-demo@example.com")
        .first()
    )
    if user is None:
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            first_name="TESTLAND",
            last_name="Demo",
            email="testland-demo@example.com",
            password_hash=hash_password("Password123!"),
        )
        db.add(user)
        db.flush()

    db.commit()

    token = create_access_token(
        subject=str(user.id),
        additional_claims={"organization_id": str(organization.id), "role_id": str(role.id)},
    )
    return {"organization": organization, "headers": {"Authorization": f"Bearer {token}"}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email", required=True,
        help="Email of an existing RegNova-internal REGULATORY_KNOWLEDGE_LEAD account.",
    )
    args = parser.parse_args()

    settings = get_settings()
    database = build_database(settings)
    session = database.session_factory()

    try:
        writer = build_writer(session, args.email)
        tenant = build_demo_tenant(session)
    finally:
        session.close()

    with TestClient(app) as client:
        beauty = tl.build_beauty_content(client, writer)
        nutra = tl.build_nutra_content(client, writer)
        meddevice = tl.build_meddevice_content(client, writer)

        # One demo product per category, browsable through the real
        # API - not the full golden-case matrix (that lives in
        # tests/test_testland_corpus.py). Each is immediately assessed
        # with a DELIBERATELY different outcome (same input_facts shapes
        # tests/test_testland_corpus.py asserts on, via the shared
        # builders in tests/testland/fixtures.py) so a baseline
        # dashboard pointed at this seeded data has three visibly
        # different states to show, not three identical "not yet
        # assessed" cells - see CLAUDE.md "TESTLAND corpus".
        _, _, beauty_state = tl.new_golden_product(client, tenant, "TESTLAND Demo - Beauty", tl.CATEGORY_BEAUTY)
        beauty_snapshot = tl.run_market_readiness(
            client, tenant, beauty_state["id"],
            tl.beauty_facts(wording="Softens and smooths skin"),  # clean pass
        )

        _, _, nutra_state = tl.new_golden_product(client, tenant, "TESTLAND Demo - Nutraceuticals", tl.CATEGORY_NUTRA)
        nutra_snapshot = tl.run_market_readiness(
            client, tenant, nutra_state["id"],
            tl.nutra_facts(dosage_mg=2500, wording="Supports normal energy metabolism"),  # critical-fail
        )

        _, _, meddevice_state = tl.new_golden_product(
            client, tenant, "TESTLAND Demo - Medical Devices", tl.CATEGORY_MEDDEVICE,
        )
        meddevice_snapshot = tl.run_market_readiness(
            client, tenant, meddevice_state["id"],
            tl.meddevice_facts(  # human-review (low-confidence classification)
                risk_class="III", confidence=0.3,
                documents=[{"document_type": "clinical_evidence_report", "status": "uploaded"}],
                bench_test_report_ref="BTR-1", notified_body_signoff_ref="NB-1",
                self_declaration_ref="SD-1",
            ),
        )

    for label, corpus in (("Beauty", beauty), ("Nutraceuticals", nutra), ("Medical Devices", meddevice)):
        print(f"{label}: release {corpus['release']['id']}, "
              f"{len(corpus['requirement_versions'])} requirements, "
              f"{len(corpus['rule_versions'])} rules")

    print(f"demo organization: {tenant['organization'].id} ({DEMO_ORG_NAME!r})")
    for label, state, snapshot in (
        ("Beauty", beauty_state, beauty_snapshot),
        ("Nutraceuticals", nutra_state, nutra_snapshot),
        ("Medical Devices", meddevice_state, meddevice_snapshot),
    ):
        print(
            f"{label} demo product_market_state: {state['id']} "
            f"- gate={snapshot['overall_gate']} reasons={snapshot['readiness_reason_codes']}",
        )


if __name__ == "__main__":
    main()
