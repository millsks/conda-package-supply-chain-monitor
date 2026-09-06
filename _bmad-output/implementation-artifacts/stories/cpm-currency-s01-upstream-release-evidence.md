---
title: 'CPM-CURRENCY-S01: Upstream release evidence'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '7af67f26f60d2908dc1ce7ff4cc8312b69915f79'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s01-five-outcome-states-precedence-order.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s04-three-queues-cadence-as-data.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s05-collector-base-carrying-external-call.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s08-conditional-requests-and-caching.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s02-resolution-records-where-came-from.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s07-watchlist-inventory-source.md
warnings: []
deferred:
  - summary: >-
      The declared allowance cannot sweep the inventory: sixty unauthenticated requests an
      hour is fifteen packages an hour, against `CPM-NFR-1`'s ten thousand.
    evidence: |-
      `SOURCE_RELEASE_RATE_LIMIT` is `RateLimit(calls=60, per=1 hour)`, which is GitHub's
      documented anonymous allowance and therefore the honest declaration for a collector
      that sends no credential. The base charges `1 + retries` per collection
      (`CPM-EVIDENCE-S05`), so the real throughput is fifteen packages an hour -- roughly
      four weeks to observe ten thousand packages once. `CPM-EVIDENCE-S05`'s own deferred
      list already named this ("GitHub's API is unusable unauthenticated at sweep volume").
      The tag fallback makes it slightly worse than the arithmetic says: a repository that
      publishes no releases costs a second request that the base charged nothing for, so the
      local counter under-counts the remote spend for exactly the repositories the fallback
      exists to serve.
      Raising it means authenticating, which needs a credential, a settings key to carry it
      and a declared `Authorization` header; the number and the credential are one decision
      and none of the three is this story's. Nothing is scheduled to try in the meantime --
      no cadence entry exists -- so the exposure is latent rather than live, and it becomes
      real in `CPM-CURRENCY-S05`, which is the story that sweeps.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py -- SOURCE_RELEASE_RATE_LIMIT
    severity: high
  - summary: >-
      The recorded repository activity signal is *release* activity, not push or commit
      activity, because one collection is one call.
    evidence: |-
      `CPM-FR-7` asks for "a repository activity signal" and does not say which.
      `Collector.collect` issues exactly one `fetch`, and GitHub answers the release
      question and the push question on two different endpoints -- `/releases` carries
      `published_at` and `created_at`, and `pushed_at` lives on `/repos/{owner}/{repo}`.
      So `last_activity_at` is the most recent instant any listed release carries,
      prereleases and drafts included, which is a real signal (it distinguishes a project
      mid-cycle from one that stopped releasing) and is not the stronger one a second call
      would give. Recorded rather than papered over: the column's own docstring says what it
      is, and a push-level signal needs either a second locator per collection -- a change
      to the base's one-call shape -- or a second collector.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/models.py -- SourceReleaseSnapshot.last_activity_at
    severity: medium
  - summary: >-
      A package with no source repository, or one on a host this collector cannot read,
      produces a `failed` ledger row rather than a `not_applicable` observation.
    evidence: |-
      `source_for` raises `SourceLocatorError` before the window, the allowance and the
      transport, so the run ledger records the reason and no evidence row is written.
      `CPM-FR-6` would prefer `not_applicable` -- the check does not apply to this package --
      but the collector base offers no `not_applicable` write path: `sentinel_evidence` is
      called only with `ERROR` and `NOT_FOUND`, and writing a row outside `collect()` would
      put a second evidence writer beside the base's (`CPM-AD-7`). Today nothing selects
      packages to collect, so nothing produces those rows; the moment something does, the
      ledger fills with `failed` runs for every unmapped package, which is a real reporting
      problem rather than a cosmetic one. It is resolvable in two ways -- a selection that
      only offers packages with an established source repository, or a `not_applicable` path
      in the base -- and the story that first runs the sweep is the one that can tell which.
      `collectors/selection.py` exists already (`CPM-IDENTITY-S04`) and is *not* that
      selection: it ranks packages for identity review. A collection selection does not exist
      yet, and `CPM-CURRENCY-S05` owns it.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py -- SourceLocatorError
    severity: medium
  - summary: >-
      Nothing schedules this collector, and the cadence its freshness target is derived from
      is an assumption rather than a declaration anything reads.
    evidence: |-
      `SOURCE_RELEASE_CADENCE` is a module constant that `SOURCE_RELEASE_FRESHNESS_TARGET`
      and `SOURCE_RELEASE_OBSERVATION_WINDOW` are both derived from, and `CPM-AD-20` puts the
      real cadence in `django_celery_beat`'s `DatabaseScheduler` as data. No
      `CELERY_BEAT_SCHEDULE` entry exists for `cpm.collect.source_release`, so the two cannot
      disagree yet -- and cannot be reconciled either. Whoever writes the schedule entry has
      to reconcile them, and nothing fails if they do not: a weekly schedule against a
      daily-derived two-day target would make the whole inventory read stale five days out of
      seven, with every gate green. It belongs with `CPM-CURRENCY-S05`, which is where a
      cadence is first written down.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py -- SOURCE_RELEASE_CADENCE
    severity: medium
  - summary: >-
      One page of releases is read, so a repository whose newest thirty releases are all
      prereleases records `not_found` for the latest-release question.
    evidence: |-
      `RELEASES_PER_PAGE` is thirty and one collection is one call, so `release_facts` decides
      from the page it was served. The row is honest about what this run could see -- the
      activity signal and `releases_seen` both say the repository is alive -- but it is not
      the same statement as "this repository has never published a stable release". The tag
      fallback carries the same bound and a second one: the tags endpoint supplies no dates,
      so "newest tag" means "first the source listed", which is the source's ordering rather
      than a fact this collector established. Paging, or dating a tag, would each need more
      calls per collection than the base makes.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py -- RELEASES_PER_PAGE
    severity: low
  - summary: >-
      A conditional request still spends the full `1 + retries` allowance, inherited from
      `CPM-EVIDENCE-S08` and now attached to a source that really counts.
    evidence: |-
      `CPM-EVIDENCE-S08` recorded this against a repository with no collector in it: the base
      charges the limiter before the call, conditional or not, and GitHub does not count `304`
      responses against its primary rate limit at all. This is the first collector where that
      arithmetic costs something real -- every revalidated read spends four of sixty hourly
      requests that the source would not have charged for. The entry is repeated here rather
      than left in that story because this is where it stops being hypothetical.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/collection.py -- collect
    severity: medium
  - summary: >-
      A `not_found` row means "absent **or** unreadable" while no credential is configured,
      and no reader is currently obliged to know that.
    evidence: |-
      `core/transport.py` maps `404` and `410` to `found=False`, which is right in general and
      ambiguous against this source: GitHub answers `404` identically for a repository that is
      absent, private, moved or blocked, deliberately, so an unauthenticated reader cannot
      enumerate private repositories. This collector sends no credential and cannot tell them
      apart. The state is left as `not_found` -- it is what the source said, and inventing a
      sixth outcome would be worse -- and the row, the model docstring and `docs/deployment.md`
      all carry the caveat. What is deferred is the *resolution*: authentication is the only
      thing that distinguishes them, and it belongs with the credential decision above. Until
      then a currency policy reading these rows is reading a weaker fact than the column name
      suggests, and `CPM-CURRENCY-S06` is the first pass that will have to decide what to do
      with one.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py -- ABSENT_CAVEAT
    severity: medium
  - summary: >-
      The local limiter cannot see a remote refusal, so an exhausted GitHub quota is recorded
      as an ordinary failure and the counter keeps granting.
    evidence: |-
      GitHub signals a spent anonymous quota with `403` plus `X-RateLimit-Remaining: 0` and
      `X-RateLimit-Reset`, and a secondary limit with `403` plus `Retry-After`. `403` is not in
      `DEFAULT_RETRY_STATUSES`, so `core/transport.py` reads it as a failed call and the base
      writes an `error` row -- indistinguishable in `state` from a source that is broken, and
      separable only by the `detail` convention this story documents. Worse, the local counter
      never learns: it goes on granting for the rest of its own window, and every collection in
      that window repeats the trip. Fixing it means the transport surfacing response headers,
      or a status-specific error the base can hand the limiter, and both are changes to `core`
      that belong with the story that first sweeps at volume.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/transport.py -- DEFAULT_RETRY_STATUSES
    severity: medium
  - summary: >-
      The declared allowance is per collector while GitHub's is per source IP, and two later
      epics will add readers against the same budget.
    evidence: |-
      `core/rate_limit.py` keys its counter on the collector name, so `RateLimit(calls=60,
      per=1 hour)` bounds *this collector's* requests. GitHub's anonymous limit is per source
      IP, and every worker in a deployment shares one egress address. `CPM-EP-SECURITY`'s
      advisory collectors and `CPM-EP-PY314`'s verification collectors will read GitHub too,
      each with an allowance of its own, and the sum of three declared sixties is one hundred
      and eighty requests an hour against a budget of sixty. Nothing is wrong today -- there is
      one GitHub reader -- and nothing detects it when there are three. A per-host allowance, or
      a shared counter keyed on the host rather than the collector, is a `core` change and
      belongs with the second GitHub reader.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/rate_limit.py -- window_key
    severity: medium
  - summary: >-
      `PackageMapping` already holds the fact that would distinguish "does not apply" from
      "failed", and `source_for` reads past it.
    evidence: |-
      `CPM-IDENTITY-S02` gives every package a `PackageMapping` row per `MappingKind`, and
      `SOURCE_REPOSITORY`'s `outcome` says exactly which of the five states resolution reached:
      `established`, `not_found`, `not_applicable`, `unknown` or `error`. `source_for` reads
      only `Package.source_repository_url`, so a package whose source repository resolution
      recorded as `not_applicable` is indistinguishable here from one nobody has looked at --
      both produce a blank URL and both fail the run. Reading the mapping outcome would let the
      collector, or the selection in front of it, tell them apart, which is most of what the
      `not_applicable` gap above is asking for. Not done here because the consumer that needs
      the distinction does not exist yet, and building the read before the reader would fix its
      shape blind.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py -- _repository_url
    severity: medium
  - summary: >-
      The cadence reconciliation this story defers is cheaper than the entry above implies: the
      stage-two sweep could make it.
    evidence: |-
      `config/startup/stage_two.py` already walks the registered collectors and refuses one
      whose freshness target is absent or non-positive (`CPM-AD-28`). A collector that also
      declared the cadence its target was derived from could be checked against its
      `django_celery_beat` entry in the same sweep -- target strictly greater than cadence,
      cadence equal to what the schedule actually says -- which turns "whoever writes the
      schedule entry has to remember" into a boot refusal. It is not done here because there is
      no schedule entry to check against and a sweep over an empty set proves nothing; it is
      recorded so the story that writes the first entry knows the guard is one function rather
      than a design.
    location: >-
      src/config/startup/stage_two.py -- _refuse_collector_without_freshness_target
    severity: low
