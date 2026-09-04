# CPM-IDENTITY-S07: The watchlist is the inventory source

Status: ready-for-dev

Epic: `CPM-EP-IDENTITY` — Every package resolved, or visibly not

**Sequenced with `CPM-IDENTITY-S06`.** S06 owns the ingestion collector, the snapshot model
and the cut-off-bound read; S07 owns the adapter contract, the watchlist files and the
selection rule. Neither is useful alone, and S06's acceptance criteria cannot be exercised
without a source.

## Story

As a platform lead,
I want the packages we track declared in a reviewed file and read by the ingestion collector,
so that the inventory is something we own and change on the record, and a developer can run
the product against a realistic subset.

## Acceptance Criteria

1. **Given** the inventory source adapter contract
   **When** ingestion runs
   **Then** it resolves exactly one declared adapter and calls it, and `CPM-IDENTITY-S06`'s
   collector carries no branch on which source is active
   **And** no adapter is discovered by entry point or by scanning (inherited `AD-8`)

2. **Given** the versioned watchlist file
   **When** the adapter reads it
   **Then** each row yields a record carrying the source package key, the package name,
   `internal_component_count` and `internal_lob_count`
   **And** `apps`, `platforms`, `downloads` and `versions` are yielded as present when
   populated and as missing when blank, distinguishably from zero

3. **Given** a watchlist carrying a column the contract does not define — a repository URL,
   a feedstock URL, a purl, a confidence
   **When** the adapter reads it
   **Then** the run is refused rather than the column ignored, because ingestion never
   asserts a mapping (`CPM-FR-42`, `CPM-FR-1`)

4. **Given** a file that is unreadable, missing a required column, carrying a non-numeric
   count, or repeating a source package key
   **When** the adapter reads it
   **Then** `ImproperlyConfigured` is raised and the run fails before any row is written,
   leaving no package and no snapshot behind (inherited `CG-3`)

5. **Given** a run where `config.locality.is_local()` is true
   **When** the adapter selects its file
   **Then** it reads the development subset

6. **Given** a run where `COMPONENT_RUNTIME` is absent, empty, or set to an unrecognized
   value
   **When** the adapter selects its file
   **Then** it reads the production watchlist, because selection fails closed toward
   production (`CPM-AD-29`), and a test asserts all three of those cases separately

7. **Given** the development subset
   **When** it is ingested into an empty database
   **Then** every row becomes a package at `unmapped` confidence carrying a snapshot with
   both required signals, so `CPM-IDENTITY-S04`'s queue and `CPM-EP-APP`'s surfaces have
   data to render

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-42`, with `CPM-IDENTITY-S06`

**Governed by:**

- `CPM-AD-29` — The inventory source is a declared adapter; locality selects its file
- `CPM-AD-27` — The collector base owns the transport seam
- `CPM-AD-25` — The inventory arrives as evidence; resolution still owns the package row
- `CPM-AD-14` — Governed reference data has exactly one write path

**Constrained:** the watchlist *content* — which packages are tracked, and their breadth
counts — is an organizational decision and not this story's. The story ships the contract,
the selection rule, the refusals, and a development subset sized for a developer machine.

### Project Structure Notes

- Domain applications live under `src/django_apps/`, the second import root declared
  in `pyproject.toml` by `CPM-PLATFORM-S01`. App adoption is explicit and two-line —
  a `pixi.toml` dependency plus an `adopted_apps` entry in `component.toml`, in that
  order. Entry-point discovery is forbidden (inherited `AD-8`), and `CPM-AD-29` extends
  that prohibition to adapter selection.
- **The watchlist files must live under `src/`.** `[tool.hatch.build.targets.wheel]` sets
  `only-include = [ "src" ]` (`pyproject.toml:238`), so a data file at the repository root
  is absent from the wheel and therefore absent from a deployed container. The failure is
  quiet in the worst way: `pixi run build` still succeeds, CI still passes, and the refusal
  arrives only when the deployed adapter cannot find its file.
- No new runnable entry point is needed for local use. `CPM-EVIDENCE-S05` already provides
  manual recollection that bypasses the observation window; ingestion is a collector and
  inherits it.
- A domain app contributes only to `DATABASES`, `DATABASE_ROUTERS`, `INSTALLED_APPS`,
  `NAVIGATION_REGISTRY`, `CELERY_BEAT_SCHEDULE`, `CELERY_IMPORTS`, `CELERY_TASK_ROUTES` —
  never `AUTHENTICATION_BACKENDS`, `DEFAULT_AUTHENTICATION_CLASSES`,
  `DEFAULT_PERMISSION_CLASSES` or `MIDDLEWARE`.
- Every refusal raises `ImproperlyConfigured` — never a warning, never log-and-continue
  (inherited `CG-3`).

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory. Adapter parsing and refusal are unit
  tests over in-memory content; file selection and ingestion are integration tests.
- The locality cases are asserted with `monkeypatch.setenv` / `delenv`, matching how
  `config.locality` is already tested — it reads `os.environ` at call time by design, so a
  test that mocks `is_local` would assert the mock rather than the fail-closed behaviour
  `CPM-AD-29` depends on.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- Time comes from the injected clock in `core` (`CPM-AD-26`); no module calls
  `timezone.now()` directly.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S07]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-29]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-27]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-25]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-14]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-42]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-1]
- [Source: _bmad-output/planning-artifacts/sprint-change-proposal-2026-09-04.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
