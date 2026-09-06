---
title: 'CPM-CURRENCY-S02: PyPI release evidence'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '76c73d2cd1b9b0aaf93e8d43333819a8ba5ad38b'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s01-upstream-release-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s01-five-outcome-states-precedence-order.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s05-collector-base-carrying-external-call.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s08-conditional-requests-and-caching.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s02-resolution-records-where-came-from.md
warnings:
  - oversized
deferred:
  - summary: >-
      A package whose release-ecosystem identity is unresolved (`unknown`, `not_found`,
      `error`, or no mapping row) produces a `failed` ledger row rather than any observation.
    evidence: |-
      `PyPIReleaseCollector.source_for` raises `PyPILocatorError` for every mapping that is
      not `established`, on the terms `SourceLocatorError` set in `CPM-CURRENCY-S01`. The
      `not_applicable` path deliberately does not absorb these: "resolution has not decided"
      is not "does not apply", and recording it as one would be the guess `CPM-FR-1`
      forbids. Today no resolver populates `release_ecosystem` mappings, so a sweep that
      offered every package to this collector would fail every run. The selection that
      offers only askable packages is `CPM-CURRENCY-S05`'s, as the Design Notes record.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py -- PyPILocatorError
    severity: medium
  - summary: >-
      The declared PyPI allowance is a courtesy bound this product chose, not a ceiling the
      source stated, and nothing has measured it against the source's actual tolerance.
    evidence: |-
      `PYPI_RELEASE_RATE_LIMIT` is `RateLimit(calls=60, per=1 minute)`. PyPI publishes no
      numeric limit for its JSON API; its guidance is an identifying `User-Agent`, caching,
      and reasonableness. Sixty a minute is written down so the base enforces *something*
      and a reader can see what "reasonable" was taken to mean. At `1 + retries` per
      collection that is fifteen packages a minute -- roughly eleven hours to observe
      `CPM-NFR-1`'s ten thousand once, which fits a daily cadence but only just, and the
      number has not been tested against a real sweep. `CPM-CURRENCY-S05` is where it gets
      measured.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py -- PYPI_RELEASE_RATE_LIMIT
    severity: low
  - summary: >-
      `inapplicability` is asked on every run inside the window too, so a suppressed run
      still costs one identity read.
    evidence: |-
      The base asks `inapplicability` before the window so that a collector whose question
      does not apply is never asked for a locator -- the ordering `CPM-FR-1` needs. The
      consequence is that a `skipped` run performs the collector's identity query before
      discovering it is inside the window, where `CPM-CURRENCY-S01`'s collector also read
      identity (`source_for`) before the window. One indexed query per suppressed run is
      cheap; it is recorded because a sweep at `CPM-NFR-1` volume is where "cheap per run"
      stops being free, and the fix (window first, then the hooks) changes the ordering
      this story's base docstring is written about.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/collection.py -- Collector.collect
    severity: low
  - summary: >-
      `_earliest_upload` dates the latest version from its files regardless of their `yanked`
      flag, and `info.version` is taken as Warehouse states it; whether a yanked upload should
      date a release, or a wholly-yanked latest version should be recorded at all, is undecided.
    evidence: |-
      PyPI serves a per-file `yanked` flag and applies its own rule when computing
      `info.version`; this collector records what the source states and applies no rule of
      its own, so a version whose only files were yanked after release can still be `ok` and
      dated by a yanked upload. The decision belongs with the currency policy that compares
      versions (`CPM-CURRENCY-S06`), because it is a question about what "latest" should mean
      for a comparison rather than about what PyPI said.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py -- _earliest_upload
    severity: low
  - summary: >-
      `collectors/source_release.py` builds its locators with no bound against
      `SourceReleaseSnapshot.source`'s width, the same parity gap this story closes for the
      PyPI locator.
    evidence: |-
      `Package.source_repository_url` is 512 wide and `releases_locator`/`tags_locator`
      prepend the API host and append the endpoint and page size, so a very long but valid
      repository URL yields a locator PostgreSQL refuses at insert and SQLite stores.
      Pre-existing in `CPM-CURRENCY-S01`, surfaced by this story's review; fixed here for the
      PyPI collector only, because the sibling's fix belongs with that module's own cases.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py -- _repository_segments
    severity: low
---

# CPM-CURRENCY-S02: PyPI release evidence

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

<intent-contract>

## Story

As a packaging engineer,
I want PyPI existence, latest version and `Requires-Python` recorded,
so that Python packages can be compared against their primary release ecosystem.

## Acceptance Criteria

1. **Given** a Python package
   **When** the PyPI collector runs
   **Then** it records project existence, latest version and date, and `Requires-Python`

2. **Given** a package with no PyPI presence
   **When** the collector runs
   **Then** it records `not_found`

3. **Given** a non-Python package
   **When** the collector runs
   **Then** it records `not_applicable`, and the package is never marked stale against PyPI for not being published there

## Intent

**Problem:** `CPM-FR-8` needs a second surface collector -- PyPI -- and nothing observes it. The
collector base (`core/collection.py`) has no path that records `not_applicable`: every
per-package run either reaches the transport or fails, so AC 3 is unwritable today (recorded as
deferred by `CPM-CURRENCY-S01`).

