# CPM-EVIDENCE-S01: Five outcome states with one precedence order

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

## Story

As a developer,
I want a single status type carrying `not_applicable`, `unknown`, `not_found` and `error`,
so that no two policies can invent incompatible vocabularies for the same idea.

## Acceptance Criteria

1. **Given** `django_apps.core` exists
   **When** `OutcomeState` is defined as a `TextChoices` with fixed lowercase string values
   **Then** it carries `not_applicable`, `unknown`, `not_found` and `error`
   **And** a per-status determinate type inherits those four sentinels by name *and* value

2. **Given** a derived status needs storing
   **When** the field is declared
   **Then** it is a `CharField` with `choices`, never a boolean and never a nullable boolean
   **And** a test enumerates every derived-status field from the model registry, never a
   hand-written list, and asserts the four sentinels are present (`EVIDENCE.01-AUDIT-001`)

3. **Given** two statuses must be aggregated into one
   **When** the precedence order is applied
   **Then** it comes from the single total order defined in `core`
   **And** a test asserts no other module defines an ordering

4. **Given** any module in the project
   **When** it needs the current time
   **Then** it takes it from the injected clock in `core`, and an audit fails on a direct
   `timezone.now()` call (`EVIDENCE.01-AUDIT-002`)

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-6`

**Governed by:**

- `CPM-AD-5` — One status type, fixed values, one precedence order
- `CPM-AD-26` — Time comes from an injected clock

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `EVIDENCE.01-AUDIT-001`, `EVIDENCE.01-AUDIT-002`
- Risks this story closes: `R-01`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-5]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-26]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-6]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
