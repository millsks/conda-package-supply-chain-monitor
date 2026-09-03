# CPM-IDENTITY-S01: The package identity model

Status: ready-for-dev

Epic: `CPM-EP-IDENTITY` — Every package resolved, or visibly not

## Story

As a developer,
I want one row per package holding identity and nothing else,
so that no observation or derived status can be written onto it later.

## Acceptance Criteria

1. **Given** the `identity` application
   **When** the `Package` model is defined
   **Then** its primary key is a surrogate integer and `canonical_name` is a unique indexed column
   **And** `canonical_name` is never a foreign-key target, so correcting it does not cascade

2. **Given** the model
   **When** its fields are reviewed
   **Then** it holds only canonical name, cross-ecosystem mappings, provenance and confidence
   **And** it holds no derived status, no observation and no workflow state
   **And** it holds no internal usage signal; those are observed evidence (`CPM-AD-25`)

3. **Given** the PRD's export column headings
   **When** an export is produced
   **Then** the headings are applied by the reporting layer, and no model field is named for one

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** the model prerequisite for `CPM-FR-1` – `CPM-FR-6`

**Governed by:**

- `CPM-AD-1` — The package row is package identity and nothing else
- `CPM-AD-3` — Surrogate key, correctable canonical name

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-1]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-3]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-1]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-6]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
