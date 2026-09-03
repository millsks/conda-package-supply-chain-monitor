# CPM-APP-S07: A governed, documented API

Status: ready-for-dev

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a integrator,
I want the same reads available over HTTP with a published schema,
so that automation uses the product's own contract rather than the database.

## Acceptance Criteria

1. **Given** the API
   **When** it is exposed
   **Then** current-health, package-detail and report reads are available
   **And** the schema is generated from the implementation, not maintained by hand

2. **Given** any collection endpoint
   **When** it is called
   **Then** it is paginated with a maximum page size

3. **Given** the API in v1
   **When** its writes are enumerated
   **Then** the only writes are the package-identity override and queue actions
   **And** no endpoint writes evidence or a derived status

4. **Given** an API request
   **When** authorization is evaluated
   **Then** the same role scoping as the application applies

5. **Given** a derived status on any API response
   **When** it is serialized
   **Then** it is emitted verbatim as its `OutcomeState` value, and never maps to `null`,
   `""` or a boolean (`APP.07-API-001`)

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-27`

**Governed by:**

- `CPM-AD-9` — The request/task boundary
- `CPM-AD-10` — Derived state is read-only to the application
- `CPM-AD-12` — Pagination is structural  *(net-new: no pagination is configured today)*
- `CPM-AD-13` — Authorization is declared per surface, enforced centrally
- `CPM-AD-24` — Every read surface projects the same values

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `APP.07-API-001`
- Risks this story closes: `R-01`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S07]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-9]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-10]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-12]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-13]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-24]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-27]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
