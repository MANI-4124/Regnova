# TESTLAND synthetic corpus

A permanent, reusable test fixture that exercises the assessment engine
end to end across three product categories with genuinely different
regulatory shapes, in a **fictional jurisdiction that cannot be mistaken
for real content**. Content lives in `tests/testland/fixtures.py`; golden
cases live in `tests/test_testland_corpus.py`; a demo-seeding pair lives in
`scripts/seed_testland_corpus.py` / `scripts/delete_testland_corpus.py`.

## Provenance - how you know this isn't real

- Jurisdiction/market values: `TESTLAND-BEAUTY`, `TESTLAND-NUTRA`,
  `TESTLAND-MEDDEVICE` (share the `TESTLAND` prefix, not one exact value -
  see "Why jurisdiction equals market" below).
- Authority: `"Testland Bureau of Product Safety (TBPS)"` - does not exist.
- Every `SourceVersion`/`RequirementVersion`/`RuleVersion.notes` field
  carries the literal string `[REGNOVA-SYNTHETIC-CORPUS:TESTLAND] Fictional
  content for engine testing. Not a real regulation.` - visible in any
  admin/list view, and the actual key `delete_testland_corpus.py` deletes by.
- `Source.official_url` points at `regulations.testland.example` (the
  `.example` TLD is reserved by RFC 2606 specifically so it can never
  resolve to a real site).
- One dedicated demo `Organization` (name-prefixed the same way) owns
  every customer-side row `scripts/seed_testland_corpus.py` creates.

## Why jurisdiction equals market (not a shared constant)