---

# CPM-CURRENCY-S01: Upstream release evidence

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

## Story

As a packaging engineer,
I want the latest upstream release and its date recorded for each package,
so that I can tell whether a package is behind its own source.

## Acceptance Criteria

1. **Given** a package with a source repository
   **When** the source collector runs
   **Then** it records latest release or tag, its date, and a repository activity signal
   **And** lookup status is recorded explicitly, including `not_found` and `error`

2. **Given** a repository that publishes no releases at all
   **When** the collector runs
   **Then** it records that fact rather than reporting the package stale

## Tasks / Subtasks

Planned against the codebase at `7af67f2` -- the story's own `baseline_revision` --
after `CPM-EP-EVIDENCE` and
`CPM-EP-IDENTITY` shipped. The contracts this story inherits rather than invents:
`Collector`'s per-package `collect()` path and its nine declarations
(`CPM-EVIDENCE-S05`), the transport seam and its `Payload` (`CPM-AD-27`), the
conditional-request cache (`CPM-EVIDENCE-S08`), the run ledger and its outside-any-
transaction rule (`CPM-EVIDENCE-S03`), the three queues and the `cpm.collect.*`
namespace (`CPM-EVIDENCE-S04`), `AppendOnlyModel` (`CPM-AD-2`), `OutcomeState`
(`CPM-AD-5`), the injected `Clock` (`CPM-AD-26`), and `Package.source_repository_url`
as `CPM-IDENTITY-S02` establishes it.

