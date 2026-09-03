# CPM-IDENTITY-S02: Resolution that records where it came from

Status: ready-for-dev

Epic: `CPM-EP-IDENTITY` — Every package resolved, or visibly not

## Story

As a packaging engineer,
I want each package resolved to its mappings with the provenance and confidence recorded,
so that I can tell a verified mapping from an inferred one.

## Acceptance Criteria

1. **Given** an inventory package
   **When** resolution runs
   **Then** it records canonical name, source repository, release ecosystem identity and zero or more feedstocks
   **And** every resolution records an identity source, an associator key and a confidence

2. **Given** a mapping cannot be established
   **When** resolution completes
   **Then** it records `unmapped`, never a guess

3. **Given** a package type to which a mapping does not apply
   **When** resolution completes
   **Then** it records `not_applicable`, distinct from `unmapped` and from a successful empty result

4. **Given** an existing `verified` confidence
   **When** a lower-confidence resolution runs
   **Then** it does not overwrite it

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-1`, `CPM-FR-2`, `CPM-FR-6`

**Governed by:**

- `CPM-AD-1` — The package row is package identity and nothing else
- `CPM-AD-4` — Confidence gates every outward claim, by writing a value

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S02]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-1]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-1]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-2]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-6]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
