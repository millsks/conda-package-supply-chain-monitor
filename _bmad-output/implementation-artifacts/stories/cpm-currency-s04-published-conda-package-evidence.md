---
title: 'CPM-CURRENCY-S04: Published conda package evidence'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '6cb6a2b4b76026f5314c4fc0901c43e8c8badba3'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s02-pypi-release-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s03-feedstock-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s07-watchlist-inventory-source.md
warnings:
  - oversized
deferred:
  - summary: >-
      The bounded call each further channel costs is not charged against the local allowance,
      so every collection spends more of the remote budget than the counter believes.
    evidence: |-
      The base charges `1 + retries` once, before the first call. `_channel_instead` is issued
      from `translate`, after that charge, exactly as `collectors/feedstock.py`'s two second
      calls are -- and unlike those, the number of them here is *configuration*, so the
      undercount grows with the declaration: four monitored channels means four calls against
      an allowance that saw one collection. Charging it would mean reaching past the base's
      orchestration into the limiter, and the arithmetic belongs with the story that first
      sweeps at volume (`CPM-CURRENCY-S05`).
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py -- _channel_instead
    severity: medium
  - summary: >-
      The declared allowance is a courtesy bound this product invented, not a rate anaconda.org
      stated, and nothing has measured it against a sweep.
    evidence: |-
      `CONDA_PACKAGE_RATE_LIMIT` is `RateLimit(calls=30, per=1 minute)`. anaconda.org publishes
      no numeric ceiling for its package API, so the number is a declared courtesy -- half what
      `collectors/pypi_release.py` declares against a source with the same silence, because a
      collection here issues up to `MAX_MONITORED_CHANNELS` calls rather than one. At the
      `1 + retries` the base charges that is seven packages a minute, which is not a rate that
      sweeps `CPM-NFR-1`'s ten thousand. It is also blind the way its siblings are: a remote
      refusal arrives as an ordinary transport failure and the local counter keeps granting.
      `CPM-CURRENCY-S05` is where the arithmetic is measured against a real sweep.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py -- CONDA_PACKAGE_RATE_LIMIT
    severity: medium
  - summary: >-
      `core/transport.py` transfers and decodes a whole response body before any collector's
      size ceiling is measured, so no ceiling in this product bounds the transfer.
    evidence: |-
      `MAX_DOCUMENT_CHARACTERS` bounds only the parse: by the time a body reaches this module
      the transport has already transferred it and decoded it to a string. The ceiling is worth
      more here than on the siblings -- a channel's package document lists every file of every
      version and is the largest body this product reads -- and it still buys only a refusal to
      spend a soft time limit parsing what no honest source serves. A real bound needs a
      streamed read with a byte cap in the transport, which is `core`'s and affects all five
      collectors. Recorded on `CPM-CURRENCY-S03` as well; restated because this story's
      documents are the biggest.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/transport.py -- RequestsTransport.fetch
    severity: medium
  - summary: >-
      Which package name a channel is asked about is the canonical name, and nothing resolves a
      conda name that differs from it.
    evidence: |-
      `source_for` builds every locator from `Package.canonical_name`. `identity` also carries
      `conda_purl`, which is the package URL naming the package *as a conda artifact*, and for
      a package whose conda name differs from its canonical one -- the PyPI-to-conda renames
      conda-forge carries, `pytorch` for `torch` among them -- every channel will answer `404`
      and this collector will record a `not_found` that is about the wrong name. Reading the
      conda purl means a mapping read, a refusal for an unresolved one, and the `CPM-UJ-2`
      argument that goes with it, which is a second identity posture rather than a line;
      nothing writes `conda_purl` yet either. `CPM-CURRENCY-S05`'s selection is where the
      askable set is decided.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py -- CondaPackageCollector.source_for
    severity: medium
  - summary: >-
      Which channels and platforms are monitored ships empty, so the collector observes nothing
      until an operator answers PRD Open Question 4.
    evidence: |-
      `CPM_MONITORED_CHANNELS` and `CPM_MONITORED_PLATFORMS` are assigned `()` in
      `config/settings/base.py` and every collection fails until they are declared -- a
      `CondaChannelError` naming the setting, a `failed` ledger row, and no evidence row. That
      is this story's Block If answered rather than a defect, and `docs/deployment.md` tells an
      operator exactly what the failure looks like. It is recorded here because a reader of
      the evidence tables will otherwise find `conda_package_snapshots` permanently empty and
      no other artefact says why.
    location: src/config/settings/base.py -- CPM_MONITORED_CHANNELS
    severity: low
  - summary: >-
      A platform carrying several builds of one version records one of them, and which build a
      solver would actually pick is not that simple.
    evidence: |-
      `_platform_fact` takes `max` by build number, ties broken by the greatest build string,
      and `detail` states both the rule and how many builds there were -- so nothing about the
      column is arbitrary or unreproducible. What it still is not is a prediction: a channel
      may hold two builds of one version for different variants -- a `py311` and a `py312` file
      share a subdir and a version -- and conda picks between them by the environment's own
      constraints, which this collector has none of. Recording all of them means a row per
      file, which is a different table shape.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py -- _platform_fact
    severity: low
  - summary: >-
      Only the first monitored channel's answer is cached, so channels two onward re-transfer
      their whole document on every run for ever.
    evidence: |-
      `CONDA_PACKAGE_CACHE_TTL` is declared and honoured -- by the *base*, around the one call
      the base makes. `_channel_instead` passes `entry=None` to `request_headers`, so its
      requests carry no validator, and it neither remembers nor forgets, so nothing is written
      back. A channel's package document lists every file of every version and is the largest
      body this product reads, so a four-channel declaration re-transfers three of them every
      day for ever -- and a `304` from one of them is a source answering a question nobody
      asked, which the row records as `error`. Extending the cache to them means reaching past
      the base's orchestration into the response cache, and belongs with the story that first
      sweeps at volume (`CPM-CURRENCY-S05`).
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py -- _channel_instead
    severity: medium
  - summary: >-
      A permanent misconfiguration leaves the task the same way a transient failure does, so a
      retry policy would turn the shipped empty declaration into an unbounded loop.
    evidence: |-
      `collect_conda_package` lets `CondaChannelError` escape as an ordinary exception.
      Celery cannot tell it from a socket timeout, and no retry will make an undeclared channel
      declared -- so under a retry policy an unconfigured component would spend its allowance on
      a series of identical failed collections, each writing a ledger row saying the same thing.
      Nothing declares `autoretry_for` today, so the loop is not reachable in this tree; the
      task documents the hazard instead. Separating a permanent refusal from a transient failure
      at the task boundary is a decision about every collector's task rather than this one's.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py -- collect_conda_package
    severity: medium
  - summary: >-
      `collectors/feedstock.py` describes its bounded second call as un-retried, and it is not.
    evidence: |-
      The same false premise this story corrected for the published-package collector: the call
      goes through the shared `RequestsTransport`, whose mounted retry policy applies to every
      request that session issues. Feedstock's worst case still fits inside the inherited soft
      limit because it makes at most two calls where this collector makes up to four, so the
      arithmetic is safe and only the description is wrong. Correcting it means editing a
      shipped collector, which this story's Never list forbids.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py -- FEEDSTOCK_TIMEOUT
    severity: medium
  - summary: >-
      This is the first collector whose evidence for one package is a matrix, and nothing says
      how several rows sharing one instant collapse into one package-level answer.
    evidence: |-
      `core/freshness.py`'s `latest_observation` returns one `Max(observed_at)` for the whole
      package and `Collector.freshness` takes the status from its caller, so a package with `ok`
      on one channel, `not_found` on another and `error` on a third has no defined reading --
      and adding a platform to the declaration leaves the package reading fresh while the new
      pair has never been observed. The rule belongs with the read surface that first asks the
      question, which is `CPM-CURRENCY-S06`'s currency policy.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/freshness.py -- latest_observation
    severity: medium
  - summary: >-
      The monitored declaration is remembered on the collector instance, so two concurrent
      collections through one instance could read each other's channels.
    evidence: |-
      `_monitored`, `_package_name` and `_locator` are instance attributes written by
      `source_for` and read by `translate` and `sentinel_evidence`, on the terms
      `CPM-CURRENCY-S01` through `CPM-CURRENCY-S03` set. Unreachable through the task, which
      builds a collector per call, and through every case, which collects once per instance;
      it becomes reachable the day something reuses one instance across threads. Passing the
      declaration through `translate`'s arguments would need a base signature change.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py -- CondaPackageCollector
    severity: low
