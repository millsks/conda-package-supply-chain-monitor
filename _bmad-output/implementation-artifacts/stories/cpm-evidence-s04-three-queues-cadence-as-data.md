# CPM-EVIDENCE-S04: Three queues and cadence as data

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

## Story

As a platform lead,
I want collection, policy and verification work on separate queues with cadence in the scheduler,
so that a compute-backed build cannot starve the daily security sweep.

## Acceptance Criteria

1. **Given** no Celery routing exists today
   **When** routing is configured
   **Then** three queues exist — `collect` for external I/O, `policy` for CPU work, `verify` for compute-backed builds
   **And** tasks reach them through `CELERY_TASK_ROUTES`, contributed via the platform's allowlist

2. **Given** any scheduled work
   **When** its cadence is set
   **Then** it lives in the database scheduler as data, never as a decorator on the task

3. **Given** a task that would exceed the inherited 5-minute time limit
   **When** the work is designed
   **Then** it is chunked per package rather than the limit being raised

4. **Given** every registered task
   **When** routing is audited
   **Then** each task's declared route resolves to one of the three queues, asserted as
   configuration because eager Celery hides routing (`EVIDENCE.04-AUDIT-001`)

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-NFR-2`

**Governed by:**

- `CPM-AD-20` — Scheduling is data; three queues by workload class
- `CPM-AD-9` — The request/task boundary

**Note:** built here rather than in a collector epic because `CPM-EP-CURRENCY`, `CPM-EP-SECURITY` and `CPM-EP-PY314` all need these queues and none depends on the others.

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `EVIDENCE.04-AUDIT-001`
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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S04]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-20]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-9]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-2]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
