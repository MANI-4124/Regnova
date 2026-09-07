from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.load_regulatory_content import (  # noqa: E402
    LoadContext,
    content_hash,
    run_load,
)

from app.modules.requirement_version.repository import RequirementVersionRepository  # noqa: E402
from app.modules.rule_version.repository import RuleVersionRepository  # noqa: E402
from app.modules.source_version.repository import SourceVersionRepository  # noqa: E402

_REPOS = {
    "requirement_version": RequirementVersionRepository,
    "rule_version": RuleVersionRepository,
    "source_version": SourceVersionRepository,
}

SOURCE_YAML = """\
key: test-source-1
title: Test Source Document
issuing_authority: Test Authority
jurisdiction: Freedonia
tier: 1
source_type: OFFICIAL_GUIDELINE
"""

REQUIREMENT_YAML = """\
key: test-requirement-1
jurisdiction: Freedonia
category: Beauty
dimension: CLAIMS
authority: Test Authority
authority_interpretation_label: AUTHORITY_REQUIREMENT
obligation_type: PROHIBITED_THERAPEUTIC_CLAIM
canonical_statement: Claims must not be therapeutic.
default_severity: CRITICAL
is_hard_gate: true
rules:
  - output_type: FINDING_PROPOSAL
    unknown_behavior: HUMAN_REVIEW
    condition:
      op: in
      field: wording
      value: [cures acne]
"""


def _write_content_dir(tmp_path, *, source_yaml=SOURCE_YAML, requirement_yaml=REQUIREMENT_YAML):
    content_dir = tmp_path / "regulatory_content"
    (content_dir / "Freedonia" / "Beauty" / "sources").mkdir(parents=True, exist_ok=True)
    (content_dir / "Freedonia" / "Beauty" / "requirements" / "claims").mkdir(parents=True, exist_ok=True)

    (content_dir / "Freedonia" / "Beauty" / "sources" / "test-source.yaml").write_text(source_yaml)
    (content_dir / "Freedonia" / "Beauty" / "requirements" / "claims" / "test-requirement.yaml").write_text(requirement_yaml)

    return content_dir


def _ctx(client, writer, *, submit=True):
    return LoadContext(
        client=client, writer=writer, commit="deadbeef1234", submit=submit,
    )


def _status_of(db, entry):
    repository = _REPOS[entry.content_type](db)
    row = repository.get_by_id_only(uuid.UUID(entry.content_id))
    return row.status


# --- pure functions --------------------------------------------------------


# --- the two explicitly required behaviors ---------------------------------


def test_loader_never_produces_verified_or_active_content(client, db, tmp_path, regulatory_content_advisor):
    """
    The loader has no code path that calls verify()/activate() at all -
    this proves it end to end: every row it touches, submitted for
    review or not, is DRAFT or IN_REVIEW, never VERIFIED or ACTIVE.
    """
    content_dir = _write_content_dir(tmp_path)
    ctx = _ctx(client, regulatory_content_advisor, submit=True)

    manifest = run_load(ctx, content_dir)

    assert len(manifest) == 3  # source + requirement + its one inline rule
    for entry in manifest:
        status = _status_of(db, entry)
        assert status in ("DRAFT", "IN_REVIEW"), f"{entry.content_type} {entry.key} was {status}"


def test_no_submit_flag_leaves_everything_at_bare_draft(client, db, tmp_path, regulatory_content_advisor):
    content_dir = _write_content_dir(tmp_path)
    ctx = _ctx(client, regulatory_content_advisor, submit=False)

    manifest = run_load(ctx, content_dir)

    for entry in manifest:
        assert _status_of(db, entry) == "DRAFT"


def test_rerun_with_unchanged_files_is_a_true_noop(client, db, tmp_path, regulatory_content_advisor):
    content_dir = _write_content_dir(tmp_path)

    first = run_load(_ctx(client, regulatory_content_advisor), content_dir)
    assert {e.action for e in first} == {"created"}

    requirements_before = client.get("/requirements", headers=regulatory_content_advisor["headers"]).json()
    rules_before = client.get("/rules", headers=regulatory_content_advisor["headers"]).json()
    sources_before = client.get("/sources", headers=regulatory_content_advisor["headers"]).json()

    second = run_load(_ctx(client, regulatory_content_advisor), content_dir)

    assert {e.action for e in second} == {"unchanged"}
    assert {(e.content_type, e.content_id) for e in second} == {(e.content_type, e.content_id) for e in first}

    requirements_after = client.get("/requirements", headers=regulatory_content_advisor["headers"]).json()
    rules_after = client.get("/rules", headers=regulatory_content_advisor["headers"]).json()
    sources_after = client.get("/sources", headers=regulatory_content_advisor["headers"]).json()

    assert len(requirements_after) == len(requirements_before)
    assert len(rules_after) == len(rules_before)
    assert len(sources_after) == len(sources_before)


