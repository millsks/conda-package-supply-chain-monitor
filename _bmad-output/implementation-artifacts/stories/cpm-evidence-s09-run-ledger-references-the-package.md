# CPM-EVIDENCE-S09: The run ledger references the package it names

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

**Sequenced after `CPM-IDENTITY-S06`.** That inverts this epic's usual order and is deliberate:
`core/models.py` has said since `CPM-EVIDENCE-S03` that `CPM-EP-IDENTITY` converts this column
"when the model lands". The model landed in `CPM-IDENTITY-S01` and packages first existed in
`CPM-IDENTITY-S06`; both declined the conversion for the same sound reason, that it is not a field
swap but a change to `core/ledger.py`'s recorder contract. Two hand-offs is where a deferral stops
being one. It belongs to `CPM-EP-EVIDENCE` because the run ledger is `core`'s, not identity's.

## Story

As a platform lead,
I want a collection run's package reference to be a real foreign key,
so that a run cannot be recorded against a package that does not exist, and `CPM-AD-3` is met by
every table rather than by all but one.

## Acceptance Criteria

1. **Given** `core.CollectionRun`
   **When** its package reference is inspected
   **Then** it is a `ForeignKey` to `identity.Package` with `on_delete=PROTECT`, still nullable
   **And** the database column is still named `package_id`

2. **Given** an existing `collection_runs` table carrying rows
   **When** the migration is applied
   **Then** no row is lost and the column is preserved rather than dropped and re-added

3. **Given** the `collection_run` recorder
   **When** a run is recorded against a package key that names no package
   **Then** the write is refused rather than stored, and the refusal names the key

4. **Given** a sweep that is not scoped to one package
   **When** its run is recorded
   **Then** the reference is NULL, and that remains an ordinary state rather than a refused one

5. **Given** a package with collection runs against it
   **When** it is deleted
   **Then** the delete is refused — `CPM-AD-25` says no package row is ever deleted, and `PROTECT`
   is what makes that true rather than merely intended

6. **Given** `core/models.py`, `tests/collectors.py` and every other place recording this
   conversion as owed
   **When** they are read after this story
   **Then** none of them claims it is still outstanding

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.

## Dev Notes

**Satisfies:** completes `CPM-AD-3` for the run ledger

**Governed by:**

- `CPM-AD-2` — Evidence is append-only; run ledgers are not evidence
- `CPM-AD-3` — Surrogate key, correctable canonical name
- `CPM-AD-23` — Transaction boundaries are per package

**Depends on:** `CPM-IDENTITY-S01` for the model, `CPM-IDENTITY-S06` for packages to point at.

**The cost is the recorder's contract, not the column.** `core/ledger.py`'s `_require_package_key`
rejects only negatives today, and every existing `core` integration case passes a literal key —
`A_PACKAGE_ID = 4269` — for a package no test creates. A real foreign key is enforced immediately,
so each of those cases must create a package first. That ripple is the whole reason two stories
declined this, and it is what makes it a story of its own.

**The migration is not a single `AlterField`.** The attribute is named `package_id`, so a
`ForeignKey` named `package` reads to the autodetector as a remove-and-add — which would drop the
column and lose its rows. Preserving it needs a hand-written `RenameField` plus `AlterField` pair.

**`CollectionRun` is a run-ledger model, not evidence** (`not_evidence = True`), so
`EVIDENCE.02-AUDIT-001`'s `PROTECT` requirement does not bind it. `PROTECT` is still the right
answer, for `CPM-AD-25`'s reason rather than that audit's.

**Out of scope.** `PolicyRun` carries no package reference and does not gain one here.
`core/collection.py`'s `window_query`, `has_recent_success` and `_inside_window` already take
`package_id: int | None` after `CPM-IDENTITY-S06`'s sweep path, and the NULL case is exercised —
this story must keep both true. `core/freshness.py`'s `PACKAGE_FIELD` already resolves a
`ForeignKey` through its `attname`, so it needs no change.

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- `pixi run gate-postgres` is where `PROTECT` and the foreign key are genuinely enforced; the
  default suite runs on the SQLite fallback.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S09]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-3]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-2]
- [Source: _bmad-output/implementation-artifacts/stories/cpm-identity-s01-package-identity-model.md]
- [Source: _bmad-output/implementation-artifacts/stories/cpm-identity-s06-inventory-arrives-arrives-as-evidence.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
