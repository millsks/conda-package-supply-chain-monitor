# CPM-RENAME-S01: The import root becomes `conda_sentinel`

Status: ready-for-dev

Epic: `CPM-EP-RENAME` — The product is called Conda-Sentinel

## Story

As an engineer reading this codebase,
I want the import root to carry the product's name,
so that the module path and the product stop disagreeing.

## Acceptance Criteria

1. **Given** the repository after this story
   **When** `conda_package_supply_chain_monitor` is searched for anywhere under `src/` or
   `tests/`
   **Then** it appears nowhere, and a test fails if it ever returns

2. **Given** the database schema before and after this story
   **When** the two are compared
   **Then** no table, column, index or constraint differs, and `makemigrations --check`
   reports no changes

3. **Given** the twenty-four existing migration files
   **When** the diff for this story is read
   **Then** no migration's operations are edited, and no `AlterModelTable` is added

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: the file counts below are a survey taken when the epic was
      written, and the epics ahead of this one will change them.

## Dev Notes

**Satisfies:** no functional requirement — this story changes no behaviour

**Governed by:**

- `CPM-AD-8` — adoption stays explicit; entry-point discovery remains forbidden

### What the survey found

Taken at `b44b745`, and expected to grow before this story is picked up:

- 180 files name `conda_package_supply_chain_monitor`. 132 of them are tests.
- All 19 models declare an explicit `db_table`, and none carries the package name.
- The four `AppConfig.name` values are `conda_package_supply_chain_monitor.{core,identity,collectors,policies}`,
  so the derived labels are `core`, `identity`, `collectors`, `policies`.
- 24 migrations exist; 3 mention the package name, none in a way that binds the schema.

### Project Structure Notes

- Domain applications live under `src/django_apps/`, the second import root declared
  in `pyproject.toml` by `CPM-PLATFORM-S01`. The directory this story renames is that
  root's single child. App adoption is explicit and two-line — a `pixi.toml` dependency
  plus an `adopted_apps` entry in `component.toml`, in that order. Entry-point discovery
  is forbidden (inherited `AD-8`).
- The four `AppConfig.name` values move with the package; their derived **labels** must
  not change. A story that changes an app label has changed the migration graph and
  `django_content_type`, which this story is defined not to do.
- `pyproject.toml` declares the import roots and ruff's `known-first-party`; both name
  the package and both move.

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- `pixi run gate-postgres` must pass: this story's second acceptance criterion is a schema
  claim, and SQLite cannot prove it.
- The guard for the first acceptance criterion is a source scan in the style this repository
  already uses for its other audits, with the historical artifacts of `CPM-RENAME-S03`
  recorded as exemptions rather than silently skipped.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-RENAME-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
