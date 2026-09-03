# CPM-PLATFORM-S02: Group claims resolve to the three product roles

Status: ready-for-dev

Epic: `CPM-EP-PLATFORM` — The service platform

## Story

As a platform lead,
I want the identity provider's group claims to grant one of the three product roles,
so that a person's access follows from what the provider asserts, with no manual step.

## Acceptance Criteria

1. **Given** the platform already syncs asserted group claims to Django groups
   **When** the three product role groups are provisioned by migration, as the platform provisions its designated groups
   **Then** a person whose claims assert a role group holds that role at their next authentication
   **And** a group revoked at the provider removes the role at the next resolution

2. **Given** a role group name is configured
   **When** the configuration is read
   **Then** it comes from the environment and has no default value baked into the settings module

3. **Given** an authentication asserts no group claim at all
   **When** authorization is resolved
   **Then** it is refused, and that refusal is distinguishable from an authentication asserting zero groups

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-29`, `CPM-FR-30`

**Governed by:** inherited `AD-10`, `R-2`, `CG-3`

**Note:** authentication itself, the probes (`CPM-FR-28`) and trace correlation (`CPM-FR-39`) are inherited and already working; this story adds only the product's role groups.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-PLATFORM-S02]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-29]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-30]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
