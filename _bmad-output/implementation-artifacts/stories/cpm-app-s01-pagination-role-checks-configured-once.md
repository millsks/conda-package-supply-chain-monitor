# CPM-APP-S01: Pagination and role checks, configured once

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a platform lead,
I want pagination and role enforcement to be structural rather than per-view,
so that no endpoint can be shipped unpaginated or unguarded.

## Acceptance Criteria

1. **Given** no DRF pagination exists today
   **When** it is configured
   **Then** `DEFAULT_PAGINATION_CLASS` and a maximum `PAGE_SIZE` are set globally
   **And** a test asserts no view or serializer opts out

2. **Given** a permission class in `core`
   **When** any view, viewset or report is defined
   **Then** it declares the role it requires, and the check is implemented once

3. **Given** a request from a role without the required grant
   **When** it is handled
   **Then** it is refused and the refusal is logged with the acting user identity

4. **Given** the domain applications
   **When** their settings contributions are reviewed
   **Then** none of them touches `DEFAULT_PERMISSION_CLASSES`, `AUTHENTICATION_BACKENDS`, `DEFAULT_AUTHENTICATION_CLASSES` or `MIDDLEWARE`

## Tasks / Subtasks

- [x] `core/pagination.py` — the one pagination class, installed globally.
- [x] `core/permissions.py` — `RolePermission`, `requires_roles`, `AnyProductRole`,
      and the one refusal log.
- [x] `config/settings/base.py` — `DEFAULT_PAGINATION_CLASS` and `PAGE_SIZE`.
- [x] `tests/unit/django_apps/test_pagination_audit.py` — AC 1's audit.
- [x] `tests/unit/django_apps/test_permission_audit.py` — AC 2 and AC 4's audits.
- [x] `tests/unit/django_apps/test_permissions.py` — what the check decides.
- [x] `tests/integration/django_apps/test_role_permissions.py` — AC 3, through a
      real request, and the global page bound reaching a view that says nothing.
- [x] `docs/development.md`, `docs/authentication.md`.

## Dev Notes

**Satisfies:** `CPM-FR-31`, `CPM-NFR-4`, `CPM-NFR-11`

**Governed by:**

- `CPM-AD-12` — Pagination is structural  *(net-new: no pagination is configured today)*
- `CPM-AD-13` — Authorization is declared per surface, enforced centrally

**Test design.** Bound by the TEA system-level test design:

- Risks this story closes: `R-12`

### Project Structure Notes

- Domain applications live under `src/django_apps/`, the second import root declared
  in `pyproject.toml` by `CPM-PLATFORM-S01`. App adoption is explicit and two-line —
  a `pixi.toml` dependency plus an `adopted_apps` entry in `component.toml`, in that
  order. Entry-point discovery is forbidden (inherited `AD-8`).
- A domain app contributes only to `DATABASES`, `DATABASE_ROUTERS`, `INSTALLED_APPS`,
  `NAVIGATION_REGISTRY`, `CELERY_BEAT_SCHEDULE`, `CELERY_IMPORTS`, `CELERY_TASK_ROUTES` —
  never `AUTHENTICATION_BACKENDS`, `DEFAULT_AUTHENTICATION_CLASSES`,
  `DEFAULT_PERMISSION_CLASSES` or `MIDDLEWARE`.
- Every refusal raises `ImproperlyConfigured` — never a warning, never log-and-continue
  (inherited `CG-3`).

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- Time comes from the injected clock in `core` (`CPM-AD-26`); no module calls
  `timezone.now()` directly.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-12]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-13]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-31]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-4]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-11]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**What this story is: two settings, two modules, and four audits that are the
actual deliverable.** The configuration is nine lines. What makes the story worth
its size is that `CPM-AD-12` and `CPM-AD-13` are both rules about code *not yet
written* — the first product view arrives in `CPM-APP-S02` — so shipping the
mechanism without the sweeps would ship two decisions nothing enforces.

