"""
One-time seed script for the first batch of regulatory Source content.

Every row here was found via AI-assisted web research (WebSearch/WebFetch
against npra.gov.my) on 2026-08-11, for the RegNova Regulatory OS
regulatory-content-model milestone. It is NOT primary-source legal
reading. Every SourceVersion is created in DRAFT status with a notes
field stating exactly this - none of it should be treated as
VERIFIED/ACTIVE until RegNova's Knowledge Lead / an authorized RA
reviewer confirms it against the actual primary text.

Run against a real (non-SQLite) database once DATABASE_URL points to one,
from the backend/ directory:

    python scripts/seed_regulatory_sources.py

This has been exercised against the SQLite test harness (see
tests/test_seed_regulatory_sources.py) to confirm the logic itself is
correct, but has NOT been run against a real Postgres database - there
isn't one available in this environment.
"""

from __future__ import annotations

from app.core.database import build_database
from app.core.settings import get_settings
from app.modules.source.models import Source
from app.modules.source.repository import SourceRepository
from app.modules.source_version.models import SourceVersion, TranslationStatus
from app.modules.source_version.repository import SourceVersionRepository

RESEARCH_DATE = "2026-08-11"

_PROVENANCE = (
    f"AI-assisted web research ({RESEARCH_DATE}), pending RA verification - "
    "not primary-source legal reading. "
)

