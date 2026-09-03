# CPM-EVIDENCE-S06: Stale and failed evidence read as themselves

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

## Story

As a platform lead,
I want evidence past its freshness target and failed collection to be visibly distinct from clean,
so that the coverage view tells me what the monitor cannot see.

## Acceptance Criteria

1. **Given** a freshness target configured per collector
   **When** the latest evidence for a package and collector is older than that target
   **Then** it reports `stale`, and `stale` is never rendered as clean

2. **Given** collection runs that failed
   **When** the collector-health query runs
   **Then** failures are retrievable in the application layer, not only from logs
   **And** each failure exposes its error detail and its `trace_id`

3. **Given** derived state
   **When** any model holding it is defined
   **Then** no current-status field is directly writable from outside a policy run

4. **Given** a registered collector that declares no freshness target
   **When** the application starts
   **Then** startup raises `ImproperlyConfigured` rather than defaulting to fresh-forever
   (`EVIDENCE.06-AUDIT-001`)

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-37`, `CPM-FR-38`

**Governed by:**

- `CPM-AD-5` — One status type, fixed values, one precedence order
- `CPM-AD-11` — Current health is a refreshed rollup table, one row per package
- `CPM-AD-28` — A collector without a freshness target refuses to start

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `EVIDENCE.06-AUDIT-001`
- Risks this story closes: `R-03`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S06]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-5]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-11]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-28]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-37]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-38]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
