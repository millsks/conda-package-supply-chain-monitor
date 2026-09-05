---
title: 'CPM-EVIDENCE-S09: The run ledger references the package it names'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
baseline_revision: '736370d14850102fe1a4e771d711c07a31b1be11'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s01-package-identity-model.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s06-inventory-arrives-arrives-as-evidence.md
warnings: []
followup_review_recommended: true
deferred:
  - summary: >-
      `tests/packages.py` is a fifth spelling of "create a package for this test", not the
      consolidation its docstring claims to be.
    evidence: |-
      Four integration modules already carry their own local `Package.objects.create(...)`
      helper. The new module's key-first signature cannot express the name-first case those
      four need, so the extraction is partial by construction. Pre-existing duplication that
      this story surfaced rather than caused.
    location: >-
      tests/integration/django_apps/test_rollup.py:143, test_policy_run.py:102,
      test_selection.py:163, test_identity_models.py:74
    severity: low
  - summary: >-
      No planning or architecture artifact records that `CPM-AD-3` is now closed for the run
      ledger.
    evidence: |-
      AC 6's sweep retired the stale claims in `src/` and `tests/`, but the closure is recorded
      only in source docstrings. `epics.md` still carries the migration pair as work to be done
      (correct, as frozen story spec), and `ARCHITECTURE-SPINE.md` gives the next reader no way
      to see that the last table without the surrogate-key relation now has one.
    location: >-
      _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-3
    severity: low
  - summary: >-
      `packages_fixture` inserts explicit primary keys, which does not advance PostgreSQL's
      identity sequence.
    evidence: |-
      No module using it goes on to create a package without a key, so nothing collides today.
      A future case in one of those three modules calling `Package.objects.create()` with no
      `pk` that happened to reach a key the fixture had already taken would fail as a
      duplicate-key error. It fails loudly rather than silently, which is why this is filed
      rather than fixed.
    location: >-
      tests/packages.py
    severity: low
---

# CPM-EVIDENCE-S09: The run ledger references the package it names

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

- [x] Convert `core.CollectionRun.package_id` to `package = ForeignKey(identity.Package,
      on_delete=PROTECT, null=True, related_name="collection_runs")` (AC 1).
- [x] Hand-write `core/migrations/0004_collection_run_package.py` as a `RenameField`, a data
      step and an `AlterField`, so the column carries its rows across and the foreign key can be
      added over a table written under the old contract (AC 2).
- [x] Prove AC 2 by running the migration against a populated table, on both backends
      (`tests/integration/django_apps/test_run_ledger_migration.py`).
- [x] Extend `core/ledger.py`'s `_require_package_key` to refuse a key that names no package,
      before the row is written, with the key in the message (AC 3).
- [x] Keep `package_id=None` an ordinary state: never looked up, never refused (AC 4).
- [x] Prove `PROTECT` refuses the delete, and that a package no run names still deletes, so the
      refusal is the relation's (AC 5).
- [x] Create the packages the `core` integration constants name -- `tests/packages.py`, used by
      `test_run_ledger.py`, `test_collection.py` and `test_collector_health.py`.
- [x] Retire every recorded claim that the conversion is still owed: `core/models.py`,
      `core/freshness.py`, `identity/models.py`, `tests/collectors.py`, and the two run-ledger
      test modules (AC 6).

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

`claude-opus-5[1m]` via Claude Code.

### Debug Log References

- `pixi run ci` — exit 0 (precommit, build, typecheck, lint, coverage 98.39%, 4353 passed).
- `pixi run gate-postgres` — exit 0 against `postgres:17`, where the foreign key and `PROTECT`
  are genuinely enforced.
- AC 2 is verified by `tests/integration/django_apps/test_run_ledger_migration.py`, which runs
  under both gates. It was checked against a deliberately broken migration: with the data step
  removed, the case fails with the foreign-key violation the step exists to prevent.

### Completion Notes List

