# CPM-SECURITY-S06: Whether a finding can actually be acted on

Status: ready-for-dev

Epic: `CPM-EP-SECURITY` — Vulnerability, KEV and licence exposure

## Story

As a security reviewer,
I want to know if a fix exists and where,
so that I can separate work I can do now from work that is waiting on someone else.

## Acceptance Criteria

1. **Given** a package with an open finding
   **When** the readiness policy runs
   **Then** it derives readiness from whether a fixed version exists and where it is available — upstream, PyPI, recipe or a monitored channel

2. **Given** a finding whose fix exists nowhere yet
   **When** readiness is computed
   **Then** it is `blocked`, distinct from `ready` and from `unknown`

3. **Given** the supporting evidence is past its freshness target
   **When** readiness is computed
   **Then** it reports stale rather than asserting a fix is available

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-41`

**Governed by:**

- `CPM-AD-5` — One status type, fixed values, one precedence order
- `CPM-AD-8` — Policy is a separate versioned pass

**Test design.** Bound by the TEA system-level test design:

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-SECURITY-S06]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-5]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-41]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
