# CPM-PLATFORM-S01: A second import root for domain applications

Status: ready-for-dev

Epic: `CPM-EP-PLATFORM` — The service platform

## Story

As a developer,
I want `src/django_apps/` to be an importable second root with one app in it,
so that every domain application has a declared home before any of them is written.

## Acceptance Criteria

1. **Given** `pyproject.toml` declares `src/` as the wheel root
   **When** `src/django_apps/` is added to the same `[tool.hatch.build.targets.wheel]` sources
   **Then** `django_apps` imports as a top-level package alongside `config` and `django_service`
   **And** the import root is declared in exactly one place, and a test pins that it is not declared twice

2. **Given** the new root exists
   **When** a minimal `django_apps.core` application is created following the `django_service/users/` layout
   **Then** it is adopted in two lines — a `pixi.toml` entry and an `adopted_apps` entry in `component.toml` — in that order
   **And** nothing self-registers and no entry-point discovery is introduced

3. **Given** the app is adopted
   **When** `pixi run ci` runs
   **Then** it exits 0 with coverage at or above the 90% floor

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** structural prerequisite for every later epic

**Governed by:**

- `CPM-AD-19` — One app per domain, routed centrally
- Also: `CPM-AD-19`, inherited `AD-8`, `AD-28`

**Test design.** Bound by the TEA system-level test design:

- Risks this story closes: `R-14`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-PLATFORM-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-19]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
