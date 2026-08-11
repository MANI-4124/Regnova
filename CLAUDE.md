# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo's git root is `backend/` itself (not the `D:\Regnova` parent — there is no repo at the parent level). All commands below assume the working directory is `D:\Regnova\backend`.

## Product spec

The full product/engineering spec — "RegNova Regulatory OS: Agency Product & Engineering Definition Pack", v1.0 — lives at `C:\Users\manid\Downloads\agency-definition-pack.md`. It's intentionally **not** committed to this repo: it's marked Confidential and is an external business document, not source code. Sections referenced so far: A5.2 (bounded contexts / modular-monolith strategy), C14 (event and audit contract), Appendix 2 (canonical V1 domain events), C4/C4.1 (regulatory source model, source tiers), C9 (bitemporal versioning), C8.1 (document extraction schemas). Check there before inventing bounded-context, event-catalog, or product-behavior details from scratch — this repo's actual code is currently a much smaller slice than what the spec describes (see the outbox/domain-events notes below for a concrete example of that gap).

## Commands

No lint/format tooling is configured. Tests use pytest against an in-memory SQLite DB (see `tests/conftest.py`) — no live Postgres needed to run them.

```bash
# Install (editable) with dependencies, including the dev group (pytest, httpx)
pip install -e ".[dev]"

# Run the dev server
uvicorn app.main:app --reload

# Run the test suite
pytest
pytest tests/test_product_version_cross_org.py -v   # single file
pytest -k test_get_version_across_orgs_returns_404  # single test

# Alembic migrations (run from backend/, alembic.ini lives here)
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

Alembic's `autogenerate` needs a live Postgres connection (`DATABASE_URL`); migrations authored without one (as `product_versions`' was) are hand-written to match the `op.create_table`/`op.create_index` style Alembic itself produces — check the revision chain (`down_revision`) against the newest file in `migrations/versions/` before adding another one by hand.

Environment variables are loaded from `backend/.env` via `app/core/settings.py` (`Settings`, pydantic-settings). Key vars: `DATABASE_URL`, `SECRET_KEY`, `DEBUG`, `API_PREFIX`.

`python-jose[cryptography]`, `passlib[bcrypt]`, and `email-validator` (needed by `app/modules/auth` and pydantic's `EmailStr`) are declared in `pyproject.toml`'s `dependencies` — a clean `pip install -e .` (or `-e ".[dev]"`) picks them up. (These were missing from `pyproject.toml` for a while despite being imported by `auth` — only present in this sandbox's `.venv` because they'd been pip-installed ad hoc — fixed once this actually broke a fresh install.)

## Architecture

FastAPI + SQLAlchemy 2.0 (ORM, not Core) + Alembic + PostgreSQL (via `psycopg` v3), Pydantic v2 for schemas/settings. Multi-tenant SaaS: almost every domain entity belongs to an `Organization`.

### Module structure

Code lives under `app/modules/<name>/`, each module following the same file split:

- `models.py` — SQLAlchemy `Base` subclasses (see `app/core/database.py` for `Base`)
- `repository.py` — DB queries only, subclasses `BaseRepository[Model]` (`app/common/repository.py`), constructed as `Repository(db: Session)`
- `service.py` — business logic; owns transaction boundaries (`self.db.commit()` / `rollback()`), converts models to response schemas
- `schemas.py` — Pydantic request/response models
- `router.py` — FastAPI `APIRouter`; each router defines its own `get_<name>_service(db = Depends(get_db_session)) -> XService` provider
- `exceptions.py` — module-specific exceptions subclassing the shared ones in `app/common/exceptions.py`

Existing modules: `auth`, `organization`, `product`, `product_version`, `role`, `user`, `rbac`, `source`, `source_version`, `source_location`, `requirement`, `requirement_version`.

`audit` owns the transactional outbox (`app/modules/audit/models.py:OutboxEvent`) — no `router.py`/`schemas.py`, since there's no public API for outbox rows in this milestone. Domain modules depend on it one-directionally (`organization`/`user`/`product_version` import `OutboxRepository`; `audit` imports nothing domain-specific back).

New modules should copy this same five/six-file shape and get wired into `app/main.py` (`create_app()`: import the router, `app.include_router(...)`) and into `app/models.py` (imported there so Alembic's `target_metadata` picks it up — see `migrations/env.py`, which imports `app.models`).

**`product_version` is the first nested-resource module** — its router (`app/modules/product_version/router.py`) is mounted at `/products/{product_id}/versions` instead of a flat top-level prefix. Its service resolves `product_id` through `ProductRepository.get_by_id(organization_id, product_id)` and 404s before doing anything version-related, so a `product_id` belonging to another org can't be used to list/create/read versions — the same "resolve the parent through the tenant boundary first" shape as the `role_id` fix in `rbac/service.py`. Its repository's `get_by_id` also takes `(organization_id, product_id, version_id)` — three args, not the `(organization_id, entity_id)` shape used by `Product`/`User`/`Role` — because a version fetched through the wrong `product_id` (even within the same org) should 404 too, not just across orgs. If you add another nested-resource module, follow this shape rather than the flat one.

### Regulatory content: `source` / `source_version` / `source_location`

Implements the RegNova spec's C4 (regulatory source model) + C9 (bitemporal versioning), modeling how a Malaysia cosmetics regulation, ASEAN directive annex, or RegNova interpretation is cited down to an exact section/article/page/table/paragraph coordinate.

- **Not organization-scoped, unlike every other module.** Per spec A2's scope table, canonical regulatory sources are "Supplied / validated by RegNova," not customer data — all orgs read the *same* `Source` rows. None of the three models carry `organization_id`; `SourceRepository`/`SourceVersionRepository`/`SourceLocationRepository` are correspondingly not org-scoped. Don't add `organization_id` here by reflex just because every other module has it.
- **`Source` is deliberately near-empty** (just `id`/timestamps) — descriptive fields (`title`, `issuing_authority`, `jurisdiction`, `tier`, `source_type`, `official_url`) live on `SourceVersion`, following C4.1's literal field placement rather than hoisting them onto `Source` for query convenience. This was a flagged, not obvious, choice — if querying "list all sources with their current title" without a join turns out to matter, revisit.
- **`SourceVersion.tier` is a plain `Integer` (1–4), not a string enum** like `status` — tier has real ordinal meaning the spec leans on (`tier <= 2` is a meaningful query), unlike `DRAFT`/`ACTIVE`/etc.
- **`SourceLocation` uses a compound coordinate** — `section`/`article`/`schedule`/`page`/`table_ref`/`paragraph` are independent nullable columns on one row (not a `location_type` enum + single value), since real citations are usually compound (e.g. "Section 5(2), Second Schedule, page 47"). At least one must be set — enforced by a Pydantic `model_validator` in `schemas.py`, not a DB constraint. Column is named `table_ref`, not `table` — the latter is a reserved SQL keyword.
- **`source_version` is nested under `source`** (`/sources/{source_id}/versions`, same shape as `product_version`: resolves `source_id` and 404s before touching versions, `get_by_id(source_id, version_id)` compound-scoped). **`source_location` is deliberately flat** (`/source-locations`, filterable by `?source_version_id=`), not nested a third level deep — `SourceLocationCreate` carries `source_version_id` as a body field instead of a path param, and the service validates it resolves to a real `SourceVersion` (404 if not) via `SourceVersionRepository.get_by_id_only(version_id)` — a second, unscoped lookup method distinct from the compound one `source_version`'s own nesting needs. This FK check is existence-only, not a tenant-boundary check like the `role_id`/`product_id` validations elsewhere in this codebase — there's no organization dimension on `SourceVersion` to cross.
- **Reads are open to any authenticated user** (`require_employee` — the first real use of that dependency in the codebase; every other module uses `require_manager`/`require_admin`) since Source is meant to be citable/visible to any customer user, gated more finely by `is_full_text_displayable` on the content itself, not by role.
- **Write endpoints (`POST`/`PUT` on all three) are gated behind `require_admin` as an explicitly-flagged interim placeholder — this is a known-wrong stopgap, not a real decision.** Source content is authored/reviewed by RegNova's own staff (spec FR-13: "Regulatory Knowledge Lead, authorized RA reviewer"), not a customer org's admin, and the RBAC model has no concept of a RegNova-internal actor distinct from a customer-org role yet. The working assumption (unconfirmed) is that RegNova would be modeled as `Organization` "tenant zero" with its own `User`/`Role` rows using new codes (`KNOWLEDGE_LEAD`, `RA_REVIEWER`) rather than a new actor-type concept — see the router files' inline comments. Don't build on top of `require_admin` here as if it were correct; replace it once the actor model is resolved.
- **No lifecycle audit trail**, mirroring `product_version`'s same gap: `SourceVersionService.update()` just overwrites `status`/`verified_at`/`recorded_at`/`activated_at`/`supersedes_id`/`superseded_by_id` in place via a generic `setattr` loop — no dedicated `verify()`/`activate()`/`supersede()` methods, no record of who transitioned what or when. When a new version supersedes an old one, the caller is responsible for setting **both** `old.superseded_by_id` and `new.supersedes_id` — nothing enforces they're kept in sync.
- `scripts/seed_regulatory_sources.py` — a one-off script (not wired into the app) that creates the first batch of `Source`/`SourceVersion` rows via the service layer directly (bypassing HTTP/RBAC entirely, since it's a data-curation operation, not a simulated customer request). All rows are `DRAFT` with a `notes` field stating they came from AI-assisted web research, not primary-source legal reading. Exercised against the SQLite test harness (`tests/test_seed_regulatory_sources.py`) but never run against a real Postgres database — none is available in this environment.

### Regulatory content: `requirement` / `requirement_version`

Implements C5 (requirement model). Same ownership model as `source` — no `organization_id`, reads via `require_employee`, writes via `require_admin` as the same explicitly-flagged interim placeholder (same unresolved actor-model question — see the `source` section above).

- **`Requirement` vs. `RequirementVersion` split**: unlike C4.1 (which named its field table "Required Source Version fields," making the split fairly explicit), C5 doesn't say which of its eight field groups live on `Requirement` vs. `RequirementVersion`. The decision made here: `Requirement` stays a thin identity anchor (`id` + `human_reference`, mirroring `Source`'s shape) and **all eight C5 field groups — including Scope — live on `RequirementVersion`**. The tell is C5's own definition: *"A Requirement Version is the effective, source-backed expression of that obligation **for a defined context**"* — "for a defined context" reads as Scope being part of what a version pins down, not a fixed property of the stable concept. Flagged as a judgment call, not a certainty, when this was proposed.
- **`dimension` + `context`**: the spec's "product/ingredient/claim/document/test context" bullet isn't five separate typed columns — the actual shape of "context" varies completely by which of B3's eight dimensions a requirement targets. Modeled as a real `dimension` column (matching B3's eight dimensions exactly: `CLASSIFICATION_ELIGIBILITY`/`INGREDIENTS`/`CLAIMS`/`LABEL`/`DOCUMENTS`/`TESTING`/`REPRESENTATION`/`REGISTRATION_READINESS`) plus a `context` JSON column (schema-versioned via `context_schema_name`/`context_schema_version`), leaning on C3's explicit allowance for schema-versioned JSON payloads alongside relational ownership. Same schema-versioned-JSON treatment for `applicability_predicate` (a "constrained predicate," read as the same kind of constrained-declarative-expression C6 describes for Rule's Condition component, not free code).
- **`unknown_behavior`** reuses C6's own three-value vocabulary verbatim (`FAIL_CLOSED`/`REQUEST_INPUT`/`HUMAN_REVIEW`) — C5's "explicit unknown behavior" and C6's "Unknown policy" read as the same concept at two layers of the system.
- **`default_severity`** reuses B4's Finding severity vocabulary verbatim (`CRITICAL`/`MAJOR`/`MODERATE`/`MINOR`/`INFORMATIONAL`) — B4 explicitly frames Finding severity as inherited from the requirement.
- **`authority_interpretation_label`** reuses FR-11's exact four-value vocabulary (`AUTHORITY_REQUIREMENT`/`RECOGNISED_STANDARD`/`REGNOVA_INTERPRETATION`/`SECONDARY_RESEARCH`), which maps 1:1 onto `Source`'s four tiers — **independently settable, not derived from linked `SourceLocation`/`SourceVersion` tiers.** That non-derivation was an explicit decision, not an oversight — flag it if it turns out the two should actually stay in sync.
- **`verification_level` is a plain open `String`, not an enum** — deliberately not reusing A6's Trust States (`AI_ASSESSED`/etc.), since "verification level" for evidence policy isn't independently defined anywhere in the spec. Treat this the same way as `obligation_type`: needs real definition from RegNova's Regulatory Knowledge Lead before it's worth constraining to a closed vocabulary.
- **Temporal fields use the exact same names as `SourceVersion`** — `effective_from`/`effective_to`, `recorded_at`/`retired_at`, `supersedes_id`/`superseded_by_id`. C5's own Temporal group lists "valid-from/to" as a field distinct from "effective-from/to," which doesn't match C9's bitemporal table (only one system-time pair, expressed as `recorded_at`/`retired_at` point-in-time timestamps, not a named range). Resolved as: "valid-from/to" is C5's phrasing for that same `recorded_at`/`retired_at` axis, not a third temporal concept — so `RequirementVersion` reuses those two field names directly rather than introducing `valid_from`/`valid_to` as new terminology. "Included basis releases" is deferred exactly like `SourceVersion`'s "release membership" — not built, will be a join table once Regulatory Basis Release exists.
- **Provenance's "one or more source-location links"** is a plain many-to-many association table (`requirement_version_source_locations` — `RequirementVersionSourceLocation` in `requirement_version/models.py`), not a dedicated five-file linking module — it carries no independent lifecycle, just `requirement_version_id` + `source_location_id`. Exposed on `RequirementVersionCreate`/`Update` as `source_location_ids: list[UUID]`; the service validates every id resolves to a real `SourceLocation` (404 if not) via `SourceLocationRepository.get_by_id()` (looped per id — fine at this scale, revisit if it ever needs to be bulk). `update()` treats `source_location_ids` as PATCH-replace-the-whole-set semantics when explicitly provided (checked via `payload.model_fields_set`, not just truthiness, so an explicit empty list correctly clears all links rather than being indistinguishable from "not provided").
- **Applicability outcomes (C5.1: Applies/Does Not Apply/Unknown/Conflict) are NOT stored on `RequirementVersion` at all.** `status` describes the content's own review maturity; an applicability outcome describes the *result of evaluating* a specific `RequirementVersion` against a specific product/context at assessment time — C10 confirms this belongs to a future "Requirement Result" entity produced by an Assessment Run, not built in this milestone. C5.1's retention requirement (*"that decision must retain its predicate inputs and source/rule lineage"*) is a hard constraint on whatever builds that entity: it needs `outcome` (the four-value enum), a JSON snapshot of the actual `predicate_inputs` evaluated, and **relational** (not JSON-buried) links to the `RequirementVersion`, `RuleVersion`(s) (once C6 exists), and `SourceLocation`(s) involved — per C3's rule that lineage must stay a queryable relational key. The B5.2 business rule ("only Does Not Apply excludes from the readiness denominator") is enforced wherever that future entity's aggregation logic lives, not here.
- Same lifecycle-audit-trail gap as `source_version`/`product_version`: `update()` just overwrites fields via `setattr`, no dedicated `verify()`/`activate()`/`supersede()` methods.

## Regulatory content decisions (not yet reflected in code)

No `document`/`documents` module exists yet (C8.1's extraction schemas aren't implemented), so these are recorded here for whoever builds it, confirmed against real NPRA requirements via web research on 2026-08-11:

- **Add "Safety Assessment Report" as an eighth C8.1 extraction schema** (originally seven: Formula/INCI, Artwork, GMP certificate, CFS, COA, Stability report, LOA). NPRA's PIF guideline (Annex I, Part 13) and its dedicated Safety Assessment guideline (Annex I, Part 6) both require this as a distinct document. Required normalized fields: product/formula version, safety assessor identity/qualification, toxicological endpoints assessed, exposure calculation, conclusion, assessment date.
- **COA's required fields must explicitly include heavy metal and microbiological test limits**, not leave them implicit under generic "specification/result/unit" — NPRA has a dedicated limit table for these (Annex I, Part 14).

### Request flow

`router.py` → FastAPI `Depends` chain resolves a `Session` (`app/core/dependencies.py:get_db_session`, one session per request, pulled from `request.app.state.database.session_factory`) → a `Service` instance → the service uses a `Repository` for queries and owns the commit/rollback. Errors are raised as `AppException` subclasses (`app/common/exceptions.py`) and turned into a uniform JSON error body by the global handler registered in `app/common/handlers.py` (`{"success": false, "error": {"code", "message"}}`). Routers do NOT catch `AppException` themselves — only a couple of legacy routes still catch bare `ValueError` and re-raise as `HTTPException` (see `organization/router.py`); new code should just let `AppException` subclasses propagate.

### Domain events / outbox

State-changing actions publish schema-versioned domain events through a transactional outbox (`app/modules/audit/`), per the RegNova spec's C14 event/audit contract.

- Every event-emitting service builds an `OutboxRepository(db)` alongside its own repository (same shape as `product_version`'s `self.products = ProductRepository(db)`) and calls `self.outbox.append(...)` **before** its own `self.db.commit()` — never a separate commit. The outbox row and the domain write land in the exact same transaction; that's the whole transactional guarantee, and it falls out of this codebase's existing "repositories flush, services commit once" convention rather than needing new plumbing.
- `correlation_id` and `actor_user_id` are threaded as explicit optional keyword arguments into the specific service methods that emit events (not baked into service `__init__`), sourced from `Depends(get_correlation_id)` and `current_user.id` in the router handler — matching the existing convention of passing context (like `organization_id`) explicitly into service methods rather than stashing it on the instance.
- `CorrelationIdMiddleware` (`app/core/correlation.py`) reads/generates `X-Correlation-Id` per request onto `request.state`; `get_correlation_id` (`app/core/dependencies.py`) is the FastAPI dependency that exposes it to routers.
- `OutboxRepository.get_unpublished()` applies `FOR UPDATE SKIP LOCKED` only when the session's dialect is `postgresql` — that's a Postgres-only concurrent-claim guarantee, not something meaningfully testable against the SQLite database the test suite runs on (SQLite silently no-ops `with_for_update()` rather than erroring, but relying on that silently would be fragile).
- `app/modules/audit/worker.py:dispatch_pending_events()` is the dispatcher — a plain function, not auto-started anywhere (no background loop wired into `lifespan()`). It's meant to be invoked by a scheduler/worker process. The actual dispatch transport (queue/bus/etc.) is deliberately not chosen yet — it logs the event — pending the durable-work architecture spike the spec (A5.1) calls for.
- First three events wired up so far: `WorkspaceActivated` (`OrganizationService.create()`), `MembershipChanged` (`UserService.create()`/`update()` when `role_id`/`is_active` change/`delete()` — **not** `RoleService`, since Appendix 2 describes membership/assignment changes, not `Role`-entity-definition edits — open question logged for RegNova product-side clarification if that's wrong), `ProductVersionPublished` (`ProductVersionService.publish()`, a dedicated method/endpoint — not folded into the generic `update()`; see the Known Limitations note below on why).

### Multi-tenancy pattern

`Organization` is the tenant root (`app/modules/organization/models.py`). Entities scoped to an org (`User`, `Role`, `Product`) carry an `organization_id` FK and their repositories require `organization_id` as an explicit argument on lookups (see `UserRepository.get_by_id(organization_id, user_id)`, `get_all(organization_id)`) — this is how tenant isolation is enforced, there is no automatic row-level filtering. When adding a new org-scoped entity, follow this same explicit-`organization_id`-parameter convention rather than relying on `BaseRepository`'s plain `get_by_id(entity_id)`. `Organization` itself and other non-scoped lookups use `BaseRepository`'s methods directly.

### Auth & RBAC

- JWT access/refresh tokens (`app/modules/auth/jwt.py`, HS256 via `settings.secret_key`). Access tokens embed `organization_id` and `role_id` as custom claims.
- `get_current_user`/`get_current_active_user` (`app/modules/auth/dependencies.py`) decode the bearer token and load the `User` scoped by `organization_id` from the token — a token cannot be used to fetch a user from a different org.
- RBAC is role-code based, not a permissions table: `app/modules/rbac/service.py:RBACService.require_role(db, user, *role_codes)` loads the user's `Role` and checks `role.code.upper() in role_codes`. `app/modules/rbac/dependencies.py` exposes ready-made FastAPI dependencies `require_admin` / `require_manager` / `require_employee` (each a superset of the next, e.g. `require_manager` accepts `ADMIN` or `MANAGER`) — use these in router signatures rather than calling `RBACService` directly.
- `app/modules/rbac/permissions.py` defines a `Permission` enum (`organization:read`, `user:write`, etc.) but nothing currently consumes it — the enforcement path in use today is role-code based (`require_admin` etc.), not permission-based.

### Shared building blocks

- `app/shared/mixins/`: `UUIDMixin` (UUID PK, `default=uuid.uuid4`), `TimestampMixin` (`created_at`/`updated_at` with `server_default=func.now()`). Every model inherits both.
- `app/common/repository.py:BaseRepository` — generic `get_all`/`get_by_id`/`create`/`update`/`refresh`/`delete`. `create`/`update` call `flush()`+`refresh()` but not `commit()` — committing is the service layer's job.
- `app/common/exceptions.py` — base `AppException` plus `NotFoundException` (404), `ConflictException` (409), `ValidationException` (400), `AuthenticationException` (401), `AuthorizationException` (403). Module exceptions subclass these (e.g. `OrganizationNotFound(NotFoundException)`), matching FastAPI status codes to the base class.
- `app/common/responses.py:ApiResponse[T]` — a generic response envelope; not currently wired into routers (routers return response-model schemas or plain dicts directly).

## Security

- **`organization_id` must always be derived from `current_user.organization_id`, never accepted as a query or body parameter from the client.** Every org-scoped route must depend on `get_current_active_user` (directly or via `require_admin`/`require_manager`/`require_employee`) and pass `current_user.organization_id` into the service call — do not add `organization_id: UUID` as a router function parameter. This applies to every org-scoped module (`product`, `product_version`, `role`, `user`). Accepting it from the request lets an authenticated caller from one org read or write another org's data (cross-tenant IDOR) simply by passing a different `organization_id`.
- **Any other foreign key crossing into another resource must be validated against the caller's org too, not just `organization_id` itself.** `product_version`'s service resolves `product_id` through the `product` module's own org-scoped repository before touching anything else — don't trust a path/body id just because the surrounding request is authenticated.

## Known limitations / revisit later

- **`product_version`'s "current version" is a computed query** (`ProductVersionRepository.get_current`: most recent `is_active` version with `status == APPROVED`, ordered by `created_at`), not a stored pointer. This will likely need revisiting once multi-market versions exist (e.g. "current version for region X" isn't expressible as a single global ordering anymore).
- **`product_version` `status` transitions (`DRAFT`/`IN_REVIEW`/`APPROVED`/`ARCHIVED` via `update()`) still have no audit trail** — `update()` just overwrites `status` in place, with no record of who changed it or when. `publish()` is a separate, unrelated action: it sets `released_at` and emits `ProductVersionPublished`, but doesn't touch `status` at all.
- **`product_version`'s publish lifecycle needs a full pass against FR-02** (`Draft`/`Ready to Publish`/`Published`/`Superseded` states, immutable content hash, idempotent impact job) — this milestone only adds the event (`publish()` sets `released_at` and emits `ProductVersionPublished`, guarded so it can't fire twice via `ProductVersionAlreadyPublished`), not the real state machine. `ProductVersion.status` (`DRAFT`/`IN_REVIEW`/`APPROVED`/`ARCHIVED`) is a *different* vocabulary than the spec's publish lifecycle and the two are not reconciled yet.
- **`source`/`source_version`/`source_location` write endpoints are gated behind `require_admin`, which is the wrong permission model** — Source is RegNova-owned content, not customer-org data, and there's no actor-type distinction in RBAC yet for RegNova's own staff (Knowledge Lead / RA reviewer, spec FR-13). See the "Regulatory content" section above for the working (unconfirmed) assumption. Do not treat any `Source`/`SourceVersion` row as trustworthy/citable until this is resolved and content has gone through real RA review — everything seeded by `scripts/seed_regulatory_sources.py` is `DRAFT` and explicitly marked as AI-research-derived for exactly this reason.
- **`source_version`'s draft→review→verified→active→superseded→archived lifecycle has no dedicated transition methods or audit trail**, mirroring `product_version`'s same gap — see the "Regulatory content" section above.

## Conventions observed in existing code

- Commit messages follow Conventional Commits scoped to the module: `feat(organization): implement complete CRUD module`.
- Function signatures and imports are heavily one-argument-per-line formatted throughout the codebase — match this style in new code within these modules rather than collapsing to single lines.
- `from __future__ import annotations` at the top of nearly every module file.