**The shape.** This is the first collector on the per-package path: inventory
ingestion (`CPM-IDENTITY-S06`/`-S07`) reads one document naming many packages and
refuses all three per-package hooks. So this story is the first exercise of
`source_for` / `translate` / `sentinel_evidence`, and everything it adds hangs off
them.

- [x] **`collectors/models.py` — `SourceReleaseSnapshot`, table `source_release_snapshots`.**
      PRD Appendix A.2's four facts -- upstream latest version, release date,
      repository activity, lookup status -- plus the columns every evidence row
      carries. `package` is a `PROTECT` FK (`EVIDENCE.02-AUDIT-001`); the lookup
      status is `state` over `OutcomeState` and never a boolean (`CPM-AD-5`), named
      `state` for the reason `InventorySnapshot.state` is; `releases_seen` is
      nullable so "we read a document and counted none" stays distinguishable from
      "we never read one". One `CheckConstraint` -- a determinate row carries a
      version and a release date, and no other row carries either -- and one index
      on `(package, -observed_at)` for `core/freshness.py`'s read. No unique
      constraint of any kind (`EVIDENCE.02-AUDIT-003`).
- [x] **`collectors/migrations/0002_source_release_snapshots.py`** -- the table, its
      index and its constraint. `test_migration_completeness.py` fails without it.
