---
title: 'CPM-CURRENCY-S03: Feedstock evidence'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '6706828353e6aeb588a70bd6473960773ca04ad9'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s01-upstream-release-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s02-pypi-release-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s05-collector-base-carrying-external-call.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s02-resolution-records-where-came-from.md
warnings:
  - oversized
deferred:
  - summary: >-
      The declared allowance is GitHub's search allowance and is not a rate that sweeps
      `CPM-NFR-1`'s ten thousand packages; nothing has measured it against a real sweep.
    evidence: |-
      `FEEDSTOCK_RATE_LIMIT` is `RateLimit(calls=10, per=1 minute)` -- GitHub's documented
      unauthenticated ceiling for `/search/issues`, which the absent branch reads. The base
      charges one allowance per collection before it knows which branch a package will take,
      so a single number has to cover both branches and the tighter of the two is the only
      one that cannot be exceeded by accident. At `1 + retries` per collection that is two
      packages a minute -- roughly three and a half days to observe ten thousand once, which
      does not fit a weekly cadence with any margin. Raising it means authenticating, which
      needs a credential, a setting to carry it and a declared header; none of the three is
      this story's. `CPM-CURRENCY-S05` is where the arithmetic is measured against a sweep.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- FEEDSTOCK_RATE_LIMIT
    severity: medium
  - summary: >-
      Each branch's bounded second call is not charged against the local allowance, so every
      collection spends more of the remote budget than the counter believes.
    evidence: |-
      The base charges `1 + retries` once, before the first call. `_recipe_instead` and
      `_conventional_instead` are issued from `translate`, after that charge, exactly as
      `collectors/source_release.py`'s `_tagged_instead` is -- and unlike that one, this
      collector reaches a second call on *both* branches rather than on one, so the
      undercount is every collection rather than the tail of them. Charging it would mean
      reaching past the base's orchestration into the limiter, and the arithmetic belongs
      with the story that first sweeps at volume (`CPM-CURRENCY-S05`).
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- _recipe_instead
    severity: medium
  - summary: >-
      Only `recipe/meta.yaml` is read, so a feedstock on conda-forge's v1 `recipe/recipe.yaml`
      layout records as present with an unreadable recipe version.
    evidence: |-
      `RECIPE_PATH` names `HEAD/recipe/meta.yaml`, which is where every conda-forge feedstock
      has kept its recipe until now. conda-forge is migrating to a v1 recipe format at
      `recipe/recipe.yaml` with a different schema, and a feedstock that has moved answers
      `404` here -- which this collector records as `ok` (the feedstock exists, which the
      repository established) with `recipe_version` blank and `detail` naming the locator.
      That is the honest row rather than a wrong one, but the version is a fact `CPM-FR-16`
      will want; reading the second layout is a second document reader and belongs with the
      story that needs the comparison.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- RECIPE_PATH
    severity: low
  - summary: >-
      The recipe is read from a second host whose limits this product's counter does not see.
    evidence: |-
      `recipe_locator` reads `raw.githubusercontent.com`, chosen over the API's contents
      endpoint because that one returns the file base64-encoded inside a JSON envelope. The
      raw host has rate limits of its own, unrelated to the API allowance
      `FEEDSTOCK_RATE_LIMIT` declares, and a refusal from it arrives as an ordinary transport
      failure -- so it becomes "the recipe could not be read" in `detail` rather than
      anything a reader could tell from an exhausted quota. The same blindness the upstream
      collector has to GitHub's `403`, on a second host.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- recipe_locator
    severity: low
  - summary: >-
      A package whose feedstock mapping is unresolved produces a `failed` ledger row rather
      than any observation, and no resolver populates feedstock mappings yet.
    evidence: |-
      `FeedstockCollector.source_for` raises `FeedstockLocatorError` for a mapping that is
      `unknown` or `error`, or absent, on the terms `CPM-CURRENCY-S02` set and because
      `CPM-UJ-2` says absence of a feedstock cannot be claimed for a package whose identity is
      unresolved. Today no resolver writes `feedstock` mappings or `Feedstock` rows, so a
      sweep that offered every package to this collector would fail every run. The selection
      that offers only askable packages is `CPM-CURRENCY-S05`'s, as it is for the two release
      collectors.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- FeedstockLocatorError
    severity: medium
  - summary: >-
      A staged-recipes match is decided from the pull request's title alone, so a title that
      does not name the package in a token is missed and a neighbouring one can make the
      answer ambiguous.
    evidence: |-
      `staged_recipe` cuts each title on the characters a package name cannot contain and
      matches a token that normalises to exactly the package's name. That is what keeps `Add
      numpy-quaternion` from reading as a recipe for `numpy`, and it is still a heuristic over
      free text: a pull request titled "new recipe for the numerical library" is not matched,
      and two open requests that both name the package are refused rather than picked. Reading
      the pull request's changed paths would answer exactly -- `recipes/<name>/meta.yaml` --
      and costs a call per candidate, which is not affordable inside the declared allowance.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- staged_recipe
    severity: low
  - summary: >-
      `core/transport.py` transfers and decodes a whole response body before any collector's
      size ceiling is measured, so no ceiling in this product bounds the transfer.
    evidence: |-
      Every collector declares a `MAX_DOCUMENT_CHARACTERS` and each of them bounds only the
      parse: by the time a body reaches a collector the transport has already transferred it
      and decoded it to a string, so a source that streams a very large body spends the
      worker's memory before the refusal is reached. What the ceilings do buy is real -- they
      refuse to spend a soft time limit parsing what no honest source serves -- but the prose
      in three collectors said "memory" and only `CPM-CURRENCY-S02`'s had been corrected; this
      story corrects its own. A real bound needs a streamed read with a byte cap in the
      transport, which is `core`'s and affects all four collectors rather than this one.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/transport.py -- RequestsTransport.fetch
    severity: medium
  - summary: >-
      A feedstock repository that has been renamed answers `301`, which the transport refuses
      rather than follows, so an existing feedstock is recorded absent.
    evidence: |-
      `FOLLOW_REDIRECTS` is `False` in `core/transport.py`, deliberately -- a followed
      redirect is a source choosing what this product reads. GitHub answers `301` for a
      renamed repository, which is exactly the case where following one would be safe and
      informative: conda-forge renames feedstocks when a package is renamed upstream, and the
      old locator keeps pointing at the new repository for ever. Today that arrives here as a
      transport failure or a `not_found`, and the row records "absent" for a feedstock that
      exists under another name. Resolving it means either a status-specific path in the
      transport or a `Location`-aware retry, both of which are `core` changes affecting every
      collector.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- _conventional_instead
    severity: low
  - summary: >-
      The branch a collection took is remembered on the collector instance, so two concurrent
      collections through one instance could read each other's branch.
    evidence: |-
      `_branch`, `_asked`, `_repository` and `_locator` are instance attributes written by
      `source_for` and read by `translate` and `sentinel_evidence`, on the terms
      `CPM-CURRENCY-S01` and `CPM-CURRENCY-S02` set for `_locator` and the remembered
      identity. Unreachable through the task, which builds a collector per call, and through
      every case, which collects once per instance; it becomes reachable the day something
      reuses one instance across threads -- and this collector has more to lose than its
      siblings, because a crossed branch would make a row claim the wrong *question* was
      answered rather than only the wrong locator. Passing the branch through `translate`'s
      arguments would need a base signature change.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- FeedstockCollector
    severity: low
---

# CPM-CURRENCY-S03: Feedstock evidence

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

<intent-contract>

## Story

As a packaging engineer,
I want feedstock existence, recipe version and recipe activity recorded,
so that I can see whether conda-forge has caught up and whether anyone is maintaining it.

## Acceptance Criteria

1. **Given** a package
   **When** the feedstock collector runs
   **Then** it records feedstock existence, recipe version, recipe metadata and recent recipe activity
   **And** absence of a feedstock is an observation with a timestamp, not a null

2. **Given** a package with a staged recipe but no feedstock
   **When** the collector runs
   **Then** staged-recipe state is recorded separately from an existing feedstock

## Intent

**Problem:** `CPM-FR-9` needs the third surface collector -- conda-forge. Nothing observes
whether a package has a feedstock, what version its recipe pins, or whether anyone has touched
it. `CPM-FR-40` (`CPM-CURRENCY-S07`) and `CPM-UJ-2`'s feedstock-gap report both read evidence
that does not exist yet, and PRD Open Question 10 leaves "what counts as recipe activity"
to this epic to answer.

**Approach:** Add `FeedstockCollector` on the base's per-package path, writing
`feedstock_snapshots` (PRD Appendix A.2), with the question it asks chosen from what
resolution recorded about the package's feedstock mapping (`CPM-IDENTITY-S02`). A package
resolution gave a feedstock is asked about that feedstock; a package resolution gave none is
asked about the staged-recipes queue and has the conventional feedstock confirmed absent. Both
branches take at most two calls, and the branch is decided before either is made.

## Boundaries & Constraints

**Always:**
- Every evidence row is written by the base through `_write_evidence` (`CPM-AD-7`); the
  collector never saves a row and never opens a transaction.
- Existence is a `state` column over `OutcomeState`, emitted verbatim (`CPM-AD-5`,
  `CPM-AD-24`). Never a boolean, never a `*_status`/`*_outcome` name.
- Absence is a written row carrying this run's `observed_at`, never a missing row (AC 1).
- Staged-recipe state lives in its own column and can never be recorded on a row that found a
  feedstock (AC 2). The database enforces that, not a convention.
- Which feedstock is asked about is read from identity and never guessed *when resolution
  established one*. Where resolution established none, the conventional conda-forge name is
  derived from `canonical_name` and the row records the locator it actually asked.
- Time comes from the injected clock; every row carries the run's instant.
- All I/O goes through the base's transport seam; nothing is fetched from
  `sentinel_evidence`.
- `pixi` is the only runner; `pixi run ci` exits 0 at the end.

**Block If:**
- Recording the recipe version would require executing or rendering Jinja. This story reads
  the `{% set version = "..." %}` assignment conda-forge's own recipes use, falls back to a
  literal `version:` under `package:`, and records the recipe as present with an unreadable
  version otherwise. If review finds that reading indefensible, HALT.

**Never:**
- No authentication, credential or settings key for GitHub.
- No schedule, no `CELERY_BEAT_SCHEDULE` entry, no per-task time limit.
- No version comparison or normalisation -- `CPM-FR-16` is a policy pass (`CPM-AD-8`).
- No maintenance *verdict*: "unmaintained" is `CPM-FR-40`'s policy with a versioned
  threshold (`CPM-CURRENCY-S07`). This story records the activity instant and nothing else.
- No build or test outputs. PRD Appendix A.2 lists them on this table; they are
  `CPM-EP-PY314`'s and no column for them is added here.
- No change to `core/collection.py`, `core/freshness.py`, `OutcomeState`, `identity`'s
  writers, or the two shipped collectors.
- No collector imports another (`CPM-AD-7`): shared pieces live in `collectors/agent.py` and
  `core/transport.py`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mapped feedstock exists | `feedstock` mapping `established` with a `Feedstock` row; repo answers | `ok` row: `feedstock_name`, `feedstock_url` (the repo's web URL), `last_recipe_activity_at` from the repo's last push, and from the recipe read `recipe_version`, `recipe_build_number`, `recipe_metadata_url`; `staged_recipe_url` blank; ledger `succeeded` | No error |
| Recipe unreadable | Feedstock found; the recipe call fails, 404s, or sets no readable version | `ok` row (the feedstock exists, which is what `state` says) with `recipe_version` blank and `detail` naming why | Second call's failure never fails the run |
| Mapped feedstock is gone | mapping `established` with a row; repo answers 404 | `not_found` row, ledger `succeeded`; `detail` says the feedstock resolution named is absent; no staged-recipe lookup | Base's sentinel path |
| No feedstock, staged recipe (AC 2) | mapping `established` with zero rows, or `not_found`; staged-recipes has one open PR for the name | `not_found` row with `staged_recipe_url` set and every feedstock fact blank; ledger `succeeded` | No error |
| No feedstock, no staged recipe | as above, search matches nothing | `not_found` row, `staged_recipe_url` blank, `detail` says both were looked for and neither found | No error |
| No feedstock per identity, but one exists | as above; the conventional repo answers 200 | `ok` row naming the conventional feedstock, `detail` says resolution had not established it | No error |
| Ambiguous staged recipe | search returns more than one open PR | `not_found` row, `staged_recipe_url` blank, `detail` names how many matched | Refused rather than picked |
| Feedstock mapping inapplicable | mapping outcome `not_applicable` | One `not_applicable` row through the base's `inapplicability` hook: no call, no allowance, no cache read; ledger `succeeded` | No error |
| Feedstock mapping unresolved | outcome `unknown` or `error`, or no mapping row, or no package row | `FeedstockLocatorError` (a `ValueError`) from `source_for`; ledger `failed`; no evidence row | `CPM-UJ-2`: absence is not claimed for an unresolved identity |
| Unusable feedstock name | established row whose name is blank, or normalises to something that is not a repository segment | `FeedstockLocatorError`; ledger `failed`; no row | Refused, never repaired |
| Name needs the suffix | established row named `numpy` | Locator names `numpy-feedstock`; a row already named `numpy-feedstock` is not doubled | No error |
| More than one mapped feedstock | mapping `established` with several rows | The first by name is observed; `detail` names how many there were | No error |
| Unreadable document | body over the bound, not JSON, not an object, a field of the wrong type, or a value wider than its column | `FeedstockDocumentError` from `translate`; base writes `error` row and re-raises; ledger `failed` | Refused rather than partly read |
| Unusable push instant | repo's push instant absent, unparseable or naive | `ok` row with `last_recipe_activity_at` NULL and `detail` saying so | Never invented |
| Spent allowance | limiter refuses | `error` row, ledger `failed`, `collection.refused_by_rate_limit` | Base path |
| Revalidated answer | cached entry, source answers 304 | The row a 200 would have written; entry refreshed | Base path |
| Sentinel asked for `ok`/`unknown` | `sentinel_evidence(state=OK)` | `CollectorConfigurationError` | Refused at the call |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py` -- the
  closest template. Its `inapplicability` / `source_for` / `translate` / `sentinel_evidence`
  shape, its remembered-per-run identity read (`_release_identity`, reset at the start of
  `inapplicability`), its `_require_storable` / `_column_width` width guards, its
  `asks_about` / `inapplicability_of` split, and its three-state sentinel are all reused
  here. Read it before writing anything.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py` -- the
  precedent for a **bounded second call** (`_tagged_instead`): reached on one branch only,
  one page, and a failure of it never fails the collection. This story makes the same move
  twice, once per branch. Also the GitHub locator refusals to mirror.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/agent.py` -- `USER_AGENT`,
  shared by every collector. This collector declares it in `headers`.
