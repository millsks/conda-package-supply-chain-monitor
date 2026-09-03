# CPM-IDENTITY-S06: The inventory arrives, and arrives as evidence

Status: ready-for-dev

Epic: `CPM-EP-IDENTITY` — Every package resolved, or visibly not

**Sequenced first in its epic.** Numbered last because story keys are never reused;
built first because every later story in the epic assumes packages exist.

## Story

As a platform lead,
I want the package inventory and its usage signals observed like any other source,
so that every later story has packages to work on and a replay reads the numbers that were
true at its cut-off.

## Acceptance Criteria

1. **Given** the inventory source configured as data
   **When** the ingestion collector runs
   **Then** it runs on the `collect` queue through the shared collector base, inheriting its
   timeout, retry, backoff and ledger row
   **And** the source location and its credentials come from the environment with no default

2. **Given** a source record naming a package that does not exist yet
   **When** ingestion processes it
   **Then** `identity`'s resolution service creates the shell at `unmapped` confidence
   **And** the collector never writes the package table itself, and a test asserts it

3. **Given** a source record
   **When** its snapshot is written
   **Then** the shell and the snapshot commit in one per-package transaction
   **And** the row is append-only, references the package by integer pk, and carries
   `observed_at`, the usage signals as observed, and the run's `trace_id`

4. **Given** ingestion runs a second time over unchanged source data
   **When** the rows are written
   **Then** a new row is inserted rather than a prior one updated

5. **Given** a package present in an earlier run and absent from this one
   **When** ingestion completes
   **Then** absence is recorded as an observation with a timestamp, and no package row is deleted

6. **Given** a policy that reads a usage signal
   **When** it runs
   **Then** it reads the latest snapshot at or before its run's cut-off, and a replay at a stated
   cut-off reproduces identical results

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-42`, and the inventory prerequisite for `CPM-FR-1` – `CPM-FR-6`

**Governed by:**

- `CPM-AD-25` — The inventory arrives as evidence; resolution still owns the package row
- `CPM-AD-2` — Evidence is append-only; run ledgers are not evidence
- `CPM-AD-3` — Surrogate key, correctable canonical name
- `CPM-AD-14` — Governed reference data has exactly one write path
- `CPM-AD-23` — Transaction boundaries are per package, and audits are atomic with their write

**Constrained:** the inventory source and the usage-signal field set are PRD Open Question 3. This story builds the collector, the model and the cut-off-bound read; it does not choose the source or invent the fields.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S06]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-25]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-2]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-3]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-14]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-23]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-42]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-1]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-6]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
