---
title: 'CPM-PLATFORM-S01: A second import root for domain applications'
type: 'feature'
created: '2026-09-03'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
warnings: ['oversized']
deferred:
  - summary: >-
      Nothing exercises a newly added application resolving without a reinstall; the
      future-app promise is gated only against the built wheel.
    evidence: |-
      The derived assertion in tests/integration/test_import_resolution.py demands the wheel
      carry any package added under conda_package_supply_chain_monitor, but only once someone
      adds it. The import half of the matrix row was checked with a throwaway `billing`
      package that was not kept, so it is not re-runnable by `pixi run ci`.
    location: >-
      tests/integration/test_import_resolution.py
    severity: medium
  - summary: >-
      No test ties the hatchling version bound to the invariants that depend on it.
    evidence: |-
      dev-mode-exact, the sort-then-first-prefix matching rule, and the `"" = wheel root`
      semantics are all load-bearing and all pinned only by `hatchling >=1.27,<2` in
      pixi.toml. The check that would catch a behavioural regression is integration-marked,
      so `pixi run test` cannot see it.
    location: >-
      pixi.toml
    severity: medium
  - summary: >-
      The wheel-layout expectation is derived from the tree rather than pinning the absolute
      set of three top-level names.
    evidence: |-
      A tree reorganisation that moved applications out of conda_package_supply_chain_monitor
      and directly into django_apps would move the expectation with it and still pass. The
      anti-vacuity guard prevents an empty comparison but not a moving one.
    location: >-
      tests/integration/test_import_resolution.py
    severity: low
  - summary: >-
      Path assertions compare unresolved __file__ against a resolved repository root.
    evidence: |-
      Under a symlinked checkout (macOS /tmp, git worktrees) is_relative_to can return False
      for a path that is genuinely inside the tree, producing a false failure.
    location: >-
      tests/unit/django_apps/test_core_app.py
    severity: low
baseline_revision: '0895bb09521fd97b68ee1e369e97d7443b8dafbf'
---

<intent-contract>

## Intent

**Problem:** `src/django_apps/` does not exist, so no domain application has a home. The story
as written says to add `src/django_apps` to the `[tool.hatch.build.targets.wheel] sources`
array; that is a proven no-op — hatchling sorts `sources` alphabetically ascending
(`hatchling/builders/config.py:650`) and returns on the first prefix match
(`:740-749`), so `"src"` always shadows `"src/django_apps"` and apps would still import as
`django_apps.core`.

**Approach:** Replace the `sources` array with a three-entry mapping that enumerates the
subtrees instead of their parent, so no key is a prefix of another. `config` and
`django_service` keep their names; everything under `src/django_apps/` flattens to the root,
making `src/django_apps` a genuine second path root. Domain applications live under one
distribution package inside that root, `conda_package_supply_chain_monitor`, so they share a
single stable top-level name. Then create the first app, `core`, and adopt it explicitly.

## Boundaries & Constraints

**Always:** The import root is declared in exactly one place — the wheel table. The editable
`.pth` and the built wheel are both generated from it. `src/django_apps/` has **no**
`__init__.py`: it is a path root, not a package, and never appears in an import statement.
`src/django_apps/conda_package_supply_chain_monitor/` **is** a package and does have one; every
domain application is a subpackage of it. Adding a future app requires no edit to
`pyproject.toml`. Refusals raise
`ImproperlyConfigured`. `pixi` is the only runner. `pixi run ci` must exit 0.

**Block If:** Making `core` importable requires any second runtime declaration (a `.pth`, a
`sys.path` insert, `PYTHONPATH`, pytest `pythonpath`, or `--app-dir`) — all are banned by
`tests/unit/test_import_roots.py` and none is authorised here. Also block if flattening
proves to require one `sources` entry per app.

**Never:** No `sys.path` mutation anywhere. No per-app enumeration in `pyproject.toml`. No
`packages = [...]` key. No `ready()` override calling `run_stage_two()` — `users` is the sole
stage-two owner. No `# pragma: no cover`. No coverage `omit` entry for the new package. No
`pytest.skip`/`xfail`. `conda_package_supply_chain_monitor.core` must not precede
`django_service.users` in `LOCAL_APPS`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| App import | `import conda_package_supply_chain_monitor.core` under the editable install | Resolves from `src/django_apps/conda_package_supply_chain_monitor/core/` | No error expected |
| Root is not a package | `import django_apps` | `ModuleNotFoundError` — the root never appears in an import path | Expected failure, asserted |
| Built wheel layout | `hatchling build -t wheel` | Top level is `config`, `django_service`, `conda_package_supply_chain_monitor` | No error expected |
| Platform names preserved | `import config.asgi`, `import django_service` | Resolve unchanged from `src/` | No error expected |
| Future app, no config edit | a new dir `src/django_apps/conda_package_supply_chain_monitor/billing/` | Ships and imports as `conda_package_supply_chain_monitor.billing` with no `pyproject.toml` change | No error expected |
| App registry | `django.setup()` | `conda_package_supply_chain_monitor.core` present in `INSTALLED_APPS` after `django_service.users` | `ImproperlyConfigured` if misordered |

