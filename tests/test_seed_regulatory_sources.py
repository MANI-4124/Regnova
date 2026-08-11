from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seed_regulatory_sources import SCAFFOLD_SOURCES, seed  # noqa: E402


def test_seed_creates_one_draft_version_per_scaffold_entry(db):
    created = seed(db)

    assert len(created) == len(SCAFFOLD_SOURCES) == 7

    for version in created:
        assert version.id is not None
        assert version.source_id is not None
        assert version.status == "DRAFT"
        assert version.notes is not None
        assert "AI-assisted web research" in version.notes
        assert "pending RA verification" in version.notes


def test_seed_tiers_match_the_spec_s_own_classification(db):
    """
    Legislation/official guidelines are Tier 1; the ASEAN Cosmetic
    Directive annexes are Tier 2 - the spec's own tier table lists
    "Regional directives" as a Tier 2 example, even though NPRA hosts
    and enforces them directly for Malaysia.
    """
    created = seed(db)

    by_title = {v.title: v for v in created}

    assert by_title["Guidelines for Control of Cosmetic Products in Malaysia (Second Edition)"].tier == 1
    assert by_title["Control of Drugs and Cosmetics Regulations 1984"].tier == 1

    asean_versions = [v for v in created if "ASEAN Cosmetic Directive" in v.title]
    assert len(asean_versions) == 5
    assert all(v.tier == 2 for v in asean_versions)
    assert all(v.jurisdiction == "Malaysia" for v in asean_versions)
    assert all("NPRA" in v.issuing_authority for v in asean_versions)
    assert all(v.usage_restrictions and "ASEAN-harmonized" in v.usage_restrictions for v in asean_versions)


def test_seeded_versions_are_readable_via_the_api(client, db, tenant_a):
    """
    Sanity check end-to-end: seed directly via the service layer, then
    confirm the rows are visible through the actual HTTP API (proving
    the seed script's writes and the router's reads agree).
    """
    seed(db)

    response = client.get("/sources", headers=tenant_a["headers"])
    assert response.status_code == 200
    assert len(response.json()) == 7
