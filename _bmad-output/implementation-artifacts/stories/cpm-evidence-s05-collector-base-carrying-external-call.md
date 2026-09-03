# CPM-EVIDENCE-S05: One collector base carrying every external-call rule

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

## Story

As a developer,
I want retry, backoff, timeout, rate limiting and the observation window in one place,
so that eight collectors cannot each implement them differently.

## Acceptance Criteria

1. **Given** a collector base in `core`
   **When** a collector makes an outbound call through it
   **Then** the call has a timeout, a rate limit and retry with backoff applied by the base
   **And** no collector implements any of them itself

2. **Given** a successful run already exists for this collector and package inside the configured observation window
   **When** the collector runs again
   **Then** it records a ledger row with status `skipped` and writes no evidence

3. **Given** a recollection is triggered manually
   **When** the collector runs
   **Then** it bypasses the observation window and always writes

4. **Given** an external source is rate-limited or unavailable
   **When** the call ultimately fails
   **Then** an evidence row carrying `error` or `not_found` is inserted, never a clean result, and never no row

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-NFR-3`

**Governed by:**

- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts
- `CPM-AD-20` — Scheduling is data; three queues by workload class

**Constrained:** observation-window and freshness-target *values* are PRD Open Question 7. This story builds the mechanism and reads them as per-collector configuration; it does not choose them.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S05]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-20]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-3]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
