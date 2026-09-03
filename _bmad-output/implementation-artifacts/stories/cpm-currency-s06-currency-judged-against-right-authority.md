# CPM-CURRENCY-S06: Currency judged against the right authority

Status: ready-for-dev

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

## Story

As a packaging engineer,
I want each package compared against the ecosystem that is actually authoritative for it,
so that a package is never called stale against a registry it never published to.

## Acceptance Criteria

1. **Given** a package
   **When** the currency policy runs
   **Then** it compares source, PyPI, recipe and published conda versions using the authority order recorded on that package
   **And** the chosen authority and its supporting evidence are stored with the result

2. **Given** no authority is explicitly set
   **When** the policy runs
   **Then** it applies the documented default order

3. **Given** a package current at source but behind on the feedstock
   **When** currency is computed
   **Then** the two are expressible separately, per surface

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-16`

**Governed by:**

- `CPM-AD-6` — Version authority is explicit per package
- `CPM-AD-8` — Policy is a separate versioned pass

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S06]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-6]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-16]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
