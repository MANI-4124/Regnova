"""
Bulk-verifies (and optionally bulk-activates) the content a loader run
just produced, using the manifest scripts/load_regulatory_content.py's
--manifest-out writes - the practical-at-volume counterpart to clicking
verify() on hundreds of rows individually. See CLAUDE.md "File-based
regulatory content pipeline".

Authenticates as a real Knowledge Lead (--email) and calls the real
POST /content-review/bulk-verify (and, with --activate, bulk-activate)
endpoints - every item still goes through ContentReviewWorkflow's own
per-row authority and status checks, this is not a bypass. One bad item
fails on its own without blocking the rest of the batch; failures are
printed, not silently swallowed.

The rationale is never auto-generated from the manifest or commit hash
- it's the reviewer's own attestation. This script prints the commit
and file list clearly so you can write a rationale that references it
meaningfully, but never validates or templates that text itself.

Usage:

    python scripts/load_regulatory_content.py --email advisor@example.com --manifest-out manifest.json
    python scripts/bulk_verify_content.py --manifest manifest.json --email lead@example.com \\
        --rationale "Verified against primary source text for commit a1b2c3d." [--activate]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.database import build_database
from app.core.settings import get_settings
from app.main import app
from app.modules.auth.jwt import create_access_token
from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.user.repository import UserRepository

sys.path.insert(0, ".")


def build_writer(db, email: str) -> dict:
    users = UserRepository(db)
    user = users.get_by_email_global(email)
    if user is None:
        raise SystemExit(f"no user found with email {email!r}.")

    assignments = InternalRoleAssignmentRepository(db)
    is_lead = assignments.get_active_for_user_role(
        user.id, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
    ) is not None
    if not is_lead:
        raise SystemExit(f"{email} does not hold an APPROVED REGULATORY_KNOWLEDGE_LEAD assignment.")

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(user.organization_id),
            "role_id": str(user.role_id),
        },
    )
    return {"headers": {"Authorization": f"Bearer {token}"}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", required=True, help="Path to a manifest written by load_regulatory_content.py --manifest-out.")
    parser.add_argument("--email", required=True, help="Knowledge Lead account to authenticate as.")
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--activate", action="store_true", help="Also bulk-activate the same items after verifying.")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    items = [{"content_type": i["content_type"], "content_id": i["content_id"]} for i in manifest["items"]]

    if not items:
        print("manifest has no items to verify.")
        return

    print(f"manifest commit: {manifest.get('commit')}")
    print(f"{len(items)} item(s) to verify:")
    for i in manifest["items"]:
        print(f"  {i['content_type']:20s} {i['key']:40s} <- {i['file']}")

    settings = get_settings()
    database = build_database(settings)
    session = database.session_factory()
    try:
        writer = build_writer(session, args.email)
    finally:
        session.close()

    with TestClient(app) as client:
        response = client.post(
            "/content-review/bulk-verify",
            json={"items": items, "rationale": args.rationale},
            headers=writer["headers"],
        )
        response.raise_for_status()
        _report("verify", response.json()["results"])

        if args.activate:
            response = client.post(
                "/content-review/bulk-activate",
                json={"items": items, "rationale": args.rationale},
                headers=writer["headers"],
            )
            response.raise_for_status()
            _report("activate", response.json()["results"])


def _report(action: str, results: list[dict]) -> None:
    succeeded = [r for r in results if r["status"] != "failed"]
    failed = [r for r in results if r["status"] == "failed"]

    print(f"{action}: {len(succeeded)} succeeded, {len(failed)} failed")
    for r in failed:
        print(f"  FAILED {r['content_type']} {r['content_id']}: {r['error']}")


if __name__ == "__main__":
    main()