**Approach:** Add `PyPIReleaseCollector` on the base's per-package path, writing
`pypi_release_snapshots` (PRD Appendix A.2), driven by the identity `CPM-IDENTITY-S02` established
(`Package.primary_purl` / `primary_type` and the `release_ecosystem` `PackageMapping` outcome).
Give the base one optional hook -- `inapplicability(package_id)` -- so a collector can say the
question does not apply, and the base writes the `not_applicable` sentinel row itself, as it
writes `error` and `not_found`, with no call made and no allowance spent.

## Boundaries & Constraints

**Always:**
- Every evidence row is written by the base through `_write_evidence` (`CPM-AD-7`); the collector
  never saves a row and never opens a transaction.
- The lookup status is a `state` column over `OutcomeState`, emitted verbatim (`CPM-AD-5`,
  `CPM-AD-24`); never a boolean, never a `*_status`/`*_outcome` name.
- Applicability is read from identity and never guessed: a package is asked about on PyPI only when
  `MappingKind.RELEASE_ECOSYSTEM` is `established` with `primary_type == "pypi"`; the project name
  comes from `primary_purl`, never from `canonical_name` (`CPM-FR-1`).
- Time comes from the injected clock; `observed_at` on every row is the run's instant.
- `pixi` is the only runner; `pixi run ci` exits 0 at the end.
- The two existing collectors keep their behaviour: `inapplicability` defaults to "applies", and
  `SourceReleaseCollector` and `InventoryIngestionCollector` are unchanged in what they write.

**Block If:**
- A `not_applicable` observation would need `core/freshness.py` to treat one status differently from
  another (a status-aware staleness rule). This story reads AC 3 as `CPM-CURRENCY-S01` read its
  AC 2: the row is an observation, it is fresh when observed and ages like any other, and what AC 3
  forbids is staleness *caused by* PyPI absence. If review finds that reading indefensible, HALT.

**Never:**
- No authentication, credential or settings key for PyPI.
- No schedule, no `CELERY_BEAT_SCHEDULE` entry, no per-task time limit (`CPM-AD-20`, `CPM-AD-9`).
- No version normalisation or comparison -- `CPM-FR-16` is a policy pass (`CPM-AD-8`).
- No change to the `sweep()` path, to `identity`'s writers, or to `OutcomeState`.
- No second collector may import from `collectors/source_release.py`: shared pieces move to a
  shared home rather than one collector importing another.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Python package on PyPI | `release_ecosystem` established, `primary_type="pypi"`, `primary_purl="pkg:pypi/Django"`; source serves the project document | One `ok` row: `latest_version=info.version`, `released_at`= earliest usable `upload_time_iso_8601` of that version's files, `requires_python=info.requires_python`, `source`= the locator; ledger `succeeded` | No error |
| Latest version has no files | `releases[info.version]` is `[]` or absent | `ok` row with `released_at` NULL; `detail` says the source dated nothing | No error |
| `requires_python` null | `info.requires_python` is `null`/absent | `ok` row with `requires_python=""` (blank means missing) | No error |
| No PyPI presence (AC 2) | source answers 404/410 (`Payload.found=False`) | `not_found` sentinel row, ledger `succeeded`; freshness reads not stale | Base path; no caveat -- PyPI is public, a 404 is unambiguous |
| Non-Python package (AC 3) | `release_ecosystem` outcome `not_applicable`, or `established` with `primary_type != "pypi"` | One `not_applicable` row, ledger `succeeded` with the reason as `detail`; no transport call, no allowance charged, no cache read; freshness reads not stale with status `not_applicable` | No error |
| Not applicable, inside window | as above, a `succeeded` run of this collector for this package inside `observation_window` | ledger `skipped`, no row (`CPM-AD-7`); `force=True` writes again | No error |
| Release ecosystem unresolved | outcome `unknown`, `not_found`, `error`, or no mapping row / no package row | `PyPILocatorError` (a `ValueError`) escapes `collect()`; ledger `failed` carrying the message; no evidence row | Raised from `source_for`, as `SourceLocatorError` is in S01 |
| Unreadable purl | `primary_purl` blank, not `pkg:`, type not `pypi`, carries a namespace, empty name, or a name that is not a valid project name after PEP 503 normalisation | `PyPILocatorError`; ledger `failed`; no row | Refused, never repaired |
| purl carries version/qualifiers/subpath | `pkg:pypi/Foo_Bar@1.0?x=y#sub` | Locator names `foo-bar` only; `@`, `?`, `#` parts dropped; name percent-decoded then normalised | No error |
| Unreadable document | body over the size bound, not JSON, not an object, `info` not an object, `version`/`requires_python`/an upload time of the wrong type, version or specifier wider than its column | `PyPIDocumentError` (a `ValueError`) from `translate`; base writes `error` row, re-raises; ledger `failed` | Refused rather than partially read |
| Blank latest version | `info.version` missing or blank | `not_found` row with a detail naming the reason (the project lists no release) | No error |
| Unusable upload time | a string that does not parse or parses naive | That file dates nothing; other files still may | No error |
| Spent allowance | limiter refuses | `error` row, ledger `failed`, `collection.refused_by_rate_limit` | Base path |
| Revalidated answer | cached entry, source answers 304 | Same row a 200 would have written; entry refreshed | Base path |
| Existing collectors | `SourceReleaseCollector`, `InventoryIngestionCollector` | `inapplicability` returns `""`; nothing about their runs changes | No error |
| Sentinel asked for `ok`/`unknown` | `sentinel_evidence(state=OK)` | `CollectorConfigurationError` | Refused; `not_applicable` is now a shaped row |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py` -- the base. `collect()`
  (line ~928) opens the recorder, reads `observed_at`, calls `source_for`, then window, limiter,
  cache, fetch, `translate`, `_write_evidence`. Add the `inapplicability` hook (non-abstract, default
  `""`) and, **before** `source_for`, the not-applicable branch: window check (skip unless `force`)
  then `_write_evidence([self._sentinel(OutcomeState.NOT_APPLICABLE, ...)])`, `run.succeeded(detail=reason)`,
  return `CollectionResult(SUCCEEDED, rows, reason)`. New `COLLECTION_NOT_APPLICABLE_EVENT =
  "collection.not_applicable"` (info) with `EVENT_KEYS` (`source` is `""` -- no locator exists on this
  path; say so). Update: module docstring ("never a clean result" paragraph), `sentinel_evidence`
  docstring (three states), `collect()`'s "seven returns" prose (now eight; keep the `noqa`),
  `EVENT_KEYS` comment (seven events). `_sentinel` already checks the state is carried verbatim.
- `src/django_apps/conda_package_supply_chain_monitor/core/transport.py` -- home for
  `worst_case_call_seconds` (moved from `source_release.py`; it computes the arithmetic this
  module's docstring states in prose). Add to `__all__`; update the prose.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/agent.py` -- **new**, the shared
  `User-Agent` identity: `DISTRIBUTION_NAME`, `PROJECT_URL`, `UNKNOWN_VERSION`, `distribution_version`,
  `USER_AGENT` (moved from `source_release.py`).
