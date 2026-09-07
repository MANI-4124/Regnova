"""
Loads regulatory content authored as YAML files under regulatory_content/
into a real, running backend - the "slide-in" half of the content
lifecycle (scripts/delete_testland_corpus.py's structural-provenance
deletion is the "slide-out" half, for synthetic content specifically;
this script is for real, reviewable content). See CLAUDE.md "File-based
regulatory content pipeline" for the full design.

Real verified content should arrive as files that can be reviewed as a
diff, not as a sequence of API calls nobody can audit afterwards. This
script is the loader half of that: it turns YAML files into DRAFT (or,
by default, IN_REVIEW - see --no-submit) rows through the REAL running
API, so every RBAC/content-review check applies exactly as it would to
a human author using the UI. It authenticates as an advisor or Knowledge
Lead account (--email) - same convention as scripts/seed_testland_corpus.py,
not scripts/seed_regulatory_sources.py's direct-service-layer bypass,
because the whole point here is that real authority checks apply.

This script can NEVER produce VERIFIED or ACTIVE content - it only ever
calls create/update/submit-for-review. Verification and activation are
real Knowledge Lead actions, taken through the existing content-review
endpoints (or scripts/bulk_verify_content.py at volume), never through
this loader.

Idempotent and re-runnable:
  - Requirement/Rule/Source are addressed by a stable, author-assigned
    `key` in each file, which becomes `human_reference` (DB-unique) -
    the same field this codebase already built for "stable identity...
    across versions" (see Requirement/Rule/Source models). A file
    without an explicit `key` gets one derived from its path relative to
    --content-dir.
  - Each written version's `notes` carries a provenance line -
    `[FILE-LOADED] file=<relpath> commit=<sha> content_sha256=<hash>` -
    checked on every re-run: unchanged file+hash is a true no-op: no
    version is created, no PUT/POST for that file happens at all.
    A change to a version still sitting at DRAFT (never reviewed) is
    updated in place; a change to a VERIFIED/ACTIVE version creates a
    new version instead, with supersedes_id set - the versioning model
    this codebase already has, not a new mechanism.

Folder layout:

    regulatory_content/
      <jurisdiction>/<category>/sources/*.yaml
      <jurisdiction>/<category>/requirements/<dimension>/*.yaml

Category scoping is now real (see CLAUDE.md "Category scoping"):
ProductVersion.category, ProductMarketState.jurisdiction and
RegulatoryBasisRelease.category are genuine fields, so `jurisdiction`/
`category` are sent to the API exactly as authored in each file - no
composition, no workaround. `market` is still sent (required by
RequirementVersionCreate/RegulatoryBasisReleaseCreate) but always set
equal to `jurisdiction`, matching the "market is non-authoritative,
kept for now" resolution - see CLAUDE.md. SourceVersion.jurisdiction is
sent as authored too; it was never part of any pinning mechanism to
begin with, being real-world descriptive metadata about where a
document was actually published.

Usage (from the backend/ directory, against a real running backend):

    python scripts/load_regulatory_content.py --email you@example.com
    python scripts/load_regulatory_content.py --email you@example.com --no-submit
    python scripts/load_regulatory_content.py --email you@example.com --manifest-out manifest.json

Prints a manifest (file, key, content_type, content_id, action) and the
git commit it loaded from clearly enough that a Knowledge Lead can write
a meaningful rationale referencing it when bulk-verifying afterwards
(see scripts/bulk_verify_content.py) - the rationale itself is never
auto-generated from this output, it stays the reviewer's own attestation.

Deliberately deferred from this pass (see CLAUDE.md): SourceLocation
authoring/citation resolution (source_refs) - files describe Source/
Requirement/Rule content only, not individual citation coordinates yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.core.database import build_database
from app.core.settings import get_settings
from app.main import app
from app.modules.auth.jwt import create_access_token
from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.user.repository import UserRepository

sys.path.insert(0, ".")

PROVENANCE_PREFIX = "[FILE-LOADED]"


@dataclass
class ManifestEntry:
    content_type: str
    content_id: str
    key: str
    file: str
    action: str  # created | updated | superseded | unchanged


@dataclass
class LoadContext:
    client: TestClient
    writer: dict
    commit: str
    submit: bool
    manifest: list = field(default_factory=list)
    source_map: dict = field(default_factory=dict)  # key -> source_version_id

    def get(self, path: str):
        response = self.client.get(path, headers=self.writer["headers"])
        assert response.status_code == 200, response.text
        return response.json()

    def post(self, path: str, body: dict):
        response = self.client.post(path, json=body, headers=self.writer["headers"])
        return response

    def put(self, path: str, body: dict):
        response = self.client.put(path, json=body, headers=self.writer["headers"])
        return response

    def submit_for_review(self, versions_path: str, version_id: str) -> None:
        if not self.submit:
            return
        response = self.post(f"{versions_path}/{version_id}/submit-for-review", {})
        assert response.status_code == 200, response.text


def build_writer(db, email: str) -> dict:
    users = UserRepository(db)
    user = users.get_by_email_global(email)
    if user is None:
        raise SystemExit(
            f"no user found with email {email!r} - this script authenticates AS an "
            "existing account, it does not create one.",
        )

    assignments = InternalRoleAssignmentRepository(db)
    is_advisor = assignments.get_active_for_user_role(
        user.id, InternalRoleCode.REGULATORY_CONTENT_ADVISOR.value,
    ) is not None
    is_lead = assignments.get_active_for_user_role(
        user.id, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value,
    ) is not None

    if not (is_advisor or is_lead):
        raise SystemExit(
            f"{email} holds neither REGULATORY_CONTENT_ADVISOR nor REGULATORY_KNOWLEDGE_LEAD - "
            "one is required to draft/submit content.",
        )

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(user.organization_id),
            "role_id": str(user.role_id),
        },
    )
    return {"headers": {"Authorization": f"Bearer {token}"}}


def detect_commit(content_dir: Path, override: str | None) -> str:
    if override:
        return override

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=content_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "UNKNOWN"


def content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def provenance_note(*, relpath: str, commit: str, content_sha256: str) -> str:
    return f"{PROVENANCE_PREFIX} file={relpath} commit={commit} content_sha256={content_sha256}"


def parse_provenance(notes: str | None) -> dict[str, str] | None:
    if not notes or PROVENANCE_PREFIX not in notes:
        return None

    remainder = notes.split(PROVENANCE_PREFIX, 1)[1].strip()
    fields = {}
    for token in remainder.split():
        if "=" in token:
            key, _, value = token.partition("=")
            fields[key] = value
    return fields


def slug_from_path(path: Path, content_dir: Path) -> str:
    relative = path.relative_to(content_dir).with_suffix("")
    return str(relative).replace("\\", "/").replace("/", "-")


def _resolve_action(ctx: LoadContext, *, existing_versions: list, sha: str) -> tuple[dict | None, str]:
    """
    Shared "what should happen to this file's row" decision, identical
    across Source/Requirement/Rule: unchanged content is a no-op,
    a changed DRAFT is updated in place, anything else changed gets
    superseded by a new version. Returns (latest_version_or_None, action).
    """

    latest = existing_versions[0] if existing_versions else None
    if latest is None:
        return None, "created"

    prior = parse_provenance(latest.get("notes"))
    if prior and prior.get("content_sha256") == sha:
        return latest, "unchanged"

    if latest["status"] == "DRAFT":
        return latest, "updated"

    return latest, "superseded"


def load_source_file(ctx: LoadContext, path: Path, content_dir: Path) -> None:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    relpath = str(path.relative_to(content_dir)).replace("\\", "/")
    key = data.get("key") or slug_from_path(path, content_dir)
    sha = content_hash(raw)
    note = provenance_note(relpath=relpath, commit=ctx.commit, content_sha256=sha)

    payload = {
        "title": data["title"],
        "issuing_authority": data["issuing_authority"],
        "jurisdiction": data["jurisdiction"],  # never composed - see module docstring
        "tier": data["tier"],
        "source_type": data["source_type"],
        "official_url": data.get("official_url"),
        "notes": note,
    }

    existing_source = next(
        (s for s in ctx.get("/sources") if s.get("human_reference") == key), None,
    )

    if existing_source is None:
        source = ctx.post("/sources", {"human_reference": key}).json()
        existing_versions = []
    else:
        source = existing_source
        existing_versions = ctx.get(f"/sources/{source['id']}/versions")

    latest, action = _resolve_action(ctx, existing_versions=existing_versions, sha=sha)

    if action == "unchanged":
        version = latest
    elif action == "updated":
        version = ctx.put(f"/sources/{source['id']}/versions/{latest['id']}", payload).json()
    else:
        version = ctx.post(f"/sources/{source['id']}/versions", payload).json()

    if action != "unchanged":
        ctx.submit_for_review(f"/sources/{source['id']}/versions", version["id"])

    ctx.source_map[key] = version["id"]
    ctx.manifest.append(ManifestEntry("source_version", version["id"], key, relpath, action))


def load_requirement_file(ctx: LoadContext, path: Path, content_dir: Path) -> None:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    relpath = str(path.relative_to(content_dir)).replace("\\", "/")
    key = data.get("key") or slug_from_path(path, content_dir)
    sha = content_hash(raw)
    note = provenance_note(relpath=relpath, commit=ctx.commit, content_sha256=sha)

    payload = {
        "jurisdiction": data["jurisdiction"],
        "market": data["jurisdiction"],  # non-authoritative - see module docstring
        "authority": data["authority"],
        "category": data["category"],
        "dimension": data["dimension"],
        "obligation_type": data["obligation_type"],
        "canonical_statement": data["canonical_statement"],
        "default_severity": data["default_severity"],
        "is_hard_gate": data.get("is_hard_gate", False),
        "authority_interpretation_label": data.get("authority_interpretation_label", "AUTHORITY_REQUIREMENT"),
        "notes": note,
    }

    existing_requirement = next(
        (r for r in ctx.get("/requirements") if r.get("human_reference") == key), None,
    )

    if existing_requirement is None:
        requirement = ctx.post("/requirements", {"human_reference": key}).json()
        existing_versions = []
    else:
        requirement = existing_requirement
        existing_versions = ctx.get(f"/requirements/{requirement['id']}/versions")

    latest, action = _resolve_action(ctx, existing_versions=existing_versions, sha=sha)

    if action == "unchanged":
        version = latest
    elif action == "updated":
        version = ctx.put(f"/requirements/{requirement['id']}/versions/{latest['id']}", payload).json()
    else:
        version = ctx.post(f"/requirements/{requirement['id']}/versions", payload).json()

    if action != "unchanged":
        ctx.submit_for_review(f"/requirements/{requirement['id']}/versions", version["id"])

    ctx.manifest.append(ManifestEntry("requirement_version", version["id"], key, relpath, action))

    for index, rule_data in enumerate(data.get("rules", [])):
        load_inline_rule(
            ctx, rule_data,
            requirement_version_id=version["id"],
            parent_key=key,
            index=index,
            relpath=relpath,
            commit=ctx.commit,
        )


def load_inline_rule(
    ctx: LoadContext,
    rule_data: dict,
    *,
    requirement_version_id: str,
    parent_key: str,
    index: int,
    relpath: str,
    commit: str,
) -> None:
    key = rule_data.get("key") or f"{parent_key}__rule-{index}"
    raw = yaml.safe_dump(rule_data, sort_keys=True).encode("utf-8")
    sha = content_hash(raw)
    note = provenance_note(relpath=f"{relpath}#{key}", commit=commit, content_sha256=sha)

    payload = {
        "requirement_version_id": requirement_version_id,
        "condition": rule_data["condition"],
        "output_type": rule_data["output_type"],
        "unknown_behavior": rule_data.get("unknown_behavior"),
        "notes": note,
    }

    existing_rule = next(
        (r for r in ctx.get("/rules") if r.get("human_reference") == key), None,
    )

    if existing_rule is None:
        rule = ctx.post("/rules", {"human_reference": key}).json()
        existing_versions = []
    else:
        rule = existing_rule
        existing_versions = ctx.get(f"/rules/{rule['id']}/versions")

    latest, action = _resolve_action(ctx, existing_versions=existing_versions, sha=sha)

    if action == "unchanged":
        version = latest
    elif action == "updated":
        version = ctx.put(f"/rules/{rule['id']}/versions/{latest['id']}", payload).json()
    else:
        version = ctx.post(f"/rules/{rule['id']}/versions", payload).json()

    if action != "unchanged":
        ctx.submit_for_review(f"/rules/{rule['id']}/versions", version["id"])

    ctx.manifest.append(ManifestEntry("rule_version", version["id"], key, f"{relpath}#{key}", action))


def run_load(ctx: LoadContext, content_dir: Path) -> list[ManifestEntry]:
    for path in sorted(content_dir.glob("**/sources/*.yaml")):
        load_source_file(ctx, path, content_dir)

    for path in sorted(content_dir.glob("**/requirements/**/*.yaml")):
        load_requirement_file(ctx, path, content_dir)

    return ctx.manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True, help="Advisor or Knowledge Lead account to authenticate as.")
    parser.add_argument("--content-dir", default="regulatory_content")
    parser.add_argument("--commit", default=None, help="Override auto-detected git commit (mainly for testing).")
    parser.add_argument(
        "--submit", dest="submit", action="store_true", default=True,
        help="Submit each new/changed DRAFT for review immediately (default: on).",
    )
    parser.add_argument("--no-submit", dest="submit", action="store_false")
    parser.add_argument("--manifest-out", default=None, help="Optional path to also write the manifest as JSON.")
    args = parser.parse_args()

    content_dir = Path(args.content_dir)
    if not content_dir.exists():
        raise SystemExit(f"content directory {content_dir} does not exist.")

    settings = get_settings()
    database = build_database(settings)
    session = database.session_factory()
    try:
        writer = build_writer(session, args.email)
    finally:
        session.close()

    commit = detect_commit(content_dir, args.commit)

    with TestClient(app) as client:
        ctx = LoadContext(client=client, writer=writer, commit=commit, submit=args.submit)
        manifest = run_load(ctx, content_dir)

    print(f"commit: {commit}")
    print(f"submitted for review: {args.submit}")
    print(f"{len(manifest)} file(s) processed:")
    for entry in manifest:
        print(f"  [{entry.action:10s}] {entry.content_type:20s} {entry.key:40s} <- {entry.file}")

    if args.manifest_out:
        Path(args.manifest_out).write_text(
            json.dumps(
                {
                    "commit": commit,
                    "items": [
                        {
                            "content_type": e.content_type,
                            "content_id": e.content_id,
                            "key": e.key,
                            "file": e.file,
                            "action": e.action,
                        }
                        for e in manifest
                        if e.action != "unchanged"
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"manifest written to {args.manifest_out}")


if __name__ == "__main__":
    main()
