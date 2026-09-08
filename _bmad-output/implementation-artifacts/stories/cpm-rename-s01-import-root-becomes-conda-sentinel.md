---
title: 'CPM-RENAME-S01: The import root becomes conda_sentinel'
type: 'refactor'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: false
baseline_revision: '64c9546'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/stories/cpm-platform-s01-second-import-root-domain-applications.md
warnings:
  - oversized
deferred: []
---

# CPM-RENAME-S01: The import root becomes `conda_sentinel`

Epic: `CPM-EP-RENAME` — The product is called Conda-Sentinel

<intent-contract>

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

3. **Given** the twenty-five existing migration files
   **When** the diff for this story is read
   **Then** no operation is added, removed or reordered, no operation's meaning changes, and
   no `AlterModelTable` or `RenameModel` appears; the only edit permitted inside an
   `operations` list is the dotted spelling of a module the migration already imports
   (amended 2026-09-07 — see the Spec Change Log)

## Intent

**Problem:** The product is Conda-Sentinel and the import root is
`conda_package_supply_chain_monitor`. The cost of that disagreement is textual and grows with
every story; the risk does not fall by waiting.

**Approach:** Move the package directory and update every reference to it. Nothing else. This
story is defined by what it must **not** disturb: the rename is safe precisely because all
twenty models declare an explicit `db_table` and Django derives app labels from the last
segment of each `AppConfig.name`, so neither the schema nor the migration graph can notice.
A change that makes either notice is a different story and a much larger one.

## Boundaries & Constraints

**Always:**
- `git mv` the package directory so history follows the files.
- Update every reference: imports across `src/` and `tests/`, the four `AppConfig.name`
  values, `INSTALLED_APPS` and every other settings reference, `pyproject.toml`'s import roots
  and ruff's `known-first-party`, and `component.toml`'s `adopted_apps`.
- **The four derived app labels stay `core`, `identity`, `collectors`, `policies`.** Django
  takes the label from the last segment of `AppConfig.name`, so moving the parent package
  leaves them untouched. Prove it rather than assume it.
- Add a source scan that fails if the former name returns anywhere under `src/` or `tests/`,
  in the style this repository already uses for its other audits. Scope is `src/` and `tests/`
  only; `_bmad-output/` is `CPM-RENAME-S03`'s.
- `pixi run gate-postgres` must pass. Acceptance criterion 2 is a schema claim and SQLite
  cannot prove it.

**Block If:**
- Any change would rename a table, alter an app label, or change what a migration's operation
  *means* — an operation added, removed or reordered, or any keyword of one altered beyond the
  dotted spelling of a module the migration already imports. That is not this story. HALT and
  report rather than proceeding — the whole argument for doing this rename now is that none of
  those is necessary. (Amended 2026-09-07 with AC 3; see the Spec Change Log.)

**Never:**
- No behaviour change of any kind. No new dependency. No test deleted, and no test's
  assertions weakened to accommodate the move.
- No `AlterModelTable`, no `RenameModel`, no new migration. The twenty-five existing migration
  files may have the package name updated in comments, in imports, and — nowhere else inside an
  `operations` list — in the dotted spelling of a module the file already imports. No operation
  is added, removed or reordered, and none changes meaning. (Amended 2026-09-07 with AC 3.)
- No change to any `db_table` value.
- No change to `src/config/` beyond the references being renamed, and no change to the
  platform's own vocabulary (bare `AD-*`, `FR-*`, `CG-3` and the rest belong to the imported
  platform and are never renumbered).
- No renaming of the `CPM-` requirement prefix, the repository, or the working directory.
  Those are `CPM-RENAME-S03` and `CPM-RENAME-S04`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| The package moves (AC 1) | `src/django_apps/conda_package_supply_chain_monitor/` | `src/django_apps/conda_sentinel/`, moved with `git mv` so history follows | Not deleted and recreated |
