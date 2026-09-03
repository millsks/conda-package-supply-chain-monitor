# CPM-EVIDENCE-S02: Evidence that refuses to be updated

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

## Story

As a compliance reviewer,
I want an observation to be impossible to overwrite,
so that what the system knew at a point in time can always be reconstructed.

## Acceptance Criteria

1. **Given** an abstract append-only base model in `core`
   **When** `save()` is called on an instance whose primary key is already set
   **Then** it raises rather than updating
   **And** the manager exposes no `update()` or `delete()` path

2. **Given** an unchanged fact is observed again
   **When** the collector writes it
   **Then** a new row is inserted with a new `observed_at`
   **And** no evidence table carries a unique constraint that would suppress that insert

3. **Given** any evidence model in the project
   **When** the test suite runs
   **Then** a test asserts it inherits the append-only base

4. **Given** an evidence table
   **When** the audit runs
   **Then** it fails on any `queryset.update()`, `bulk_update()` or raw SQL write against
   that table — the bypass `save()` cannot catch (`EVIDENCE.02-AUDIT-002`)

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-36`

**Governed by:**

- `CPM-AD-2` — Evidence is append-only; run ledgers are not evidence
- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `EVIDENCE.02-AUDIT-002`
- Risks this story closes: `R-06`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S02]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-2]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-36]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