# --- change detection: the other half of idempotency -----------------------


def test_rerun_after_edit_updates_the_still_draft_version_in_place(client, db, tmp_path, regulatory_content_advisor):
    content_dir = _write_content_dir(tmp_path)
    first = run_load(_ctx(client, regulatory_content_advisor, submit=False), content_dir)

    edited = REQUIREMENT_YAML.replace(
        "Claims must not be therapeutic.", "Claims must not be therapeutic in any form.",
    )
    _write_content_dir(tmp_path, requirement_yaml=edited)

    second = run_load(_ctx(client, regulatory_content_advisor, submit=False), content_dir)

    requirement_entries = [e for e in second if e.content_type == "requirement_version"]
    assert requirement_entries[0].action == "updated"

    # Same version row, not a new one - it was still DRAFT, so the edit
    # went through the ordinary PUT rather than creating a new version.
    first_requirement_id = next(e.content_id for e in first if e.content_type == "requirement_version")
    assert requirement_entries[0].content_id == first_requirement_id

    row = RequirementVersionRepository(db).get_by_id_only(uuid.UUID(first_requirement_id))
    assert row.canonical_statement == "Claims must not be therapeutic in any form."


def test_rerun_after_edit_to_a_verified_version_supersedes_rather_than_mutates(
    client, db, tmp_path, regulatory_content_advisor, regulatory_content_writer,
):
    content_dir = _write_content_dir(tmp_path)
    first = run_load(_ctx(client, regulatory_content_advisor, submit=True), content_dir)

    first_requirement_id = next(e.content_id for e in first if e.content_type == "requirement_version")
    requirement = next(
        r for r in client.get("/requirements", headers=regulatory_content_advisor["headers"]).json()
        if r["human_reference"] == "test-requirement-1"
    )
    path = f"/requirements/{requirement['id']}/versions/{first_requirement_id}"
    verify = client.post(f"{path}/verify", json={"rationale": "Verified."}, headers=regulatory_content_writer["headers"])
    assert verify.status_code == 200, verify.text

    edited = REQUIREMENT_YAML.replace(
        "Claims must not be therapeutic.", "Claims must not be therapeutic, in any form.",
    )
    _write_content_dir(tmp_path, requirement_yaml=edited)

    second = run_load(_ctx(client, regulatory_content_advisor, submit=False), content_dir)
    requirement_entries = [e for e in second if e.content_type == "requirement_version"]

    assert requirement_entries[0].action == "superseded"
    assert requirement_entries[0].content_id != first_requirement_id

    new_row = RequirementVersionRepository(db).get_by_id_only(uuid.UUID(requirement_entries[0].content_id))
    assert new_row.status == "DRAFT"
    assert new_row.canonical_statement == "Claims must not be therapeutic, in any form."

    old_row = RequirementVersionRepository(db).get_by_id_only(uuid.UUID(first_requirement_id))
    assert old_row.status == "VERIFIED"  # untouched by the loader


# --- provenance --------------------------------------------------------


def test_notes_carry_file_and_commit_provenance(client, db, tmp_path, regulatory_content_advisor):
    content_dir = _write_content_dir(tmp_path)
    manifest = run_load(_ctx(client, regulatory_content_advisor), content_dir)

    requirement_entry = next(e for e in manifest if e.content_type == "requirement_version")
    row = RequirementVersionRepository(db).get_by_id_only(uuid.UUID(requirement_entry.content_id))

    assert "[FILE-LOADED]" in row.notes
    assert "commit=deadbeef1234" in row.notes
    assert "file=Freedonia/Beauty/requirements/claims/test-requirement.yaml" in row.notes
    assert "content_sha256=" in row.notes


def test_content_hash_changes_when_bytes_change():
    assert content_hash(b"a") != content_hash(b"b")
    assert content_hash(b"a") == content_hash(b"a")