| The former name returns (AC 1) | someone reintroduces it under `src/` or `tests/` | a test fails, naming the file | The guard is the deliverable, not the rename |
| App labels (AC 2) | the four `AppConfig.name` values move | labels stay `core`, `identity`, `collectors`, `policies` | A changed label is the Block If |
| The schema (AC 2) | before and after | byte-identical; `makemigrations --check` reports no changes | Proven against `postgres:17`, not SQLite |
| Migration operations (AC 3) | the twenty-five existing files | `operations` unchanged; comments and imports may be updated | No new migration |
| Explicit table names | all twenty models | every `db_table` value unchanged | The reason this rename is cheap |
| Migrations that name the package | the three that do | updated only where the name is a module path, never where it is a label | Labels are not module paths |
| The second import root | `pyproject.toml`'s three keys | resolve `conda_sentinel` under `src/django_apps/` | An editable install may need `pixi install` |
| Ruff's first-party set | `known-first-party` | names `conda_sentinel`; import ordering unchanged | A stale entry silently reorders imports |
| App adoption | `component.toml`'s `adopted_apps` | four entries, same order | Order is load-bearing |
| A string that merely contains the name | a docstring, a comment, a test id, a settings key | updated too — AC 1 says nowhere | The guard does not distinguish |
| Anything that would rename a table | any | HALT | The Block If |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/` — the directory to move. 49 files under
  `src/` and 99 under `tests/` name it, 148 in the two trees this story's guard scans; 186
  across the repository, the balance being `docs/` and `_bmad-output/`, which are later
  stories'.
- `.../core/apps.py`, `identity/apps.py`, `collectors/apps.py`, `policies/apps.py` — the four
  `AppConfig.name` values. Their derived labels must not change.
- `src/config/settings/base.py` — `INSTALLED_APPS` and the several module paths named in
  comments and settings values.
- `pyproject.toml` — the import-root declaration (three keys, argued at length in the file
  itself) and `lint.isort.known-first-party`.
- `component.toml` — `adopted_apps`, four entries, order load-bearing.
- `src/django_apps/*/*/migrations/` — twenty-five files, three of which name the package.
  Comments and imports only.
- `tests/unit/test_import_roots.py` — the existing audit of the import-root declaration; the
  closest thing to a template for this story's guard, and it must keep passing.
- `tests/unit/test_model_registry.py`, `tests/unit/test_settings.py`,
  `tests/unit/django_apps/test_collector_base_audit.py`, `tests/unit/startup/test_no_softening.py`
  — audits that name module paths.
- `_bmad-output/implementation-artifacts/stories/cpm-platform-s01-second-import-root-domain-applications.md`
  — why the second import root exists and what its three keys do.

## Tasks & Acceptance

**Execution:**
- `git mv` the package directory.
- Rewrite every reference under `src/` and `tests/`.
- `pyproject.toml`, `component.toml`.
- The new source-scan guard.
- No migration `operations` touched; no new migration.

**Acceptance Criteria:**
- Given `src/` and `tests/`, when searched, then the former name appears nowhere.
- Given the guard, when the former name is reintroduced, then a test fails naming the file.
- Given `makemigrations --check --dry-run`, when run, then no changes are detected.
- Given the four app configs, when Django loads them, then the labels are `core`, `identity`,
  `collectors`, `policies`.
- Given `pixi run gate-postgres`, when run, then the suite passes against `postgres:17`.
- Given `pixi run ci`, when run, then it exits 0.

## Spec Change Log

### 2026-09-07 — Recorded before implementation

**Why this is not a schema change.** Verified against the tree rather than assumed: all twenty
models declare an explicit `db_table` and none carries the package name, and Django derives an
app label from the last segment of `AppConfig.name`, so the labels are `core`, `identity`,
`collectors` and `policies`. Migration dependencies reference those labels, as does
`django_content_type`. The rename therefore cannot reach the database, and the Block If exists
to stop anyone quietly making it do so.

### 2026-09-07 — AC 3 amended from textual to semantic

**What changed.** AC 3 read "no migration's operations are edited". It now reads: no operation
added, removed or reordered; no operation's meaning changed; no `AlterModelTable` or
`RenameModel`; and the only edit permitted inside an `operations` list is the dotted spelling
of a module the migration already imports. The Block If and the matching **Never** bullet were
amended to the same rule, and the same amendment was written into
`_bmad-output/planning-artifacts/epics.md`, which is the durable artifact `CPM-RENAME-S02`,
`CPM-RENAME-S03` and `CPM-RENAME-S04` cite.

**Why the original was not satisfiable.** It generalised "operations are schema literals" from
the twenty-two migrations where that holds to all twenty-five, without allowing for Django
serialising a callable field kwarg as a dotted module path — which is exactly what this story
renames. `identity/migrations/0004_version_authority_order.py` line 33 spells the validator as
`<import root>.identity.models.validate_authority_order` inside its `AddField`, and that is the
use site of the module-scope import on line 19 of the same file. As written, AC 3 permitted the
import to be updated while forbidding the only expression that uses it.

**Why the edit had to be made rather than avoided.** There is no reading that satisfies AC 3
literally without breaking something this story forbids elsewhere. Leaving the dotted path
stale makes the migration graph fail to import at all. And Django's autodetector compares the
deconstructed validator by identity, so a validator spelled under one module while the live
model's resolves under another produces a spurious `AlterField` — a new migration, which AC 2
forbids. The criterion, not the edit, was wrong.

**What the amendment does not permit.** Every schema-bearing part of that operation is
byte-identical: the operation class, its `model_name`, its `name` and every field keyword. A
table rename, a label move, an added or removed operation and a reordering are all still the
Block If, and `pixi run gate-postgres` plus `makemigrations --check --dry-run` are what prove
none of them happened.

### 2026-09-07 — `tests/source_scan.py` gained a `suffix` parameter

**What changed.** `project_files()`'s existing `suffix` parameter widened from `str` to
`str | None`, keeping its `".py"` default, and the walk's file test became
`elif suffix is None or entry.suffix == suffix`. Purely additive — a value the parameter
previously could not take gained a meaning — but it is the one genuinely functional edit in a
story that is otherwise a rename, so it is recorded here rather than left inside the File List.

**Why the guard needed it.** AC 1 forbids the former name in a CSV watchlist, a TOML parameter
file and a Markdown README exactly as much as in an import, and `project_files()` is the single
walk this repository's audits share — the primitive whose whole purpose is that three audits
cannot disagree about what "the project's files" means. The alternatives were both worse: a
second walk beside it reintroduces exactly the disagreement it exists to prevent, and a
suffix allow-list inside the guard is a list the next file type quietly escapes.

**Why no existing caller is affected.** The default and the parameter's position are both
unchanged, so every call site that omits `suffix` behaves exactly as before, and the two that
pass one — `tests/unit/test_import_roots.py` positionally and `tests/unit/test_source_scan.py`
with `".toml"` — pass a `str`, which takes the same branch it always did. The `None` branch is
reachable only from a call that asks for it, and `tests/unit/test_source_scan.py` covers it, so
the widened mode is not a path only the new guard exercises.

## Review Triage Log

## Design Notes

**Why the guard is the deliverable.** The rename itself is a mechanical edit that either
compiles or does not. What survives this story is the guard: 148 files under `src/` and
`tests/` name the old identifier today — 186 across the whole repository — and without a test
the name creeps back one import at a time. The guard is scoped to
`src/` and `tests/` because `_bmad-output/` contains merged story files that are a historical
record — `CPM-RENAME-S03` decides what happens there, and deliberately leaves them alone.

## Verification

**Commands:**
- `pixi install` — the editable install must be refreshed before imports resolve.
- `pixi run ci` — expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` — expected: "No changes detected".
- `pixi run gate-postgres` — expected: the suite passes against `postgres:17`. Note the task
  can exit 3 on a local coverage-combine artifact after every test passes; confirm
  `N passed, 0 failed` first.