---

# CPM-CURRENCY-S04: Published conda package evidence

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

<intent-contract>

## Story

As a packaging engineer,
I want published version and build string recorded per monitored channel,
so that what is actually installable is visible alongside what the recipe says.

## Acceptance Criteria

1. **Given** the monitored channels
   **When** the conda package collector runs
   **Then** each channel produces its own observation, and channels are never merged
   **And** each records published version, build string and channel

## Intent

**Problem:** `CPM-FR-10` needs the fourth surface collector. Nothing records what is
actually installable: a package can be current upstream, current on PyPI and current in the
recipe while the built artifact on a channel is months behind, and `CPM-FR-16`'s currency
comparison has no published version to compare against.

**Approach:** Add `CondaPackageCollector` on the base's per-package path, writing
`conda_package_snapshots` (PRD Appendix A.2). Which channels and platforms are monitored is
PRD Open Question 4 and is **configuration**, not a constant: settings declares both, they
ship empty, and a run refuses until an operator declares them -- the posture
`CPM-IDENTITY-S07` established for the inventory watchlist. One call per channel; one row per
`(channel, platform)`, so nothing is ever merged.

## Boundaries & Constraints

**Always:**
- Every evidence row is written by the base through `_write_evidence` (`CPM-AD-7`); the
  collector never saves a row and never opens a transaction.
- Every row carries the channel and the platform it is about. A channel's observation is
  never combined with another channel's, and a row never stands for two platforms.
- The published version is the one the channel itself states as latest. This collector
  performs no version comparison of its own (`CPM-AD-8`; `CPM-FR-16` is a policy pass).
- Presence is a `state` column over `OutcomeState`, emitted verbatim (`CPM-AD-5`,
  `CPM-AD-24`). Never a boolean, never a `*_status`/`*_outcome` name.
- A `(channel, platform)` pair with no published artifact is a written `not_found` row, never
  a missing one.
- Which channels and platforms are monitored is read from settings at run time. Nothing under
  `src/django_apps/` imports `config` (inherited `AD-4`): the settings *access* is a read of a
  value the platform composed, exactly as `collectors/apps.py` reads the watchlist path.
- Time comes from the injected clock; every row carries the run's instant.
- All I/O goes through the base's transport seam; nothing is fetched from
  `sentinel_evidence`.
- `pixi` is the only runner; `pixi run ci` exits 0 at the end.