- `src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py` -- import the
  moved names from their new homes and keep them in `__all__` (re-exported) so every existing
  importer and `tests/unit/django_apps/test_source_release.py` are untouched. No behaviour change.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` -- `SourceReleaseSnapshot`
  (line ~397) is the template: `package` FK `PROTECT`, `source`, `state`, `latest_version`,
  `released_at`, `detail`, `trace_id`, one read index, one `CheckConstraint`, no unique constraint.
  Add `PyPIReleaseSnapshot`, table `pypi_release_snapshots`, plus `requires_python`
  (`CharField`, new `_SPECIFIER_LENGTH = 128`, blank default `""`). Constraint
  `PYPI_FACTS_CONSTRAINT = "pypi_facts_present_exactly_when_observed"`:
  `(state=ok & latest_version != "") | (state != ok & latest_version == "" & released_at IS NULL & requires_python == "")`.
  Index `PYPI_READ_INDEX = "pypi_release_pkg_observed"` on `(package, -observed_at)`. Update the module
  docstring (three tables).
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/0003_pypi_release_snapshots.py`
  -- new; depends on `("collectors", "0002_source_release_snapshots")` and
  `("identity", "0001_package_identity")`. `tests/unit/django_apps/test_migration_completeness.py`
  fails without it.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py` -- **new**, shaped
  on `source_release.py`: `COLLECTOR_NAME = "pypi_release"`; derived declarations (cadence
  `timedelta(days=1)`, `TOLERATED_MISSED_RUNS = 1`, freshness target `cadence * 2`, window
  `cadence / 2`, retries `DEFAULT_RETRIES`, timeout `5.0` reconciled by `worst_case_call_seconds`,
  `RateLimit(calls=60, per=timedelta(minutes=1))` -- PyPI publishes no numeric ceiling, so this is a
  declared courtesy bound and the docstring says so, headers `{"Accept": "application/json",
  "User-Agent": USER_AGENT}`, cache TTL `timedelta(days=7)` -- PyPI serves an `ETag`);
  `PYPI_HOST = "pypi.org"`; `MAX_DOCUMENT_CHARACTERS = 32 * 1024 * 1024` (the project document lists
  every file of every release; large projects run to several MiB); `PyPILocatorError(ValueError)`,
  `PyPIDocumentError(ValueError)`; frozen `ReleaseIdentity(outcome, primary_type, primary_purl)`;
  frozen `PyPIFacts(state, latest_version, released_at, requires_python, detail, source)`; pure
  `project_name(purl) -> str` (parse `pkg:pypi/<name>[@v][?q][#s]`, percent-decode, PEP 503
  normalise `re.sub(r"[-_.]+", "-", name).lower()`, refuse anything not matching
  `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`), `project_locator(purl) -> "https://pypi.org/pypi/{name}/json"`,
  `pypi_facts(body, *, source) -> PyPIFacts`; `PyPIReleaseCollector(Collector)` with
  `inapplicability` (one identity read, remembered on the instance as `_identity`, plus `_locator`
  as S01 does), `source_for`, `translate` (one row, never none), `sentinel_evidence` (rows for
  `ERROR`, `NOT_FOUND`, `NOT_APPLICABLE`; refuse the rest with `is not` comparisons -- a literal
  holding two `OutcomeState` members outside `core/outcomes.py` fails
  `tests/unit/django_apps/test_single_ordering_audit.py`).
