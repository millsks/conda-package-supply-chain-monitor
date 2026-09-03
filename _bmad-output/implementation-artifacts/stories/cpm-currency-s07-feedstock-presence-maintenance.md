# CPM-CURRENCY-S07: Feedstock presence and maintenance

Status: ready-for-dev

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

## Story

As a packaging engineer,
I want to know whether a feedstock exists and whether anyone is maintaining it,
so that I can find the gaps worth filling.

## Acceptance Criteria

1. **Given** a package at `verified` or `inventory-derived` confidence
   **When** the feedstock policy runs
   **Then** it derives one of absent, present-and-maintained, present-and-inactive, or staged-recipe-pending

2. **Given** a package at `unmapped` confidence
   **When** the policy runs
   **Then** it reports `unknown` and never absent

3. **Given** the inactivity threshold
   **When** it is applied
   **Then** it is read as a versioned policy parameter, not a constant in code

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-40`

**Governed by:**

- `CPM-AD-4` — Confidence gates every outward claim, by writing a value
- `CPM-AD-8` — Policy is a separate versioned pass

**Constrained:** the inactivity threshold and what counts as recipe activity are PRD Open Question 10.

**Test design.** Bound by the TEA system-level test design:

- Risks this story closes: `R-08`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S07]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-40]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