SCAFFOLD_SOURCES = [
    dict(
        title="Guidelines for Control of Cosmetic Products in Malaysia (Second Edition)",
        issuing_authority="National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia",
        jurisdiction="Malaysia",
        tier=1,
        source_type="OFFICIAL_GUIDELINE",
        official_url=(
            "https://www.npra.gov.my/images/Guidelines_Central/"
            "Guidelines_on_Cosmetic/GUIDELINES_FOR_CONTROL_OF_COSMETIC_PRODUCTS_IN_MALAYSIA.pdf"
        ),
        notes=(
            _PROVENANCE
            + "NPRA's own site lists this as 'Second Edition', updated Aug-22; "
            "not independently confirmed beyond that listing (no amendment "
            "history checked)."
        ),
    ),
    dict(
        title="Control of Drugs and Cosmetics Regulations 1984",
        issuing_authority="National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia",
        jurisdiction="Malaysia",
        tier=1,
        source_type="LEGISLATION",
        official_url=None,
        notes=(
            _PROVENANCE
            + "Title confirmed via NPRA's own citations of it, but current "
            "amendment/consolidation status was NOT verified and no confirmed "
            "official gazette URL was found. Recommend checking Malaysia's "
            "official e-Federal Gazette / Attorney General's Chambers portal "
            "before treating this as complete."
        ),
    ),
    dict(
        title=(
            "ASEAN Cosmetic Directive - Annex II: Substances Which Must Not "
            "Form Part of the Composition of Cosmetic Products (banned "
            "substances), as adopted by NPRA Malaysia"
        ),
        issuing_authority="National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia",
        jurisdiction="Malaysia",
        tier=2,
        source_type="REGIONAL_DIRECTIVE",
        official_url="https://www.npra.gov.my/index.php/en/cosmetics-guideline-annex-i-vii",
        usage_restrictions=(
            "ASEAN-harmonized content: Malaysia's NPRA-published adoption of "
            "the ASEAN Cosmetic Directive's Annex II, a regional directive "
            "(ASEAN Cosmetic Committee), not standalone Malaysian legislation."
        ),
        notes=(
            _PROVENANCE
            + "NPRA's annex index page shows 'June-26' against this annex; "
            "semantics unconfirmed (publication vs. revision vs. effective "
            "date). Direct per-annex document URL not individually captured - "
            "official_url points to the index page."
        ),
    ),
    dict(
        title=(
            "ASEAN Cosmetic Directive - Annex III: Substances Subject to "
            "Restrictions and Conditions (restricted substances), as adopted "
            "by NPRA Malaysia"
        ),
        issuing_authority="National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia",
        jurisdiction="Malaysia",
        tier=2,
        source_type="REGIONAL_DIRECTIVE",
        official_url="https://www.npra.gov.my/index.php/en/cosmetics-guideline-annex-i-vii",
        usage_restrictions=(
            "ASEAN-harmonized content: Malaysia's NPRA-published adoption of "
            "the ASEAN Cosmetic Directive's Annex III, a regional directive "
            "(ASEAN Cosmetic Committee), not standalone Malaysian legislation."
        ),
        notes=(
            _PROVENANCE
            + "NPRA's annex index page shows 'June-26' against this annex; "
            "semantics unconfirmed. Direct per-annex document URL not "
            "individually captured - official_url points to the index page."
        ),
    ),
    dict(
        title=(
            "ASEAN Cosmetic Directive - Annex IV: Colouring Agents Allowed "
            "for Use in Cosmetic Products (permitted colourants), as adopted "
            "by NPRA Malaysia"
        ),
        issuing_authority="National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia",
        jurisdiction="Malaysia",
        tier=2,
        source_type="REGIONAL_DIRECTIVE",
        official_url="https://www.npra.gov.my/index.php/en/cosmetics-guideline-annex-i-vii",
        usage_restrictions=(
            "ASEAN-harmonized content: Malaysia's NPRA-published adoption of "
            "the ASEAN Cosmetic Directive's Annex IV, a regional directive "
            "(ASEAN Cosmetic Committee), not standalone Malaysian legislation."
        ),
        notes=(
            _PROVENANCE
            + "Revision date for this annex was not captured in my fetch of "
            "NPRA's index page (unlike the others) - recheck npra.gov.my "
            "directly. Direct per-annex document URL not individually "
            "captured - official_url points to the index page."
        ),
    ),
    dict(
        title=(
            "ASEAN Cosmetic Directive - Annex VI: Preservatives Which "
            "Cosmetic Products May Contain (permitted preservatives), as "
            "adopted by NPRA Malaysia"
        ),
        issuing_authority="National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia",
        jurisdiction="Malaysia",
        tier=2,
        source_type="REGIONAL_DIRECTIVE",
        official_url="https://www.npra.gov.my/index.php/en/cosmetics-guideline-annex-i-vii",
        usage_restrictions=(
            "ASEAN-harmonized content: Malaysia's NPRA-published adoption of "
            "the ASEAN Cosmetic Directive's Annex VI, a regional directive "
            "(ASEAN Cosmetic Committee), not standalone Malaysian legislation."
        ),
        notes=(
            _PROVENANCE
            + "NPRA's annex index page shows 'June-26' against this annex; "
            "semantics unconfirmed. Direct per-annex document URL not "
            "individually captured - official_url points to the index page."
        ),
    ),
    dict(
        title=(
            "ASEAN Cosmetic Directive - Annex VII: UV Filters Which "
            "Cosmetic Products May Contain (permitted UV filters), as "
            "adopted by NPRA Malaysia"
        ),
        issuing_authority="National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia",
        jurisdiction="Malaysia",
        tier=2,
        source_type="REGIONAL_DIRECTIVE",
        official_url="https://www.npra.gov.my/index.php/en/cosmetics-guideline-annex-i-vii",
        usage_restrictions=(
            "ASEAN-harmonized content: Malaysia's NPRA-published adoption of "
            "the ASEAN Cosmetic Directive's Annex VII, a regional directive "
            "(ASEAN Cosmetic Committee), not standalone Malaysian legislation."
        ),
        notes=(
            _PROVENANCE
            + "NPRA's annex index page shows 'Dec-25' against this annex; "
            "semantics unconfirmed. Direct per-annex document URL not "
            "individually captured - official_url points to the index page."
        ),
    ),
]


def seed(db) -> list[SourceVersion]:
    sources = SourceRepository(db)
    versions = SourceVersionRepository(db)

    created = []

    for entry in SCAFFOLD_SOURCES:
        source = sources.create(Source())

        version = SourceVersion(
            source_id=source.id,
            translation_status=TranslationStatus.ORIGINAL.value,
            **entry,
        )
        versions.create(version)
        created.append(version)

    db.commit()

    return created


def main() -> None:
    settings = get_settings()
    database = build_database(settings)
    session = database.session_factory()

    try:
        created = seed(session)
        for version in created:
            print(f"created DRAFT source_version {version.id}: {version.title}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
