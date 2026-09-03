# CPM-IDENTITY-S04: Unresolved packages are selectable and ranked

Status: ready-for-dev

Epic: `CPM-EP-IDENTITY` — Every package resolved, or visibly not

## Story

As a platform lead,
I want the set of packages needing identity review to be queryable and ranked,
so that the review surface has something correct to render before the surface exists.

## Acceptance Criteria

1. **Given** packages at `unmapped` or `inventory-derived` confidence
   **When** the unresolved-package selection runs
   **Then** it returns every one of them, ranked by internal usage breadth
   **And** candidate mappings and the evidence for each are available where any exist

2. **Given** a package whose confidence reaches `verified`
   **When** the selection runs again
   **Then** it no longer appears

3. **Given** this story
   **When** its scope is reviewed
   **Then** it creates no queue table and no workflow state — `CPM-AD-22` puts all three queues in the `workflow` app, which sits above `policies` and is built in `CPM-APP-S04`

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** the selection half of `CPM-FR-4`

**Governed by:**

- `CPM-AD-4` — Confidence gates every outward claim, by writing a value
- `CPM-AD-1` — The package row is package identity and nothing else

**Constrained:** internal usage breadth is read from inventory evidence at a cut-off (`CPM-AD-25`); its field set and source are PRD Open Question 3 and are not chosen here.

**Note:** the worked queue surface that completes `CPM-FR-4` is `CPM-APP-S05`. Split because `identity` sits below `policies` in the layer order and cannot host a workflow table.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S04]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-1]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-4]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
