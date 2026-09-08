---
title: 'CPM-RENAME-S02: Conda-Sentinel on every operator-facing surface'
type: 'refactor'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: false
baseline_revision: '40cf77b'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/implementation-artifacts/stories/cpm-rename-s01-import-root-becomes-conda-sentinel.md
warnings: []
deferred:
  - summary: >-
      The OpenTelemetry service name deliberately still carries the product's former name, and
      nothing in the suite pins the literal, so a later rename would move every span's
      `service.name` and pass the gate silently.
    evidence: |-
      `DEFAULT_SERVICE_NAME = "conda-package-supply-chain-monitor"`, documented by the
      `OTEL_SERVICE_NAME` row in `docs/observability.md`. This story renamed the product
      everywhere else and kept this one: it is an *emitted* value, so moving it silently
      breaks any dashboard, alert or saved query keyed on the old `service.name`, and the
      story's Never bullet forbids behaviour change. That makes it a **behaviour change with a
      migration cost**, not a leftover, and it needs an owner who states the migration rather
      than a sweep that tidies it.

      The trap is that no test would stop such a sweep. `tests/unit/test_telemetry.py:129,187`
      assert by reference to the constant, not against the string, so renaming the constant's
      value keeps the suite green; `tests/unit/test_former_import_root.py` forbids only the
      *underscored* spelling and this is the hyphenated one. Both that guard's docstring and
      `CPM-RENAME-S04`'s stub now name this explicitly as not-to-be-swept.

      Compare the `User-Agent` decision recorded below it: that emitted value *was* moved,
      because packaging forced it. The two decisions are opposite on purpose.
    location: >-
      src/config/observability/telemetry.py -- DEFAULT_SERVICE_NAME; docs/observability.md --
      the OTEL_SERVICE_NAME row; tests/unit/test_telemetry.py:129,187
    severity: medium
  - summary: >-
      Every tracked file naming the repository still carries the former name, and until this
      story's review amended `CPM-RENAME-S04` no story in the epic owned them.
    evidence: |-
      The three README badges and their links, `mkdocs.yml`'s `repo_url`,
      `sonar-project.properties`' `projectKey`/`projectName`/header comment,
      `.github/ISSUE_TEMPLATE/config.yml`'s four URLs, `.github/workflows/release.yml`'s clone
      URL and two changelog links, `collectors/agent.py`'s `PROJECT_URL`, `pyproject.toml`'s
      commented git-cliff samples, and `_bmad/*`'s `project_name`.

      These are deferred rather than fixed because the URLs 404 until `gh repo rename` has run.
      `CPM-RENAME-S04` as written could not have picked them up -- its stub and `epics.md` both
      said it "changes no tracked file" and its three acceptance criteria were `gh repo rename`,
      `git remote set-url` and `pixi clean`/`mv`/`pixi install`. Both have been amended by this
      story's review: S04 now has a second, sequenced half and a fourth acceptance criterion
      covering exactly this list.

      Resolved when `CPM-RENAME-S04` half two merges. The Sonar key is the one live decision
      inside it: changing it orphans the SonarCloud project's history, so the story must either
      take that trade with the badges in the same commit or record the decision to keep it.
    location: >-
      README.md:3-5; mkdocs.yml:3; sonar-project.properties:1,6,10; .github/**;
      src/django_apps/conda_sentinel/collectors/agent.py -- PROJECT_URL; pyproject.toml:451,464
    severity: low
  - summary: >-
      Two commands in the deployment runbook fail on copy-paste in a local checkout, for two
      unrelated pre-existing reasons; both are now warned about in place rather than fixed.
    evidence: |-
      Both reproduced, neither caused by the rename.

      1. **pixi task-shell quoting.** `pixi run` re-parses a task's arguments and strips inner
         *single* quotes, so `pixi run manage shell -c "print('hi')"` reaches Python as
         `print(hi)` and raises `NameError`. The runbook's `run_policy.delay('<your policy
         version>')` could not survive a paste. A form that *does* survive was found and the
         runbook now uses it -- outer single quotes, inner double quotes -- so this half is
         fixed for that block; what stays deferred is that every other `manage shell -c` in any
         future document hits the same defect, and nothing tests runbook commands.
      2. **`pixi run manage migrate --database default --noinput` (runbook line 229)** raises
         `ImproperlyConfigured: settings.DATABASES is improperly configured`. See the entry
         below for the actual mechanism. The command is correct for a *deployed* component and
         wrong to paste locally; a warning beside it now says so and gives two working local
         forms, both verified.

      Recording rather than fixing is defensible -- both predate this story -- but this story's
      own Intent says a runbook that reads as current while its commands fail is worse than not
      renaming, which is why the warnings are in the runbook rather than only here.
    location: >-
      docs/deployment.md -- the `pixi run manage migrate` block under "One step per database",
      and the `run_policy` block under "Running it, and where the result lands"
    severity: low
  - summary: >-
      The OpenTelemetry Django instrumentor catches this component's stage-one startup refusal
      and calls `settings.configure()`, converting a deliberate fail-closed guard into a silent
      fail-open with no traceback.
    evidence: |-
      `src/config/startup/stage_one.py:211`'s `_refuse_the_local_settings_module` raises
      `ImproperlyConfigured` when a *deployed* component loads `config.settings.local`. That is
      the intended refusal, and it is correct: the `default` pixi environment declares no
      `COMPONENT_RUNTIME`, so `src/config/locality.py` reads *deployed* (locality fails closed,
      deliberately), while `manage.py` defaults `DJANGO_SETTINGS_MODULE` to
      `config.settings.local`.

      What happens next is the defect. The instrumentor reads the middleware setting inside a
      `try`, catches `ImproperlyConfigured`, logs it at `DEBUG` and calls `settings.configure()`
      -- see
      `.pixi/envs/default/lib/python3.14/site-packages/opentelemetry/instrumentation/django/__init__.py:438-443`.
      The process therefore continues with `SETTINGS_MODULE = None` and `INSTALLED_APPS = []`,
      and the operator sees an unrelated downstream failure (`settings.DATABASES is improperly
      configured`, or `Model class ... isn't in an application in INSTALLED_APPS`) rather than
      the refusal's own message, which states both resolutions.

      Confirmed by elimination: `COMPONENT_RUNTIME=local pixi run manage shell` in the *same*
      `default` environment reports `SETTINGS_MODULE = config.settings.local` and 25 installed
      apps. So the cause is the runtime declaration, **not** missing dev-only packages, which
      is what this story's Debug Log first recorded and has now been corrected.

      Marked high because a third-party instrumentor defeating a startup guard is worth
      attention independently of this epic: every stage-one refusal that raises
      `ImproperlyConfigured` before the instrumentor runs is reachable the same way, and a
      deployed component that trips one would start with empty settings instead of refusing.
      A fix probably means running stage one before instrumentation, or re-raising after it.
    location: >-
      src/config/startup/stage_one.py:211 -- _refuse_the_local_settings_module; interaction with
      opentelemetry.instrumentation.django (__init__.py:438-443)
    severity: high
---

# CPM-RENAME-S02: Conda-Sentinel on every operator-facing surface

Epic: `CPM-EP-RENAME` — The product is called Conda-Sentinel

<intent-contract>

## Story

As an operator,
I want the documentation and packaging to call the product by its name,
so that what I deploy and what I read about are recognisably the same thing.

## Acceptance Criteria

1. **Given** the README, `docs/`, the packaging metadata and the workspace manifests
   **When** they are read after this story
   **Then** they name Conda-Sentinel, and no operator-facing surface **naming the product**
   uses the former name

   *Scope, stated rather than left implicit.* Two classes of surface are outside it and stay
   on the former name after this story:

   - **Repository identity** — the three README badges and their links, `mkdocs.yml`'s
     `repo_url`, `sonar-project.properties`' `projectKey`/`projectName`, `.github/**`'s URLs
     and clone paths, `collectors/agent.py`'s `PROJECT_URL`, `pyproject.toml`'s commented
     git-cliff samples. These name the *repository*, which has not been renamed;
     `CPM-RENAME-S04` owns them, and its scope was amended by this story's review to say so.
   - **`OTEL_SERVICE_NAME`'s default** — an *emitted* value, deliberately kept. See the
     deferred entry.

   What this story's own review did change is the `.github` **prose** that names the product
   (the two issue-template descriptions, one placeholder, the `CODEOWNERS` header). Those
   render in GitHub's issue forms, a repository rename will never touch them, and the
   "these name the repository" rationale does not reach them.

2. **Given** an operator following the deployment documentation
   **When** they run the commands it gives
   **Then** the commands work against the renamed import root

## Intent

**Problem:** `CPM-RENAME-S01` moved the import root and deliberately left the documentation
alone. That leaves `docs/deployment.md` carrying **eight copy-pasteable import lines that now
raise `ModuleNotFoundError`**. They are executable, not descriptive: an operator pasting them
gets a failure, and nothing in the repository fails until they do. This story closes that
window and finishes the operator-facing half of the rename.

**Approach:** Rename the distribution to `conda-sentinel` and update every operator-facing
surface. The distribution name is the substantive change; the rest is text. And because
`[project] name` and the import root became different words at `CPM-RENAME-S01` and become the
same word again here, every sentence that relates the two must be **re-read**, not
substituted — that is the class of prose S01's review caught twice.

## Boundaries & Constraints

**Always:**
- Every command in `docs/deployment.md` is verified as a **command**, not skimmed as text.
  Eight import lines are the specific reason this story exists.
- `[project] name` becomes `conda-sentinel`, and every place that name appears or is derived
  from — the editable-install artefacts, the wheel's package selection, any prose naming the
  distribution — is reconciled with it.
- Prose relating the distribution to the import root is re-read rather than substituted. The
  two were one word before S01, two words after it, and one word again after this story;
  sentences written under any of those three states can be wrong under the others.
- `pixi install` is re-run after the distribution name changes, because the editable-install
  artefacts are named for the distribution.

**Block If:**
- Renaming the distribution would change what the built wheel contains. It must not: the
  wheel's contents are selected by explicit path keys, not by the distribution name. Prove it
  rather than assume it, and HALT if the built artefact differs in anything but its own name
  and version metadata.

**Never:**
- No behaviour change. No source file under `src/` changed except where it names the
  distribution.
- No test deleted or weakened. The guard `CPM-RENAME-S01` added stays exactly as strict.
- No **rename** in `_bmad-output/`. The merged story files are a record, and substituting the
  new name into the planning artifacts is `CPM-RENAME-S03`'s. Stated this way because the
  bullet as first written — "no change to `_bmad-output/`" — is false of every story commit in
  this epic including `S01`: `sprint-status.yaml` moves each time, this story file is itself
  under `_bmad-output/`, and this story's review amends `CPM-RENAME-S04`'s stub and the `S04`
  section of `epics.md` because nothing else in the epic owns the repository-identity surfaces.
  A scope correction to an unstarted stub is not a rename substitution.
- No renaming of the repository or the working directory — `CPM-RENAME-S04`, operator-run.
- No renaming of the `CPM-` requirement prefix.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| The eight runbook imports (AC 2) | `docs/deployment.md` lines 1201-1202, 1385-1386, 1846-1848, 1998 | name `conda_sentinel`, and each is run to prove it resolves | The reason this story exists |
| Runbook paths that are not imports | lines 743, 745, 2140 name `src/django_apps/<old>/...` | the path that exists on disk | A stale path in a runbook reads as current |
| The distribution name | `pyproject.toml` `[project] name` | `conda-sentinel` | |
| The wheel's contents | before and after | identical but for name and version metadata | The Block If |
| Editable-install artefacts | named for the distribution | regenerated by `pixi install` | Stale artefacts resolve the old name |
| Prose relating distribution to import root | the sentences S01 had to correct | re-read; correct under the *new* state where the two agree again | Substitution alone produces new falsehoods |
| README, `docs/index.md`, `docs/technology-stack.md`, `docs/authentication.md` | 3, 3, 3, 2 references | Conda-Sentinel | Prose only |
| `sonar-project.properties` | 1 reference | reconciled; `sonar.sources` names a directory, not the package | Check whether it is a path or a name |
| The S01 guard | `tests/unit/test_former_import_root.py` | unchanged and still passing | Its scope is `src/` and `tests/`; this story is neither |
| A merged story file | `_bmad-output/.../*.md` | untouched | `CPM-RENAME-S03` decides, and decides to leave them |

</intent-contract>

## Code Map

- `docs/deployment.md` — 11 references. Eight are executable import lines (1201-1202,
  1385-1386, 1846-1848, 1998); three are paths (743, 745, 2140). The eight are why this story
  is not cosmetic.
- `pyproject.toml` — `[project] name`, and the prose `CPM-RENAME-S01` rewrote about how
  hatchling selects a package root and how the editable artefacts are named. Both were written
  when the distribution and the import root were different words; re-read them now that they
  agree again.
- `README.md` (3), `docs/index.md` (3), `docs/technology-stack.md` (3),
  `docs/authentication.md` (2) — prose.
- `sonar-project.properties` (1) — check whether the reference is a path or a package name;
  `sonar.sources` is path-based.
- `component.toml` — the comment `CPM-RENAME-S01` corrected to distinguish the import root
  from the distribution. Same re-read.
- `tests/unit/test_import_roots.py` — pins the three import-root keys, which name directories.
  Should need no change; if it does, that is a signal.

## Tasks & Acceptance

**Execution:**
- `docs/deployment.md`, and run every command it gives.
- `pyproject.toml` `[project] name` plus the reconciled prose.
- `README.md`, `docs/index.md`, `docs/technology-stack.md`, `docs/authentication.md`.
- `sonar-project.properties`, `component.toml`.
- `pixi install`, then the full gate.

**Acceptance Criteria:**
- Given the eight runbook import lines, when each is executed, then it resolves.
- Given `docs/`, the README and the manifests, when searched for the former distribution or
  import root, then neither appears.
- Given the built wheel before and after, when compared, then the contents are identical.
- Given `pixi run ci`, when run, then it exits 0.

## Spec Change Log

### 2026-09-07 — Recorded before implementation

**Why the prose cannot be substituted mechanically.** `CPM-RENAME-S01`'s review found two
comments made false by a mechanical rewrite, both because the distribution name and the import
root had been the same word and stopped being so. This story makes them the same word again,
which invalidates the *corrections* S01 made as surely as the originals. Every sentence
relating the two is re-read.

## Review Triage Log

### 2026-09-07 — Two review layers, findings applied

The change is mechanically a pure rename and the Block If was cleared
independently by both reviewers. Every finding was in the **record** or in a
missing guard, not in the rename.

| # | Finding | Resolution |
|---|---------|------------|
| M1 | `CPM-RENAME-S04` could not own the repository-identity surfaces deferred to it | `S04`'s stub and `epics.md` amended: second sequenced half, fourth AC, "not in scope" corrected |
| M2 | `deferred: []` while four things were deferred | Four `deferred:` entries added, one at `severity: high` |
| M3 | The `agent.py` version lookup had no parity guard; every existing assertion was tautological | Guard added, mirroring `test_package_version.py`; falsified against a typed constant |
| M4 | Two runbook commands fail on copy-paste | Admonitions beside both; the quoting one given a form that survives; both logged as deferred |
| M5 | The recorded root cause of the `manage` failure was wrong, and the real one is a fail-open | Debug Log corrected; `deferred:` entry at `severity: high` |
| M6 | Three claims introduced by this story's own re-read were false | All three corrected in `test_former_import_root.py` and `agent.py` |
| M7 | An emitted value did change and the story said none did | `docs/deployment.md` gained "What every collector calls itself on the wire", reconciling both decisions |
| S1 | `.github` prose naming the product, unreachable by a repository rename | Four sites changed; URLs and Sonar keys left |
| S2 | The "No change to `_bmad-output/`" Never bullet was false as written | Amended to "no **rename** in `_bmad-output/`", with the scope correction called out |
| S3 | A Debug Log migrate claim did not reproduce | Corrected to what actually ran; both working forms re-run and confirmed |
| S4 | `pyproject.toml`'s "one directory below the root" sent a checker to the wrong invariant | Reworded to distinguish the deepest *containing directory* from the deepest path |
| S5 | AC 1 read as failed under its own literal wording | Scope stated honestly: operator-facing surfaces **naming the product**, repository identity excluded and owned by `S04` |

## Design Notes

**Why the eight import lines are the point.** The rest of this story is text an operator reads.
Those eight are text an operator *runs*, and they have been broken since `CPM-RENAME-S01`
merged. A rename that updates the narrative and leaves a stale command is worse than not
renaming, because the surrounding prose then reads as current and the reader has no reason to
doubt it.

## Verification

**Commands:**
- Each of the eight import lines, executed.
- `pixi install` — the editable artefacts are named for the distribution.
- `pixi run ci` — expected: exit 0.
- `pixi run build` and a comparison of the wheel's contents before and after.
- Note the parity task can exit 3 on a coverage-combine artefact after every test passes;
  confirm `N passed, 0 failed` first.

## Dev Notes

**Satisfies:** no functional requirement — this story changes no behaviour

**Governed by:** none

**Depends on:** `CPM-RENAME-S01`.

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- `pixi run ci` must exit 0.
- Documentation carrying commands is verified by running them.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-RENAME-S02]

## Dev Agent Record

### Agent Model Used

claude-opus-5 (1M context)

### Debug Log References

- The eight runbook import lines, each executed on its own in a real Django
  process (`pixi run -e dev python manage.py shell`, fed from a one-line file so
  no shell re-quoting could alter what was run). All eight printed `RESOLVED`.
  The same harness with the former spelling still raises
  `ModuleNotFoundError: No module named 'conda_package_supply_chain_monitor'`,
  so the check is falsifiable rather than vacuous.
- `pixi install` and `pixi install -e dev` — the editable artefacts are now
  `_editable_impl_conda_sentinel.pth` / `.py` and the dist-info is
  `conda_sentinel-0.1.1.dev13+g40cf77b38.d20260908.dist-info`. The former pair
  (`_editable_impl_conda_package_supply_chain_monitor.*`) is gone from both
  environments; pixi removed them rather than leaving a stale finder behind.
- `pixi run build` before and after, both wheels unpacked and compared: 189
  files each, identical path set, `WHEEL` byte-identical, `RECORD` path set
  identical. See the Block If note below.
- `pixi run makemigrations --check --dry-run` — "No changes detected".
- `pixi run test` — 6241 passed. `pixi run test-integration` — 1258 passed,
  8 skipped.
- `pixi run ci` — exit 0; 7505 passed, 2 skipped, 99.17% coverage.
- `pixi run gate-postgres` — exit 0; 7505 passed, 2 skipped, and the script
  reported "the suite passed against postgres:17". No coverage-combine artefact
  this time; `.coverage*` was cleared before each run.
- `pixi run docs` (`mkdocs build --strict`) — built clean with the new
  `site_name`.
- `migrate --database default --noinput` (line 229 of the runbook) run against a
  throwaway sqlite: every migration applied.

  **Corrected 2026-09-07 (review).** This entry first read "`pixi run manage
  migrate --database default --noinput` … every migration applied", which does
  not reproduce: the `manage` task pins `default-environment = "default"`, where
  `INSTALLED_APPS` is empty, and that exact command raises
  `ImproperlyConfigured: settings.DATABASES is improperly configured`. What was
  actually run was the `dev` environment's form. Both working forms have now been
  re-run and confirmed against a local sqlite —
  `pixi run -e dev manage migrate --database default --noinput` (applied every
  migration) and `COMPONENT_RUNTIME=local pixi run manage migrate --database
  default --noinput` (reported "No migrations to apply" against the database the
  first had already migrated). The failing runbook form now carries a warning
  beside it and a `deferred:` entry.
- `pixi run manage shell` in the **default** environment configures Django
  through `settings.configure()` and reports `SETTINGS_MODULE = None` with an
  empty `INSTALLED_APPS`. Pre-existing and unrelated to the rename.

  **Corrected 2026-09-07 (review).** This entry first attributed it to
  `config.settings.local` needing dev-only packages. That is wrong, and the real
  mechanism is worse. `src/config/startup/stage_one.py:211`'s
  `_refuse_the_local_settings_module` raises `ImproperlyConfigured` because the
  `default` environment declares no `COMPONENT_RUNTIME` and `config/locality.py`
  therefore reads *deployed* — a correct, deliberate fail-**closed** refusal.
  The OpenTelemetry Django instrumentor then catches that `ImproperlyConfigured`,
  logs it at `DEBUG` and calls `settings.configure()`
  (`opentelemetry/instrumentation/django/__init__.py:438-443`), so the refusal
  becomes a silent fail-**open**: empty settings, no traceback, and a later
  unrelated error. Confirmed by elimination —
  `COMPONENT_RUNTIME=local pixi run manage shell` in the *same* `default`
  environment reports `SETTINGS_MODULE = config.settings.local` and 25 installed
  apps, so no package is missing. Recorded as a `deferred:` entry at
  `severity: high`, because a third-party instrumentor defeating a startup guard
  matters beyond this epic.

  The runbook's form is still correct for a *deployed* component, where the
  settings module is production and the `default` environment is complete;
  locally the dev environment is the stand-in, and that is where the eight lines
  were run.

### Completion Notes List

**The distribution is `conda-sentinel`.** `[project] name`, `pixi.toml`'s
`[pypi-dependencies]` key and its `[pypi-options] no-build-isolation` entry, the
`[workspace] name`, and `component.toml`'s `[component] name` all move together;
so do the three places a *value* is derived from the distribution name at
runtime — `django_service.__init__`'s `version()` lookup, `collectors/agent.py`'s
`DISTRIBUTION_NAME` (the key `distribution_version()` reads metadata by), and the
four tests that pin one of those. `pixi.lock`'s one `name:` entry for the
editable self-install followed from `pixi install`.

**The eight import lines.** All eight were executed, not read. They are the whole
reason this story is not cosmetic: they were `ModuleNotFoundError` from the
moment `CPM-RENAME-S01` merged, and the prose around them read as current.

**The Block If: the wheel's contents did not change.** Built before the rename
and after, unpacked both, compared. 189 files on each side and the path sets are
identical once the dist-info directory's own name is normalised; `WHEEL` is
byte-identical; `RECORD`'s path set is identical. Four files' *contents* differ,
and every one is the distribution's own name: `METADATA` (`Name:`, plus the
embedded README, which is the renamed prose), `RECORD` (hashes of the other
three), `django_service/__init__.py` (the `version()` key) and
`conda_sentinel/collectors/agent.py` (`DISTRIBUTION_NAME` and its comment).
Nothing was added to or dropped from the wheel, which is what the Block If is
about: selection is by `only-include`/`sources`, not by the distribution name.

**Prose re-read rather than substituted.** Five sites. In each case the sentence
was written under a state where the distribution and the import root were one
word or two, and this story makes them one again:

1. `pyproject.toml`, the `only-include` paragraph. It said the fallback misses
   "for two independent reasons": depth, *and* that the import root is not
   spelled like the distribution. The second reason is now gone — the
   underscored spelling of `conda-sentinel` **is** `conda_sentinel` — so the
   paragraph now says depth is the only reason left and that the margin is one
   directory level. Checked against the pinned hatchling
   (`builders/wheel.py::default_file_selection_options`) rather than assumed.
2. `pyproject.toml`, the near-miss warning under it. Its mechanism was already
   correct after `CPM-RENAME-S01`; what changed is that the near-miss stopped
   being hypothetical. Moving `conda_sentinel` up one level from
   `src/django_apps/` to `src/` now trips the second heuristic exactly, so the
   paragraph names that move.
3. `pyproject.toml`, the `_editable_impl_<distribution>.pth` sentence. It said
   the file is named for the distribution "not for any of the three import roots
   below" — a distinguishing clause that is now false, since the name coincides
   with one of them. It now names the actual file
   (`_editable_impl_conda_sentinel`), says the coincidence is arithmetic rather
   than causal, and gives the test: renaming `[project] name` alone moves the
   file and moves none of the three roots.
4. `component.toml`, the `adopted_apps` comment. It said "the import root is not
   the distribution: what pixi installs is still
   `conda-package-supply-chain-monitor`, and since `CPM-RENAME-S01` the two are
   different names". Both halves are now false. The distinction it was making is
   still the right one and is now *harder* to see, so it is stated positively:
   an entry is a subpackage of the import root, the editable install maps three
   roots, and only the third is the one these entries sit inside.
5. `README.md`. "one distribution package holding one pluggable Django
   application per business domain" was harmless while the distribution and the
   package were the same word and is an invitation to a false reading now that
   they are the same word *again* for a different reason. It now says "one
   top-level package", and says explicitly that it is not the distribution,
   which also ships `config` and `django_service`.

**`tests/unit/test_former_import_root.py` was corrected, not weakened.** Its
module docstring asserted that `[project] name` "is still the hyphenated
`conda-package-supply-chain-monitor`, and `CPM-RENAME-S02` owns it" — a sentence
this story falsifies. The constant `DISTRIBUTION_NAME` was renamed to
`NEAR_MISS_HYPHENATED_SPELLING` and keeps its value: that string is no longer the
distribution, but it is still the hyphenated spelling of the five forbidden
words and it still legitimately appears under `src/`, in
`collectors/agent.py`'s `PROJECT_URL`, which `CPM-RENAME-S04` owns. So the
separation case still has a live subject and is if anything sharper than before.
No assertion was removed or relaxed; the case count is unchanged (7505 as at
`CPM-RENAME-S01`).

**`sonar-project.properties` carried a path, not a package name.** `sonar.sources`
is `src` and needed nothing. The one reference the Code Map counted is the
layout comment above it, which named the former import root as a directory; that
is the line that changed. `sonar.projectKey`, `sonar.projectName` and the header
comment are the **repository's** Sonar identity (`millsks_<repo>`), and they are
deliberately left: changing the key orphans the project and its history and
breaks the README badges, and renaming the display name alone would put it out
of step with both. `CPM-RENAME-S04` renames the repository and these follow it.

**Left alone deliberately, and why.**

- Every GitHub URL — `mkdocs.yml`'s `repo_url`, the three README badges,
  `.github/**`, `pyproject.toml`'s commented git-cliff samples, and
  `collectors/agent.py`'s `PROJECT_URL`. These name the *repository*, which is
  `CPM-RENAME-S04` and is operator-run. A note beside `PROJECT_URL` now records
  that the distribution and the repository disagree on purpose until then.
- `src/config/observability/telemetry.py`'s `DEFAULT_SERVICE_NAME`, and the
  `OTEL_SERVICE_NAME` row in `docs/observability.md` that documents it. This is
  the only place the former name survives that is neither the repository nor a
  historical record, and it is the one judgement call in the story. Moving it
  would change an **emitted** value — every span's `service.name` — which the
  Never bullet forbids and which silently breaks any dashboard or alert keyed on
  the old one. The documentation row now says the default deliberately still
  carries the former name and why, so the surface is honest rather than merely
  stale. A story that wants the trace identity renamed should say so and own the
  migration note.
- `_bmad-output/` apart from this file, and the three planning-artifact
  directory names quoted in `docs/ux/ui-mockups.html`, which are real paths under
  it. `CPM-RENAME-S03`'s.

**Interpreted rather than followed literally.** The Scope list named eight files.
Six more were changed and one more was read and left:

- `pixi.toml`, `pixi.lock`, `src/django_service/__init__.py`,
  `src/django_apps/conda_sentinel/collectors/agent.py` and four test modules —
  all forced by `[project] name`. The `[pypi-dependencies]` key must equal the
  distribution or `pixi install` refuses; the two `version()` lookups are keyed
  by it and would silently report `0.0.0` rather than raise; the tests pin it.
  These are the "every place that name appears or is derived from" the Always
  bullet asks for, rather than an extension of scope.
- `mkdocs.yml`'s `site_name`, `README.md`'s title and lead sentence, and the
  three product-name strings in `docs/ux/ui-mockups.html` — AC 1 says the README
  and `docs/` name Conda-Sentinel, and a documentation site titled with the
  former name is the most operator-facing surface there is.
- `docs/development.md` line 160 quotes the `[pypi-dependencies]` entry
  verbatim; leaving it would have made a document that names a manifest line
  disagree with the manifest.
- `docs/observability.md` — see above.

**Runbook commands, all of them.** `docs/deployment.md` has four shell blocks and
five Python blocks. Every one was run or resolved: the eight imports, the
`load_component_declaration` block (which now reports `name: conda-sentinel`),
`pixi run manage migrate --database default --noinput` against a throwaway
sqlite, and the `run_policy` block as far as a broker-free process allows —
`run_policy.name` is `cpm.policy.run` and `.delay` is bound. The three deployed
process commands (`pixi run web` / `worker` / `beat`) are declared tasks and are
reconciled against `component.toml` by `tests/unit/test_process_model.py`; they
start long-running servers and were verified as declarations rather than run.
Every backticked repository path in the five changed documents was
existence-checked, and the two data paths the runbook says "ship inside the
wheel" were confirmed inside the built wheel at `conda_sentinel/collectors/data/`
and `conda_sentinel/policies/data/`.

**Two runbook commands this story did not cause, now warned about in place.**
Both were found while running every command the runbook gives, both predate the
rename, and both are recorded as `deferred:` entries.

1. **pixi's task shell strips inner single quotes.**
   `pixi run manage shell -c "print('hi')"` runs `print(hi)` and raises
   `NameError`, so `run_policy.delay('<your policy version>')` could not survive
   a copy-paste. A form that *does* survive was found by testing three:
   inverting the quotes — outer single, inner double — round-trips intact, while
   escaping the inner ones delivers literal backslashes and raises
   `SyntaxError`. The runbook block now uses the working form.
2. **`pixi run manage migrate --database default --noinput` (line 229) fails
   locally**, for the `COMPONENT_RUNTIME` reason corrected in the Debug Log above.

Both now carry an admonition beside the command rather than only a note here.
This story's own Intent is the reason: a runbook that reads as current while its
commands fail is worse than not renaming, and that argument does not stop applying
because the failure predates the rename. The operator meets the warning where
they would hit the failure.

**One emitted value did change, and it was forced.** `collectors/agent.py:78`
builds the outbound `User-Agent` from `DISTRIBUTION_NAME`, so the leading token
moved from the former name to `conda-sentinel` on the wire for GitHub, PyPI,
anaconda.org, OSV and KEV. It was not a choice: pixi validates the
`[pypi-dependencies]` key against the built metadata name, so the distribution
name and this string cannot disagree. But the runbook tells the operator those
sources ask for an identifying agent, and a source owner's allowlist keyed on the
old string is the exact analogue of the dashboard argument used to justify *not*
moving `OTEL_SERVICE_NAME`. So `docs/deployment.md` gained a section, "What every
collector calls itself on the wire", that shows the string, warns that it changed,
and reconciles the two decisions explicitly: one emitted identity was forced to
move and the cost lands on external allowlists a note can reach; the other was not
forced and deliberately did not move, because moving it would rewrite what every
dashboard is keyed on with no equivalent note. The `deferred:` entry for the
telemetry name records the sharper half — nothing pins the literal
(`tests/unit/test_telemetry.py:129,187` assert by reference), so a later sweep
would move it silently.

**The version lookup now has a parity guard.** `agent.py`'s comment already stated
the hazard — a spelling that drifts from `[project] name` "does not raise, it
reports `UNKNOWN_VERSION` on every request forever" — and nothing tested it. Every
existing assertion was tautological: `test_source_release.py`'s user-agent case
checks that `USER_AGENT` starts with `DISTRIBUTION_NAME` and contains
`distribution_version()`, both of which hold when the version is `"0.0.0"`.
`test_the_distribution_name_is_one_that_is_actually_installed` mirrors
`tests/unit/test_package_version.py`'s guard for the sibling lookup in
`django_service`: it calls `importlib.metadata.version(DISTRIBUTION_NAME)` once
*without* the catch, so a wrong name raises. Falsified by typing the constant to
`"conda-sentinal"` — the new case fails with
`PackageNotFoundError: No package metadata was found for conda-sentinal`, and the
pre-existing user-agent case still passes, which is the point.

**Three claims this story's own re-read got wrong, now corrected.** The class of
defect this story exists to prevent, caught by review rather than by the story:

- `tests/unit/test_former_import_root.py` said the hyphenated spelling survives
  only where it names the *repository*. `src/config/observability/telemetry.py`'s
  `DEFAULT_SERVICE_NAME` is a counter-example in the same tree, and
  `docs/observability.md` — changed in this same commit — says it deliberately
  carries the former *product* name. Two documents in one commit gave incompatible
  accounts, and the docstring is the one a later reader would trust before
  "fixing" telemetry and breaking every dashboard. The docstring, the
  `NEAR_MISS_HYPHENATED_SPELLING` comment and the separation case now name both
  survivors and say which is which.
- The same file said `_bmad-output/` is `CPM-RENAME-S03`'s "and which it decides
  to leave alone". `S03` *requires* the planning artifacts to name paths that
  exist; only the merged story files are left alone, which the file's own later
  paragraph gets right. Corrected.
- `agent.py`'s note said "the repository is still under its former name" and
  claimed a GitHub redirect. The repository is under its *current* name and has
  never been renamed — the former name is the *product's* — and no redirect exists
  yet because nothing has moved. Corrected to say the URL is live today and that
  the redirect is what covers published copies *after* `CPM-RENAME-S04`.

**`CPM-RENAME-S04` was amended, because it could not have owned the work this
story deferred to it.** Its stub and `epics.md` both said it "changes no tracked
file"; its "Not in scope" said the distribution name was `CPM-RENAME-S01`'s (it
never was — `S01`'s guard docstring recorded that `S02` owned it); and its three
acceptance criteria were `gh repo rename`, `git remote set-url` and
`pixi clean`/`mv`/`pixi install`. Nothing there touches a badge, a `repo_url`, a
Sonar key or an issue template, so as written the epic would have closed with the
former name on all of them and no story to pick them up. Both the stub and
`epics.md` now give `S04` a second half — tracked files that name the repository —
sequenced *after* the rename, because those URLs 404 until the repository has
moved; a fourth acceptance criterion covering it; and an explicit list of what it
must not sweep up, `DEFAULT_SERVICE_NAME` first.

**The `.github` prose that names the product was changed after all.** Four sites
name the *product* in prose rather than the repository in a URL:
`.github/ISSUE_TEMPLATE/bug_report.yml:2`, `feature_request.yml:2` and `:26`, and
`.github/CODEOWNERS:1`. The first three render in GitHub's issue forms, so they
are as operator-facing as the README; the "these name the repository" rationale
does not reach them, and a repository rename will never touch them. The URLs,
`sonar.projectKey`, `sonar.projectName` and the workflow clone paths in the same
tree are left, as before.

### File List

**Edited — packaging and manifests**
- `pyproject.toml` — `[project] name`; the `only-include` paragraph, the
  near-miss paragraph and the `_editable_impl` sentence re-read and rewritten.
- `pixi.toml` — `[workspace] name`, the `[pypi-dependencies]` key, and the
  `[pypi-options] no-build-isolation` entry.
- `pixi.lock` — the editable self-install's `name:`, regenerated by
  `pixi install`.
- `component.toml` — `[component] name`, and the `adopted_apps` comment re-read
  and rewritten.
- `sonar-project.properties` — the layout comment above `sonar.sources`.
- `mkdocs.yml` — `site_name`.

**Edited — source (`src/`), only where it names the distribution**
- `src/django_service/__init__.py` — the `version()` lookup key.
- `src/django_apps/conda_sentinel/collectors/agent.py` — `DISTRIBUTION_NAME`,
  plus a note on why it must equal `[project] name` literally and why
  `PROJECT_URL` disagrees with it until `CPM-RENAME-S04`.

**Edited — documentation**
- `docs/deployment.md` — the eight executable import lines and the three
  filesystem paths.
- `README.md` — title, lead sentence, the layout tree, and the "one distribution
  package" sentence.
- `docs/index.md`, `docs/technology-stack.md`, `docs/authentication.md` — the
  former import root in prose and paths.
- `docs/development.md` — the quoted `[pypi-dependencies]` entry.
- `docs/observability.md` — the `OTEL_SERVICE_NAME` row now records why its
  default still carries the former name.
- `docs/ux/ui-mockups.html` — the three product-name strings; the planning-artifact
  directory names it quotes are left alone.

**Edited — tests (values and prose only; no assertion removed or relaxed)**
- `tests/unit/test_former_import_root.py` — the docstring sentences this story
  falsified, and `DISTRIBUTION_NAME` renamed to `NEAR_MISS_HYPHENATED_SPELLING`
  with its value and every assertion intact.
- `tests/unit/test_package_version.py`, `tests/unit/test_dependency_policy.py`,
  `tests/unit/test_component_declaration.py` — the pinned distribution name.
- `tests/integration/test_image_payload.py` — the derived docker image tag.

**Edited — review round (2026-09-07)**

- `_bmad-output/implementation-artifacts/stories/cpm-rename-s04-repository-is-called-conda-sentinel.md`
  — a second, sequenced tracked-file half; a fourth acceptance criterion; the
  "Not in scope" correction (the distribution name was `S02`'s, not `S01`'s); and
  testing standards for both halves. `M1`.
- `_bmad-output/planning-artifacts/epics.md` — the same amendment to `S04`'s
  acceptance criteria and Constrained note, with the "changes no tracked file"
  claim withdrawn and dated; and `S02`'s AC 1 scoped to surfaces naming the
  *product*. `M1`, `S5`.
- `tests/unit/django_apps/test_source_release.py` —
  `test_the_distribution_name_is_one_that_is_actually_installed`, the parity guard
  for `agent.py`'s metadata key. `M3`.
- `docs/deployment.md` — an admonition beside the `migrate` command and beside the
  `run_policy` block, the `run_policy` block re-quoted into a form that survives
  a paste, and a new section "What every collector calls itself on the wire".
  `M4`, `M7`.
- `src/django_apps/conda_sentinel/collectors/agent.py` — the note corrected: the
  repository has never been renamed, and its URL is live rather than redirected.
  `M6`.
- `tests/unit/test_former_import_root.py` — the module docstring's account of
  `_bmad-output/` and of which hyphenated spellings survive under `src/`, the
  `NEAR_MISS_HYPHENATED_SPELLING` comment, and the separation case's docstring.
  `M6`.
- `pyproject.toml` — the `only-include` paragraph's depth claim reworded. `S4`.
- `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`,
  `.github/CODEOWNERS` — the four places that name the product in prose. `S1`.

## Auto Run Result

**Outcome:** done. The operator-facing half of the rename is finished, and the epic's own
sequencing defect was found and closed.

**Review loop:** one iteration, two layers — a blind hunter that never read the spec, and an
intent auditor. Both independently reproduced the Block If's wheel comparison. Seven must-fix,
five should-fix.

**The eight lines this story exists for.** Each was executed in a real Django process, fed from
a file so shell re-quoting could not alter what ran; all eight resolved, and the former spelling
through the same harness still raises `ModuleNotFoundError`. That is the difference between
changing text and verifying a command.

**The finding that mattered most was a planning defect, not a code one.** This story deferred
the Sonar identity, the README badges, the doc-site repository link, the issue templates and the
project URL to `CPM-RENAME-S04`. S04 could not own any of it: its stub and `epics.md` both said
it "changes no tracked file", and its three acceptance criteria are shell commands. The epic
would have closed with the former name on the badges and the Sonar project and no story left to
change them — a deferral to a story defined not to accept it. S04 now has two explicitly
sequenced halves, operator-run first and tracked-file second, because those URLs do not resolve
until the repository has actually moved, plus a fourth acceptance criterion and an enumerated
list of the surfaces it owns.

**An emitted value changed and the story said none did.** The outbound `User-Agent` is built
from the distribution name, so it moved on the wire for GitHub, PyPI, conda-forge, OSV and KEV,
and the runbook itself tells the operator those sources ask for an identifying agent. The change
was forced — pixi validates the dependency key against the built metadata name — so it is
correct, but a source owner's allowlist keyed on the old string is the exact analogue of the
dashboard argument used to justify *not* moving the telemetry service name. The runbook now
carries an operator note reconciling the two: one emitted identity was forced to move, the other
was not and deliberately did not.

**A guard that documented its own hazard without closing it.** The comment beside the collector's
version lookup states that a name drifting from `[project] name` "does not raise — it reports
`UNKNOWN_VERSION` on every request forever". Every test around it was tautological: they assert
the agent string starts with the distribution name and contains the version, both of which hold
when the version is zeros. The sibling lookup was guarded properly all along. A parity guard now
mirrors it, and was falsified: with the constant misspelled the new case fails with
`PackageNotFoundError` while the pre-existing user-agent case still passes — which is precisely
the gap.

**Three false claims introduced by this story's own re-reading**, the class it was written to
prevent. The guard's docstring said the hyphenated spelling survives only where it names the
repository, while `docs/observability.md` — added in the same change — said the telemetry
service name deliberately keeps the former *product* name. Whoever ran S04 would have trusted
the docstring, "fixed" telemetry, and silently broken every dashboard keyed on the old service
name. All three corrected, and S04 now carries a "not to be swept up" list headed by that
constant.

**Two runbook commands failed on copy-paste, and one turned out to be fixable.** The task shell
strips inner single quotes, so the documented call could not survive a paste; outer single with
inner double quotes does, and the runbook now uses that form. Escaped inner quotes raise a
syntax error and were ruled out rather than assumed. The other command carries a warning beside
it with two verified working forms.

**A worse defect found while investigating that.** The recorded cause of the failing command was
wrong. The real one is that a deliberate fail-closed startup refusal is caught by the
OpenTelemetry Django instrumentor, logged at debug level, and converted into a silent fail-open
with no settings module and no applications loaded. Recorded at `severity: high`, independently
of this epic.

**Four `deferred:` entries added.** The story previously recorded its deferrals in prose only, in
a file about to become a historical record nobody sweeps. The ledger this project already uses
is swept.

**Verification (run directly, not only reported):** `pixi run ci` exit 0 — 7506 passed, 2
skipped, coverage 99.17%. `makemigrations --check --dry-run` reports no changes.
`pixi run docs` builds clean under `--strict`. Against `postgres:17` the suite passed 7506 with
zero failures; the task's exit 3 is the known coverage-combine artefact, confirmed by the three
recorded checks — no failed or errored tests, the exact `no such table: context` signature, and
a zero-byte `.coverage.*` file timestamped at the run's end.
