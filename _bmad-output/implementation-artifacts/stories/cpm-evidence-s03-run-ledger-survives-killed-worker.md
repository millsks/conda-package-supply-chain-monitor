# CPM-EVIDENCE-S03: A run ledger that survives a killed worker

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

## Story

As a platform lead,
I want every collection and policy run recorded from before it starts until after it ends,
so that a run that died mid-call is visible rather than absent.

## Acceptance Criteria

1. **Given** run-ledger models in `core`
   **When** they are defined
   **Then** they are mutable and explicitly exempt from the append-only base, and that exemption is documented at the definition

2. **Given** a run begins
   **When** the ledger row is written
   **Then** it is created with status `running` *before* the first outbound call
   **And** it carries the collector or policy name, the package, and the `trace_id` of the request or task

3. **Given** a run ends by any path including an exception
   **When** control leaves the run
   **Then** the row is finalized in a `finally` to `succeeded`, `partial`, `failed` or `skipped`
   **And** a collector raising mid-run still finalizes its row, which is never absent
   (`EVIDENCE.03-INT-002`)

4. **Given** a worker is killed mid-run
   **When** the coverage view is queried
   **Then** the row is still present showing `running`, and "started and never finished" is answerable

5. **Given** a collector whose run is not scoped to a single package
   **When** its ledger row is written
   **Then** the package reference is absent rather than fabricated, and "started and never
   finished" stays answerable for that run

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-39`, and the ledger half of `CPM-FR-38`

**Governed by:**

- `CPM-AD-2` — Evidence is append-only; run ledgers are not evidence
- `CPM-AD-15` — Every observation carries the platform's correlation identifiers

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `EVIDENCE.03-INT-002`
- Risks this story closes: `R-05`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S03]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-2]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-15]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-39]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-38]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