- `src/django_apps/conda_package_supply_chain_monitor/identity/models.py` -- read only:
  `Package.primary_purl`, `Package.primary_type` (line ~368), `PackageMapping` (`kind`, `outcome`;
  `MappingKind.RELEASE_ECOSYSTEM`; `MappingOutcome` values `established`/`not_applicable`/...).
  `ESTABLISHED` is exported; the sentinel values are `OutcomeState`'s strings.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` -- `collect_source_release`
  (line ~1139) is the template. Add `COLLECT_PYPI_RELEASE_TASK_NAME = "cpm.collect.pypi_release"` and
  `collect_pypi_release(*, package_id, force=False) -> str`; `__all__`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` -- add
  `PyPIReleaseCollector` to the roster tuple in `ready()` (same guard).
- `docs/deployment.md` -- new section after "The upstream-release collector reads GitHub
  unauthenticated": the PyPI collector reads pypi.org unauthenticated; the declared allowance and what
  it is; how applicability is decided from identity; what a `not_applicable` row means; that a
  package with no established release-ecosystem identity fails the run rather than being guessed at.
- `tests/collectors.py` -- `collector_class` factory (line ~572) and the `*_collector_class`
  subclass helpers. Add `inapplicable_collector_class(*, declared_model, reason=A_REASON)` overriding
  `inapplicability`; add `A_NOT_APPLICABLE_REASON` constant.
- `tests/unit/django_apps/test_collection.py` -- add: the fixture collector's `inapplicability`
  returns `""`; the hook takes its argument by keyword (mirror
  `test_sentinel_evidence_takes_every_argument_by_keyword`).
- `tests/integration/django_apps/test_collection.py` -- `DISTINCT_COLLECTION_EVENTS` 6 -> 7 and
  the event lists in `test_every_event_the_base_emits_is_dotted_and_carries_the_same_keys`. Add: an
  inapplicable collector writes one `not_applicable` row and finalizes `succeeded` with the reason
  as `detail`; the transport is never called and the limiter never asked (a `FixedLimiter`
  refusing everything still yields success); the window skips a second run and `force` bypasses it;
  the event is emitted with `EVENT_KEYS`; a sentinel that refuses `NOT_APPLICABLE` surfaces
  `CollectorConfigurationError` and the ledger row finalizes `failed`.
- `tests/unit/django_apps/test_pypi_release.py` -- **new**, mirror `test_source_release.py`:
  declarations and derivations (target = cadence x (1 + tolerated), strictly greater than cadence;
  worst case inside `settings.CELERY_TASK_SOFT_TIME_LIMIT` with margin; no conditional header
  declared; task name routes to `Queue.COLLECT`), every `project_name` refusal and normalisation
  case, every `pypi_facts` row in the matrix, the three sentinel shapes and the two refusals, a
  source sweep asserting the module names `Package`/`PackageMapping` and reaches for no write method.
- `tests/unit/django_apps/test_source_release.py` -- untouched if the re-exports hold; if a case
  asserts the moved names' *defining* module, point it at the new home.
- `tests/integration/django_apps/test_pypi_release.py` -- **new**, mirror
  `test_source_release.py`'s `_a_package`/`_collect`/`_rows`/`_run` helpers, with `_a_package`
  taking `outcome`, `primary_type`, `primary_purl` and creating the `PackageMapping` row. Cases:
  every matrix row that needs a run; AC 2 and AC 3 read back through
  `PyPIReleaseCollector.freshness(...)` (`stale is False`, status carried) with the paired
  never-observed case reading `UNOBSERVED_STATUS`; the task collects / skips / forces and returns the
  run state; each conjunct of the constraint (`IntegrityError` inside `transaction.atomic()`);
  re-observation inserts.
- `tests/unit/test_model_registry.py` -- `EVIDENCE_MODEL_LABELS` gains `"collectors.PyPIReleaseSnapshot"`.
- `tests/integration/startup/test_stage_two_collector_registry.py` -- roster is three names.
- `tests/unit/django_apps/test_collector_base_audit.py` -- `THE_PYPI_COLLECTOR` anchor in `THE_NEW_MODULES`.
- `tests/unit/django_apps/test_task_routing_audit.py` -- `A_COLLECTOR_TASK` is literally
  `"cpm.collect.pypi_release"` and `tests/celery_tasks.py`'s `registered_tasks` refuses a name the
  registry already holds; rename the fixture constant to `"cpm.collect.fixture_release"`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- `cpm-currency-s02-pypi-release-evidence`
  to `in-progress` at implementation, `done` at finalization.

## Tasks & Acceptance

**Execution:**
- `core/transport.py`, `collectors/agent.py`, `collectors/source_release.py` -- move
  `worst_case_call_seconds` and the User-Agent identity to shared homes; re-export from
  `source_release` -- two collectors may not import each other.
- `core/collection.py` -- `inapplicability` hook, the `not_applicable` branch before `source_for`,
  the new event, docstrings -- the base owns which sentinel and that there is always one.
- `tests/collectors.py`, `tests/unit/django_apps/test_collection.py`,
  `tests/integration/django_apps/test_collection.py` -- the base's own contract for the new branch,
  event count 7.
- `collectors/models.py`, `collectors/migrations/0003_pypi_release_snapshots.py` -- the table, index,
  constraint -- Appendix A.2's `pypi_release_snapshots`.
- `collectors/pypi_release.py` -- declarations, pure functions, the collector -- `CPM-AD-27`'s split.
- `collectors/tasks.py`, `collectors/apps.py` -- the task and its adoption.
- `tests/unit/django_apps/test_pypi_release.py`, `tests/integration/django_apps/test_pypi_release.py`
  -- every matrix row covered by a test that ran.
- `tests/unit/test_model_registry.py`, `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py`, `tests/unit/django_apps/test_task_routing_audit.py`
  -- rosters and the fixture-name collision.
- `docs/deployment.md` -- the operator's view of the new collector.

**Acceptance Criteria:**
- Given a package whose `release_ecosystem` mapping is `established` with `primary_type="pypi"`, when
  `collect_pypi_release(package_id=...)` runs against a source serving the project document, then one
  `pypi_release_snapshots` row carries `state="ok"`, `info.version`, the earliest upload instant of
  that version's files and `info.requires_python`, and the ledger row is `succeeded`.
- Given the source answers 404, when the collector runs, then the row carries `not_found`, the
  ledger is `succeeded`, and `PyPIReleaseCollector(...).freshness(package_id=..., now=...)` reports
  `stale is False`.
- Given a package whose `release_ecosystem` mapping is `not_applicable` (or established for another
  ecosystem), when the collector runs, then the row carries `not_applicable`, the ledger is
  `succeeded`, the transport was never called, the limiter never asked, and the freshness read
  reports `stale is False` with the status carried through.
- Given the two existing collectors, when the full suite runs, then no case of theirs changed.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage at or above the floor.

## Spec Change Log

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 0, medium 2, low 14)
- defer: 2: (high 0, medium 0, low 2)
- reject: 6: (high 0, medium 0, low 6)
- addressed_findings:
  - `[medium]` `[patch]` The identity read was cached for the collector instance's whole life,
    not per run, so one instance collecting a package twice — a suppressed run then a forced
    one, or a future sweep reusing a collector — would answer the second run from the first
    run's mapping. A resolution that moved from `unknown` to `established` between them stayed
    refused. `inapplicability` now clears the cache at the start of every run, which keeps the
    one-query-per-run property the counting case pins and makes each run read fresh.
  - `[medium]` `[patch]` The locator was bounded by nothing, while the row's `source` column
    takes 512 and `Package.primary_purl` is 512 wide too — so a valid purl with a very long
    name built a locator PostgreSQL refuses at insert and SQLite stores. That is the `R-5`
    parity gap this module already closed for its two other text columns, and it fired *after*
    the call had been made. `project_locator` now refuses an over-wide locator where the value
    enters, through the same column-width read `_require_storable` uses.
  - `[low]` `[patch]` An `established` mapping carrying a blank `primary_type` was recorded as
    `not_applicable` — an observation derived from an identity row that contradicts itself.
    It now returns no reason and is refused by `source_for` instead.
  - `[low]` `[patch]` The version and the specifier were stripped while three docstrings and a
    test claimed they were stored exactly as spelled. The stripping stays — a stored version
    with surrounding whitespace breaks every later comparison — and the prose now says so;
    `_earliest_upload` also falls back to the raw `info.version` key, so a padded version
    still finds its files and still dates.
  - `[low]` `[patch]` A subclass answering `inapplicability` with a non-string or a
    whitespace-only reason had it written into the row, the ledger and the log line.
    `_require_reason` refuses both at the hook, as `_sentinel` refuses a row that does not
    carry its state.
  - `[low]` `[patch]` The document ceiling was described as bounding memory and the soft limit,
    which it does not: the transport has already decoded the body by then. The wording now
    claims only what it does — it bounds the JSON decode.
  - `[low]` `[patch]` `__str__` rendered `(no release)` on every row without a version,
    including a `not_applicable` one — a row saying there is no release for a package the log
    records as never having been asked. It renders `(no version)`.
  - `[low]` `[patch]` Nothing asserted the Celery decorator's `name` matched the declared
    constant, so a renamed constant would route correctly in the queue test while the worker
    registered something else.
  - `[low]` `[patch]` The "established and pypi" rule was spelled twice; a single `asks_about`
    helper now serves both, so the hook cannot say "applies" while `source_for` refuses the
    same identity.
  - `[low]` `[patch]` The ceiling case allocated 32 MiB on every unit run; it patches the
    constant and asserts the message names the patched bound.
  - `[low]` `[patch]` The module said `info.version` is "PyPI's own latest" without saying what
    that means for prereleases and yanked releases — which is exactly what a currency
    comparison will depend on. The docstring now states it, and the yanked question is
    deferred rather than answered.
  - `[low]` `[patch]` The nonexistent-package case was asserted through `source_for` alone,
    while `collect()` never reaches that hook: the recorder refuses the key first. A case now
    drives `collect()` and asserts the real surface — `RunLedgerError`, no ledger row, no
    evidence row, no call.
  - `[low]` `[patch]` "The two existing collectors declare nothing new" was asserted on the
    fixture and on the unbound base method, not on the two real classes. It is now asserted on
    them by identity.
  - `[low]` `[patch]` AC 3 was proved only at age zero, where every row is fresh. A case now
    reads a `not_applicable` observation past the freshness target and asserts it *does* go
    stale, which is what makes the story's reading of "never marked stale against PyPI"
    explicit: what AC 3 forbids is staleness caused by absence from PyPI, not by not being
    re-observed.
  - `[low]` `[patch]` The docs and a test docstring said the window stops a sweep writing the
    same fact once per day; with a window of half the cadence it stops more than one per
    window, and they now say that.
  - `[low]` `[patch]` The operator documentation did not mention that an established mapping
    with a blank primary type is refused rather than recorded.

## Design Notes

**Why the base changes.** Evidence is written only by the base (`CPM-AD-7`, enforced by
`test_collector_base_audit.py`), and the base's only sentinels were the two a *call* can produce.
"Does not apply" is decided before any call, so it needs a hook that runs before `source_for` --
a collector that cannot name a locator for a non-Python package must not be asked for one. The
hook is non-abstract with a default of "applies", so the two shipped collectors declare nothing new.
The window still applies (`CPM-AD-7`: a second run inside the window is `skipped`); the limiter is
not charged because no request may be issued; the cache is not read because nothing is fetched.

**Why `not_applicable` is decided from identity, not from the canonical name.** `CPM-FR-1` says
"a package whose type makes a mapping inapplicable records `not_applicable` for that mapping" --
resolution already answers the question. A collector that inferred "Python" from a name would be
the guess `CPM-FR-1` forbids. A mapping that is `unknown`/`not_found`/`error` cannot be turned into
a PyPI question either, and it is refused (run `failed`, no row), on the terms
`SourceLocatorError` set in S01: the selection that offers only askable packages is
`CPM-CURRENCY-S05`'s. Record this as `deferred` on the spec if review agrees.

**Why the JSON API and one call.** `GET https://pypi.org/pypi/<name>/json` answers all four facts
in one document: `info.version` is PyPI's own "latest", `info.requires_python` is the specifier,
`releases[<version>]` dates it, and a project with no releases is a 404 (AC 2). The document is
large for big projects; the bound is a refusal to be surprised, not a guess at size.