</intent-contract>

## Code Map

- `pyproject.toml:192-194` -- THE import-root declaration. `only-include = ["src"]`,
  `sources = ["src"]`. Becomes a `[tool.hatch.build.targets.wheel.sources]` mapping.
- `pyproject.toml:165-191` -- comment block that documents the old design. Lines 169-172
  ("an app added later needs no edit here") and 182-191 (the Epic 9 `sources`-addition plan)
  are both stale and contradict each other. Rewrite.
- `pyproject.toml:125` -- `lint.isort.known-first-party = ["config","django_service","tests"]`.
  Add `"conda_package_supply_chain_monitor"` -- one entry covers every present and future app,
  so no ruff `src` change is needed.
- `tests/unit/test_import_roots.py:449-454` -- asserts `"src" in wheel["sources"]`. Must
  accept the mapping form and pin the three keys.
- `tests/unit/test_import_roots.py:472-484` -- `FORMERLY_ENUMERATED` forbids a `sources`
  entry named `config` or `django_service`. That guard was written against
  `packages = [...]` per-package enumeration; the new mapping enumerates *subtrees*, and
  apps still need no entry. Update the guard, keep `"packages" not in wheel`.
- `tests/integration/test_import_resolution.py:474-509` -- builds a real wheel; `expected` is
  derived from `src/`'s subdirectories at `:507`. Must become "platform packages plus the
  packages inside `src/django_apps`".
