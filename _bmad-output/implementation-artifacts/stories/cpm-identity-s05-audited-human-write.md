# CPM-IDENTITY-S05: The one audited human write

Status: ready-for-dev

Epic: `CPM-EP-IDENTITY` — Every package resolved, or visibly not

## Story

As a platform lead,
I want to correct a wrong package identity on the record,
so that a collector's mistake can be fixed without anyone editing the database directly.

## Acceptance Criteria

1. **Given** a user holding the override permission
   **When** they submit a package-identity correction with a reason
   **Then** the identity is updated and an override row records actor, timestamp, prior value, new value and reason
   **And** both writes happen in one transaction, so neither survives alone
   (`IDENTITY.05-INT-001`)

2. **Given** a user not holding the override permission
   **When** they attempt the same write
   **Then** it is refused, and the refusal is logged with the acting user identity

3. **Given** a submission with an empty reason
   **When** it is validated
   **Then** it is rejected

4. **Given** an override exists
   **When** automated resolution next runs
   **Then** the override survives, and is downgraded only by an explicit re-resolution

5. **Given** an auditor
   **When** they query overrides
   **Then** every human correction is retrievable as a set

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-3`, `CPM-FR-32`

**Governed by:**

- `CPM-AD-14` — Governed reference data has exactly one write path
- `CPM-AD-23` — Transaction boundaries are per package, and audits are atomic with their write

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `IDENTITY.05-INT-001`
- Risks this story closes: `R-07`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S05]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-14]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-23]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-3]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-32]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