- [x] **`collectors/source_release.py` — new.** The declarations and the two pure
      functions the unit tier is written against:
      - the derived configuration: cadence (daily, `CPM-NFR-2`'s fast end for version
        currency), observation window (half the cadence, so a scheduled run is never
        suppressed by the previous one), freshness target (`cadence x (1 + 1)` = two
        days, PRD Open Question 7's arithmetic), timeout and retries chosen so the
        worst-case call fits inside the inherited 60-second soft limit
        (`CPM-AD-9`), the rate limit, the declared headers, and the response-cache
        lifetime.
      - `releases_locator(repository_url)` and `tags_locator(repository_url)` -- pure,
        no database: the package's repository URL to the two locators this collector
        reads, over one shared parse. Refuse a blank URL, an unparseable one, an
        unsupported scheme or host, a path that is not `owner/repo`, and a relative
        reference; normalise case; percent-encode both segments.
      - `release_facts(body)` and `tag_facts(body)` -- pure: a document to the facts.
        An empty release list falls back to tags (AC 1's "or tag"), and only a
        repository with neither records `not_found`, which is AC 2.
      - `SourceReleaseCollector` -- `source_for` (the one database read), `translate`
        (which drives the fallback), and `sentinel_evidence`.
- [x] **`collectors/tasks.py` — the `cpm.collect.source_release` task.** It lives
      there and not beside the collector because celery's autodiscovery imports each
      application's `tasks` module and no other; a `@shared_task` anywhere else is
      registered by whatever happens to import it. No schedule and no time limit
      (`CPM-AD-20`, `CPM-AD-9`).
- [x] **`collectors/apps.py`** -- register the collector in `ready()`, under the
      same identity guard the ingestion registration beside it carries.
- [x] **`tests/unit/django_apps/test_source_release.py` — new.** The declarations and
      their derivations (including the worst-case-call arithmetic reconciled against
      the settings module's own soft limit), every `releases_locator` refusal, every
      `release_facts` row, the sentinel's shape, and a source sweep over the new
      module.
- [x] **`tests/integration/django_apps/test_source_release.py` — new.** The rows that
      need a real table and a real ledger: a determinate observation, a repository
      that publishes no releases, an absent repository, an unreachable source, the
      window and its bypass, `source_for`'s refusals, the check constraint, and the
      freshness read that makes AC 2's "records that fact rather than reporting the
      package stale" observable.
- [x] **`tests/unit/test_model_registry.py`** -- `EVIDENCE_MODEL_LABELS` gains the new
      model; the set is asserted for exact equality.
- [x] **`tests/integration/startup/test_stage_two_collector_registry.py`** -- the
      roster a deployed boot sweeps is two collectors now, not one.
- [x] **`tests/unit/django_apps/test_collector_base_audit.py`** -- the new module joins
      `THE_NEW_MODULES` as a named anchor, so a scan that stopped reaching the
      collectors subtree fails there rather than reporting a clean repository.
- [x] **`docs/deployment.md`** -- what an operator has to know: the collector reads
      GitHub unauthenticated, and what that allowance does and does not cover.

## Dev Notes

**Satisfies:** `CPM-FR-7`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-7]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context), via `bmad-build`.

### Debug Log References

- `pixi run ci` -- exit 0. 4610 passed, 2 pre-existing skips, coverage 98.44% against a
  90% floor, with `collectors/source_release.py` at 100%.
- `pixi run gate-postgres` -- exit 0 against a throwaway `postgres:17`, which is where the
  new `CheckConstraint` and the `PROTECT` relation are actually enforced.
- `pixi run gate-redis` -- exit 0 against `redis:7`, with nothing skipped.
- `pixi run python manage.py makemigrations --check --dry-run` -- "No changes detected"
  after `0002_source_release_snapshots.py`, so the model and the migration agree.

### Completion Notes List

**What was implemented.** The first collector on the base's per-package path. Inventory
ingestion reads one document naming many packages and refuses all three per-package hooks;
this is the first class to implement `source_for`, `translate` and `sentinel_evidence`, and
the first evidence table a *surface* collector writes.

**"Latest release or tag" is two endpoints and one fallback.** Publishing a GitHub Release
is a deliberate act many projects never perform: they tag, and the release feed is empty for
ever. Reading releases alone would record `not_found` for every one of them -- a false fact
in an append-only log -- and would collapse AC 2 into a restatement of AC 1's absence case.
So an empty release list falls back to the repository's tags, and only a repository with
**neither** records `not_found`. The fallback costs a second call and fires only where it is
needed; that it is uncharged against the base's allowance is recorded as deferred.

**A tag carries no date, and the schema was changed to let it say so.** The tags endpoint
supplies no instants and its ordering is the source's rather than this collector's. So a
tagged row is `ok`, names the version, leaves both instants NULL, and says in `detail` that
the ordering is not its own. The `CheckConstraint` is written to permit exactly that: a
determinate row names a *version*, and a date is something only a release can supply.

**The four facts, and where each comes from.** `SourceReleaseSnapshot` holds what PRD
Appendix A.2 gives `source_release_snapshots`: the latest version, its release date, a
repository activity signal, and the lookup status -- plus the locator the observation was
read from, because `Package.source_repository_url` is mutable and an append-only history can
legitimately hold rows read from two different repositories. The status is `state` over
`OutcomeState`, named as `InventorySnapshot.state` is so it stays out of the derived-status
sweep, which is about statuses a *policy* derived.

**A `404` is not proof of absence to an unauthenticated reader.** GitHub answers `404`
identically for an absent repository and for a private, moved or blocked one, deliberately.
This collector sends no credential, so the state stays `not_found` -- that is what the source
said -- and the row carries the caveat in `detail`, with the model docstring and
`docs/deployment.md` saying the same thing to the two other audiences.

**AC 2 is proved through the freshness read, not the row.** "Records that fact rather than
reporting the package stale" is a claim about what a later reader sees, so the case asks
`core/freshness.py` -- the module every read surface asks -- and asserts the observation
reads *not stale*, with a paired case showing the same read answering with no instant for a
package this collector never observed.

**Zero and missing stay apart, in the one column where both are reachable.**
`releases_seen` is `0` on a row written from a document this run read -- including the tagged
row, because the release list really was empty -- and NULL on a sentinel row, because a
sentinel is written for a call that produced no document and counted nothing.

**Two module functions carry the whole of the behaviour, and they are pure.** The locators
and the document readers touch no database, socket or clock, which is what puts 112 of the
story's 137 cases in the unit tier -- the split `CPM-AD-27` exists to make. They refuse
rather than guess: a blank URL, an unparseable authority, an unreadable scheme, a missing or
unknown host, a path that is not `owner/repository`, a relative reference (refused rather
than encoded, because `.` and `..` are unreserved and survive `quote`, and refused *after*
the `.git` suffix is stripped so `..git` cannot slip past), and a document whose shape has
changed. Owner and repository are lower-cased, because GitHub treats them case-insensitively
and every key built from the result is exact.

**The declared timeout is bounded by the inherited Celery limit, and the arithmetic is
computed rather than eyeballed.** `worst_case_call_seconds()` reconciles the declarations
against `settings.CELERY_TASK_SOFT_TIME_LIMIT` with a stated three-quarter margin, refuses
inputs it cannot answer for, and says in its own docstring that it ignores `urllib3`'s
backoff cap and therefore over-reports rather than under-reports.

**The task lives in `collectors/tasks.py` and the collector does not.** Celery's
autodiscovery imports each application's `tasks` module and no other, so a `@shared_task`
beside the collector would be registered by whatever happened to import it -- the suite, and
not a worker.

### Review Triage Log

#### 2026-09-06 -- Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 24 (high 3, medium 13, low 8)
- defer: 5 new entries, on top of the six recorded at implementation
- reject: 2 (recorded by the coordinator, not acted on)

**The three high-severity findings all changed shipped behaviour.**

- `[high]` AC 1 says "latest release **or tag**" and only releases were read, so every
  repository that tags without publishing a Release recorded a false `not_found`. The tag
  fallback is the fix, and it is what makes AC 2 a narrower case than AC 1's absence rather
  than a restatement of it. The `CheckConstraint` moved with it, because a tag has no date.
- `[high]` The task's `force` pass-through and its return value were observed by nothing:
  the one task case drove a package whose `source_for` raises before the window is consulted,
  and the force case bypassed the task entirely. Demonstrated by changing the task to
  `force=False` with the whole suite still green. Now driven through the task three times --
  collect, suppressed, forced -- with the returned string asserted each time.
- `[high]` A GitHub `404` was recorded as a confident absence, which it is not for an
  unauthenticated reader. The state is unchanged (it is what the source said) and the row,
  the model docstring and the operator documentation now all carry the caveat, with a
  `deferred` entry of its own.

**The thirteen MEDIUM findings**, each addressed: `__str__` is rendered by two cases;
each conjunct of the constraint is isolated by a case of its own and the permission it has to
grant is asserted too; `sentinel_evidence` refuses a state it has no row shape for; the
`.git` suffix is stripped before the traversal check; a malformed authority is re-raised as
`SourceLocatorError`; the `detail` convention that separates a refused call from a failing
source is documented in three places and the limiter's blindness to a remote `403` is
deferred; the missing host check is made rather than the docstring softened; owner and
repository case is normalised and the "every spelling" case now covers it; the `304` replay
has a case; a mistyped date is refused on the same terms a mistyped flag is, with the
string-but-unreadable case documented as the deliberate difference; the "no published
release" reason is composed from the exclusions that actually occurred; the locator is
recorded on every row; and the document is bounded in size with `RecursionError` caught
beside the decode error.

**The eight LOW findings**, each addressed: the declarations are compared by value; the
migration depends on `identity.0001_package_identity`, which is the migration that creates
the only relation it has; the tautological freshness assertion is gone; `worst_case_call_seconds`
refuses inputs it cannot answer for; the activity signal is the maximum over both date fields
rather than the first available; the backoff coefficients have constants of their own and the
soft-limit case carries a stated margin; the `User-Agent` names the distribution, the version
the running build reports and a way to reach the owner, with both branches of the version
lookup exercised; and the documentation and story corrections are made -- the `selection.py`
reference, the baseline revision, the File List's full paths, and a document helper that can
write an omitted field and an explicit `null` as the two different documents they are.

### File List

- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` --
  `SourceReleaseSnapshot`, `RELEASE_FACTS_CONSTRAINT`, `RELEASE_READ_INDEX`, the `source`
  column, and the module docstring's account of why two collectors' tables share one file.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/0002_source_release_snapshots.py`
  -- new. The table, its index and its constraint; no data step.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/source_release.py` -- new.
  The derived configuration, `releases_locator`, `tags_locator`, `release_facts`,
  `tag_facts`, `distribution_version`, `worst_case_call_seconds`, `SourceLocatorError`,
  `SourceReleaseDocumentError` and `SourceReleaseCollector`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` --
  `COLLECT_SOURCE_RELEASE_TASK_NAME` and the `collect_source_release` task, plus the module
  docstring's account of why it is here.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` -- `ready()` adopts
  both collectors, under one guard.
- `tests/unit/django_apps/test_source_release.py` -- new. The declarations and their
  derivations, every locator refusal, both document readers, the row shapes, the rendering,
  and the module's own source sweeps.
- `tests/integration/django_apps/test_source_release.py` -- new. Everything that needs a run:
  the four lookup statuses, the tag fallback and its failures, AC 2 read back through
  freshness, the window and its bypass, the spent allowance, the cache write and the `304`
  replay, the locator refusals, the task's wiring and its `force`, each conjunct of the
  constraint, and re-observation.
- `tests/unit/test_model_registry.py`,
  `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py` -- the two frozen rosters and one
  named scan anchor.
- `docs/deployment.md` -- what an operator has to know: an unauthenticated allowance, the
  fallback's second call, how to read a `detail`, and what a `not_found` row does not prove.

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 24: (high 3, medium 13, low 8)
- defer: 5: (high 0, medium 4, low 1)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[patch]` AC 1 says "latest release **or tag**" and the implementation read releases
    only, so a repository that tags without publishing Releases recorded `not_found` — a false
    fact in an append-only log. The tell was structural: under releases-only, AC 2 collapses into
    a restatement of AC 1's `not_found` rather than being the distinct case it reads as. A tags
    fallback now fires on an empty release list; only a repository with neither records
    `not_found`.
  - `[high]` `[patch]` The Celery task's `force` pass-through and return value were observed by
    nothing, and that task is the only path `CPM-UJ-1`'s manual recollection can take. Against a
    twelve-hour observation window a dropped `force` silently suppresses the recollection.
    Demonstrated: setting `force=False` in the task left the whole suite passing.
  - `[high]` `[patch]` An unauthenticated GitHub `404` was recorded as a confident `not_found`,
    but GitHub answers `404` identically for private, moved and blocked repositories. The states
    cannot be distinguished without a credential, so the row stopped claiming certainty rather
    than changing state: the `detail`, both docstrings and `docs/deployment.md` now say a
    `not_found` means absent *or* unreadable while no credential is configured.
  - `[medium]` `[patch]` `__str__` had three defensive branches rendered by no test; a mutation
    reintroducing `RelatedObjectDoesNotExist` passed the whole suite.
  - `[medium]` `[patch]` One conjunct of the facts constraint was unpinned — the determinate-row
    case violated two conjuncts at once, so the date half could be dropped undetected.
  - `[medium]` `[patch]` `sentinel_evidence` accepted states it has no row for, building rows the
    constraint then refused at insert.
  - `[medium]` `[patch]` The `.git` suffix was stripped after the traversal check, so a `..git`
    repository segment became `..` in the locator path.
  - `[medium]` `[patch]` A malformed authority let a bare `ValueError` escape the documented
    `SourceLocatorError` contract.
  - `[medium]` `[patch]` A rate-limit refusal and a broken source were the same `error` state,
    separable only by string-matching `detail` — the inference `CPM-AD-5` exists to remove.
  - `[medium]` `[patch]` The locator's docstring promised a host-presence refusal the code did not
    make, and emitted a message asserting a host that was not there.
  - `[medium]` `[patch]` Owner and repository case was not normalised, so one repository produced
    two cache keys and two ledger `source` values.
  - `[medium]` `[patch]` The `304` revalidation path was never exercised despite a week-long cache
    TTL chosen so scheduled runs revalidate.
  - `[medium]` `[patch]` Mistyped flags refused the document while mistyped dates were silently
    dropped — the same argument applied two opposite ways.
  - `[medium]` `[patch]` The "no published release" detail could record a false reason when entries
    were excluded for a blank tag or unusable date, in a table nothing may ever correct.
  - `[medium]` `[patch]` The evidence row recorded no locator, though `source_repository_url` is
    mutable, so history could hold rows from two repositories with nothing to tell them apart.
  - `[medium]` `[patch]` Nothing bounded the response body against memory or soft-limit exhaustion.
  - `[medium]` `[patch]` The declaration audit asserted only that seven names existed, so an
    attribute rebound to the wrong constant passed.
  - `[low]` `[patch]` The migration depended on `identity.0003_identity_override` rather than the
    `0001_package_identity` it actually uses.
  - `[low]` `[patch]` A tautological freshness assertion restated a value the test supplied.
  - `[low]` `[patch]` A negative `retries` made the worst case read as zero, passing the soft-limit
    reconciliation vacuously.
  - `[low]` `[patch]` The activity signal took the first available date rather than the maximum, so
    a live project could read dormant.
  - `[low]` `[patch]` The worst-case test reused `PHASES_PER_ATTEMPT` as the backoff coefficient —
    right arithmetic, wrong constant — and the soft-limit case had no stated margin.
  - `[low]` `[patch]` The `User-Agent` was a bare hand-spelled literal with no version or contact.
  - `[low]` `[patch]` Documentation and story corrections: stale `collectors/selection.py`
    references, a baseline mismatch, elided File List paths, and a test helper that could not
    express an explicit JSON `null`.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** The first collector on the base's per-package path — inventory ingestion
refuses all three per-package hooks, so this is the first implementation of `source_for`,
`translate` and `sentinel_evidence`. `SourceReleaseSnapshot` records the latest upstream release or
tag, its date, a repository activity signal and an explicit lookup state; `SourceReleaseCollector`
reads GitHub's releases document, falls back to tags when it is empty, and writes one row per
collection. `cpm.collect.source_release` is the task, registered in `collectors/tasks.py` because
Celery autodiscovery imports only that module.

**Files changed.**

- `collectors/models.py` — `SourceReleaseSnapshot`, a `PROTECT` FK, `state` over `OutcomeState`, a
  read index, and a `CheckConstraint` making the determinate-row rule a database rule.
- `collectors/migrations/0002_source_release_snapshots.py` *(new)* — schema only.
- `collectors/source_release.py` *(new)* — derived configuration, the pure locators and fact
  readers, `worst_case_call_seconds`, and the collector.
- `collectors/tasks.py`, `collectors/apps.py` — the task and its adoption.
- `docs/deployment.md` — the unauthenticated allowance, what it does not cover, and how to read an
  ambiguous `not_found`.
- New unit and integration modules, two frozen rosters updated, one scan anchor added.

**Review findings.** 24 patched (3 high, 13 medium, 8 low), 5 deferred, 2 rejected. Four review
layers ran in parallel over the 3,375-line diff.

**Follow-up review recommended:** true. Three high-severity patches (the rule fires on any high).
Patched counts: high 3, medium 13, low 8; score `3 x 13 + 1 x 8 = 47`, itself far over the
threshold of 5.

**The three high findings were the same failure in three places: the log recording something it
could not know.** The epic's premise is an evidence log that cannot lie, and each of these wrote a
confident answer where the truth was either different or unavailable. The tags one was a
misreading of the acceptance criterion's own words; the `404` one was a real limit of
unauthenticated reading that the row simply did not admit to; the `force` one was a claim about
behaviour that no test observed, demonstrated by a mutation the whole suite accepted.

**A judgement call the implementer flagged, and it was the right one.** Expressing the sentinel
states as a two-member `frozenset` failed `test_single_ordering_audit.py`, which reads any such
literal outside `core/outcomes.py` as a second precedence order. Rather than record an audit
exemption for a convenience constant, the refusal became two identity comparisons with the reason
written at the check.

**Verification.** `pixi run ci` exits 0 — 4610 passed, 2 pre-existing skips, coverage 98.53%, the
new module at 100%. `pixi run gate-postgres` exits 0 against `postgres:17`, where the check
constraint and `PROTECT` are enforced. `pixi run gate-redis` exits 0 against `redis:7` with nothing
skipped. All three were re-run by the orchestrating session after the patch round.

**Residual risks.** Eleven `deferred` entries. The two that matter most for the rest of this epic:
the declared allowance is GitHub's anonymous 60/hour, which at one call plus retries is roughly 15
packages/hour against `CPM-NFR-1`'s ten thousand — and that allowance is per collector here while
GitHub's is per source IP, with `CPM-EP-SECURITY` and `CPM-EP-PY314` both due to add further GitHub
readers against the same budget. Nothing schedules this collector yet, so both are latent, but
`CPM-CURRENCY-S05` inherits them along with selection and cadence.
