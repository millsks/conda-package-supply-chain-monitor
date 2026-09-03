# CPM-PRIORITY-S01: An explainable priority bucket and score

Status: ready-for-dev

Epic: `CPM-EP-PRIORITY` — A ranked, explainable queue of work

## Story

As a platform lead,
I want every priority assignment to explain itself,
so that nobody has to read the rule set to understand why a package is P1.

## Acceptance Criteria

1. **Given** a package with derived statuses
   **When** the priority policy runs
   **Then** it assigns `P1`–`P10` by top-down first-match rules and computes a 1–100 score from internal usage signals
   **And** rank is derived from bucket and score and is stable for a given policy run

2. **Given** any assignment
   **When** it is stored
   **Then** it records the bucket description, the rule that matched, and the reason

3. **Given** the rule set and the score function
   **When** they are loaded
   **Then** they are versioned data, changeable without a deployment, and every result records the version that produced it

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-20`

**Governed by:**

- `CPM-AD-8` — Policy is a separate versioned pass
- `CPM-AD-21` — One orchestrated policy run owns the rollup

**Constrained:** the rule content and the score function are PRD Open Question 8; the internal usage signals they score are PRD Open Question 3, read from inventory evidence at the run's cut-off (`CPM-AD-25`). This story ships the engine, the schema and the explainability fields — not a seeded rule set.

**Test design.** Bound by the TEA system-level test design:

- Risks this story closes: `R-02`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-PRIORITY-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-21]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-20]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
