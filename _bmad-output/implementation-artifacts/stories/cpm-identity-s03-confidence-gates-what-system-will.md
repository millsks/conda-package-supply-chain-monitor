# CPM-IDENTITY-S03: Confidence gates what the system will claim

Status: ready-for-dev

Epic: `CPM-EP-IDENTITY` — Every package resolved, or visibly not

## Story

As a security reviewer,
I want an unmapped package to never read as current or clean,
so that absence of evidence is never presented as evidence of absence.

## Acceptance Criteria

1. **Given** a single gate function in `core`
   **When** a package at `unmapped` confidence is evaluated
   **Then** every gated status is written as `unknown`, and the package is never reported current, clean, or lacking a feedstock

2. **Given** a package at `inventory-derived` confidence
   **When** it is evaluated
   **Then** the result is shown with a confidence label and its value is not degraded

3. **Given** the gate
   **When** the test suite runs
   **Then** a test asserts the gate is implemented once and not re-implemented per policy

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-5`

**Governed by:**

- `CPM-AD-4` — Confidence gates every outward claim, by writing a value

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `IDENTITY.03-AUDIT-001`
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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S03]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-5]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
