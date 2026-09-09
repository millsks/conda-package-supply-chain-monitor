# CPM-PRIORITY-S03: Replay a policy version over history

Status: done

Epic: `CPM-EP-PRIORITY` — A ranked, explainable queue of work

## Story

As a compliance reviewer,
I want to re-run a stated policy version against a stated cut-off,
so that I can reproduce exactly what the system concluded at a point in time.

## Acceptance Criteria

1. **Given** a policy version and an evidence cut-off
   **When** the run is repeated
   **Then** it reproduces identical results
   **And** it requires no recollection

2. **Given** any policy run
   **When** it completes
   **Then** it recorded policy version, run timestamp, evidence cut-off and status

3. **Given** a policy run
   **When** it executes
   **Then** it never mutates evidence

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-22`

**Governed by:**

- `CPM-AD-8` — Policy is a separate versioned pass
- `CPM-AD-21` — One orchestrated policy run owns the rollup

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-PRIORITY-S03]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-21]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-22]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**What this story found already built, and what it therefore is.**
`execute_policy_run` has taken `evidence_cutoff` as a parameter since the
orchestration was built, and its docstring already cites `CPM-FR-22`'s replay as the
reason. Every pass reads `observed_at <= cutoff` and each already has a per-domain
replay case. So the *capability* was there; what was missing was a way for the person
who needs it to use it, and any way at all to check that a replay actually
reproduced.

This story is those two things: a front door, and a comparison.

**Files added:** `core/replay.py` (the comparison),
`core/management/commands/replay_policy_run.py` (the command), the `management`
package, and `tests/integration/django_apps/test_policy_replay.py`.

**Files changed:** `docs/deployment.md`. **No migration and no model change** — the
requirement is about reproducing what the tables already hold.

**Each acceptance criterion:**

- **AC 1 (reproduces, needs no recollection).** `compare_runs` reads every registered
  pass's derived table and compares every column of every package's row, excluding
  only the primary key and the run reference. The load-bearing case writes *new
  evidence after the cut-off between the two runs* and asserts the replay still
  reproduces — a replay that reproduced only because nothing changed would prove the
  passes are not random and nothing else. "No recollection" is asserted as the
  evidence tables being byte-identical and no collection run being opened.
- **AC 2 (records version, timestamp, cut-off, status).** Asserted as the four the
  requirement names on one finished ledger row.
- **AC 3 (never mutates evidence).** Asserted over the rows themselves rather than a
  count: a count catches an insert or a delete, and an *update* is the mutation a
  pass could plausibly perform by reaching for `save()` on a row it read.

**The negative control is what makes the rest mean anything.** Two runs at
*different* cut-offs must differ, and the comparison must name the package and the
column. Without it a comparison that always reported success would satisfy every
other case in the module.

**One operational consequence is stated three times, deliberately.** A replay
rewrites `package_health` — `CPM-AD-11` gives it one row per package and the writer
replaces it — so replaying an old cut-off leaves current health historical until the
next scheduled run. It is visible on the row (`computed_at`, `evidence_cutoff`) but
only to a reader who looks, so the command warns, asks for confirmation, and
`docs/deployment.md` says what to do instead if that is unacceptable.

**Coverage:** both new modules at 100%.