- **The column is enforced from two directions, and both were needed.** The recorder refuses an
  unknown key before the insert; the relation refuses it at the constraint. The recorder's
  refusal is not redundant: Django declares its SQLite foreign keys
  `DEFERRABLE INITIALLY DEFERRED`, so the constraint speaks at `COMMIT`, which inside a test
  transaction or mid-task is a long way from the call that caused it. The message names the key.
- **The ripple was the story, as the spec said.** Three `core` integration modules recorded runs
  against literal keys for packages nothing created. Rather than replacing the constants with
  allocated primary keys -- which would have made `row.package_id == A_PACKAGE_ID` assert only
  that two reads agree -- `tests/packages.py` creates the packages *at* those keys. `0` is why:
  it is a falsy value and a perfectly good primary key, and no sequence issues it.
- **The `check_constraints` finding.** Django's SQLite backend runs `PRAGMA foreign_key_check`
  at `TestCase` teardown, so a row written directly past the recorder is caught locally as well
  as in the gate. That is why the two modules writing rows without the recorder
  (`test_collection.py`, `test_collector_health.py`) needed the packages too.
- **Out of scope, held.** `PolicyRun` gained no package reference. `core/collection.py`'s
  `window_query`, `has_recent_success` and `_inside_window` are untouched and the NULL case is
  still exercised; `core/freshness.py`'s `PACKAGE_FIELD` needed no change, and only its docstring
  moved -- it now says both spellings are in use rather than that one is anticipated.

**From the review round:**

- **The migration would have failed on a deployed table.** The old recorder wrote any
  non-negative integer, so `collection_runs` can hold references naming no package, and both
  backends validate the new foreign key against the rows already there. A `RunPython` between
  the rename and the alter now NULLs those — every row survives, and the discarded value pointed
  at nothing. `collection_runs` is a run ledger, which `CPM-AD-2` exempts from the append-only
  rule, so the `queryset.update()` is recorded as an exemption in
  `tests/unit/django_apps/test_mutation_path_audit.py` rather than evaded by a row-by-row
  `save()`.
- **A pytest-django hazard, found while writing the AC 2 executor case and worth knowing about
  beyond this story.** `django_db_setup` creates a test database only for aliases some
  *collected* case asks for — by the `django_db` marker or the `db` fixture. In a session where
  nothing is marked, no alias is set up, and `django_db_blocker.unblock()` then hands out a
  connection to the developer's working `db.sqlite3`. The first draft of the migration case was
  unmarked, and it was migrating and writing to the real database. It is closed two ways: the
  module keeps one marked case (which is also its vacuity guard), and the fixture refuses
  outright if the connection still names the database `settings` named at import time. The
  existing `django_db_blocker` fixtures in this repo are safe only because marked cases request
  them.
- **One shared package fixture rather than three.** `tests/packages.py` now exposes
  `packages_fixture(*keys)`, which the three `core` modules bind; it depends on `db` explicitly
  so the rows land in the transaction that rolls them back, rather than relying on undeclared
  ordering between two autouse fixtures, and it uses `get_or_create` so a duplicate is not an
  `IntegrityError` raised inside a fixture.

### File List

**Source**

