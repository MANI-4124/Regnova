"""
Deletes the entire TESTLAND synthetic corpus (see tests/testland/README.md)
from a real, running backend - everything scripts/seed_testland_corpus.py
creates. "One operation" from the operator's point of view (one command),
but internally TWO ORDERED steps, not one - see the comment above
_delete_customer_side_rows for why the order matters.

Structural provenance used to find rows, NOT trust/an app-level flag:
  1. The demo Organization, matched by tl.DEMO_ORG_NAME - owns every
     customer-side row (Product/ProductVersion/ProductMarketState/
     AssessmentRun/StepRun/Finding/FindingRevision/StateSnapshot) via
     organization_id ON DELETE CASCADE.
  2. Every RequirementVersion/RuleVersion/SourceVersion whose `notes`
     field contains tl.SYNTHETIC_NOTE - the actual deletion key for
     regulatory content, since Requirement/Rule/Source parent rows
     carry no jurisdiction/provenance field of their own (see
     fixtures.py's module docstring).
  3. Every RegulatoryBasisRelease whose jurisdiction starts with
     tl.JURISDICTION ("TESTLAND") - a prefix, not an exact value,
     because jurisdiction must equal market per category
     (TESTLAND-BEAUTY/TESTLAND-NUTRA/TESTLAND-MEDDEVICE) for
     ProductMarketStateService's auto-pin to work - see fixtures.py.

Run against a real (non-SQLite) database from the backend/ directory:

    python scripts/delete_testland_corpus.py --yes

Without --yes, only reports what would be deleted (counts), deletes
nothing.
"""

from __future__ import annotations

import argparse
import sys

from app.core.database import build_database
from app.core.settings import get_settings
from app.modules.organization.models import Organization
from app.modules.regulatory_basis_release.models import RegulatoryBasisRelease
from app.modules.requirement.models import Requirement
from app.modules.requirement_version.models import RequirementVersion
from app.modules.rule.models import Rule
from app.modules.rule_version.models import RuleVersion
from app.modules.source.models import Source
from app.modules.source_version.models import SourceVersion

sys.path.insert(0, ".")
from tests.testland import fixtures as tl  # noqa: E402


def _delete_customer_side_rows(db, *, dry_run: bool) -> int:
    """
    Step 1: delete the demo Organization(s). This must happen BEFORE
    step 2 - AssessmentRun.regulatory_basis_release_id and
    StateSnapshot.regulatory_basis_release_id are both ON DELETE
    RESTRICT (so a released regulatory basis can never be silently
    yanked out from under a run that used it), and those two tables
    are exactly the ones that reference the RegulatoryBasisRelease rows
    step 2 deletes. Deleting the Organization first cascades away every
    AssessmentRun/StateSnapshot row that could hold that RESTRICT open
    (organization_id is ON DELETE CASCADE on both), so by the time step
    2 runs, nothing references the regulatory content anymore. Doing
    this in the other order fails outright on the RESTRICT constraint.
    """

    organizations = db.query(Organization).filter(Organization.name == tl.DEMO_ORG_NAME).all()
    print(f"[1/2] demo organizations matching {tl.DEMO_ORG_NAME!r}: {len(organizations)}")

    if not dry_run:
        for organization in organizations:
            db.delete(organization)
        db.commit()

    return len(organizations)


def _delete_regulatory_content(db, *, dry_run: bool) -> dict[str, int]:
    """
    Step 2: delete the regulatory content itself, via its top-level
    Requirement/Rule/Source rows (deleting these CASCADEs to every
    *Version row and to the RegulatoryBasisRelease join-table rows -
    see the models' own ondelete="CASCADE" declarations), plus the
    RegulatoryBasisRelease rows directly (they have no parent to
    cascade from).
    """

    requirement_ids = {
        row.requirement_id
        for row in db.query(RequirementVersion.requirement_id)
        .filter(RequirementVersion.notes.contains(tl.SYNTHETIC_NOTE))
        .all()
    }
    rule_ids = {
        row.rule_id
        for row in db.query(RuleVersion.rule_id)
        .filter(RuleVersion.notes.contains(tl.SYNTHETIC_NOTE))
        .all()
    }
    source_ids = {
        row.source_id
        for row in db.query(SourceVersion.source_id)
        .filter(SourceVersion.notes.contains(tl.SYNTHETIC_NOTE))
        .all()
    }
    releases = (
        db.query(RegulatoryBasisRelease)
        .filter(RegulatoryBasisRelease.jurisdiction.like(f"{tl.JURISDICTION}%"))
        .all()
    )

    counts = {
        "requirements": len(requirement_ids),
        "rules": len(rule_ids),
        "sources": len(source_ids),
        "regulatory_basis_releases": len(releases),
    }
    print(f"[2/2] synthetic regulatory content: {counts}")

    if not dry_run:
        for release in releases:
            db.delete(release)
        if requirement_ids:
            db.query(Requirement).filter(Requirement.id.in_(requirement_ids)).delete(synchronize_session=False)
        if rule_ids:
            db.query(Rule).filter(Rule.id.in_(rule_ids)).delete(synchronize_session=False)
        if source_ids:
            db.query(Source).filter(Source.id.in_(source_ids)).delete(synchronize_session=False)
        db.commit()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true",
        help="Actually delete. Without this flag, only reports counts of what would be deleted.",
    )
    args = parser.parse_args()

    settings = get_settings()
    database = build_database(settings)
    session = database.session_factory()

    try:
        org_count = _delete_customer_side_rows(session, dry_run=not args.yes)
        content_counts = _delete_regulatory_content(session, dry_run=not args.yes)
    finally:
        session.close()

    if not args.yes:
        print("dry run only - nothing deleted. Re-run with --yes to actually delete.")
    else:
        print(f"deleted {org_count} demo organization(s) and {content_counts}")


if __name__ == "__main__":
    main()