**`released_at` is the earliest usable upload instant of the latest version's files** -- the moment
the version became installable. A version with no dated files leaves it NULL and says so in `detail`.

**Golden example (purl to locator):**
```python
project_locator("pkg:pypi/Zope.Interface@6.0?foo=bar#x")
# -> "https://pypi.org/pypi/zope-interface/json"
```

## Verification

**Commands:**
- `pixi run test` -- expected: exit 0, new unit module collected and passing.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: exit 0, no diagnostics.
- `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, `collectors/pypi_release.py` at 100%.

**Manual checks (if no CLI):**
- `git diff --stat 76c73d2` lists every file in the Code Map that was meant to change and none of
  the read-only ones (`identity/models.py`, `identity/services.py`, `core/outcomes.py`,
  `core/freshness.py`).

## Dev Notes

**Satisfies:** `CPM-FR-8`

**Governed by:**

- `CPM-AD-5` — One status type, fixed values, one precedence order
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
- Every `pytest.mark.django_db` case rolls back; `tests/integration/conftest.py` applies the
  integration marker by directory.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S02]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-5]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-8]

## Dev Agent Record

### Agent Model Used

Claude Fable 5.1, as a `bmad-build` implementation agent.

### Debug Log References

- `pixi run ci` -- exit 0. 4788 passed, 2 pre-existing skips, coverage 98.60% against a
  90% floor, with `collectors/pypi_release.py`, `collectors/agent.py`, `core/collection.py`
  and `core/transport.py` each at 100%.
- `pixi run makemigrations --check --dry-run` -- "No changes detected" after
  `0003_pypi_release_snapshots.py`.
- `pixi run format && pixi run lint && pixi run typecheck` -- clean.
- `git diff --stat --cached 76c73d2` -- every Code Map file and none of the read-only ones
  (`identity/models.py`, `identity/services.py`, `core/outcomes.py`, `core/freshness.py`).
- `pixi run gate-postgres` / `gate-redis` were **not** run in this session.

### Completion Notes List

**The base grew one hook and one branch.** `Collector.inapplicability(*, package_id)` is
non-abstract and answers `""` by default, so the two shipped collectors declare nothing new.
`collect()` asks it first, asks `source_for` only when the question applies, consults the
window over both, and then -- for a question that does not apply -- writes the
`not_applicable` sentinel through `_write_evidence`, emits `collection.not_applicable` with
`EVENT_KEYS` (`source=""`, because no locator exists on that path) and finalizes `succeeded`
with the reason. `_not_applicable` is a helper beside `_failed` so `collect()` stays under
ruff's complexity ceiling; the eighth return is licensed by the existing `noqa`.

**Two collectors may not import each other, so two things moved.** `worst_case_call_seconds`
went to `core/transport.py`, which already stated the arithmetic in prose; the `User-Agent`
identity (`DISTRIBUTION_NAME`, `PROJECT_URL`, `UNKNOWN_VERSION`, `distribution_version`,
`USER_AGENT`) went to a new `collectors/agent.py`. `source_release.py` re-exports all six
names, so every importer is untouched. One S01 unit case monkeypatched the *defining*
module's `version` and was pointed at `agent`, as the spec allowed.

**Applicability is a pure function over what resolution recorded.** `inapplicability_of`
was added beside the three named pure functions: it returns a reason for a mapping recorded
`not_applicable` or established for another type, and `""` otherwise -- including for an
unresolved mapping, which `source_for` then refuses as `PyPILocatorError`. The collector
makes one identity query (`PackageMapping` joined to `package__primary_type` /
`package__primary_purl`), remembered on the instance keyed by package so the two hooks agree
and a direct caller for another package is not answered about the last; an integration case
counts the queries. `inapplicability` also resets `_locator`, so a `not_applicable` row never
carries the previous package's locator on a reused instance.

**The purl is normalised before it names anything.** `project_name` drops `@version`,
`?qualifiers` and `#subpath`, percent-decodes, applies PEP 503, and refuses a name that does
not match the project-name grammar afterwards -- which is also what refuses `.` and `..`
(they normalise to `-`). The golden example resolves as the spec states.

