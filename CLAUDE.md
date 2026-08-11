# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo's git root is `backend/` itself (not the `D:\Regnova` parent — there is no repo at the parent level). All commands below assume the working directory is `D:\Regnova\backend`.

## Product spec

The full product/engineering spec — "RegNova Regulatory OS: Agency Product & Engineering Definition Pack", v1.0 — lives at `C:\Users\manid\Downloads\agency-definition-pack.md`. It's intentionally **not** committed to this repo: it's marked Confidential and is an external business document, not source code. Sections referenced so far: A5.2 (bounded contexts / modular-monolith strategy), C14 (event and audit contract), Appendix 2 (canonical V1 domain events). Check there before inventing bounded-context, event-catalog, or product-behavior details from scratch — this repo's actual code is currently a much smaller slice than what the spec describes (see the outbox/domain-events notes below for a concrete example of that gap).

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

**Dependency gap:** `app/modules/auth` imports `jose` (python-jose), `passlib`, and pydantic's `EmailStr` (needs `email-validator`), but none of these three are listed in `pyproject.toml`'s `dependencies`. They're only present because they were pip-installed directly into `.venv`. If you touch auth or run a clean install, add them to `pyproject.toml`.

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

Existing modules: `auth`, `organization`, `product`, `product_version`, `role`, `user`, `rbac`.

`audit` owns the transactional outbox (`app/modules/audit/models.py:OutboxEvent`) — no `router.py`/`schemas.py`, since there's no public API for outbox rows in this milestone. Domain modules depend on it one-directionally (`organization`/`user`/`product_version` import `OutboxRepository`; `audit` imports nothing domain-specific back).

New modules should copy this same five/six-file shape and get wired into `app/main.py` (`create_app()`: import the router, `app.include_router(...)`) and into `app/models.py` (imported there so Alembic's `target_metadata` picks it up — see `migrations/env.py`, which imports `app.models`).

**`product_version` is the first nested-resource module** — its router (`app/modules/product_version/router.py`) is mounted at `/products/{product_id}/versions` instead of a flat top-level prefix. Its service resolves `product_id` through `ProductRepository.get_by_id(organization_id, product_id)` and 404s before doing anything version-related, so a `product_id` belonging to another org can't be used to list/create/read versions — the same "resolve the parent through the tenant boundary first" shape as the `role_id` fix in `rbac/service.py`. Its repository's `get_by_id` also takes `(organization_id, product_id, version_id)` — three args, not the `(organization_id, entity_id)` shape used by `Product`/`User`/`Role` — because a version fetched through the wrong `product_id` (even within the same org) should 404 too, not just across orgs. If you add another nested-resource module, follow this shape rather than the flat one.

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

## Conventions observed in existing code

- Commit messages follow Conventional Commits scoped to the module: `feat(organization): implement complete CRUD module`.
- Function signatures and imports are heavily one-argument-per-line formatted throughout the codebase — match this style in new code within these modules rather than collapsing to single lines.
- `from __future__ import annotations` at the top of nearly every module file.