**Block If:**
- Answering "which channels and platforms are monitored" would require choosing them. It is
  PRD Open Question 4 and is not this story's to answer: this story ships the *mechanism* and
  an empty declaration, and a run that finds nothing declared fails loudly saying so. If
  review finds that indefensible, HALT.

**Never:**
- No authentication or credential for the channel API.
- No schedule, no `CELERY_BEAT_SCHEDULE` entry, no per-task time limit.
- No version normalisation, comparison or ranking anywhere in this story.
- No change to `core/freshness.py`, `OutcomeState`, `identity`'s writers, or the three
  shipped collectors. `core/collection.py` may gain **one additive, defaulted hook** if and
  only if the per-`(channel, platform)` guarantee above cannot otherwise be kept -- on the
  terms `CPM-CURRENCY-S02` added `inapplicability`: non-abstract, with a default that leaves
  every existing collector's behaviour byte-identical. Nothing else in the base changes.
- No collector imports another (`CPM-AD-7`).
- No `repodata.json` read. A channel's per-platform index is hundreds of megabytes; this
  collector reads the per-package document instead.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Published on one channel and platform | one channel, one platform declared; the channel serves the package with a file on that platform | One `ok` row: `channel`, `platform`, `published_version` (the channel's own latest), `build_string`, `build_number`, `source`; ledger `succeeded` | No error |
| Several channels (AC 1) | two channels declared, both serve the package | Two rows, one per channel, each naming its own channel and carrying its own version and build; never one merged row; the run makes one call per channel | No error |
| Several platforms | one channel, two platforms declared, both have files | Two rows, one per platform, each with that platform's own build string | No error |
| Latest version absent from a platform | channel's latest version has files only on another platform | `not_found` row for that `(channel, platform)`, `detail` naming the version that exists elsewhere; the other platform's row is `ok` | No error |
| Package absent from a channel | the channel does not serve the package at all | One `not_found` row **per declared platform** for that channel; other channels unaffected | Read from the channel's answer, not from the base's sentinel |
| Every channel absent | no channel serves the package | A `not_found` row per `(channel, platform)`; ledger `succeeded` | The base's sentinel is not the path here |
| One channel fails, another answers | first channel answers, second raises a transport failure | The answering channel's rows are written and the failing channel's `(channel, platform)` rows carry `error` with the reason; ledger `succeeded`; nothing is lost | A channel's failure never discards another channel's answer |
| The only channel fails | one channel declared, it raises | `error` rows for its platforms; ledger `failed` | `CPM-FR-15`'s partial success has nothing to be partial about |
| Nothing declared | `CPM_MONITORED_CHANNELS` or `CPM_MONITORED_PLATFORMS` empty | `CondaChannelError` (a `ValueError`) from `source_for`; ledger `failed`; no evidence row; the message names the setting and says an operator must declare it | Refused, never defaulted |
| Setting absent entirely | the settings module declares no such name | `ImproperlyConfigured` at `AppConfig.ready()`, on the terms the watchlist setting is refused | Boot refusal |
| Unusable channel or platform name | a declared entry that is blank, not a string, or carries a path separator | `CondaChannelError`; ledger `failed`; no row | Refused rather than encoded |
| Duplicate declarations | the same channel or platform declared twice | Refused: two identical rows for one observation would be two facts where there is one | Refused at read |
| Unreadable document | body over the bound, not JSON, not an object, a field of the wrong type, or a value wider than its column | `CondaDocumentError` from `translate`; base writes `error` row and re-raises; ledger `failed` | Refused rather than partly read |
| No latest version stated | the channel serves the package but names no latest version | `not_found` rows with `detail` saying the channel named none | No error |
| Spent allowance | limiter refuses | `error` row, ledger `failed`, `collection.refused_by_rate_limit` | Base path |
| Revalidated answer | cached entry, first channel answers 304 | The rows a 200 would have written; entry refreshed | Base path |
| Sentinel asked for `ok`/`unknown` | `sentinel_evidence(state=OK)` | `CollectorConfigurationError` | Refused at the call |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/collectors/feedstock.py` -- the closest
  template and the most recently reviewed. Reuse its shape wholesale: the branch/identity
  read remembered per run and reset at the start of `inapplicability`, the
  `_require_storable` / `_column_width` guards, the pure-function split, the three-state
  sentinel, the bounded extra call whose every failure becomes a sentence in `detail` rather
  than an exception, and the distinction it now draws between *asked and absent* and *could
  not ask*. Read it and its story's Review Triage Log before writing anything -- the twenty-
  three findings there are the mistakes not to repeat.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py` -- the
  `_optional_string` / document-shape refusals, and the "the source states its own latest"
  posture this story takes for `published_version`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/agent.py` -- `USER_AGENT`.
- `src/django_apps/conda_package_supply_chain_monitor/core/transport.py` --
  `worst_case_call_seconds`, `DEFAULT_RETRIES`, `Payload`.
- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py` -- read only. The
  `inapplicability` hook, the window, the limiter, `_write_evidence` (which accepts a
  **sequence** of rows -- this is the first per-package collector that returns more than
  one), and the `not_found` branch that bypasses `translate`, which is why absence is read
  from the channel's own answer rather than left to the base's sentinel wherever more than
  one row is owed.
- `src/django_apps/conda_package_supply_chain_monitor/core/collection.py` -- the one
  additive, defaulted hook the amended spec permits: `Collector.sentinel_evidence_rows`, the
  private `_sentinel_rows` check that replaces `_sentinel`, and the four call sites that now
  write whatever the hook returns.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` -- the three
  existing snapshot models are the template. Add `CondaPackageSnapshot` /
  `conda_package_snapshots`: `package` (`PROTECT`), `source`, `state`, `channel`, `platform`,
  `published_version`, `build_string`, `build_number` (nullable), `detail`, `trace_id`; read
  index on `(package, -observed_at)`; a `CheckConstraint` making the published facts present
  exactly on a determinate row, and a second requiring `channel` and `platform` on **every**
  row -- a row that cannot say which channel and platform it is about is not an observation.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/` -- `0004` is
  newest; add `0005_conda_package_snapshots.py`.
- `src/config/settings/base.py` -- assigns `INVENTORY_WATCHLIST_PATH` at line ~305 with the
  reasoning for reading at import time. Assign `CPM_MONITORED_CHANNELS` and
  `CPM_MONITORED_PLATFORMS` beside it, both empty, both with a comment saying they are PRD
  Open Question 4's and that a run refuses until they are declared.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` --
  `WATCHLIST_PATH_SETTING` and its `ImproperlyConfigured` refusal are the template for
  refusing an *absent* channels or platforms setting at boot; the roster tuple becomes five.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` --
  `COLLECT_CONDA_PACKAGE_TASK_NAME = "cpm.collect.conda_package"` and `collect_conda_package`.
- `tests/collectors.py` -- `RecordedTransport`, `ScriptedTransport` (moved here by
  `CPM-CURRENCY-S03`, and the one this story needs -- several locators, one per channel),
  `FixedLimiter`, `RecordingResponseCache`, `recorded_payload`, `cached_response`.
- `tests/unit/django_apps/test_feedstock.py` / `tests/integration/django_apps/test_feedstock.py`
  -- the module shapes to mirror, including the AST source sweeps, the one-ask-many-requests
  assertion, the distractor mapping in the package helper, and the freshness read with its
  never-observed and ageing controls.
- `tests/unit/test_settings.py` -- where a new settings key is asserted; add the two.
- `tests/unit/test_model_registry.py`, `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py` -- the three frozen rosters.
- `docs/deployment.md` -- the three collector sections are the template; this one must also
  tell an operator that the component observes nothing until channels and platforms are
  declared, and what the failure looks like until then.

## Tasks & Acceptance

**Execution:**
- `config/settings/base.py`, `tests/unit/test_settings.py` -- the two declarations, empty,
  with the reasoning; asserted in all four settings modules.
- `collectors/models.py`, `collectors/migrations/0005_conda_package_snapshots.py` -- the
  table, its read index and its two constraints -- a row that cannot name its channel and
  platform is not an observation.
- `collectors/conda_package.py` -- new. Declarations (cadence daily, `CPM-NFR-2`'s fast end
  for a published-artifact surface; the derived target and window; the allowance; the shared
  `User-Agent`; a cache lifetime longer than the cadence). Pure functions:
  `monitored(channels, platforms)` (refuse empty, blank, mistyped, duplicated, or
  separator-carrying entries), `package_locator(channel, name)`, and `channel_facts(body, *,
  channel, platforms, source)` returning one fact per platform. Then `CondaPackageCollector`,
  whose `translate` writes the first channel's rows from the base's payload and makes one
  bounded call per remaining channel, never letting one channel's failure discard another's.
- `collectors/tasks.py`, `collectors/apps.py` -- the task, the boot refusal for an absent
  setting, and a roster of five.
- `tests/unit/django_apps/test_conda_package.py` -- new. Every matrix row that needs no run,
  plus the module's own AST source sweeps.
- `tests/integration/django_apps/test_conda_package.py` -- new. Every matrix row that needs a
  run: two channels producing two unmerged rows, two platforms producing two rows, a failing
  channel beside an answering one, absence per `(channel, platform)`, the refusal when
  nothing is declared, the window and `force`, the allowance, the cache and the `304`, the
  task, each constraint conjunct, the freshness read with its two controls, and
  re-observation.
- `tests/unit/test_model_registry.py`, `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py` -- the three rosters.
- `docs/deployment.md` -- the operator section, including that nothing is observed until the
  two settings are declared.

**Acceptance Criteria:**
- Given two monitored channels that both serve the package, when the collector runs, then two
  rows exist, each naming its own channel, and no row names two channels.
- Given a monitored channel and two monitored platforms, when the collector runs, then each
  platform has its own row carrying that platform's build string.
- Given one channel that answers and one that fails, when the collector runs, then the
  answering channel's rows are written and the failing channel's carry `error`.
- Given no declared channels, when the collector runs, then the run fails with a message
  naming the setting and no evidence row is written.
- Given a `(channel, platform)` with no published artifact, when the collector runs, then a
  `not_found` row exists for it carrying this run's instant.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

### 2026-09-06 — Amended after the first implementation pass

**Triggering finding.** The implementer reported, and the diff confirmed, that when the
**first** declared channel answers `404` or fails, the base writes one sentinel row and
`translate` is never reached -- so the remaining channels are never asked at all. A package
absent from the first channel but published on the second recorded nothing whatever about
the second. That is AC 1's "each channel produces its own observation" failing outright, and
it is the matrix's "Package absent from a channel ... other channels unaffected" row not
holding.

**What was amended.** The Never item forbidding any change to `core/collection.py`. It was
this spec's scoping choice rather than anything the story, the epic or the architecture asks
for -- `CPM-CURRENCY-S02` changed the same module, additively and correctly, when its
acceptance criterion could not be met without it. The item now permits exactly one additive,
defaulted hook on the same terms, and forbids everything else in the base.

**Known-bad state avoided.** Leaving the item as written forced a choice between two bad
outcomes: an implementation that silently drops every channel after a failing first one, or
a HALT on a contradiction inside the contract that only this spec had created.

**KEEP.** Everything already built survives re-derivation: the two `CheckConstraint`s
(especially `conda_package_names_channel_and_platform`, which makes AC 1 a database rule);
`translate` returning a sequence and `_channel_instead` being total, so no channel's failure
discards another's rows; the settings pair shipping empty with a boot refusal for absence and
a run refusal for emptiness; the bounded channel count with its soft-limit reconciliation at
the ceiling; and `sentinel_evidence` refusing `not_applicable` along with `ok` and `unknown`.

## Review Triage Log

### 2026-09-06 — Review pass

- intent_gap: 0
- bad_spec: 1: (high 1, medium 0, low 0)
- patch: 26: (high 4, medium 13, low 9)
- defer: 4: (high 0, medium 4, low 0)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[bad_spec]` The first implementation pass reported that when the **first**
    declared channel answered `404` or failed, the base wrote one sentinel row, `translate`
    was never reached, and every remaining channel went unasked — so a package absent from the
    first channel and published on the second recorded nothing at all about the second. That
    is AC 1 failing outright. The root cause was this spec's own Never item forbidding any
    change to `core/collection.py`, which nothing in the story, the epic or the architecture
    asks for. The item was amended to permit one additive, defaulted hook on the terms
    `CPM-CURRENCY-S02` added `inapplicability`, and the code was re-derived. See the Spec
    Change Log.
  - `[high]` `[patch]` Every call this collector makes is retried — the transport mounts its
    retry policy on the session — so the "un-retried second call" the timeout, the channel
    ceiling, the operator documentation and the reconciliation test were all sized against did
    not exist. The real worst case at four channels was about ninety-two seconds against a
    sixty-second soft limit: a killed task writing no rows, which is the failure the ceiling
    exists to prevent. The retry count is lowered, the arithmetic is reconciled at the
    ceiling, and a second case asserts the shared default would not fit.
  - `[high]` `[patch]` The relaxed sentinel check let determinate rows land under a `failed`
    ledger row: `_write_sentinel` runs after the run is already failed, and the check
    constrained only one row of the set. A row carrying `ok` is now refused on the `error` and
    `not_applicable` paths and still permitted on `not_found`, where it is legitimate.
  - `[high]` `[patch]` A mistyped platform was recorded as a published-artifact absence —
    `linux_64` passed the grammar and produced a row saying the channel's latest version has
    no file on a subdir that does not exist, permanently and indistinguishably from a true
    absence. Declared platforms are checked against conda's closed subdir vocabulary.
  - `[high]` `[patch]` Labels were ignored while the row claimed to be what a fresh install
    resolves to, so a release candidate on a non-default label was recorded as the channel's
    published version. The claim is withdrawn and the row now names the observed file's labels
    whenever they exclude the default one.
  - `[medium]` `[patch]` Thirteen further findings, each addressed: the bounded call's failure
    handling was narrower than its stated invariant; the plural hook could raise from a path
    that must not; the state check was satisfied by any field that happened to equal the
    state's value; the boot refusal tested presence but not shape, so the most plausible
    misconfiguration booted clean; the response cache covered one call in four with nothing
    saying so; a half-declaration built a row the database refuses and let a raw integrity
    error escape; the table had no index for the read it exists to serve; nothing asserted the
    declared headers reached any call but the first; a refusal named the wrong hook; the
    build tie-break was undocumented and its detail misstated; a package removed mid-run let a
    bare model exception escape; the task's permanent misconfiguration was indistinguishable
    from a transient failure to the queue; and the document ceiling was sized without regard
    to how many are parsed inside one soft limit.
  - `[low]` `[patch]` Nine further findings: the ceiling's four channels are now exercised end
    to end; a foreign-package row set is characterised; the reference fixture no longer calls
    a raisable hook from one that must not raise; the operator documentation enumerates all
    four meanings of an absence rather than two; two prose deferrals point at real entries; a
    floating documentation comment became a plain one; the decode refuses two more ways a body
    can fail to be a string; and the ceiling case has a named constant of its own.

## Design Notes

**Why one row per `(channel, platform)` rather than per channel.** AC 1 forbids merging
channels; a build string is a property of a *build*, which is per platform, so a row that
named a channel and one build string would already have merged the platforms to produce it.
Splitting on both is the only shape in which no row stands for two of anything, and it makes
"installable on linux-64 but not osx-arm64" expressible, which is what a packaging engineer
reading this table is looking for.

**Why several rows come out of one collection rather than several runs.** The observation
window and the ledger row are per `(collector, package)`, so collecting each channel as its
own run would have the second channel suppressed by the first. `translate` returns a sequence
and the base inserts it -- this is the first per-package collector to use that, and it is
what `CPM-FR-15`'s partial success looks like on the per-package path: one channel's failure
becomes `error` rows for that channel and never discards another channel's answer.

**Why the channels are configuration and ship empty.** PRD Open Question 4 is unresolved and
explicitly blocks this epic. Choosing a channel here would answer it by default and would be
wrong in exactly the way `CPM-IDENTITY-S07`'s watchlist would have been wrong if it had
shipped populated: a component that monitored a channel nobody chose would record facts about
the wrong surface, permanently. So the mechanism ships, the declaration ships empty, and the
run fails loudly naming the setting -- which is the same trade the watchlist makes and the
same one `docs/deployment.md` already explains to operators.

**Golden example:**

```python
package_locator("conda-forge", "numpy")
# -> "https://api.anaconda.org/package/conda-forge/numpy"
```

## Verification

**Commands:**
- `pixi run test` -- expected: exit 0, the new unit module collected and passing.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: exit 0, no diagnostics.
- `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, `collectors/conda_package.py` at 100%.
- `pixi run gate-postgres` -- expected: exit 0; the new constraints are enforced there.

**Manual checks (if no CLI):**
- `git diff --stat 6cb6a2b` names every Code Map file that was meant to change and none of
  the read-only ones (`core/`, `identity/`, and the three shipped collector modules).

## Dev Notes

**Satisfies:** `CPM-FR-10`

**Governed by:**

- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts

**Constrained:** which channels and platforms are monitored is PRD Open Question 4. The
collector reads them as configuration.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S04]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-10]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context), as a `bmad-build` implementation agent.

### Debug Log References

- `pixi run ci` -- exit 0. 5265 passed, 2 pre-existing skips, coverage 98.70% against a 90%
  floor, with `collectors/conda_package.py`, `collectors/models.py`, `collectors/tasks.py`,
  `collectors/apps.py` and `core/collection.py` each at 100%.
- `pixi run manage makemigrations --check --dry-run` -- "No changes detected" after
  `0005_conda_package_snapshots.py`.
- `pixi run gate-postgres` -- exit 0; the suite passed against `postgres:17`, so both new
  `CheckConstraint`s and the `PROTECT` relation are proved on PostgreSQL and not only on
  SQLite. `pixi run gate-redis` was **not** run in this session.
- `git diff --cached --stat 6cb6a2b` -- every Code Map file that was meant to change and none
  of the read-only ones (`core/`, `identity/`, `collectors/source_release.py`,
  `collectors/pypi_release.py`, `collectors/feedstock.py`). `tests/collectors.py` is
  unchanged: `ScriptedTransport`, which `CPM-CURRENCY-S03` moved there, already answers each
  locator from its own script, which is exactly what a per-channel collector needs.

### Completion Notes List

**The base gained exactly one additive, defaulted hook, and nothing else.** `translate`
returning a *sequence* was always the base's contract, and this is the first per-package
collector to use it -- but the base's own sentinel paths wrote exactly one row and bypassed
`translate`, so a first channel that answered `404` ended the collection and every remaining
channel went unasked. That is AC 1 failing outright, and the amended spec permits the one hook
that closes it: `Collector.sentinel_evidence_rows`, non-abstract, defaulting to
`[self.sentinel_evidence(...)]`. Every collector written before it is byte-identical, which a
unit case pins by identity over all four. `core/freshness.py`, `OutcomeState`, `identity`'s
writers and the four shipped collectors are untouched.

**One check in the base was relaxed, and it had to be.** `CPM-AD-24`'s verbatim check read
"the row carries the state the base asked for"; it now reads "at least one of the rows does".
The state the base decides is about the *one call the base made*, and a collector answering for
surfaces that call never touched can only report what each of them said -- a row saying "this
other channel publishes 2.1.3" is an observation, not a sentinel that forgot which sentinel it
is. What the check still guarantees is the half it is actually about: the base's own answer is
on the record, and a collector whose whole answer is determinate rows is refused exactly as it
was before (`test_a_sentinel_that_ignores_the_state_it_was_asked_for_is_refused`, unchanged in
substance).

**One call per channel, and the first of them is the base's.** `source_for` names the first
declared channel's package document and `translate` reads that answer, then makes one bounded
call per remaining channel. A two-channel run makes exactly two calls, which is asserted
rather than documented -- and the platforms cost rows rather than calls, which is asserted
too.

**One row per `(channel, platform)`, and the database says so.**
`conda_package_names_channel_and_platform` requires both columns of **every** row, sentinel
rows included, which is the half a convention would have missed: a sentinel that could not
name a pair would be an observation of nowhere. The facts constraint is the biconditional the
three sibling tables carry, over the published version, the build string and the build number.

**A build string is not required of a determinate row**, on the terms `SourceReleaseSnapshot`
does not require a date of one. A channel that states its latest version while stating the
build poorly is answering, not failing, and requiring the build here would have made the
honest row unwritable and pushed the collector into inventing one.

**A channel's failure never discards another channel's answer** (`CPM-FR-15`).
`_channel_instead` cannot raise: a transport failure, an unreadable document, an unconditional
`304` and an unnameable locator each become `error` facts for that channel's platforms, and a
`404` becomes `not_found` facts -- which is the channel's *own* answer and a different claim
from "this run could not find out". An integration case asserts the three reasons are three
distinct sentences.

**`repodata.json` is never read.** A channel's per-platform index runs to hundreds of
megabytes and answers a question about every package; the per-package document answers the
question about one in kilobytes. That is a Never in the spec and is why the locator is
`/package/<channel>/<name>`.

**The channels are configuration and ship empty** (the Block If). PRD Open Question 4 is
unresolved, so `config/settings/base.py` assigns both lists `()` and a collection refuses
until an operator declares them -- a `CondaChannelError` naming the setting, a `failed` ledger
row, and no evidence row, because every row must name a channel and platform and an empty
declaration names neither. An **absent** setting is a different thing and is refused earlier,
at `AppConfig.ready()`, on the terms the watchlist path is; an **empty** one boots, which the
unit tier pins in both directions.

**`MAX_MONITORED_CHANNELS` is a time bound rather than an opinion.** Which channels this
product watches is not this module's to answer; how many of them one Celery task can ask about
inside the inherited sixty-second soft limit is. Every channel past the first costs an
un-retried connect and read from inside `translate`, outside the retry policy
`worst_case_call_seconds` bounds -- this is the only collector here whose worst case grows
with a configured value -- so the declared timeout dropped to 2.5 seconds and the ceiling is
four channels, which comes to 38 of the 60. The unit case reconciles it **at the maximum**,
against the settings module's own limit.

**`not_applicable` is refused rather than shaped.** A published-artifact question applies to
every package: "it is not there" is the observation `CPM-FR-10` asks for, not a reason not to
look. So `inapplicability` never answers a reason, the base never asks for that sentinel, and
`sentinel_evidence` refuses `ok`, `unknown` **and** `not_applicable`. The hook is still
overridden, because it is the first thing the base calls on every run and therefore the one
place a run's remembered declaration can be forgotten.

**A `not_found` asks the remaining channels; an `error` does not, and the difference is the
ledger row.** `not_found` means the first channel *answered* -- the allowance was granted, one
call was made, and the base finalizes the run `succeeded` -- so the rest are asked exactly as
`translate` asks them and every pair gets the row it earns. `error` is reachable from a
*refused allowance* as well as from a failed call, and `_failed` calls `run.failed()` before
the hook runs: issuing calls there would spend the remote budget the limiter has just refused
(`CPM-AD-20`) and would write `ok` rows underneath a ledger row saying the run failed. So
every pair gets an `error` row carrying the base's own reason and nothing is asked. Both
halves are integration cases.

**Eleven `deferred` entries recorded**, none of them high. The one that was high --
a first channel's `404` losing every other channel -- is fixed rather than deferred, and its
entry is removed.

### Review patch round (26 findings, all applied)

**The four high findings were four different ways of being confidently wrong.**

- *The arithmetic rested on a premise that was false.* Every "un-retried second call" in this
  module, its sibling's, the operator documentation and the reconciliation test was wrong:
  `RequestsTransport` mounts its retry policy on the **session**, so a call made from inside
  `translate` is retried exactly like the one the base makes. The real worst case at four
  channels and the shared retry default is about 92 seconds against a 60-second soft limit --
  a killed task that writes nothing, which is the precise failure the ceiling exists to
  prevent. The reconciliation is now `MAX_MONITORED_CHANNELS * worst_case_call_seconds(...)`
  asserted at the ceiling, the retry budget dropped to one (with a case asserting the shared
  default would *not* fit), and every description was corrected. The same false premise in
  `collectors/feedstock.py` is a `deferred` entry, because correcting it means editing a
  shipped collector.
- *Determinate rows could land under a `failed` ledger row.* The relaxed "at least one row
  carries the state" check constrained none of the others, so an override returning `ok` rows
  from `_failed` would write published-version evidence permanently beneath a run that failed.
  The base now refuses a determinate row on the `error` and `not_applicable` paths and keeps
  it on `not_found`, where it is the whole point; both halves are cases at both tiers.
- *A mistyped platform was recorded as a published-artifact absence.* `linux_64` passed the
  segment grammar and produced `not_found` rows saying a channel's latest version had no file
  on a subdir that does not exist -- a false statement, permanently, indistinguishable from a
  true one. Platforms are now checked against `CONDA_SUBDIRS`, conda's own closed vocabulary,
  and the refusal names the permitted set.
- *Labels were ignored.* `latest_version` spans every label, so a release candidate uploaded to
  `dev` is what the channel calls latest while `conda install` resolves to something older, and
  `_platform_fact` claimed the opposite in as many words. The contract fixes the version as the
  one the channel states, so the version is unchanged and the *claim* went: the row now names
  the observed file's labels whenever they do not include `main`, and the docstring, the module
  docstring and `docs/deployment.md` all say so.

**Five medium findings were about a method documented as unable to fail.**
`_channel_instead` caught three exception types and is now broad, as the base is around
`translate`; `_require_shapeable` no longer raises from the plural hook, which the base does
not guard, and stays on `sentinel_evidence` where a caller meets it; a hook asked before a
declaration was read -- or with channels but no platforms -- is refused by name rather than
building a blank pair the table refuses at insert or raising `IndexError`; and a `Package` row
that went between the ledger's key check and the name read is re-raised as `CondaChannelError`.

**The boot refusal now checks shape as well as presence**, through the collector's own rule, so
`CPM_MONITORED_CHANNELS = "conda-forge"` -- the misconfiguration the module goes to length to
describe -- stops the component at start-up instead of failing every run for ever.

**Two findings were about reads rather than writes.** `_carries` matched any field equal to the
state's value, which several rows make several times likelier to hit by accident; it now reads
the column the outcome is declared in (`STATE_FIELD`). And the table had no index for the read
it exists to serve: `(package, channel, platform, -observed_at)` is now in the model and in
`0005`, because this table grows `channels x platforms` times faster than any sibling and the
per-pair scan is the one that degrades first.

### File List

- `src/config/settings/base.py` -- `CPM_MONITORED_CHANNELS` and `CPM_MONITORED_PLATFORMS`,
  both empty, with PRD Open Question 4's reasoning beside `INVENTORY_WATCHLIST_PATH`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` --
  `CondaPackageSnapshot`, `_CHANNEL_LENGTH`, `_PLATFORM_LENGTH`, `_BUILD_STRING_LENGTH`,
  `CONDA_PACKAGE_FACTS_CONSTRAINT`, `CHANNEL_AND_PLATFORM_CONSTRAINT`,
  `CONDA_PACKAGE_READ_INDEX`, module docstring (five tables).
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/0005_conda_package_snapshots.py`
  -- new; depends on `collectors.0004` and `identity.0001`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py` -- new; the
  declarations, `CondaChannelError`, `CondaDocumentError`, `Monitored`, `ChannelFact`,
  `monitored`, `package_locator`, `channel_facts`, and `CondaPackageCollector` with its
  per-channel bounded call.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` --
  `COLLECT_CONDA_PACKAGE_TASK_NAME`, `collect_conda_package`, `__all__`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` -- roster of five,
  and the boot refusal for an absent monitored-surfaces setting.
- `docs/deployment.md` -- the operator section, including what the failure looks like until
  the two settings are declared.
- `tests/unit/django_apps/test_conda_package.py` -- new.
- `tests/integration/django_apps/test_conda_package.py` -- new.
- `tests/collectors.py` -- four fixture collectors for the new hook: one owing several
  sentinel rows, one answering with none, one answering with a row rather than with rows, and
  one answering about another package.
- `tests/unit/django_apps/test_collection.py`, `tests/integration/django_apps/test_collection.py`
  -- the base's own cases for the hook: the default shape, its keyword-only signature, the four
  shipped collectors inheriting it by identity, several rows written on both sentinel paths,
  the relaxed verbatim check, and the two refusals.
- `tests/unit/test_settings.py` -- the two declarations, asserted empty and tuple-typed over
  all four settings modules.
- `tests/unit/test_model_registry.py`,
  `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py` -- the three frozen rosters.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` -- `in-progress`.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** `CPM-FR-10`'s published-conda-package collector, and the one base
change it needed. `CondaPackageCollector` writes `conda_package_snapshots` with **one row per
`(channel, platform)`** — a build string is a property of a build, which is per platform, so a
row naming a channel and one build string would already have merged the platforms to produce
it. Splitting on both is the only shape in which no row stands for two of anything, and two
`CheckConstraint`s make it a database rule: the published facts are present exactly on a
determinate row, and **every** row names its channel and platform.

**Which channels and platforms are monitored is PRD Open Question 4, and this story does not
answer it.** Settings declares both, they ship empty, an absent declaration is refused at boot
and an empty one fails the run naming the setting — the posture `CPM-IDENTITY-S07` established
for the inventory watchlist, and for the same reason: a component that monitored a channel
nobody chose would record facts about the wrong surface, permanently.

**The base gained one hook.** `Collector.sentinel_evidence_rows` is non-abstract and defaults
to the single row `sentinel_evidence` shapes, so all four shipped collectors are byte-identical
in behaviour and each is asserted to inherit the default by identity. It exists because the
base's `not_found` branch never reaches `translate`, so without it a first channel answering
`404` left every remaining channel unasked — which is AC 1 failing outright rather than a
documentation problem. See the Spec Change Log: the Never item that forbade this was this
spec's own scoping error.

**Files changed.**

- `core/collection.py` — the plural sentinel hook, its two refusals (an empty answer, a
  non-sequence), and the determinate-row refusal on the failing paths.
- `collectors/models.py`, `collectors/migrations/0005_conda_package_snapshots.py` — the table,
  its two read indexes and its two constraints.
- `collectors/conda_package.py` *(new)* — the declarations, the pure declaration, locator and
  document functions, and the collector with its bounded per-channel calls.
- `config/settings/base.py` — the two declarations, empty, with Open Question 4's reasoning.
- `collectors/tasks.py`, `collectors/apps.py` — the task, the boot refusal, a roster of five.
- `docs/deployment.md` — including that the component observes nothing until an operator
  declares channels and platforms, and what the failure looks like until then.
- New unit and integration modules; base cases at both tiers for the new hook; four frozen
  rosters and the settings suite updated.

**Review findings.** 1 spec repair and 26 patched (4 high, 13 medium, 9 low), 4 deferred, 2
rejected. Four review layers ran in parallel over the 5,900-line diff.

**Follow-up review recommended:** true. Four high-severity patches and a spec repair.
Patched counts: high 4, medium 13, low 9; score `3 x 13 + 1 x 9 = 48`, far over the
threshold of 5.

**The two most valuable findings were both premises nobody had checked.** Every call this
collector makes is retried, because the transport mounts its retry policy on the session — so
the timeout, the channel ceiling and the reconciliation test had all been sized against an
un-retried call that does not exist, and the real worst case exceeded the soft limit the
ceiling exists to respect. And the relaxed sentinel check, which the base change required,
would have let determinate rows land beneath a `failed` ledger row: the check constrained one
row of a set where it used to constrain the only row there was.

**Verification.** `pixi run ci` exits 0 — 5265 passed, 2 pre-existing skips, coverage 98.78%,
with `collectors/conda_package.py` and `core/collection.py` each at 100%.
`makemigrations --check --dry-run` reports "No changes detected". `pixi run gate-postgres`
passes against `postgres:17`, where both new constraints are enforced. All three were re-run
by the orchestrating session after the patch round.

**Residual risks.** Eleven `deferred` entries. The ones that matter for the rest of this epic:
the response cache and the declared allowance both cover only the first channel's call, so
every channel past the first re-transfers its document each run and spends remote budget the
local counter does not see; a permanent misconfiguration leaves the task as an ordinary
exception the queue cannot tell from a transient failure, which with the shipped empty default
is an unbounded loop of identical failed runs; and this is the first collector whose evidence
for one package is a matrix, with no rule yet for how several rows sharing one instant collapse
into one package-level answer — which lands on `CPM-CURRENCY-S06`.