**`released_at` is the earliest usable upload instant of the latest version's files**, and a
version with none is `ok` with `released_at` NULL and `detail` saying so; the constraint
permits exactly that. A blank `info.version` on a `200` is `not_found` with all facts
blanked, so the row satisfies the constraint's sentinel half.

**A `not_found` row carries no caveat.** PyPI is a public index; the base's own sentence is
the whole `detail`.

**`test_task_routing_audit.py`'s fixture task was renamed** to `cpm.collect.fixture_release`,
because the registry helper refuses a fixture registered over a task it already holds and
`cpm.collect.pypi_release` is now real.

**Review patch round (16 findings, all applied).** The identity read is now forgotten at the
start of every run (`inapplicability` clears it), so a long-lived instance reads fresh while
one run still costs one query. `project_locator` refuses a locator wider than the `source`
column (`_column_width` serves it and `_require_storable`). The "established and pypi" rule
has one spelling, `asks_about`, read by both `inapplicability_of` and `source_for`; an
`established` mapping with a blank type is refused rather than recorded. `core/collection.py`
checks the hook's answer (`_require_reason`): not a string, or whitespace-only, is a
`CollectorConfigurationError`. Versions and specifiers are documented as trimmed-then-verbatim,
and a padded `info.version` is looked up in `releases` by its raw spelling when the trimmed
key finds nothing. `MAX_DOCUMENT_CHARACTERS` prose says what the bound protects (the decode,
not the transfer); the module docstring says `info.version` is Warehouse's "latest" under
Warehouse's rules, dated regardless of `yanked`. `__str__` renders `(no version)`. Tests added:
the Celery binding, both boundaries of the locator width, the blank-type identity, the padded
version, the small-bound ceiling case (no 32 MiB allocation), the two hook-answer refusals,
the two shipped collectors not overriding the hook, `collect()` on a missing package leaving
no ledger row, identity re-read across two runs on one instance, and the aging case that
makes the spec's freshness reading explicit (a `not_applicable` row read past the target is
stale, status carried). Two `deferred` entries recorded: the `yanked` question, and the
sibling locator-width gap in `source_release.py`.

