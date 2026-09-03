# CPM-EVIDENCE-S07: The policy run, and the one writer of the rollup

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

## Story

As a developer,
I want an orchestrated policy run with one cut-off and a single rollup writer,
so that every later policy has something correct to plug into rather than inventing its own.

## Acceptance Criteria

1. **Given** a policy run
   **When** it is scheduled
   **Then** beat schedules the run, never an individual pass
   **And** the run has one identifier, one cut-off, and a declared ordered list of passes

2. **Given** a cut-off
   **When** it is chosen
   **Then** it is the `finished_at` of a completed collection run, never the current time
   **And** no pass reads evidence written by a collection run still `running`

3. **Given** any policy pass registered with the run
   **When** it writes its results
   **Then** it writes only its own per-domain derived table, keyed `(package, policy_run)`
   **And** a test asserts no pass writes the rollup

4. **Given** the passes have completed
   **When** the rollup is composed
   **Then** one writer performs a full-row replace per package inside one transaction, stamped with the policy run id, the run's cut-off, and a per-domain version map
   **And** the rollup holds exactly one row per inventory package, always — including `unmapped` packages, whose gated statuses read `unknown`

5. **Given** the rollup
   **When** its storage is chosen
   **Then** it is a Django-managed table inside the migration graph, not a database materialized view, and it carries `computed_at`

6. **Given** a pass that needs another pass's output
   **When** it runs
   **Then** it reads a pass declared earlier in the same run, and never re-derives a status another pass owns

7. **Given** the registered passes
   **When** the ownership audit runs
   **Then** every pass declares the derived table it owns, and none declares the rollup
   (`EVIDENCE.07-AUDIT-002`)

8. **Given** two passes writing different domains in one run
   **When** the run completes
   **Then** both results survive, and neither is reset to defaults (`EVIDENCE.07-INT-001`)

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-37`, and the orchestration half of `CPM-FR-22`

**Governed by:**

- `CPM-AD-8` — Policy is a separate versioned pass
- `CPM-AD-11` — Current health is a refreshed rollup table, one row per package
- `CPM-AD-21` — One orchestrated policy run owns the rollup
- `CPM-AD-23` — Transaction boundaries are per package, and audits are atomic with their write
- `CPM-AD-4` — Confidence gates every outward claim, by writing a value

**Note:** built here, not in `CPM-EP-PRIORITY`, because the currency, feedstock, vulnerability, licence and readiness policies all run as passes and all land before priority does. The rollup composes whatever derived tables exist, so it grows as passes are added.

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `EVIDENCE.07-AUDIT-002`, `EVIDENCE.07-INT-001`
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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S07]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-11]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-21]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-23]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-37]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-22]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