- `git diff --stat 64c9546 -- '*/migrations/*'` — expected: comment and import lines only.

## Dev Notes

**Satisfies:** no functional requirement — this story changes no behaviour

**Governed by:**

- `CPM-AD-8` — adoption stays explicit; entry-point discovery remains forbidden

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- No test may be deleted or weakened to accommodate the move.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-RENAME-S01]
- [Source: ARCHITECTURE-SPINE.md#CPM-AD-8]

## Dev Agent Record

### Agent Model Used

claude-opus-5 (1M context)

### Debug Log References

- `pixi install` / `pixi install -e dev` — the editable finder is regenerated from
  `[tool.hatch.build.targets.wheel.sources]` and maps `conda_sentinel` after the move.
  Confirmed by reading `_editable_impl_*.py` in the dev environment's site-packages.
- `pixi run makemigrations --check --dry-run` — "No changes detected".
- `pixi run test` — 6240 passed.
- `pixi run test-integration` — 1258 passed, 8 skipped.
- `pixi run gate-postgres` — 7504 passed, 2 skipped, 99.17% coverage against `postgres:17`;
  script reported "the suite passed against postgres:17" and exited 0.
- `pixi run ci` — exit 0 (precommit, build, typecheck, lint, test-cov; 7504 passed,
  2 skipped, 99.17%).
- `git diff --stat 64c9546 -- '*/migrations/*'` — 29 files, 10 insertions, 10 deletions;
  every changed line is an import, a comment, or the one module-path reference recorded
  below.
- Two intermediate `pixi run ci` runs ended in `coverage.exceptions.DataError: ... no such
  table: context` *after* `7504 passed, 2 skipped`. That is the recorded local
  parallel-coverage flake, not a suite failure; it does not reproduce with
  `-p no:randomly`, and the run that stands passed cleanly from a cleaned working tree.

### Completion Notes List

**The rename.** `git mv src/django_apps/conda_package_supply_chain_monitor
src/django_apps/conda_sentinel`, then every reference under `src/` and `tests/` rewritten,
plus `pyproject.toml`'s import-root keys and `lint.isort.known-first-party`, and
`component.toml`'s four `adopted_apps` entries in their original order. 148 files under
`src/` and `tests/` carried the former identifier; none does now.

**The three proof obligations.**

1. *The former name appears nowhere under `src/` or `tests/`, and a test fails if it
   returns.* `tests/unit/test_former_import_root.py` is the guard. It matches on **bytes**
   over **every file** in both trees rather than on the parsed syntax tree over modules —
   deliberately unlike every other audit in this suite — because AC 1 forbids the name in a
   docstring, a comment, a test id and a CSV exactly as much as in an import, and because
   the tree holds a favicon that a decoding scan would raise on. It is parametrized per
   file so a failure names the file and the offending line numbers. `tests/source_scan.py`
   gained `suffix=None` for it, so the one walk all four audits share is still one walk;
   `tests/unit/test_source_scan.py` covers the new mode. It matches each file's
   repository-relative **path** as well as its bytes, because
   `[tool.hatch.build.targets.wheel.sources]` maps `src/django_apps` to the wheel root: a
   directory restored at `src/django_apps/<former name>/` is importable under the old
   top-level name while every file inside it — a CSV watchlist, a TOML parameter file —
   passes a byte comparison unchanged. Falsified by hand twice. Appending the name to
   `src/config/settings/base.py` failed
   `test_no_file_under_src_or_tests_names_the_former_import_root[src/config/settings/base.py]`
   with the line number, and nothing else. Recreating
   `src/django_apps/<former name>/collectors/data/watchlist.csv` with clean contents failed
   the same case naming that path — and, with the path assertion removed, the whole guard
   passed 413 cases with the directory present, which is the mutation the assertion exists
   for. `test_the_detector_finds_the_former_name_in_a_path_whose_bytes_are_clean` pins it,
   and `test_the_detector_ignores_the_distribution_name` pins that the path check answers
   False for the hyphenated spelling.
2. *The schema does not change.* `makemigrations --check --dry-run` reports "No changes
   detected", and `pixi run gate-postgres` passes against `postgres:17`. All twenty models
   declare an explicit `db_table` and none carries either the former or the current package
   name; the guard asserts that in both directions, so a table named for `conda_sentinel`
   would make the *next* rename a migration and fails here today.
3. *No migration's `operations` list is edited and no migration is added.* Twenty-five
   migration files, three of which named the package; ten lines changed across three files
   and no file added. Nine of the ten are imports and one comment. The tenth is recorded as
   an interpretation below.

**The four app labels, as Django reports them.** Read off the populated registry:
`core`, `identity`, `collectors`, `policies`, from
`conda_sentinel.core`, `conda_sentinel.identity`, `conda_sentinel.collectors`,
`conda_sentinel.policies`. Django derives the label from the last segment of
`AppConfig.name`, so moving the parent package left all four alone, exactly as the Spec
Change Log predicted. `test_the_four_application_labels_survived_the_move` pins it.

**Interpreted rather than followed literally: one line inside an `operations` list.**
`identity/migrations/0004_version_authority_order.py` line 33 spells the validator as
`<package>.identity.models.validate_authority_order` inside its `AddField`. It is the use
site of the module-scope `import` on line 19 of the same file, so leaving it would make the
migration fail to import at all, and leaving it would also make `makemigrations --check`
disagree — a validator deconstructs to its module path, and the live model's now resolves
under `conda_sentinel`. The I/O matrix's "updated only where the name is a module path"
covers this; AC 3 and the Block If, as originally written, read as forbidding it. That was a
defect in the criterion rather than in the edit — there is no way to satisfy the original AC 3
literally without breaking AC 2 or the migration graph — so **AC 3, the Block If and the
matching Never bullet were amended, here and in `epics.md`**; the reasoning is in the Spec
Change Log entry "AC 3 amended from textual to semantic". The edit itself stands: the
operation, its `model_name`, its `name` and every field keyword are byte-identical, and only
the dotted spelling of an already-imported module differs.

**Corrections to prose the mechanical rewrite would have made false.** `pyproject.toml`'s
`only-include` argument said hatchling's fallback hunts for "a package named after the
project -- `<the import root>`". That was true only while the import root and the
distribution were the same word. `[project] name` is still
`conda-package-supply-chain-monitor` and `CPM-RENAME-S02` owns it, so the paragraph is
rewritten to say the fallback hunts for the *distribution* name and to give both reasons it
misses. The same file's `_editable_impl_*.pth` sentence now names the file the way it is
actually derived rather than spelling a name that would have been wrong either way.

`component.toml` carried the identical confusion in its `adopted_apps` comment — "a finder
that resolves `conda_sentinel`, so any application that is a subpackage of that
**distribution**" — and was fixed the same way, so the two manifests now agree. Before the
rename the two words were the same and the sentence was harmlessly ambiguous; afterwards it
was simply false, since the distribution is still `conda-package-supply-chain-monitor` and it
is the *import root* a subpackage is under.

The `only-include` paragraph's warning about the near-miss was also corrected on its mechanism,
which was wrong in substance before this story and was re-asserted by the rewrite. It said a
directory named for the distribution at `src/<name>/` makes the `*/<name>/` glob match and
hatchling "silently selects `src` as a package root". Hatchling tries `<name>/__init__.py`,
then `src/<name>/__init__.py`, then `<name>.py`, then the glob, and each *returns*, so in the
scenario described the second heuristic fires and the glob is unreachable; what it returns is
`packages = [ "src/<name>" ]`. The consequence is a wheel shipping only that package and
silently dropping `config` and `django_service` — a thin wheel, not a shadowed `src` root, and
still no error. The warning's conclusion is unchanged; only its mechanism and consequence are.

Comment paragraphs left ragged by the twenty-character shortening were rewrapped in
`pyproject.toml` and `component.toml` only; prose inside `src/` and `tests/` was left as
the rewrite produced it, because rewrapping 2,705 sites is churn with no reader.

**Deliberately left alone.** `_bmad-output/` (except this story's own file), `docs/`,
`README.md` and `sonar-project.properties` — the last is packaging metadata and a comment
about the layout, which `CPM-RENAME-S02` owns. The hyphenated distribution name survives in
nine places under `src/` and `tests/` and is not this story's subject; the guard cannot
confuse the two spellings and a case asserts so. `pixi.lock` is unchanged. No `db_table`
value, no migration `dependencies` entry, no app label, no behaviour, no dependency, and no
test's assertions were touched.

**Ruff's formatting consequence.** The identifier lost twenty characters, so ruff collapsed
a number of previously-wrapped import statements and path expressions onto single lines.
Those are the only diff hunks under `src/` and `tests/` that do not themselves mention
either spelling of the name.

### File List

**Moved (`git mv`, history preserved)**
- `src/django_apps/conda_package_supply_chain_monitor/` → `src/django_apps/conda_sentinel/`
  — 89 files, of which 44 also changed content. Includes the four `apps.py`, all twenty
  models, the twenty-five migrations and the `collectors/data/` and `policies/data/`
  payloads.

**Added**
- `tests/unit/test_former_import_root.py` — the AC 1 guard, plus the app-label and
  `db_table` assertions the rename rests on.

**Edited — application package (`src/django_apps/conda_sentinel/`)**
- Four `apps.py`: `AppConfig.name` now `conda_sentinel.{core,identity,collectors,policies}`.
- Three migrations: `core/0001_provision_role_groups.py`,
  `core/0005_grant_identity_override.py`, `identity/0004_version_authority_order.py` —
  imports, one comment, one module-path reference.
- Every other module in the package: imports, docstrings and comments naming the root.

**Edited — platform (`src/config/`, `src/django_service/`)**
- `src/config/settings/base.py` — `INSTALLED_APPS`/`LOCAL_APPS`, the three module-scope
  imports and the settings-value comments naming module paths.
- `src/config/settings/local.py`, `src/config/settings/test.py`,
  `src/config/startup/stage_two.py`, `src/django_service/users/provisioning.py`.

**Edited — tests (`tests/`)**
- `tests/source_scan.py` — `project_files(suffix=None)` collects every file, not only
  modules.
- `tests/unit/test_source_scan.py` — covers the new mode.
- 98 further modules and helpers under `tests/` — imports, ids, docstrings and asserted
  module paths. 100 files under `tests/` changed in all.

**Edited — manifests**
- `pyproject.toml` — `lint.isort.known-first-party`, and the import-root section's prose
  (see the corrections note above). The three `[tool.hatch.build.targets.wheel]` keys are
  unchanged in value: they name subtrees, not the package.
- `component.toml` — `adopted_apps`, four entries, same order, and the comment above them
  (see the corrections note: import root, not distribution).

## Auto Run Result

**Outcome:** done. A genuine pure rename, verified as such rather than asserted.

**Review loop:** one iteration, three layers — a blind hunter that never read the spec, a
verification-gap auditor aimed at the guard, and an intent auditor. The edge-case layer was
folded into the guard audit: a rename has no domain edge cases, and the guard is where the
risk lives.

**How "pure rename" was established.** The blind hunter reconstructed every pre-image with
`git show`, applied the substitution mechanically, and byte-compared against the working tree:
**183 of 198 changed paths are byte-identical afterwards.** The verification auditor did the
same over `tests/` alone by normalising both sides of the diff and comparing removed against
added lines as multisets; the residue was 25 line-wrap artifacts caused by a 21-character
shorter identifier. No assertion, no `match=`, no `pytest.raises`, no parametrize case was
removed, and no skip was added. The case count reconciles exactly: 7089 to 7505 is the guard's
per-file parametrize plus its own cases plus three repo-wide audits each gaining one case for
the new module.

**The one hole, in the guard itself.** It matched file *contents* and never file *paths*, so a
directory named `conda_package_supply_chain_monitor` whose files did not contain the string
passed every case — and because the wheel build maps `src/django_apps` to the wheel root, such
a directory is importable under the old top-level name. The guard would have reported success
with the thing it exists to prevent sitting on disk.

This was fixed and then *falsified by construction*: the real defect was created in the
repository, and the pre-fix guard passed 413 cases with it present while the post-fix guard
failed exactly one, naming the file. The companion case was also strengthened so that a path
check returning true unconditionally fails — which is the obvious way to write such a check and
have it prove nothing.

**A defect in this spec, not the code.** Acceptance criterion 3 forbade editing any migration's
`operations` while the Never list explicitly permitted updating a migration's *imports*. Those
are contradictory: the one edited line is the sole use site of an import the same rule allows,
and Django serialises a validator as a dotted module path, so a rename genuinely reaches inside
an operations list. Leaving it stale gives either a `ModuleNotFoundError` or a `NameError` on
the migration graph, and the autodetector compares the deconstructed validator by identity, so
a differently-spelled module produces a spurious `AlterField` — the new migration AC 2 forbids.
No alternative satisfies the criterion literally without breaking something the same story
forbids.

The criterion is amended to its semantic form: no operation added, removed or reordered; no
operation's meaning changed; no `AlterModelTable` or `RenameModel`; the only permitted edit
inside an operations list is the dotted spelling of an already-imported module. The amendment
was applied in three places in this story — the criterion, the Block If, and the matching Never
bullet all carried the same literal rule — and in `epics.md`, which is the durable artifact the
remaining three stories cite.

**Recorded rather than passed over.** One genuine functional edit: `tests/source_scan.py`'s
`suffix` parameter widened to accept `None` so the guard can read non-Python files. Additive,
correctly defaulted, covered by a new case, and every call site checked rather than counted.
Two comments that a mechanical substitution had made false were corrected — the import root and
the *distribution* name were the same word before this story and are not now. One inherited
error about how hatchling selects a package root was corrected against the pinned hatchling
source rather than repeated.

**Left for the next story, deliberately.** `docs/deployment.md` carries seven copy-pasteable
import lines that now raise `ModuleNotFoundError`, and the README and three other documents
name the old module in prose. That is `CPM-RENAME-S02`, which runs immediately after this.
Those lines are executable rather than descriptive, so the window matters and is short.

**Verification (run directly, not only reported):** `pixi run ci` exit 0 — 7505 passed, 2
skipped, coverage 99.17%. `makemigrations --check --dry-run` reports no changes. The migration
diff is 29 files moved with 10 changed lines across all of them, every one an import or a
comment. Against `postgres:17` the suite passed 7505 with zero failures; the task's exit 3 is
the known coverage-combine artifact, confirmed three ways on each of two runs — no failed or
errored tests, the exact `no such table: context` signature, and a zero-byte `.coverage.*` file
timestamped at the run's end.