### File List

- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py` -- `inapplicability`
  hook, `_not_applicable`, `_require_reason`, `COLLECTION_NOT_APPLICABLE_EVENT`, the reordered
  opening of `collect()`, and the docstring updates (module, `sentinel_evidence`, eight
  returns, seven events).
- `src/django_apps/conda_package_supply_chain_monitor/core/transport.py` -- `worst_case_call_seconds`
  (moved in), `__all__`, module prose.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/agent.py` -- new; the shared
  `User-Agent` identity.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py` -- imports the
  moved names from their new homes and re-exports them; no behaviour change.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` -- `PyPIReleaseSnapshot`,
  `_SPECIFIER_LENGTH`, `PYPI_FACTS_CONSTRAINT`, `PYPI_READ_INDEX`, module docstring (three tables).
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/0003_pypi_release_snapshots.py`
  -- new; depends on `collectors.0002` and `identity.0001`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py` -- new; the
  declarations, `PyPILocatorError`, `PyPIDocumentError`, `ReleaseIdentity`, `PyPIFacts`,
  `project_name`, `project_locator` (width-bounded), `pypi_facts`, `asks_about`,
  `inapplicability_of`, `PyPIReleaseCollector`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` --
  `COLLECT_PYPI_RELEASE_TASK_NAME`, `collect_pypi_release`, `__all__`, docstring counts.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` -- roster of three.
- `docs/deployment.md` -- the operator section for the PyPI collector.
- `tests/collectors.py` -- `A_NOT_APPLICABLE_REASON`, `inapplicable_collector_class`,
  `refusing_inapplicable_collector_class`.
- `tests/unit/django_apps/test_collection.py` -- the default hook, its keyword-only signature,
  and the two shipped collectors not overriding it.