`ProductMarketState` has only one `market` field - no jurisdiction distinct
from it. Its auto-pin lookup (`ProductMarketStateService.create()`) calls
`get_active_for_jurisdiction(payload.market, payload.market)`, passing that
one value as **both** arguments. A single shared `"TESTLAND"` jurisdiction
constant across all three category markets was the original design and it
does not pin - discovered as a real bug while building this corpus (every
release failed `NO_REGULATORY_BASIS` until fixed). Each category's
`RegulatoryBasisRelease.jurisdiction` must equal its own `market` exactly.
Logged as a standing limitation in `CLAUDE.md` ("category scoping is
unmodelled anywhere").

## "Passing" means G3, not G4

Every "clean" golden case asserts `overall_gate == "G3"` **and**
`readiness_reason_codes == ["G4_UNREACHABLE_NO_APPROVAL_MODEL"]`
specifically - G3 alone isn't enough, since the human-review golden cases
also land on G3, with a different reason code
(`HUMAN_REVIEW_REQUIRED`). G4 (Ready for Registration) and G5 (Authority
Confirmed) are permanently unreachable in this codebase today - no
Approval model exists (G4) and no Execution/Authority Event data exists
(G5), so whatever would otherwise be G4 is deliberately capped at G3. This
is a documented, structural ceiling, not a corpus gap - the bar this
corpus checks against should be raised automatically once the Approval
model lands (see `CLAUDE.md` "Known limitations", G4/G5 entry).

## Coverage

Eight-dimension coverage is required for a clean run: Market Readiness
attempts all eight canonical `RequirementDimension` values every run, and
a dimension with zero active rules reads `UNKNOWN`, which alone forces the
whole gate to G0 regardless of every other dimension's state. Each
category below has *distinctive* content for 3-4 dimensions; the rest are
filled with a minimal, uninteresting "administrative record on file"
`REQUIREMENT_RESULT` check (`build_filler_requirement` /
`build_filler_document_requirement`) so a genuinely clean case can reach
G3 at all.

| Category | Distinctive dimensions | Notable shapes exercised |
|---|---|---|
| Beauty / personal care (control case) | CLAIMS, LABEL, INGREDIENTS | list-shaped subjects, `in` + `normalize`, confidence-gated mandatory field, `APPLICABILITY`-only requirement |
| Nutraceuticals | INGREDIENTS, CLAIMS, LABEL | **flat single-subject** facts (three rules on one implicit subject: dosage soft limit, dosage hard ceiling, `REQUEST_INPUT` batch reference), `not_in` allowlist |
| Medical devices (centerpiece) | CLASSIFICATION_ELIGIBILITY, DOCUMENTS, TESTING, REGISTRATION_READINESS | risk-class-driven pathway, `CONSISTENCY_CHECK` subject kind, every Class-conditional rule modeled as `FINDING_PROPOSAL` (see "Medical devices" below) |

All five severities appear somewhere in the corpus (CRITICAL/MAJOR/MINOR
in Beauty; MODERATE/INFORMATIONAL added by Nutra/Medical Devices). All
three `UnknownBehavior` values appear (`HUMAN_REVIEW` throughout,
`FAIL_CLOSED` on the two confidence-gated LABEL rules, `REQUEST_INPUT` on
Nutra's batch-reference rule). Hard gates, `APPLICABILITY`, and one
cross-document `CONSISTENCY_CHECK` rule (medical devices'
`model_name_consistency`) are all exercised.

## Medical devices: does risk-class-driven pathway fit the model, or strain it?

This was the real question the corpus was built to answer, not just
coverage. Short answer: **it fits, but only by routing every
Class-conditional rule through `FINDING_PROPOSAL`, never
`REQUIREMENT_RESULT`** - and that constraint is not obvious going in.

- `device_risk_class` cannot be computed by this engine - classification
  itself would be a `CALCULATION_COMPONENT`, which is stubbed. It is
  modeled as a caller-supplied, confidence-wrapped fact
  (`{"value": "III", "confidence": 0.95}`), the same shape every other
  caller-supplied classification fact in this codebase uses.
- Gating a rule on class via `all(equals(device_risk_class, "III"),
  not_exists(some_ref))` is **only safe for `FINDING_PROPOSAL` and
  `APPLICABILITY` output types**. A failed `all()` child always resolves a
  definite `NO_MATCH` - for `FINDING_PROPOSAL` that's just "no Finding",
  correct; for `APPLICABILITY` that's `DOES_NOT_APPLY`, correct; but for
  `REQUIREMENT_RESULT`, `_resolve_satisfaction_outcome` maps a `NO_MATCH`
  condition to `NOT_SATISFIED` - a **false failure** for a Class I device
  being checked against a Class III rule, not "doesn't apply". There is no
  way to express "this satisfaction check is inapplicable" via a
  `REQUIREMENT_RESULT` rule's own condition. This is why
  `clinical_evidence`/`bench_test`/`notified_body`/`self_declaration` are
  all `FINDING_PROPOSAL` (checking *absence*, MATCH = problem), never
  `REQUIREMENT_RESULT`.
- A separate, standalone `APPLICABILITY` rule (`classification_iii`) exists
  purely so `test_meddevice_not_applicable_class_i_excluded_from_class_iii_eligibility`
  has something clean to assert `NO_MATCH` against - it does **not** gate
  the `FINDING_PROPOSAL` rules above; each of those re-encodes its own
  class condition independently. That's not redundancy, it's a hard
  requirement: `APPLICABILITY` resolving `DOES_NOT_APPLY` only removes a
  requirement from Market Readiness's weighted scoring, it does not stop
  sibling rules for the same requirement from firing (see `CLAUDE.md`
  "Known limitations"). If `classification_iii`'s condition and (say)
  `notified_body`'s gate condition ever drifted out of sync, nothing in
  the engine would catch it.

Net: the Requirement/Rule model **can** express a risk-class-driven
pathway, but only through a `FINDING_PROPOSAL`-only convention that isn't
enforced anywhere - an author who reaches for `REQUIREMENT_RESULT` for a
conditional rule will get a silently wrong result, not an error. A real
"requirement family" or gate-inheritance concept (one condition, applied to
every rule under a requirement) would close this; it doesn't exist today.

## AC-FR-03-03 ("unsupported categories are labeled Unsupported / Expert
Review Required, not assessed using cosmetic rules") - excluded

This acceptance criterion is **not exercised anywhere in this corpus**, by
deliberate decision, not oversight. It is currently unbuildable:
`RequirementVersion.category` is write-only (set, never read by the
engine or any query), `Product`/`ProductVersion` have no `category` field
at all, and there is no supported-categories registry to check against. A
stand-in that merely asserts a 409 `NO_REGULATORY_BASIS` when no release
exists for a market would test the *opposite* of what this AC describes -
a labelled "Unsupported" state that exists and is shown to the user, vs.
assessment creation being blocked outright - and would make the AC look
covered in test output when the actual behavior it names isn't built.
Logged as a named gap needing real product-category modeling, not
papered over with a misleading test. See `CLAUDE.md` "Known limitations"
(category scoping entry).

## Reuse / staleness - deliberately never triggered

Market Readiness reuse (`DimensionAssessment`/`StateSnapshot` reuse across
runs) has its own known edge cases (see `CLAUDE.md` "Market readiness" /
"Known limitations") that are out of scope for this corpus to exercise.
Every golden case in `tests/test_testland_corpus.py` gets a **brand-new**
`Product`/`ProductVersion`/`ProductMarketState` via `new_golden_product`
and exactly one `market-readiness-runs` call - reuse never has an
opportunity to trigger. This is a deliberate convention, not an oversight:
reuse/staleness needed its own dedicated test category to be tested
honestly, and mixing it into golden-case assertions here would make
failures ambiguous between "the corpus's content is wrong" and "reuse
served a stale result".

## Tier A - explicit, documented exclusions (not exercised at all)

These are known engine gaps that this corpus does not attempt to work
around or stand in for - exercising them honestly isn't possible without
building the missing capability first:

- **`CONFLICT` outcome** - `RequirementResult.outcome` accepts it but the
  engine never produces it; each `APPLICABILITY` rule evaluates
  independently, with no multi-rule-disagreement detection.
- **`SUPERSEDED`** - no lifecycle transition in this codebase ever sets
  this outcome/status on the content this corpus creates.
- **The normalize-function registry** - only `lowercase`/`strip`/
  `collapse_whitespace` exist. This corpus's `in`/`not_in` rules only use
  `lowercase`, deliberately not exercising anything beyond the real
  registry's current size.
- **The single global confidence threshold** (`DEFAULT_MIN_CONFIDENCE =
  0.5`, hardcoded in `app/engine/condition_evaluator.py`) - not
  release-scoped configuration yet. This corpus's confidence values
  (0.2/0.3 for "low", 0.9/0.95 for "high") are chosen relative to that one
  global constant; there is no per-category threshold to test against.

## Tier B - authoring gotchas a rule author needs to know (not bugs, but sharp edges)

- **Dimension-level `NON_COMPLIANT` is severity-blind; the gate is not.**
  Any open Finding - even MINOR severity - forces its whole dimension to
  `NON_COMPLIANT`, which forces the overall gate to G1 regardless of that
  Finding's actual severity. `test_beauty_critical_fail` and friends read
  as expected because they use CRITICAL findings, but this corpus does
  not have a MINOR-severity-forces-G1 golden case - that's this exact
  gotcha, already logged in `CLAUDE.md`, not a coverage hole worth adding
  a case for.
- **A Requirement enforced purely via `FINDING_PROPOSAL` scores zero
  weight in its dimension's progress score.** `FINDING_PROPOSAL` never
  writes a `RequirementResult` row, only a `Finding`, so
  `MarketReadinessService._dimension_score` never sees it as an
  applicable requirement. Every medical-device Class-conditional rule in
  this corpus is `FINDING_PROPOSAL` (see "Medical devices" above) -
  meaning DOCUMENTS/TESTING/REGISTRATION_READINESS's *scored* progress in
  medical devices comes entirely from the filler requirements, not the
  interesting content. Worth knowing before reading too much into a
  `dimension_summary` progress number for this category.
- **`exists`/`not_exists` never confidence-gate.** Only comparison ops
  (`equals`, `not_equals`, `gt`, etc.) check confidence. Every LABEL rule
  in this corpus deliberately uses `not_equals(extracted, "")` rather than
  `exists(extracted)` for exactly this reason - discovered as a real bug
  while building the human-review golden cases (a low-confidence value
  still resolved MATCH under `exists`).
- **`NO_MATCH` shields a sibling's `UNKNOWN` in `all()`; `MATCH` does
  not.** In an `all()` node, a definite `NO_MATCH` from one child always
  wins over a sibling's low-confidence `UNKNOWN`, but a sibling `MATCH`
  does not provide the same shielding. `test_meddevice_human_review_low_confidence_classification`
  supplies every Class-III-conditional reference as *present* specifically
  so each rule's own `not_exists` leg resolves a definite `NO_MATCH` and
  gets shielded from the classification leg's low-confidence `UNKNOWN` -
  omitting any one of them (as an earlier draft of this test did with
  `self_declaration_ref`) produces an unexpected Finding instead of a
  clean human-review case.

## Re-seeding / cleanup against a real database

`tests/test_testland_corpus.py` runs entirely against the in-memory SQLite
test harness - nothing above needs a real database. To browse this corpus
through the actual running API against Postgres:

```
python scripts/bootstrap_interim_operator.py --email you@example.com --password '...' --first-name Jane --last-name Doe   # once, if not already done
python scripts/seed_testland_corpus.py --email you@example.com
```

The seed script doesn't just create content - it immediately assesses each
of the three demo products with a **deliberately different outcome** (same
`beauty_facts`/`nutra_facts`/`meddevice_facts` shapes
`tests/test_testland_corpus.py` asserts on): Beauty comes back a clean pass,
Nutraceuticals a critical-fail (dosage over the hard ceiling), Medical
Devices a human-review case (low-confidence Class III classification). This
is specifically so a tool consuming the real API - the baseline dashboard
(`../../baseline-dashboard/`, a sibling of this repo, not committed here) -
has three visibly distinct states to render, not three identical
"not yet assessed" cells.

To remove everything the seed script created (regulatory content + the one
demo organization and its products), in one command:

```
python scripts/delete_testland_corpus.py --yes
```

Internally this is two ordered steps, not one - see the comment in
`scripts/delete_testland_corpus.py` (`_delete_customer_side_rows`) for why
the demo organization must be deleted before the regulatory content:
`AssessmentRun`/`StateSnapshot` hold `ON DELETE RESTRICT` references to
`ProductVersion`/`RegulatoryBasisRelease`, so deleting the regulatory
content first fails outright until those referencing rows are gone.
