# CPM-SECURITY-S05: Licence policy as versioned data

Status: ready-for-dev

Epic: `CPM-EP-SECURITY` — Vulnerability, KEV and licence exposure

## Story

As a compliance reviewer,
I want licence outcomes computed from a versioned policy I can change without a deployment,
so that a policy revision can be replayed over history.

## Acceptance Criteria

1. **Given** licence evidence
   **When** the policy runs
   **Then** it derives allowed, restricted, forbidden, unknown or manual-review
   **And** the policy is data, not code branches, and its version is recorded on every result

2. **Given** the policy content changes
   **When** it is re-run against unchanged evidence
   **Then** it reproduces new results without recollection

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-18`

**Governed by:**

- `CPM-AD-8` — Policy is a separate versioned pass

**Constrained:** the allow/deny content is PRD Open Question 2. This story ships the mechanism and a schema, not a seeded policy.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-SECURITY-S05]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-18]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