- `src/django_apps/conda_package_supply_chain_monitor/core/models.py`
- `src/django_apps/conda_package_supply_chain_monitor/core/ledger.py`
- `src/django_apps/conda_package_supply_chain_monitor/core/freshness.py`
- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py`
- `src/django_apps/conda_package_supply_chain_monitor/core/migrations/0004_collection_run_package.py` *(new)*
- `src/django_apps/conda_package_supply_chain_monitor/identity/models.py`

**Tests**

- `tests/packages.py` *(new)*
- `tests/unit/django_apps/test_run_ledger_migration.py` *(new)*
- `tests/integration/django_apps/test_run_ledger_migration.py` *(new)*
- `tests/unit/django_apps/test_mutation_path_audit.py`
- `tests/unit/django_apps/test_run_ledger.py`
- `tests/integration/django_apps/test_run_ledger.py`
- `tests/integration/django_apps/test_collection.py`
- `tests/integration/django_apps/test_collector_health.py`
- `tests/collectors.py`

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 2, medium 7, low 7)
- defer: 3: (high 0, medium 0, low 3)
- reject: 10: (high 0, medium 2, low 8)
- addressed_findings:
  - `[high]` `[patch]` The migration aborted on a populated table holding references naming no
    package — the old recorder accepted any non-negative integer, and both backends validate the
    new foreign key against the rows already there. A `RunPython` between the rename and the
    alter now NULLs those references, with a declared no-op reverse, so every row survives.
  - `[high]` `[patch]` AC 2 was verified by reading the migration's source and by a manual
    one-off run, never by executing it in the suite. Added
    `tests/integration/django_apps/test_run_ledger_migration.py`, which drives a
    `MigrationExecutor` back to `0003`, writes a real, a NULL and an orphan row, migrates
    forward, and asserts row survival, reference preservation and the column name by
    introspection — under both gates.
  - `[medium]` `[patch]` AC 6 was incomplete: `collectors/models.py` still described
    `CollectionRun.package_id` as a plain integer whose writer does not create the package.
  - `[medium]` `[patch]` AC 6 was incomplete: the negative-key unit test still described the
    column as `PositiveBigIntegerField` with a PostgreSQL check constraint, in the present tense.
  - `[medium]` `[patch]` `Collector.collect()` did not document the `RunLedgerError` that now
    escapes before any ledger row, log line or evidence row exists.
  - `[medium]` `[patch]` The recorder went from pure validation to I/O without saying so: three
    `Raises:` sections omitted `DatabaseError`, and the module prose did not say the recorder now
    reads before it writes.
  - `[medium]` `[patch]` `related_name="collection_runs"` is new public API and was pinned
    nowhere, as were `blank` and `default`.
  - `[medium]` `[patch]` Three copies of one autouse fixture, none requesting `db`, so landing
    inside the test transaction relied on undeclared pytest-django ordering; the
    `django_db` marker guard also missed cases requesting `db` directly. Replaced by one shared
    `packages_fixture(*keys)` that depends on `db` explicitly.
  - `[medium]` `[patch]` `packages_keyed` used `create`, so a duplicate raised `IntegrityError`
    from inside a fixture, and it silently accepted zero keys. Now `get_or_create`, and an empty
    key list is refused.
  - `[low]` `[patch]` "Nothing races it" overclaimed: `CPM-AD-25` governs writers, it does not
    serialize a check-then-act, and this diff adds the product's first `Package.delete()` caller.
  - `[low]` `[patch]` `DESTRUCTIVE_OPERATIONS` held four operations where its comment claimed
    two, and included `CreateModel`, which cannot lose this column.
  - `[low]` `[patch]` The migration-dependency test argued from a false premise — `core/0003`
    already declares `identity.0001`, so the ordering holds transitively.
  - `[low]` `[patch]` `AN_UNKNOWN_PACKAGE_ID` stated an invariant it never checked; now derived
    from the created keys and asserted absent.
  - `[low]` `[patch]` `pytest.raises(match=...)` takes a regex and was not escaped; the
    actionable half of the unknown-key message and the negative-key message were unpinned, so the
    two refusals could have converged on one text unnoticed.
  - `[low]` `[patch]` The `PROTECT` control case recorded a run no assertion touched; it now
    asserts both halves in one arrangement and is renamed for what it controls for.
  - `[low]` `[patch]` `core/freshness.py` cited `CollectionRun` as an example its only caller can
    never be given.
  - `[low]` `[patch]` Two consecutive blank lines in this file where the old `Status:` body line
    was removed.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** `core.CollectionRun`'s package reference became a real relation.
`package_id = PositiveBigIntegerField(...)` is now
`package = ForeignKey(identity.Package, on_delete=PROTECT, null=True, related_name="collection_runs")`.
Django names a foreign key's column by its `attname`, so the database column is still `package_id`
and every `row.package_id`, `filter(package_id=...)` and `CollectionRun(package_id=...)` reader
carried on untouched — `core/collection.py`'s `window_query` and `core/freshness.py`'s
`PACKAGE_FIELD` needed no code change, as the spec required. `core/ledger.py`'s recorder now
refuses a key naming no package before the row is written, with the key in the message, because
Django declares its SQLite foreign keys `DEFERRABLE INITIALLY DEFERRED` and the constraint would
otherwise speak at `COMMIT`. `None` is returned untouched and never looked up.

**Files changed.**

- `core/models.py` — the field became the protected, nullable relation.
- `core/migrations/0004_collection_run_package.py` *(new)* — hand-written `RenameField` →
  `RunPython` → `AlterField`. `makemigrations` would have written `RemoveField` + `AddField`,
  dropping the column and its rows.
- `core/ledger.py` — the recorder refuses a key naming no package; contract documented.
- `core/collection.py` — `Collector.collect()` documents the refusal that leaves no row.
- `core/freshness.py`, `identity/models.py`, `collectors/models.py` — stale claims retired (AC 6).
- `tests/packages.py` *(new)* — one shared `packages_fixture(*keys)` creating packages at the
  literal keys the `core` integration constants carry.
- `tests/unit/django_apps/test_run_ledger_migration.py` *(new)* — the migration's operation shape,
  including that the destructive operations are absent by name.
- `tests/integration/django_apps/test_run_ledger_migration.py` *(new)* — AC 2 executed against a
  populated table on whichever backend the gate runs.
- `tests/unit/django_apps/test_mutation_path_audit.py` — the data migration's `queryset.update()`
  recorded as a `CPM-AD-2` run-ledger exemption.
- `tests/unit/django_apps/test_run_ledger.py`, `tests/integration/django_apps/test_run_ledger.py`,
  `test_collection.py`, `test_collector_health.py`, `tests/collectors.py` — AC 1, 3, 4, 5 and the
  package fixtures.

**Review findings.** 16 patched (2 high, 7 medium, 7 low), 3 deferred, 10 rejected. Four review
layers ran in parallel over the diff; the verification-gap layer independently reported no gaps and
confirmed empirically that the SQLite substitution already catches a bad key at `TestCase`
teardown, so the new fixtures protect something the default suite would notice, not only the gate.

**Follow-up review recommended:** true. Two high-severity patches (the rule fires on any high).
Patched counts: high 2, medium 7, low 7; score `3 x 7 + 1 x 7 = 28`, itself over the threshold of 5.

**The two high findings were the same failure seen from opposite ends.** AC 2 says no row is lost
when the migration is applied. The first implementation asserted that by reading the migration's
own source — the safe operations present, the destructive ones absent — which proves the migration
was *written* correctly and nothing about what happens when it *runs*. Executing it exposed the
second half immediately: the old recorder accepted any non-negative integer, so a deployed
`collection_runs` can hold references naming no package, and adding the foreign key validates the
rows already there. The migration would have aborted on exactly the data the old contract
permitted. The data step and the executor case landed together, and the case was checked against
the migration with the step removed — it fails with the foreign-key violation the step prevents.

**Verification.** `pixi run ci` exits 0 — 4353 passed, 2 pre-existing skips, coverage 98.39%.
`pixi run gate-postgres` exits 0 with identical counts against `postgres:17`, which is where the
foreign key and `PROTECT` are genuinely enforced. Both were re-run by the orchestrating session
after the patch round, not only by the implementer.

**Residual risks.**

- A pytest-django hazard found while writing the AC 2 executor case, and general beyond this
  story: `django_db_setup` creates a test database only for aliases some *collected* case asks
  for, so in a session where nothing is marked, `django_db_blocker.unblock()` hands out a
  connection to the developer's working `db.sqlite3`. The first draft of that case was writing to
  the real database. It is closed two ways in the new module, but the repo's other
  `django_db_blocker` fixtures are safe only because marked cases request them. The local
  `db.sqlite3` is gitignored and was left consistent at `0004`.
- Three `deferred` entries, all low. The one worth naming: nothing in the planning or architecture
  artifacts records that `CPM-AD-3` is now closed for the run ledger, so the spine still reads as
  an open item.