- `tests/integration/django_apps/test_collection.py` -- seven events; five `not_applicable`
  cases; the two hook-answer refusals.
- `tests/unit/django_apps/test_pypi_release.py` -- new.
- `tests/integration/django_apps/test_pypi_release.py` -- new.
- `tests/unit/test_model_registry.py`, `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py`, `tests/unit/django_apps/test_task_routing_audit.py`
  -- rosters, anchor, fixture-name collision.
- `tests/unit/django_apps/test_source_release.py` -- the version-fallback case patches `agent`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- `in-progress`.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** `CPM-FR-8`'s PyPI collector, and the base change AC 3 needed. The
collector base gained one optional hook -- `Collector.inapplicability(*, package_id)`, answering
`""` by default -- and one branch: a collector may say, before any locator is asked for, that its
question is not about this package, and the base then writes the `not_applicable` sentinel row
itself with no call made, no allowance spent and no cache read, finalizing the run `succeeded`
with the reason. That is what makes `CPM-FR-6`'s third state reachable through machinery `core`
owns rather than through a second evidence writer. `PyPIReleaseCollector` reads
`https://pypi.org/pypi/<name>/json` for a package whose `release_ecosystem` mapping resolution
recorded as `established` for `pypi`, and writes `pypi_release_snapshots`: the latest version PyPI
reports, the earliest upload instant of that version's files, the `Requires-Python` specifier, and
an explicit lookup state. Applicability is read from identity and never inferred from a name; an
*unresolved* mapping is refused rather than recorded, because "resolution has not decided" is not
"does not apply".

**Files changed.**

- `core/collection.py` — the `inapplicability` hook, the `not_applicable` branch and its
  `_not_applicable` helper, `_require_reason`, the seventh event `collection.not_applicable`.
- `core/transport.py` — `worst_case_call_seconds` moved here, where the arithmetic was already
  stated in prose.
- `collectors/agent.py` *(new)* — the shared `User-Agent` identity, so no collector imports
  another (`CPM-AD-7`).
- `collectors/source_release.py` — imports the six moved names from their new homes and
  re-exports them; no behaviour change.
- `collectors/models.py` — `PyPIReleaseSnapshot`, its read index and its four-conjunct
  `CheckConstraint`.
- `collectors/migrations/0003_pypi_release_snapshots.py` *(new)* — schema only.
- `collectors/pypi_release.py` *(new)* — the declarations, the pure locator, document and
  applicability functions, and the collector.
- `collectors/tasks.py`, `collectors/apps.py` — `cpm.collect.pypi_release` and a roster of three.
- `docs/deployment.md` — what an operator has to know: an unauthenticated read, a declared
  courtesy allowance, how applicability is decided, and what a `not_applicable` row means.
- New unit and integration modules, the base's own new cases, three frozen rosters, one scan
  anchor, and the routing audit's fixture task renamed off the name this story now occupies.

**Review findings.** 16 patched (0 high, 2 medium, 14 low), 2 deferred, 6 rejected. Four review
layers ran in parallel over the 4,500-line diff.

**Follow-up review recommended:** true. No high-severity patch, so the count decides it:
`3 x 2 + 1 x 14 = 20`, against a threshold of 5.

**The two medium findings were both about a bound that was never taken.** The identity read was
remembered for the collector instance's whole life rather than for the run, so a reused instance
would answer a second run from the first run's mapping — invisible through the task, which builds a
collector per call, and waiting for the sweep that does not. And the locator was bounded by
nothing while the column that stores it takes 512, which is the `R-5` parity gap this module
already argued for its other two text columns, firing after the call had been spent.

**A judgement the review made explicit rather than changed.** AC 3 says a package is "never marked
stale against PyPI for not being published there", and a `not_applicable` row still ages like every
other observation. The story's reading is that what AC 3 forbids is staleness *caused by* absence
from PyPI — which is what a package with no row would suffer, reading `unknown` and ageing from
there — and not staleness caused by not being re-observed. A case now reads such a row past the
freshness target and asserts it does go stale, so the reading is written down where a later story
meets it rather than left implicit in a case that only ever looked at age zero.

**Verification.** `pixi run ci` exits 0 — 4799 passed, 2 pre-existing skips, coverage 98.60%
against a 90% floor, with `collectors/pypi_release.py`, `collectors/agent.py`, `core/collection.py`
and `core/transport.py` each at 100%. `pixi run makemigrations --check --dry-run` reports "No
changes detected". Both were re-run by the orchestrating session after the patch round, against the
staged tree.

**Residual risks.** Five `deferred` entries. The two that matter for the rest of this epic: no
resolver populates `release_ecosystem` mappings yet, so a sweep that offered every package to this
collector today would fail every run — the selection that offers only askable packages is
`CPM-CURRENCY-S05`'s — and the declared 60/minute allowance is a courtesy bound this product chose
rather than a ceiling PyPI stated, unmeasured against a real sweep. `pixi run gate-postgres` and
`pixi run gate-redis` were not run in this session, so the new `CheckConstraint` and the `PROTECT`
relation are proved here on SQLite only; the sibling table's identical pattern passed PostgreSQL in
`CPM-CURRENCY-S01`, and CI runs both.