- `src/config/settings/base.py:188-191` -- `LOCAL_APPS`. Nothing consumes `adopted_apps` yet
  (composition is the platform's unbuilt Epic 9), so the app is installed here, appended.
- `tests/unit/startup/test_installed_apps_ordering.py:68-105` -- `LOCAL_APPS` must be the
  trailing segment and the stage-two owner must be first. Appending satisfies both.
- `component.toml:62` -- `adopted_apps = []`, the declaration half of adoption.
- `tests/unit/test_component_declaration.py:280`, `:500` -- assert `adopted_apps` is `[]`/`()`.
  Both fail on adoption and must move to `["core"]`/`("core",)`.
- `src/django_service/users/apps.py:1-27` -- the AppConfig pattern to imitate, minus `ready()`.
- `tests/unit/startup/test_installed_apps_ordering.py` -- the audit-test shape to imitate:
  anti-vacuity guard first, then one assertion per invariant.

## Tasks & Acceptance

**Execution:**
- `pyproject.toml` -- replace `sources = ["src"]` with a `[tool.hatch.build.targets.wheel.sources]`
  mapping of `"src/config" = "config"`, `"src/django_apps" = ""`, `"src/django_service" = "django_service"`;
  keep `only-include = ["src"]` -- no key is a prefix of another, so nothing is shadowed.
- `pyproject.toml` -- rewrite the stale comment block to record the shadowing finding and why
  subtree enumeration is not the per-package enumeration it replaced.
- `pyproject.toml` -- add `"conda_package_supply_chain_monitor"` to
  `lint.isort.known-first-party` -- one entry covers every present and future app.
- `src/django_apps/conda_package_supply_chain_monitor/__init__.py` -- create empty; **no**
  `__init__.py` at `src/django_apps/`, which is a path root rather than a package.
- `src/django_apps/conda_package_supply_chain_monitor/core/__init__.py` -- create empty.
- `src/django_apps/conda_package_supply_chain_monitor/core/apps.py` -- `CoreConfig(AppConfig)`
  with `name = "conda_package_supply_chain_monitor.core"`, `verbose_name = _("Core")`; no
  `ready()`. The derived label is `core`.
- `src/django_apps/conda_package_supply_chain_monitor/core/migrations/__init__.py` -- create empty.
- `src/config/settings/base.py` -- append `"conda_package_supply_chain_monitor.core"` to
  `LOCAL_APPS` after `"django_service.users"`.
- `component.toml` -- set `adopted_apps = ["conda_package_supply_chain_monitor.core"]`, the
  declaration half of AD-8 adoption.
- `tests/unit/test_component_declaration.py` -- update `:280` and `:500` to the adopted state.
- `tests/unit/test_import_roots.py` -- accept the mapping form; assert the mapping has exactly
  three keys and that none is a prefix of another, which is the cardinality check the module
  currently lacks; keep every absence-of-alternative-mechanism assertion untouched.
- `tests/integration/test_import_resolution.py` -- derive `expected` as the platform packages
  plus the packages inside `src/django_apps`; add a probe that
  `import conda_package_supply_chain_monitor.core` resolves and that `import django_apps` raises
  `ModuleNotFoundError`.
- `tests/unit/django_apps/test_core_app.py` -- new; unit-test the I/O matrix rows that need no
  wheel build: app import, root-is-not-a-package, registry membership and ordering.
- `docs/index.md`, `docs/technology-stack.md` -- update the layout tree and the
  one-declaration-site prose to describe two roots from one declaration.

**Acceptance Criteria:**
- Given the editable install, when `import conda_package_supply_chain_monitor.core` runs, then it
  resolves from `src/django_apps/conda_package_supply_chain_monitor/core/` and `import django_apps`
  raises `ModuleNotFoundError`.
- Given a wheel built from the repository, when its top-level entries are listed, then they are
  exactly `config`, `django_service` and `conda_package_supply_chain_monitor`, and no entry is
  `django_apps`.
- Given the import root, when the repository is audited, then it is declared only in the wheel
  table, a test pins that the mapping has exactly three keys and no key shadows another, and
  every existing prohibition on alternative path mechanisms still passes.
- Given a new application package added under `src/django_apps/conda_package_supply_chain_monitor/`,
  when the wheel is built, then it ships inside that package with no change to `pyproject.toml`.
- Given `django.setup()`, when `INSTALLED_APPS` is read, then
  `conda_package_supply_chain_monitor.core` appears within `LOCAL_APPS` and after
  `django_service.users`.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage at or above 90%.

## Traceability

- **Epic:** `CPM-EP-PLATFORM` — the service platform.
- **Governed by:** `CPM-AD-19` (one app per domain, routed centrally), inherited `AD-8`
  (adoption is explicit and two-line; entry-point discovery forbidden) and `AD-28`
  (process types and release-stage migration steps declared in `component.toml`).
- **Closes risk:** `R-14` (OPS) from the TEA test design, at the `AUDIT` level.
- [Source: ../../planning-artifacts/epics.md#CPM-PLATFORM-S01]
- [Source: ../../planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-19]
- [Source: ../../test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Spec Change Log

- **2026-09-03 — planning.** The story's AC #1 named a mechanism that does not work. Verified
  against hatchling `>=1.27,<2`: `sources` is sorted ascending and matched first-prefix-wins, so
  `"src"` shadows `"src/django_apps"`. Confirmed empirically by building a throwaway wheel — the
  subtree mapping ships `core/` and `billing/` at top level and generates a `.pth` carrying both
  `src` and `src/django_apps`. The AC's outcome is preserved; only the mechanism changed.
  **KEEP:** the "declared in exactly one place" requirement — the mapping satisfies it, and the
  cardinality test the module currently lacks is what pins it.
- **2026-09-03 — planning.** `epics.md:107-109` and `pyproject.toml:182-191` both state that
  `django_apps` must be added to the `sources` array. Both are wrong for the same reason and
  should be corrected once this lands.
- **2026-09-03 — planning.** Story AC #2 asks for two-line adoption, "a `pixi.toml` dependency
  plus an `adopted_apps` entry". The first line does not apply to an in-repo app: it is already
  covered by the editable self-install at `pixi.toml:160-161`. The `component.toml` entry is
  made; the pixi half is satisfied by construction, not skipped.

- **2026-09-03 — direction change.** Domain applications are nested under one distribution
  package, `conda_package_supply_chain_monitor`, inside the root rather than sitting directly in
  it. The wheel mapping is unchanged and re-verified against a built wheel. This *simplifies* the
  tooling: all apps share one first-party name, so `known-first-party` takes a single entry and
  ruff needs no `src` change. An implementation pass against the previous flat layout was stopped
  and its tracked edits reverted; the app files were moved into the new layout rather than
  discarded.

- **2026-09-03 — implementation.** The subtree mapping alone does not satisfy AC #1's second
  clause. It is correct about the wheel — top level is exactly `config`, `django_service`,
  `conda_package_supply_chain_monitor`, with no `django_apps` — but hatchling's *default*
  editable mode writes the roots into the generated `.pth` as plain directories, so
  `<repo>/src` lands on `sys.path` and `django_apps` resolves as an implicit namespace package
  despite carrying no `__init__.py`. Measured, not reasoned:
  `import django_apps.conda_package_supply_chain_monitor.core` worked, giving every application
  a second silently-working spelling — the "never appears in an import statement" invariant
  broken in the editable install only, where no build check can see it.
  **Resolution:** `dev-mode-exact = true`, added to the same
  `[tool.hatch.build.targets.wheel]` table. It makes the editable install a redirecting finder
  over exactly the three top-level names, so `src` is never on `sys.path` and
  `import django_apps` raises `ModuleNotFoundError` as the AC requires. This is one more key in
  the one declaration site, not a second declaration: no `.pth` written by hand, no `sys.path`
  insert, no `PYTHONPATH`, no pytest `pythonpath`, no `--app-dir`. Cost, recorded in the
  `pyproject.toml` comment: a brand-new *top-level* package needs a `pixi install` before it
  resolves; a new application inside `conda_package_supply_chain_monitor/` — the graduation case
  — needs nothing, verified by adding and importing a throwaway `billing` package.
  `tests/unit/test_import_roots.py` now pins the key, and both the unit and integration suites
  assert the behaviour it produces.

- **2026-09-03 — review.** The delivered `core` is thinner than the original AC #2's "following
  the `django_service/users/` layout": it ships `apps.py`, two `__init__.py` files and an empty
  `migrations/` package, with no `models.py`, `urls.py`, `admin.py` or views. That is deliberate
  — the story's purpose is the import root, and `tests/unit/test_payload_properties.py`
  explicitly tolerates an app shipping no `models` module. Recorded because every other
  deviation from the original ACs is logged here and this one was not.

## Review Triage Log

### 2026-09-03 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 22: (high 0, medium 10, low 12)
- defer: 4: (high 0, medium 2, low 2)
- reject: 6: (high 0, medium 0, low 6)
- addressed_findings:
  - `[medium]` `[patch]` `adopted_apps` became non-empty for the first time while
    `test_installed_apps_ordering.py` still asserted only its pre-`component.toml` backstop —
    added the index comparison its own docstring promised, so every declared adopted app must be
    installed and ordered after the stage-two owner.
  - `[medium]` `[patch]` `test_the_import_root_is_not_a_package` could pass vacuously from a
    cached `sys.modules` entry — the guard on the story's central requirement now pops the module
    and invalidates caches first.
  - `[medium]` `[patch]` The `import django_apps` probe asserted only non-zero exit; it now
    asserts the stderr names the module, so a broken environment cannot read as a pass.
  - `[medium]` `[patch]` `core/apps.py` pointed readers at a stage-two-ownership guard that does
    not exist anywhere in the suite.
  - `[medium]` `[patch]` Three sites still described the editable install as putting roots on
    `sys.path`; `dev-mode-exact` installs a redirecting finder and `<repo>/src` never appears —
    `component.toml`, `docs/index.md` and a test docstring corrected.
  - `[medium]` `[patch]` The `only-include` rationale rested on there being no package named
    after the project; this change creates exactly that package.
  - `[medium]` `[patch]` `epics.md` still prescribed the `sources`-array mechanism this story
    proved a silent no-op.
  - `[medium]` `[patch]` `README.md` showed applications directly under `django_apps/`, called it
    a third top-level package, and claimed none of the directories existed.
  - `[medium]` `[patch]` The spec rewrite had dropped the epic link, governing decisions, risk
    and source references; restored as a Traceability section plus frontmatter `context`.
  - `[low]` `[patch]` Nine further fixes: tautological cardinality assertion and its misleading
    name, missing `isinstance` and `iterdir` guards, unnormalized `sources` keys, package-less
    directory derivation, `APPLICATION_MEMBER_DEPTH` off-by-one wording, a unit module whose
    docstring disclaimed the filesystem it touches, the untested present-but-empty
    `adopted_apps` state, the `django_apps.example` fixture spelling, `docs/index.md`
    understating adoption cost, and a stale `sonar-project.properties` comment.

## Design Notes

The prefix collision exists only because `"src"` is itself a source key. Enumerating the three
subtrees removes the collision without reintroducing per-package enumeration: apps live under
one key and still need no entry of their own.

```toml
[tool.hatch.build.targets.wheel.sources]
"src/config" = "config"
"src/django_apps" = ""
"src/django_service" = "django_service"
```

Verified output — wheel top level `['conda_package_supply_chain_monitor', 'config',
'django_service']`, with `core/` and a second app `billing/` inside that package; editable `.pth`
lines `<repo>/src` and `<repo>/src/django_apps`.

`adopted_apps` is a declaration only. Nothing consumes it into `INSTALLED_APPS` — that
composition step is the platform's Epic 9 and is unbuilt — so the app is installed via
`LOCAL_APPS` as well. Both are written because the declaration is the AD-8 contract and the
settings entry is what actually installs it today.

## Verification

**Commands:**
- `pixi run ci` -- expected: exits 0; precommit, build, typecheck, lint and coverage >= 90% all pass.
- `pixi run python -c "import conda_package_supply_chain_monitor.core as c, config.asgi, django_service; print(c.__file__)"`
  -- expected: resolves under `src/django_apps/conda_package_supply_chain_monitor/core/`.
- `pixi run python -c "import django_apps"` -- expected: `ModuleNotFoundError`.
- `pixi run test-integration -- -k import_resolution` -- expected: the wheel-layout assertion passes.

## Auto Run Result

Status: done

### What was implemented

`src/django_apps/` is a second import root: a path root with no `__init__.py`, never appearing
in an import statement. Domain applications live under one distribution package inside it,
`conda_package_supply_chain_monitor`, so `conda_package_supply_chain_monitor.core` resolves
while `import django_apps` raises `ModuleNotFoundError`.

The story's stated mechanism — appending `src/django_apps` to the `sources` array — was proven
a silent no-op before any code was written: hatchling sorts `sources` ascending
(`hatchling/builders/config.py:650`) and returns on the first prefix match (`:740-749`), so
`"src"` always shadows `"src/django_apps"`. The declaration is a three-key mapping of the
subtrees instead, where no key prefixes another, plus `dev-mode-exact` so the editable install
is a redirecting finder rather than directories on `sys.path`. Both live in the one wheel table.

### Files changed

- `pyproject.toml` — the `sources` mapping, `dev-mode-exact`, `known-first-party`, and the
  comment block that documented the disproven plan.
- `src/django_apps/conda_package_supply_chain_monitor/{__init__.py,core/*}` — the first app.
- `src/config/settings/base.py` — `core` appended to `LOCAL_APPS` after the stage-two owner.
- `component.toml` — `adopted_apps` carries its first entry.
- `tests/unit/test_import_roots.py` — mapping equality, cardinality, no-shadowing,
  key-normalisation and `dev-mode-exact` pinned.
- `tests/unit/test_component_declaration.py` — adopted state, present-but-empty case, fixture
  respelled off the import root.
- `tests/unit/startup/test_installed_apps_ordering.py` — the roster index comparison.
- `tests/unit/django_apps/test_core_app.py` — new.
- `tests/integration/test_import_resolution.py` — wheel layout, shipped applications, and two
  subprocess probes.
- `README.md`, `docs/index.md`, `docs/technology-stack.md`, `sonar-project.properties`,
  `_bmad-output/planning-artifacts/epics.md` — corrected to the delivered mechanism.

### Review findings

22 patched, 4 deferred, 6 rejected, 0 intent gaps, 0 spec repairs. Patched by severity:
high 0, medium 10, low 12. Score `3x10 + 1x12 = 42`, at or above 5, so
`followup_review_recommended: true`.

### Verification

- `pixi run ci` exits 0 — 1564 passed, coverage 97.05%.
- `import conda_package_supply_chain_monitor.core` resolves under
  `src/django_apps/conda_package_supply_chain_monitor/core/`; `import django_apps` raises
  `ModuleNotFoundError`. Both also asserted in clean subprocesses with `PYTHONPATH` cleared and
  `PYTHONSAFEPATH=1`.
- Built wheel top level is exactly `config`, `django_service`,
  `conda_package_supply_chain_monitor`.
- Every row of the I/O matrix is covered by a test that ran in the gate.

### Residual risks

- `dev-mode-exact` changes how every developer's editable install resolves. A new *top-level*
  package now needs a `pixi install` before it resolves; an application inside
  `conda_package_supply_chain_monitor/` needs nothing. CI runners regenerate the finder on their
  own install, so the first CI run is the real check.
- `only-include` is load-bearing in a way worth knowing: removing it fails the build outright,
  because hatchling's fallback glob reaches only one level and the package sits two deep. The
  near-miss is that moving the package up to `src/conda_package_supply_chain_monitor/` would let
  that glob match and silently reinstate the shadowing the mapping exists to remove.
- Four deferred findings are recorded in frontmatter, the sharpest being that no test ties the
  `hatchling >=1.27,<2` bound to the behaviours the design rests on.
