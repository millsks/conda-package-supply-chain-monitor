# CPM-APP-S04: One workflow table keyed on a stable finding key

Status: ready-for-dev

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a security reviewer,
I want a finding I have accepted to stay accepted after the next collection,
so that my decisions are not silently undone by re-observation.

## Acceptance Criteria

1. **Given** an evidence-backed finding
   **When** a workflow item is created for it
   **Then** it is keyed on a re-observation-stable finding key declared alongside that evidence table, never on an evidence row id

2. **Given** an accepted finding
   **When** the collector re-observes it and inserts a new evidence row
   **Then** the item does not reappear as new unactioned work

3. **Given** a state transition
   **When** it is applied
   **Then** it comes from the declared `(from_state, to_state, required_role)` data
   **And** the service locks the row, checks the expected prior state, refuses on mismatch, and appends the audit row in the same transaction

4. **Given** an item routed from one queue to another
   **When** the routing happens
   **Then** the item's queue field changes and no second item is created

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** the model half of `CPM-FR-25`

**Governed by:**

- `CPM-AD-22` — One workflow app owns every queue item, keyed on a finding key
- `CPM-AD-23` — Transaction boundaries are per package, and audits are atomic with their write

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `APP.04-INT-001`
- Risks this story closes: `R-04`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S04]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-22]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-23]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-25]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
