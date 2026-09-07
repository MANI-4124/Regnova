# Regulatory content

Real, reviewable regulatory content, authored as YAML files and loaded into
the backend through the real API by `scripts/load_regulatory_content.py`.
This is the "slide-in" half of the content lifecycle -
`scripts/delete_testland_corpus.py` is the "slide-out" half for the
synthetic TESTLAND corpus specifically; this folder is for real content.
See `../CLAUDE.md` "File-based regulatory content pipeline" for the full
design and its rationale.

**Why files, not the API directly:** real verified content should arrive
as files that can be reviewed as a diff, not as a sequence of API calls
nobody can audit afterwards. Loading a file only ever produces `DRAFT`
(or, by default, `IN_REVIEW`) content - it can never write `VERIFIED` or
`ACTIVE` directly. Only a real, authenticated Knowledge Lead can do that,
through the existing content-review endpoints (`verify`/`activate`), or
`scripts/bulk_verify_content.py` at volume.

## Layout

```
regulatory_content/
  <jurisdiction>/<category>/sources/*.yaml
  <jurisdiction>/<category>/requirements/<dimension>/*.yaml
```

`<jurisdiction>` and `<category>` are real, human-readable names (e.g.
`Malaysia`, `Beauty`) - sent to the API exactly as authored (see
"Category scoping" below). `<dimension>` is one of the eight canonical
dimensions:
`CLASSIFICATION_ELIGIBILITY` / `INGREDIENTS` / `CLAIMS` / `LABEL` /
`DOCUMENTS` / `TESTING` / `REPRESENTATION` / `REGISTRATION_READINESS`.

## Source files (`sources/*.yaml`)

```yaml
key: npra-cosmetic-guidelines        # stable identity - see "Stable keys" below
title: "Guidelines for Control of Cosmetic Products in Malaysia (Second Edition)"
issuing_authority: "National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia"
jurisdiction: Malaysia
tier: 1                              # 1 = primary legislation/official guideline, per this codebase's tier vocabulary
source_type: OFFICIAL_GUIDELINE
official_url: "https://..."          # optional
```

## Requirement files (`requirements/<dimension>/*.yaml`)

```yaml
key: beauty-claims-prohibited-therapeutic-claim
jurisdiction: Malaysia
category: Beauty
dimension: CLAIMS
authority: "National Pharmaceutical Regulatory Agency (NPRA)"
authority_interpretation_label: AUTHORITY_REQUIREMENT   # or RECOGNISED_STANDARD
obligation_type: PROHIBITED_THERAPEUTIC_CLAIM
canonical_statement: >
  Cosmetic claims must not assert a therapeutic or medicinal effect.
default_severity: CRITICAL           # CRITICAL | MAJOR | MODERATE | MINOR | INFORMATIONAL
is_hard_gate: true

rules:
  - key: beauty-claims-prohibited-wording-check   # optional - defaults to "<requirement key>__rule-<index>"
    output_type: FINDING_PROPOSAL      # FINDING_PROPOSAL | REQUIREMENT_RESULT | APPLICABILITY
    unknown_behavior: HUMAN_REVIEW     # FAIL_CLOSED | REQUEST_INPUT | HUMAN_REVIEW
    condition:
      op: in
      field: wording
      normalize: lowercase
      value: [cures acne, treats eczema]
```

One requirement file, one-or-more inline rules - the common case (an
obligation and the logic that checks it) needs no cross-file reference at
all. See `../CLAUDE.md` "Regulatory content approval workflow" for the
condition DSL and output-type semantics in full, and
`../tests/testland/fixtures.py` for more worked examples of every shape
(this format mirrors it directly).

**Deferred from this pass:** citing specific `SourceLocation` coordinates
(section/page/schedule) from a requirement/rule file. Files describe
Source/Requirement/Rule content only for now, not individual citations -
see `../CLAUDE.md` for the traceability gap this doesn't yet close.

## Stable keys (`key:`)

`key` becomes `Requirement.human_reference` / `Rule.human_reference` /
`Source.human_reference` - a database-unique, stable identity for that
concept across reloads. **Pick it once and keep it even if you rename or
move the file** - the loader finds existing content by `key`, not by file
path. If you omit `key`, the loader derives one from the file's path
relative to this folder, which means renaming the file *does* change its
identity (a new row, not an update to the old one) - set an explicit `key`
if you plan to reorganize files later.

## Category scoping - why `jurisdiction`/`category` are separate fields

Category scoping is real: `ProductVersion.category`,
`ProductMarketState.jurisdiction` and `RegulatoryBasisRelease.category`
are genuine, separately-pinned fields (see `../CLAUDE.md` "Category
scoping"). `jurisdiction`/`category` in every file are sent to the API
exactly as authored - no composition, no per-jurisdiction opt-in list.
`market` is still sent (required by `RequirementVersionCreate`/
`RegulatoryBasisReleaseCreate`) but always set equal to `jurisdiction` -
it's a non-authoritative field this codebase hasn't fully retired yet;
see `../CLAUDE.md` for that open question.

## Loading

```
python scripts/load_regulatory_content.py --email you@example.com
```

Idempotent and re-runnable - an unchanged file is a true no-op. See the
script's own docstring for `--no-submit`, `--commit`, and `--manifest-out`.

## Verifying at volume

```
python scripts/load_regulatory_content.py --email advisor@example.com --manifest-out manifest.json
python scripts/bulk_verify_content.py --manifest manifest.json --email lead@example.com \
    --rationale "Verified against primary source text, commit <sha>." [--activate]
```
