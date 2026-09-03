# CPM-PY314-S02: Verified compatibility on its own queue

Status: ready-for-dev

Epic: `CPM-EP-PY314` — Inferred and verified compatibility, kept apart

## Story

As a packaging engineer,
I want optional build and import verification that records what it actually ran on,
so that a proven-compatible package is distinguishable from a presumed-compatible one.

## Acceptance Criteria

1. **Given** a package selected for verification
   **When** verification runs
   **Then** it executes on the `verify` queue, never on `collect` or `policy`
   **And** it records the platform and architecture it ran on and a log reference

2. **Given** verification completes
   **When** the evidence is written
   **Then** inferred compatibility and verified compatibility are distinct recorded states

3. **Given** verification is not triggered
   **When** the inventory is assessed
   **Then** it is not run across the inventory by default

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** the verification half of `CPM-FR-14`

**Governed by:**

- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts
- `CPM-AD-20` — Scheduling is data; three queues by workload class

**Test design.** Bound by the TEA system-level test design:

- Risks this story closes: `R-11`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-PY314-S02]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-20]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-14]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