**Files added:** `core/pagination.py`, `core/permissions.py`,
`tests/unit/django_apps/test_pagination_audit.py`,
`tests/unit/django_apps/test_permission_audit.py`,
`tests/unit/django_apps/test_permissions.py`,
`tests/integration/django_apps/test_role_permissions.py`.

**Files changed:** `config/settings/base.py`, `docs/development.md`,
`docs/authentication.md`. **No migration and no model change.**

**Each acceptance criterion:**

- **AC 1 (pagination global, nothing opts out).** `BoundedPageNumberPagination`
  with `page_size_query_param = None`, which is deliberately stronger than
  declaring a maximum and policing it: there is no request that asks for ten
  thousand rows and is refused, because there is no request that asks.
  `max_page_size` is declared anyway as the ceiling for the day a story opens
  that parameter. The audit enumerates the three ways out — `pagination_class =
  None`, a class of the view's own, a per-view `page_size` — measures a detector
  against each, and sweeps every module this product owns.
- **AC 2 (declared per surface, implemented once).** `RolePermission` holds the
  only comparison; `requires_roles` mints subclasses and refuses at *import* on an
  empty or unknown role, because a class requiring a role nobody holds refuses
  everybody and a surface nobody can reach looks exactly like a surface nobody
  uses. The "once" half is a source sweep for `groups`, `has_perm`, `is_staff` and
  `is_superuser`, because a view that declares `AnyProductRole` and then filters
  its own queryset by group has satisfied the declaration and reintroduced the
  defect.
- **AC 3 (refused, and logged with the acting user).** Five fields —
  `actor`, `view`, `path`, `required`, `held` — asserted off a real request
  through a real URLconf against a real database. `held` is the field that
  distinguishes `EXPERIENCE.md`'s G-4 zero-groups sign-in from somebody reaching
  for another role's queue.
- **AC 4 (domain apps touch none of the four keys).**
  `config/startup/allowlist.py` already declares exactly these four as
  `FORBIDDEN_CONTRIBUTABLE_KEYS`, so the *contribution* path was covered before
  this story. What was not covered is a module assigning one directly or reaching
  through `settings.REST_FRAMEWORK[...]`. The sweep matches a **mention**, not an
  assignment, for that reason, and the two lists are reconciled so a fifth key
  added to either is a failure rather than a gap.

**Two decisions worth recording.**

*Superusers are not exempt.* Django's own admin checks `is_superuser` and it
would have been one line here. `CPM-FR-31` is about which role may see which
surface, and a superuser browsing a queue is reading another role's work — the
exact thing the decision names. A group membership is auditable; a bypass is not.
`CPM-AD-14`'s override permission is a separate question and stays on Django's
permission system, which is the one recorded exemption in the authorization sweep.

*The page size is a literal in settings and a constant in the module, reconciled
by a test rather than imported.* Importing `core/pagination.py` from
`config/settings/base.py` makes `rest_framework.pagination` evaluate
`api_settings.PAGE_SIZE` at class-definition time — during the settings module's
own import, before `REST_FRAMEWORK` is assigned — and DRF then caches its
*defaults* for the life of the process. The symptom was every `REST_FRAMEWORK`
key silently reverting, surfacing as an unrelated credential-surface test finding
`SessionAuthentication` first. The comment in `base.py` records it; `core/queues.py`
records the same constraint from the other direction.

**The fixture views are the point, not a shortcut.** No product view exists until
`CPM-APP-S02`, so the URLconf sweep passes over an empty set today and every
detector is measured against fixture source before it is trusted. The integration
module routes two views — a read surface every role may reach, and a scoped queue
one role may — which are the two shapes the product will have, so the case that
fails when `CPM-APP-S05` gets its permission wrong already exists.

**Coverage:** both new modules at 100%.

**Gate:** `pixi run ci` cannot complete on this machine —
`tests/integration/test_image_payload.py`'s `docker build` child becomes a zombie
and pytest blocks in `select_poll_poll`, which reproduces on unmodified `main`.
The steps were run individually instead: `precommit`, `build`, `typecheck`,
`lint`, then the suite with that module ignored. The GitHub gate runs it.
