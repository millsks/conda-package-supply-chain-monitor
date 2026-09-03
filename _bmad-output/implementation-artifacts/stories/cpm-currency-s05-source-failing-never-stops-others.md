# CPM-CURRENCY-S05: One source failing never stops the others

Status: ready-for-dev

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

## Story

As a platform lead,
I want a full-inventory sweep to survive a failing source,
so that one rate-limited provider does not cost me a day of monitoring everywhere else.

## Acceptance Criteria

1. **Given** a full sweep across 10,000 packages
   **When** one collector fails for some packages
   **Then** every other collector's run is unaffected and the overall run reports `partial`, not `failed`

2. **Given** a sweep in progress
   **When** a package fails partway through
   **Then** the transaction boundary is one package, and no earlier package's evidence is rolled back

3. **Given** the same collector, package, source and observation window
   **When** the run is repeated
   **Then** it does not duplicate evidence

4. **Given** 10,000 packages
   **When** the sweep is scheduled
   **Then** it completes without manual batching

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-15`, `CPM-NFR-1`

**Governed by:**

- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts
- `CPM-AD-23` — Transaction boundaries are per package, and audits are atomic with their write

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `CURRENCY.05-INT-001`
- Risks this story closes: `R-07`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S05]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-23]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-15]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-1]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