- `src/django_apps/conda_package_supply_chain_monitor/core/transport.py` --
  `worst_case_call_seconds`, `DEFAULT_RETRIES`, `ALLOWED_SCHEMES`, `Payload` (`found`,
  `body`, `source`, `not_modified`).
- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py` -- read only. The
  `inapplicability` hook (`CPM-CURRENCY-S02`), the window, the limiter, `_write_evidence`,
  and the `not_found` branch that calls `sentinel_evidence` **without** reaching `translate`
  -- which is why the staged-recipe question is asked on the branch whose first call
  succeeds, never from a shaping hook.
- `src/django_apps/conda_package_supply_chain_monitor/identity/models.py` -- read only.
  `Feedstock` (`package`, `name`, `url`, `metadata_url`; unique per package by name),
  `PackageMapping` (`kind`, `outcome`), `MappingKind.FEEDSTOCK`, `ESTABLISHED`,
  `Package.canonical_name`. `MAPPED_FIELDS[FEEDSTOCK]` is empty on purpose: the mapping *is*
  the child rows, and `established` with none is the successful empty result `CPM-FR-6`
  keeps apart from `not_found`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` --
  `PyPIReleaseSnapshot` is the template: `PROTECT` FK, `source`, `state`, facts, `detail`,
  `trace_id`, one read index on `(package, -observed_at)`, `CheckConstraint`s, no unique
  constraint. `_VERSION_LENGTH`, `_LOCATOR_LENGTH`, `_STATE_LENGTH`, `_TRACE_ID_LENGTH`
  exist; add `_FEEDSTOCK_NAME_LENGTH` (128, a name a recipe author chose, matching
  `identity`'s own `Feedstock.name`).
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/` -- `0003` is
  the newest; add `0004_feedstock_snapshots.py` depending on it and on
  `identity.0001_package_identity`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` --
  `collect_pypi_release` is the template for `collect_feedstock`; add
  `COLLECT_FEEDSTOCK_TASK_NAME = "cpm.collect.feedstock"` and both to `__all__`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` -- the roster
  tuple in `ready()` becomes four.
- `tests/unit/django_apps/test_pypi_release.py` and
  `tests/integration/django_apps/test_pypi_release.py` -- the module shapes to mirror,
  including the source sweeps (no write method, no `transaction.atomic`, no sibling-collector
  import), the declaration/derivation cases, and the freshness read.
- `tests/collectors.py` -- `RecordedTransport`, `FixedLimiter`, `RecordingResponseCache`,
  `recorded_payload`, `cached_response`. The integration module needs a two-locator
  transport; `tests/integration/django_apps/test_source_release.py`'s `ScriptedTransport` is
  the one to copy (it exists there, not in `tests/collectors.py`).
- `tests/unit/test_model_registry.py` (`EVIDENCE_MODEL_LABELS`),
  `tests/integration/startup/test_stage_two_collector_registry.py` (roster of four),
  `tests/unit/django_apps/test_collector_base_audit.py` (`THE_NEW_MODULES` anchor) -- the
  three frozen rosters.
- `docs/deployment.md` -- the two collector sections are the template for a third.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- `in-progress`, then `done`.

## Tasks & Acceptance

**Execution:**
- `collectors/models.py`, `collectors/migrations/0004_feedstock_snapshots.py` --
  `FeedstockSnapshot` / `feedstock_snapshots`: `package` (`PROTECT`), `source`, `state`,
  `feedstock_name`, `feedstock_url`, `recipe_version`, `recipe_build_number` (nullable),
  `recipe_metadata_url`, `last_recipe_activity_at` (nullable), `staged_recipe_url`, `detail`,
  `trace_id`; read index `(package, -observed_at)`; two `CheckConstraint`s --
  `feedstock_facts_present_exactly_when_observed` (a determinate row names a feedstock; a row
  that is not determinate carries no feedstock fact at all) and
  `staged_recipe_only_when_absent` (a staged recipe may be recorded only on a `not_found`
  row) -- rationale: AC 2's separation is a database rule, not a convention.
- `collectors/feedstock.py` -- new. Declarations (cadence weekly, `CPM-NFR-2`'s slow end for
  a recipe surface; target `cadence x (1 + tolerated)`; window half the cadence; timeout and
  retries reconciled against the soft limit; the allowance below; the shared `User-Agent`;
  a cache lifetime longer than the cadence). Pure functions: `feedstock_repository(name)`
  (normalise, add the `-feedstock` suffix once, refuse what is not a repository segment),
  `repository_locator`, `recipe_locator`, `staged_recipes_locator`, `repository_facts(body)`,
  `recipe_facts(body)`, `staged_recipe(body, *, name)`, and `asks_about` /
  `inapplicability_of` over a frozen `FeedstockIdentity`. Then `FeedstockCollector` with the
  four hooks and the two bounded second calls.
- `collectors/tasks.py`, `collectors/apps.py` -- `cpm.collect.feedstock` and a roster of four.
- `tests/unit/django_apps/test_feedstock.py` -- new. Every matrix row that needs no run:
  the declarations and their derivations, every locator refusal and normalisation, both
  document readers, the staged-recipe matcher including the ambiguous case, the applicability
  rule, the three sentinel shapes and the two refusals, and the module's own source sweeps.
- `tests/integration/django_apps/test_feedstock.py` -- new. Every matrix row that needs a
  run: both branches end to end, AC 1's absence read back through `core/freshness.py` (with
  the never-observed pair), AC 2's separation, the window and `force`, the spent allowance,
  the cache write and the `304` replay, the task, each constraint conjunct, and re-observation.
- `tests/unit/test_model_registry.py`, `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py` -- the three rosters.
- `docs/deployment.md` -- what an operator has to know: an unauthenticated read, why the
  declared allowance is GitHub's *search* allowance, what each branch costs, what a
  `not_found` row does and does not prove, and that an unresolved feedstock mapping fails the
  run rather than claiming absence.

**Acceptance Criteria:**
- Given a package whose feedstock mapping is `established` with a `Feedstock` row, when the
  collector runs against a source serving the repository and the recipe, then one
  `feedstock_snapshots` row carries `ok`, the feedstock's name and URL, the recipe version,
  build number and metadata URL, and the repository's last push as the recipe activity.
- Given a package with no feedstock and one open staged-recipes pull request for its name,
  when the collector runs, then the row carries `not_found` with `staged_recipe_url` set and
  every feedstock fact blank, and the run is `succeeded`.
- Given a row that carries `ok`, when a `staged_recipe_url` is written to it, then the
  database refuses the row.
- Given an absence row, when `core/freshness.py` is asked about the package, then it reports
  the observation with its instant and not stale, and a package this collector never observed
  reads as unobserved.
- Given a package whose feedstock mapping is `unknown`, `error` or absent, when the collector
  runs, then the run fails with no evidence row.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

## Review Triage Log

### 2026-09-06 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 23: (high 3, medium 10, low 10)
- defer: 3: (high 0, medium 1, low 2)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[patch]` The absent branch wrote "the conventional feedstock repository is
    absent" for a repository it had never read: `_conventional_instead` returned the same
    bare `None` for "asked and it is not there" and for "could not ask". It now returns a
    value that distinguishes them, and a transport failure, a `304`, an unreadable document
    and an unnameable locator each produce their own sentence.
  - `[high]` `[patch]` On the absent branch the first call is the staged-recipes search, so a
    `404` from *the search endpoint* made the base write a `not_found` sentinel — a row whose
    model docstring says the feedstock is absent, established by nothing. The sentinel's
    detail now says which question could not be asked, and the remembered branch became a
    three-valued name because a boolean could not tell the absent branch from a run that
    asked nothing at all.
  - `[high]` `[patch]` A literal `version: 1.0  # first build` stored the comment as part of
    the version — a value no comparison will ever match, in a table nothing may correct. An
    unquoted trailing comment is stripped; a `#` inside a quoted scalar and one inside a bare
    word both survive.
  - `[medium]` `[patch]` The absent branch's second call could fail the whole run: the
    document reader sat outside the `try`, so a conventional repository whose shape had
    changed turned an absence the run had already established into an `error` row.
  - `[medium]` `[patch]` The stored feedstock-name column was as wide as `identity`'s, but
    this collector stores the *suffixed* name — so a name in the 119-128 character band was
    storable in `feedstocks` and permanently uncollectable here.
  - `[medium]` `[patch]` The repository grammar refused a leading underscore, making
    `_openmp_mutex` and `_libgcc_mutex` — real conda-forge packages — permanent failed runs.
  - `[medium]` `[patch]` The build number accepted a non-decimal unicode digit (a `ValueError`
    escaping a function documented as total) and a number above the column's ceiling, which
    was then refused at insert outside the translation's guard.
  - `[medium]` `[patch]` The branch was chosen from the child rows alone, so a mapping
    recorded `not_found` with stale rows still took the mapped branch. The outcome and the
    rows are read together and the contradiction is refused.
  - `[medium]` `[patch]` Nothing pinned that the identity read selects the *feedstock*
    mapping: every test package carried one mapping row, so dropping the kind filter left the
    suite green while production, which writes one row per kind with no ordering, would read
    an arbitrary one. Every test package now carries a contradicting distractor mapping.
  - `[medium]` `[patch]` One page of search results was read and the count that reveals
    truncation was discarded, so a genuine staged recipe could sit on page two and the row
    would record an absence nobody established.
  - `[medium]` `[patch]` Nothing asserted the page size reached the search locator, so
    setting it to one would have turned the refusal-to-pick into a pick with the suite green.
  - `[medium]` `[patch]` The two branches passed different fallback names to the document
    reader, so one repository could record two spellings of its name.
  - `[medium]` `[patch]` The absent branch's determinate row named the search locator in
    `source` while every fact on it came from the repository locator.
  - `[low]` `[patch]` Ten further findings: an unreachable traversal guard removed; the width
    refusal no longer leaks into the branch that records no name; `__all__` completed; the
    document ceiling's claim narrowed to the parse it actually bounds; the scripted transport
    moved to the shared test module rather than copied a second time; four caveats added to
    the operator documentation, including the `403` blind spot both siblings carry; one named
    constant per concept; three missing cases added; the one-ask-two-requests property
    asserted rather than only documented; and the column-width relation asserted.

## Design Notes

**Which question is asked is decided from identity, before any call.** `CPM-FR-1` resolves
"zero or more conda-forge feedstocks", so resolution has already answered "does this package
have a feedstock" -- and `CPM-UJ-2` requires that "absence of a feedstock cannot be claimed
for a package whose identity is unresolved". So:

- mapping `established` with rows -> ask the repository. Its `404` is a real fact: the
  feedstock resolution named is gone.
- mapping `established` with **no** rows, or `not_found` -> resolution looked and found none.
  The interesting question is the staged-recipes queue, so that is the call the base makes,
  and `translate` then confirms the conventional feedstock's absence with its own bounded
  second call. Both facts land on one row.
- mapping `not_applicable` -> the base's `inapplicability` hook, one `not_applicable` row.
- mapping `unknown`/`error`/absent -> refused, on the terms `CPM-CURRENCY-S02` set.

**Why the staged-recipe question is never asked from `sentinel_evidence`.** The base's
`not_found` branch writes its row through `sentinel_evidence` and never reaches `translate`,
so a collector that wanted to look something up on the absent path would have to make a call
from a row-shaping hook -- on a path where a raised exception replaces the reason the run is
recording. Choosing the branch from identity puts the always-succeeding call
(the staged-recipes search) first exactly where absence is expected, so every fetch this
collector makes is in `translate`.

**The declared allowance is GitHub's search allowance, and that is the tighter of the two.**
The absent branch reads `/search/issues`, which GitHub limits far below its core API, and the
base charges one allowance per collection without knowing which branch a package will take.
Declaring the tighter number is the only honest option; the arithmetic against `CPM-NFR-1` is
recorded as deferred rather than hidden.

**Recipe activity is the feedstock repository's last push.** PRD Open Question 10 asks what
counts; this story answers "a push to the feedstock", records it as an instant, and leaves the
threshold that makes it *inactivity* to `CPM-FR-40` (`CPM-CURRENCY-S07`), which PRD says is a
versioned policy parameter rather than a constant in code.

**The recipe version is read the way conda-forge writes it.** Every conda-forge recipe opens
with `{% set version = "x.y.z" %}` and interpolates it; the fallback is a literal `version:`
under `package:`. A recipe that computes its version some other way records the feedstock as
present -- which is what `state` claims -- with the version blank and `detail` saying it could
not be read. Rendering Jinja to find out is out of scope and is a Block If.

**Golden example:**

```python
repository_locator("numpy")   # -> "https://api.github.com/repos/conda-forge/numpy-feedstock"
repository_locator("numpy-feedstock")  # -> the same locator; the suffix is added once
```

## Verification

**Commands:**
- `pixi run test` -- expected: exit 0, the new unit module collected and passing.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: exit 0, no diagnostics.
- `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, `collectors/feedstock.py` at 100%.

**Manual checks (if no CLI):**
- `git diff --stat 6706828` names every Code Map file that was meant to change and none of
  the read-only ones (`core/collection.py`, `core/freshness.py`, `core/outcomes.py`,
  `identity/`, `collectors/pypi_release.py`, `collectors/source_release.py`).

## Dev Notes

**Satisfies:** `CPM-FR-9`

**Governed by:**

- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S03]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-9]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context), as a `bmad-build` implementation agent.

### Debug Log References

- `pixi run ci` -- exit 0. 5031 passed, 2 pre-existing skips, coverage 98.71% against a
  90% floor, with `collectors/feedstock.py`, `collectors/models.py`, `collectors/tasks.py`
  and `collectors/apps.py` each at 100%. (Before the review patch round: 4985 passed at
  98.69%.)
- `pixi run manage makemigrations --check --dry-run` -- "No changes detected" after
  `0004_feedstock_snapshots.py`.
- `pixi run gate-postgres` -- the suite passed against `postgres:17`, so both new
  `CheckConstraint`s and the `PROTECT` relation are proved on PostgreSQL and not only on
  SQLite. `pixi run gate-redis` was **not** run in this session.
- `git diff --stat 6706828` -- every Code Map file and none of the read-only ones
  (`core/collection.py`, `core/freshness.py`, `core/outcomes.py`, `identity/`,
  `collectors/pypi_release.py`, `collectors/source_release.py`). The patch round adds two
  files the Code Map did not name: `tests/collectors.py`, which `ScriptedTransport` moved
  into, and `tests/integration/django_apps/test_source_release.py`, which now imports it
  from there instead of declaring its own copy. No behaviour of `CPM-CURRENCY-S01`'s
  collector changed.

### Completion Notes List

**The base did not change, and that is the story's main structural claim.** Every hook
`CPM-CURRENCY-S02` added was enough: `inapplicability` carries the `not_applicable` row,
`source_for` carries the refusal, and both bounded second calls live in `translate` where a
failure is a `detail` rather than a lost reason. `core/collection.py`, `core/freshness.py`,
`OutcomeState`, `identity`'s writers and the two shipped collectors are untouched.

**The branch is decided in `source_for` and remembered on the instance.** `_mapped` and
`_asked` are set beside `_locator` when the branch is chosen and cleared at the start of
every run by `inapplicability`, so `translate` knows which document it is about to read and
`sentinel_evidence` can say *which* feedstock a `not_found` row is about without asking
identity a second time on a path that is already failing.

**The identity read is two queries, not one, and the shape is the mapping's own.**
`MAPPED_FIELDS[FEEDSTOCK]` is empty because the mapping *is* the `Feedstock` child rows, so
`established` with none is `CPM-FR-6`'s successful empty result rather than a missing row.
A join would return one row per feedstock and no row at all for the empty result -- which is
precisely the case that decides the branch. An integration case counts the two.

**`established` with no rows and `not_found` are one question.** Both mean resolution looked
and named nothing, so both take the absent branch; `asks_about` is written as two
comparisons rather than as a set literal, for the reason
`tests/unit/django_apps/test_single_ordering_audit.py` gives.

**AC 2 is a database rule.** `staged_recipe_only_when_absent` refuses a staged-recipe URL on
any row that is not `not_found`, which is why the absent branch drops the staged URL from its
column when the conventional feedstock turns out to exist -- and records it in `detail`
instead, so the queue's answer is not lost. The facts constraint is the biconditional the two
sibling tables carry, widened to all six feedstock facts.

**The recipe reader is total and the repository reader is not.** The repository (or the
search) is the branch's *first* document, so an unreadable one raises `FeedstockDocumentError`
and the base writes an `error` row. The recipe is the second call, so an over-wide version, an
over-large body, a `404`, a transport failure and an unconditional `304` all become a blank
`recipe_version` with a reason -- the feedstock's existence is what `state` claims, and it was
established before the recipe was asked for.

**The recipe version is read, never rendered** (the Block If). `{% set version = "..." %}`
first, a literal `version:` under `package:` second, and a value still carrying `{{` is
recorded as unreadable rather than resolved. The section walk is line-oriented rather than a
YAML parse, because a conda-forge recipe is not valid YAML until it has been rendered.

**Staged-recipe matching narrows GitHub's word search.** `in:title numpy` returns
`Add numpy-quaternion`, so each title is cut on the characters a package name *cannot*
contain -- and deliberately not on `-`, `_` or `.`, which names do -- and a token must
normalise to exactly the package's name. More than one match is refused rather than picked,
with the count in `detail`.

**The declared timeout is four seconds rather than five.** `worst_case_call_seconds` bounds
the retried call the base makes; this collector then makes an un-retried second one inside
`translate`. At five seconds the pair comes to 53 of the inherited 60-second soft limit; at
four it comes to 43. The unit case reconciles the whole of it against
`settings.CELERY_TASK_SOFT_TIME_LIMIT` rather than against a number repeated in the test.

**Six `deferred` entries recorded**, three of them medium: the search allowance is not a
sweep rate, each branch's second call is uncharged, and no resolver populates feedstock
mappings yet.

### Review patch round (23 findings, all applied)

**The three high findings were one failure in three places: a row claiming something the
run never established.**

- `_conventional_instead` returned bare `None` for a transport failure and for a `304`, and
  `_absent` then wrote `ABSENT_FEEDSTOCK_DETAIL` -- "the conventional repository is absent"
  -- for a repository nobody had read. It now returns a `ConventionalAnswer` carrying the
  facts, the locator and what the call *established*: `ABSENT_FEEDSTOCK_DETAIL` only when the
  repository said so, and a sentence beginning `UNCHECKED_FEEDSTOCK_DETAIL` for every way of
  not finding out. Four ways are covered end to end, and a second case asserts three of them
  produce three different sentences.
- On the absent branch the base's `not_found` sentinel fires for a `404` from the
  *staged-recipes search endpoint*, which says nothing about the package. `_sentinel_detail`
  now branches three ways rather than two -- and `_mapped` became `_branch`, a value with
  three states, because a boolean could not tell "the absent branch" from "no question was
  asked".
- `recipe_facts` kept a trailing YAML comment, so `version: 1.0  # first build` stored the
  comment as part of the version. `_uncommented` strips an unquoted trailing comment before
  the quote-stripping; a `#` inside a quoted scalar and one inside a bare word both survive.

**Four medium findings about a bound that was not taken.** `repository_facts` moved inside
`_conventional_instead`'s `try`, so a conventional document whose shape has changed degrades
to the absence rather than raising out of `translate`. `_FEEDSTOCK_NAME_LENGTH` went from 128
to 160: this table stores the *suffixed* repository, so a column equal to
`identity.Feedstock.name` left a band of names `feedstocks` accepts and this collector could
never record. `_REPOSITORY_SEGMENT` now permits a leading underscore, because `_openmp_mutex`
and `_libgcc_mutex` are real conda-forge packages that were permanent `failed` runs.
`_build_number` requires an ASCII decimal and bounds by `MAX_BUILD_NUMBER` -- a non-decimal
unicode digit would have raised a `ValueError` out of a function documented as total, and a
number past PostgreSQL's `integer` ceiling would have reached the insert outside `translate`'s
`try`.

**The branch is now decided from the outcome and the rows together** (`branch_of`), so a
mapping recorded `not_found` that still carries stale `Feedstock` rows is refused as a
contradiction rather than taking the mapped branch. Both branches pass the *normalised*
repository as the document's fallback name, so one repository cannot be recorded under two
spellings; the absent branch's determinate row records the conventional repository's locator
in `source` rather than the search's, on the precedent `SourceReleaseSnapshot` sets for its
tag fallback. `staged_recipe` reads `total_count` and refuses to claim absence when the queue
overflowed the one page read.

**Test findings.** `_a_package` now seeds a `release_ecosystem` mapping carrying
`not_applicable` on every package, so a read that dropped `kind=feedstock` from its filter
fails loudly instead of leaving the suite green. The search locator's `per_page` and
`in:title` fragments are asserted. `ScriptedTransport` moved to `tests/collectors.py` and
both integration modules import it. One constant per concept replaced the shared `TWO_*`.
Cases added for: the absent branch's first-call `404`, a first document over the ceiling on
both branches, a `FeedstockDocumentError` from a second call, an overfull queue, and the
property everything rests on -- one allowance ask against two transport calls, on both
branches, with the charge asserted to be the retry budget.

**Three more `deferred` entries recorded**, making nine: no ceiling in this product bounds a
*transfer* (only the parse), a renamed feedstock's `301` is refused rather than followed, and
the branch is remembered on the instance rather than passed through `translate`.

### File List

- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` --
  `FeedstockSnapshot`, `_FEEDSTOCK_NAME_LENGTH`, `FEEDSTOCK_FACTS_CONSTRAINT`,
  `STAGED_RECIPE_CONSTRAINT`, `FEEDSTOCK_READ_INDEX`, module docstring (four tables).
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/0004_feedstock_snapshots.py`
  -- new; depends on `collectors.0003` and `identity.0001`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py` -- new; the
  declarations, `FeedstockLocatorError`, `FeedstockDocumentError`, `FeedstockIdentity`,
  `RepositoryFacts`, `RecipeFacts`, `StagedRecipe`, `feedstock_repository`, the three
  locators, `repository_facts`, `recipe_facts`, `staged_recipe`, `asks_about`,
  `inapplicability_of`, and `FeedstockCollector` with its two bounded second calls.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` --
  `COLLECT_FEEDSTOCK_TASK_NAME`, `collect_feedstock`, `__all__`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` -- roster of four.
- `docs/deployment.md` -- the operator section for the feedstock collector.
- `tests/unit/django_apps/test_feedstock.py` -- new.
- `tests/integration/django_apps/test_feedstock.py` -- new, with its own `ScriptedTransport`.
- `tests/collectors.py` -- `ScriptedTransport` moved in from
  `tests/integration/django_apps/test_source_release.py`, so two integration modules and the
  collector after them share one.
- `tests/integration/django_apps/test_source_release.py` -- imports `ScriptedTransport` from
  its new home; no case of `CPM-CURRENCY-S01`'s changed.
- `tests/unit/test_model_registry.py`,
  `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py` -- the three frozen rosters.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- `in-progress`.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** `CPM-FR-9`'s conda-forge feedstock collector, on the collector base
unchanged: every hook `CPM-CURRENCY-S02` added proved sufficient, so `core/collection.py`,
`core/freshness.py`, `OutcomeState`, `identity`'s writers and the two shipped collectors are
untouched. `FeedstockCollector` writes `feedstock_snapshots`, and which question it asks is
decided from what resolution recorded before any call is made: a package resolution gave a
feedstock is asked about that feedstock; a package resolution gave none is asked about the
staged-recipes queue, with the conventional feedstock's absence confirmed by a bounded second
call. Both branches take at most two calls, and a package whose feedstock mapping is
unresolved is refused rather than having absence claimed for it — `CPM-UJ-2`'s rule.

**Files changed.**

- `collectors/models.py` — `FeedstockSnapshot`, its read index, and **two**
  `CheckConstraint`s: the facts biconditional, and `staged_recipe_only_when_absent`, which
  makes AC 2's separation a database rule rather than a convention.
- `collectors/migrations/0004_feedstock_snapshots.py` *(new)* — schema only.
- `collectors/feedstock.py` *(new)* — the declarations, the pure locator, document,
  staged-recipe and applicability functions, and the collector with its two bounded second
  calls.
- `collectors/tasks.py`, `collectors/apps.py` — `cpm.collect.feedstock` and a roster of four.
- `docs/deployment.md` — what an operator has to know: an unauthenticated read of two hosts,
  why the declared allowance is GitHub's *search* allowance, what each branch costs, the
  `403` blind spot, and what a `not_found` row does and does not prove.
- `tests/collectors.py` — the scripted two-locator transport moved here rather than copied a
  second time; `tests/integration/django_apps/test_source_release.py` imports it from here,
  with none of its cases changed.
- New unit and integration modules; three frozen rosters updated.

**Review findings.** 23 patched (3 high, 10 medium, 10 low), 3 deferred, 2 rejected. Four
review layers ran in parallel over the 4,700-line diff.

**Follow-up review recommended:** true. Three high-severity patches (the rule fires on any
high). Patched counts: high 3, medium 10, low 10; score `3 x 10 + 1 x 10 = 40`, far over the
threshold of 5.

**The three high findings were one failure wearing three faces: a row claiming what the run
never established.** An absence written for a repository that was never read; a `404` from the
*search* endpoint recorded as "conda-forge has no feedstock"; and a YAML comment stored as
part of a version. Each is permanent in a log nothing may correct, which is the property this
epic exists to protect.

**A judgement worth recording.** The build-number ceiling is PostgreSQL's rather than the
column validator's, because the validator's limit is backend-dependent — reading it off the
field would have accepted, on SQLite, a number the deployed database refuses.

**Verification.** `pixi run ci` exits 0 — 5031 passed, 2 pre-existing skips, coverage 98.71%,
with `collectors/feedstock.py` at 100%. `makemigrations --check --dry-run` reports "No changes
detected". `pixi run gate-postgres` passes against `postgres:17`, where both new constraints
are actually enforced. All three were re-run by the orchestrating session after the patch
round.

**Residual risks.** Nine `deferred` entries. The three that matter most: the declared allowance
is GitHub's search allowance, which at two packages a minute cannot sweep `CPM-NFR-1`'s ten
thousand inside the weekly cadence; each branch's bounded second call is uncharged against
that allowance, so every collection spends more of the remote budget than the local counter
believes; and nothing populates feedstock mappings yet, so a sweep offering every package
today would fail every run. All three land on `CPM-CURRENCY-S05`.
