---
title: 'CPM-EVIDENCE-S05: One collector base carrying every external-call rule'
type: 'feature'
created: '2026-09-04'
status: 'done'
baseline_revision: '8fb2d6cadf62fedd3c2f2857dfbedb5d102bbcd0'
review_loop_iteration: 1
followup_review_recommended: true
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
warnings: ['oversized']
deferred:
  - summary: >-
      `CPM-NFR-3`'s caching clause is not implemented, so this story satisfies three of its
      four requirements rather than all of them.
    evidence: |-
      `CPM-NFR-3` requires "rate limiting, retries with backoff, request timeouts, and
      caching", and `CPM-AD-20` names the same four as living in the shared base. Rate
      limiting, retry-with-backoff and timeouts are here; there is no HTTP-level caching
      (ETag / If-Modified-Since) anywhere in `core/transport.py`. The observation window is
      not a substitute: it suppresses *runs*, not responses, so it saves nothing when a run
      is due and the upstream content is unchanged. This spec never asked for caching -- the
      omission is the spec's, not the implementation's -- and the story's "Satisfies:
      CPM-NFR-3" line should be read against this entry until a story owns it.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/transport.py
    severity: high
  - summary: >-
      A spent rate limit writes an `error` evidence row for a call that was never issued.
    evidence: |-
      `CPM-NFR-3` says a rate-limited source "degrades to stale evidence, never to a clean
      result", which argues for writing no evidence and letting the existing rows age into
      stale through the freshness target (`CPM-EVIDENCE-S06`). The intent's matrix cell said
      only "Recorded on the ledger row" and named neither the ledger status nor whether
      evidence is written, so both readings are defensible and the spec did not choose. Left
      as built rather than changed on the coordinator's preference after the fact. Decide it
      in `CPM-EP-CURRENCY`, where a rate limit first actually fires and the coverage view can
      show which reads correctly.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/collection.py
    severity: medium
  - summary: >-
      The commit-ordering fact that AC 4 exists to protect is still asserted nowhere.
    evidence: |-
      The constraint is that the `running` ledger row is *committed* before the outbound call,
      so a killed worker leaves a row. What is verified is a static property of `src/` -- that
      no `transaction.atomic()` encloses a recorder. The durability fact remains unobservable
      because `django_db` wraps every case in a transaction, which is the same gap
      `CPM-EVIDENCE-S03` recorded. The audit is now much stronger (both nesting directions,
      relative imports, single-statement `with`), but it is still a text property standing in
      for a runtime one.
    location: >-
      tests/unit/django_apps/test_collector_base_audit.py
    severity: medium
  - summary: >-
      The recorder-inside-atomic detector is single-module and syntactic.
    evidence: |-
      A recorder reached from a function that is itself called inside an atomic block in
      another module is outside its view. Stated in the audit's docstring and narrowed today
      by `core/collection.py` being the recorder's only caller -- which stops being true the
      moment a second caller exists.
    location: >-
      tests/unit/django_apps/test_collector_base_audit.py
    severity: medium
  - summary: >-
      The observation-window query runs on an unindexed, unboundedly growing ledger table.
    evidence: |-
      `window_query` filters `collection_runs` on `collector`, `package_id`, `status` and
      `finished_at`, and `CollectionRun` carries `db_index=True` on `package_id` alone -- no
      index on the other three and no composite. It runs once per package per collector per
      sweep, against a table that gains a row per run forever. Index choices need a populated
      inventory to measure against, which is why this is recorded rather than guessed.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py
    severity: medium
  - summary: >-
      `Transport.fetch(source)` offers no way to send headers, so the named collectors cannot
      authenticate or make conditional requests.
    evidence: |-
      conda-forge, PyPI and GitHub all expect a `User-Agent` and some enforce it; GitHub's API
      is unusable unauthenticated at sweep volume, and its rate limits are part of why
      `CPM-AD-20` exists. Conditional-request headers are also how the caching entry above
      would be delivered. Widening a protocol after eight collectors depend on it is the
      expensive version of this change, so it is recorded now and belongs with the first
      collector that needs a header.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/transport.py
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Eight collectors are coming, and every one of them needs a timeout, a rate
limit, retry with backoff, an observation window and a rule for what to write when the
source is unavailable. Written eight times they will differ eight ways, and the differences
surface as a rate-limited source quietly producing a clean result -- the failure `CPM-NFR-3`
names in its own words: "degrades to stale evidence, never to a clean result".

**Approach:** One base in `core` that owns the transport boundary (`CPM-AD-27`), so a
collector is a pure translation from a recorded payload to evidence rows and needs no
network to test. The base applies the limits, consults the observation window, drives the
evidence write inside a per-package transaction, and finalizes the run ledger
`CPM-EVIDENCE-S03` built.

## Boundaries & Constraints

**Always:**
- **The transport boundary is the base's and no collector's.** A collector receives a
  payload it did not fetch and returns evidence rows; it never sees a socket, a URL session,
  a retry policy or a clock. `CPM-AD-27` exists so that parse, `not_found`, `error` and
  `not_applicable` handling -- the majority of this product's behaviour -- stays in the fast
  unit tier instead of behind the network.
- Every outbound call carries a timeout. There is no default-less path, and no call site may
  pass `timeout=None`.
- Retry with backoff and the rate limit are applied by the base, from per-collector
  configuration the collector *declares* rather than implements.
- The rate limiter reads `django.core.cache` and **must not branch on the cache backend**.
  `config/settings/local.py` says why in its own words: the LocMem substitution preserves the
  cache API precisely so no call site branches, and the moment one does, local runs stop
  exercising the deployed path.
- **The run ledger is written outside any transaction the base opens.** This is
  `CPM-EVIDENCE-S03`'s recorded, deferred constraint arriving at the story that makes it
  real: the `running` row must be committed before the outbound call or a killed worker
  leaves nothing, so the base must never wrap `collection_run(...)` in `transaction.atomic()`.
  The atomic unit is one package's evidence write, nested inside the recorder and never
  around it (`CPM-AD-23`).
- **Never a clean result and never no row.** A call that ultimately fails inserts evidence
  carrying `error`; a source that answered "this does not exist" inserts `not_found`. Both
  are drawn from `core/outcomes.py`'s vocabulary and neither is `ok` (`CPM-AD-5`).
- Re-observation inserts. Evidence goes through `AppendOnlyModel`, so the base uses `create`
  or `bulk_create` and never `update_or_create` (`CPM-AD-2`).
- `observed_at` and every window comparison come from the injected `Clock` (`CPM-AD-26`).
- `structlog` only, no `print`, no stdlib `logging`. Full type hints, Google docstrings,
  line length 120.

**Block If:**
- Delivering AC 4 would require creating a concrete evidence table. `CPM-AD-7` gives each
  collector its own and puts the first in `CPM-EP-CURRENCY`; a table invented here would be
  one no collector wants and one the append-only audits would then police forever.

**Never:**
- No concrete collector and no concrete evidence model. See Design Notes for how AC 4 is
  proven without one.
- No new runtime dependency. `requests` is already present and carries `urllib3`'s retry
  machinery; a local `http.server` proves the transport without an HTTP-mocking library.
- No freshness-target or observation-window **values**. They are PRD Open Question 7; this
  story builds the mechanism and reads them as per-collector configuration.
- No startup refusal for a missing freshness target. That is `CPM-EVIDENCE-S06`
  (`EVIDENCE.06-AUDIT-001`), and declaring it here would leave two enforcement points.
- No Celery task, no queue wiring, no cadence. `CPM-EVIDENCE-S04` owns those; this base is
  what a task will later call.
- No `ready()` on `CoreConfig`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh run | no prior run in the window | transport called once; evidence inserted; ledger `succeeded` | No error expected |
| Inside the window | a `succeeded` run for this collector and package inside the window | ledger `skipped`, **no** transport call and **no** evidence | No error expected |
| Forced recollection | same state, `force=True` | window bypassed; transport called; evidence inserted (`CPM-UJ-1`) | No error expected |
| Window ignores other packages | a recent run for a *different* package | not skipped; this package is collected | No error expected |
| Window ignores failures | a recent `failed` run for this package | not skipped; only a `succeeded` run suppresses | No error expected |
| Source unavailable | transport raises after the last retry | evidence inserted carrying `error`; ledger `failed`; the row is never absent | Error recorded, not swallowed |
| Source says absent | transport reports the resource does not exist | evidence inserted carrying `not_found`, never `ok` | No error expected |
| Rate limit reached | the limiter has no token for this collector | the call waits or is refused per configuration; never issued unlimited | Recorded on the ledger row |
| Timeout omitted | a collector configured with no timeout | refused when the collector is constructed, not at call time | Raised at construction |
| Translation raises | collector's translate raises on a malformed payload | ledger `failed` with the detail; evidence carrying `error` still inserted | Exception propagates after the row |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/ledger.py:461` -- `collection_run(collector=, clock=, package_id=)`, and `RunHandle.succeeded/partial/skipped/failed` at `:282-332`. The base finalizes through this and adds no second recorder.
- `.../core/ledger.py:20-33` -- the autocommit constraint recorded there, and the reason this story is where it becomes enforceable.
- `.../core/models.py` -- `AppendOnlyModel`, `AppendOnlyQuerySet` (no `update`/`delete`, `bulk_create` conflict forms refused), `RunLedgerModel`, `CollectionRun` (`collector`, `package_id`, `status`, `finished_at`) and `RunLedgerQuerySet.unfinished()`. The window query reads `CollectionRun`.
- `.../core/outcomes.py` -- `OutcomeState`, `DETERMINATE`, `outcome_type`, `aggregate`. `error` and `not_found` come from here; nothing re-spells them.
- `.../core/clock.py` -- `Clock`, `SystemClock`, `FixedClock`, `is_aware`. Injected by parameter; there is no module-level instance.
- `.../core/runs.py` -- `RunState`, `TERMINAL_STATES`.
- `.../core/queues.py` -- `Queue`, `queue_for`. Read-only here: the task that routes to `collect` is `CPM-EVIDENCE-S04`'s and the collector this base serves is a later story's.
- `src/config/settings/local.py:32-45` -- the LocMem cache substitution and the no-branching rule the limiter is bound by.
- `src/config/settings/production.py:33-41`, `src/config/settings/test.py:66-80` -- the other two cache configurations.
- `tests/integration/django_apps/test_append_only_evidence.py` -- the pattern for a fixture evidence model with a real table (`isolate_apps` plus `connection.schema_editor()`, built once outside the per-test transaction).
- `tests/clocks.py` -- `FIXED_INSTANT`, `OBSERVATION_GAP`, `LATER_INSTANT`; two clocks, never one wound forward.
- `tests/celery_tasks.py`, `tests/model_registry.py` -- the helper-module shape for anything shared between audits.
- `tests/source_scan.py` -- `project_files`, `SRC_ROOT`, `RECORDED_EXEMPTIONS` conventions for a source sweep.

## Tasks & Acceptance

**Execution:**
- `.../core/transport.py` -- new. The `Transport` protocol and one `requests`-backed
  implementation. Timeout is a required constructor argument; retry with backoff is a
  `urllib3.Retry` mounted on an `HTTPAdapter`, so no new dependency arrives. Returns a
  recorded payload object, never a live response.
- `.../core/rate_limit.py` -- new. A cache-backed limiter keyed per collector, reading
  `django.core.cache` through its public API only. States in the module why it cannot branch
  on the backend.
- `.../core/collection.py` -- new. The collector base: declared configuration
  (`name`, `evidence_model`, `observation_window`, `timeout`, rate-limit settings), the
  abstract `translate(payload)`, the window query, the `error`/`not_found` evidence rule, and
  the orchestration that opens `collection_run(...)`, calls the transport, and writes evidence
  inside a per-package `transaction.atomic()` **nested inside** the recorder.
- `tests/collectors.py` -- new helper. Fixture collectors, a fake transport returning
  recorded payloads, and a fixture evidence model with a real table, in the shape
  `tests/integration/django_apps/test_append_only_evidence.py` already uses.
- `tests/unit/django_apps/test_transport.py` -- the timeout requirement, the retry policy's
  shape, and that a payload is recorded rather than live. No network.
- `tests/unit/django_apps/test_rate_limit.py` -- the limiter over a real LocMem cache, and
  that no branch reads the backend.
- `tests/unit/django_apps/test_collection.py` -- every I/O matrix row that needs no database,
  driven through a fake transport: window skip, forced bypass, other-package and failed-run
  cases, `error` and `not_found` mapping, and the construction-time timeout refusal.
- `tests/unit/django_apps/test_collector_base_audit.py` -- the source sweep: no module
  outside `core/transport.py` constructs a session, sets a timeout, or declares a retry or a
  rate limit; and the base never wraps the recorder in `transaction.atomic()`. Both with
  anti-vacuity guards measured against fixture sources.
- `tests/integration/django_apps/test_collection.py` -- the rows needing real tables and one
  real transport: evidence inserted against a fixture evidence model, the ledger row present
  and finalized, and one end-to-end call against a local `http.server` proving the transport
  once, as `CPM-AD-27` intends.

**Acceptance Criteria:**
- Given a collector configured with an observation window, when a `succeeded` run for the
  same collector and package sits inside it, then the transport is never called and the
  ledger row reads `skipped` with no evidence written.
- Given the same state and a forced recollection, when the collector runs, then the window is
  bypassed and evidence is written.
- Given a source that fails every retry, when the run ends, then an evidence row carrying
  `error` exists, no row carries `ok`, and the ledger row is `failed`.
- Given the base's orchestration, when the source is swept for transaction handling, then no
  `transaction.atomic()` encloses `collection_run(...)` -- the constraint
  `CPM-EVIDENCE-S03` deferred.
- Given the full gate, when `pixi run ci` runs, then it exits 0 with coverage at or above 90%.
- Given a real PostgreSQL, when `pixi run gate-postgres` runs, then the suite passes there too.

## Spec Change Log

**The I/O matrix is split across the two tiers differently from the Execution list.** The
list puts "window skip, forced bypass, other-package and failed-run cases" in
`tests/unit/django_apps/test_collection.py`. All four drive `collect()`, and `collect()`
opens `core/ledger.py`'s recorder, whose first act is to insert a `running` row -- so every
one of them touches a database by construction, and putting them in the unit tier would mean
either a `django_db` marker in a tier the architecture spine says touches no database, or
substituting the recorder, which the Always clause forbids ("adds no second recorder"). They
are in `tests/integration/django_apps/test_collection.py`, together with the rest of the
matrix. What stayed in the unit tier is everything the base decides *before* it commits to a
run: the five construction refusals, and the window's filter as a `Q` -- which is where the
other-package, other-collector and failed-run conditions are actually decided, and where a
missing keyword is one line from being invisible. Both modules say so in their docstrings.

**"Sets a timeout" is read as three rules rather than one, and the audit carries five.** The
Execution list asks the audit to fail when a module outside `core/transport.py` "constructs a
session, sets a timeout, or declares a retry or a rate limit". Taken literally, the middle
clause would ban the collector's own `timeout` declaration, which the Always clause positively
requires (configuration the collector *declares*).
`tests/unit/django_apps/test_collector_base_audit.py` therefore enforces: no transport surface
-- session, adapter, retry, socket, `urllib`, `httpx`, `aiohttp`, each listed by constructor
*and* by module-level verb -- outside `core/transport.py`; every `timeout=` keyword recorded
per module, with `timeout=None` licensed nowhere at all; and no cache read outside
`core/rate_limit.py`. Two `timeout=` keywords are recorded: `core/transport.py`'s, on the
request itself, and `core/collection.py`'s, where the base builds its default transport from
the declared value. The fourth rule is AC 4's -- no `transaction.atomic()` encloses
`collection_run(...)`, in all three spellings including the single-`with` compact one -- and
the fifth is its converse: every evidence write in `core/collection.py` must be *inside* one,
which is `CPM-AD-23` and which the inverted-nesting rule alone cannot state.

**`config/authorization/jwks.py` is a recorded exemption, and it earns its place twice.** It
is inherited platform -- a `requests.get` with an explicit timeout behind Bearer
authentication -- and routing it through `core` would make `config` import a domain
application, inverting the dependency direction `AD-4` fixes, exactly as
`tests/unit/django_apps/test_clock_audit.py` argues for its own three. It is also the audit's
only piece of in-tree evidence written by somebody else, so
`test_the_detectors_find_what_the_named_modules_actually_contain` measures the resolution
against it.

**The rate limit is required, it refuses rather than waits, and it counts requests rather
than collections.** The matrix says a spent allowance means "the call waits or is refused per
configuration". Waiting is not offered: a Celery task blocked on a limiter holds a worker slot
doing nothing against the inherited limits (`CPM-AD-9`), and `CPM-AD-23` already makes one
package the atomic unit, so the useful response to exhaustion is to record it and let the next
run collect. `RateLimit` is likewise a required declaration rather than an optional one --
"never issued unlimited" is not a property a collector should be able to opt out of by
omission.

The third part is the one `CPM-AD-20` asks for by putting retry and rate limiting in the same
base: the limiter is charged `1 + retries` per collection, because that is how many real
requests the mounted retry policy may issue. A limiter consulted once per collection while the
transport retried underneath it would turn a declared sixty calls a minute into two hundred and
forty. `retries` therefore joins the declared configuration, so the number the limiter is
charged and the number `urllib3` will attempt come from one place. All of it is stated in
`core/rate_limit.py`.

**The base declares a third abstract method, `sentinel_evidence`, and checks what it returns.**
The Execution list names `translate(payload)`. A base that owns no evidence model cannot
*shape* the `error` and `not_found` rows the Always clause requires it to always write, so the
split is: the base decides which sentinel and that there is always one, and the collector
shapes a row in the table `CPM-AD-7` gives it. Inventing a row shape in `core` would need the
concrete evidence table the Block If clause forbids.

What the base does not do is trust the result. A subclass that ignored the `state` argument and
wrote a determinate value would type-check, would write a row on every failing path so "never
no row" still held, and would report every unreachable source as clean -- "never a clean
result" defeated from inside the contract. So the base requires the returned row to carry the
state's value verbatim in one of its fields, which `CPM-AD-24` already requires of every
surface and which is exactly what makes the check possible. The same reasoning covers
`observed_at`: `bulk_create` does not call `save()`, so `AppendOnlyModel`'s naive-instant
refusal -- the one `core/models.py` calls "the one place every evidence write passes through" --
would have been bypassed by every write this base makes. It is restored at the write and
strengthened to require *this* observation's instant, because one observation has one moment
(`CPM-AD-7`) and a mis-stamped row lands in a table nothing may correct.

**`Retry` is reached through `requests.adapters`, with a narrow stub ignore.**
`requests.adapters` binds `Retry` at import time and `HTTPAdapter(max_retries=Retry(...))` is
the recipe both projects document, so no undeclared package appears in an import statement
(`pixi.toml` declares `requests`, not `urllib3`). `types-requests` does not list it among the
module's re-exports, so the import carries `# type: ignore[attr-defined]` with the reason
recorded beside it. No new dependency arrives, which is what the Never clause asks.

**The fixture evidence model is built inside `isolate_apps` and cached, not declared at
module scope.** Declared at module scope in `tests/collectors.py` it would join the global app
registry as a model in `core`, which is a table no migration builds
(`test_migration_completeness.py`) and an evidence model every audit in
`tests/model_registry.py`'s family then has an opinion about. Built inside `isolate_apps` and
cached, it is one class for the whole session -- the unit tier's type and the integration
tier's real table -- and invisible to the sweeps.
`test_the_fixture_evidence_model_is_invisible_to_the_registry_sweeps` asserts the consequence
rather than trusting the mechanism, from the unit tier, where the audits it guards run.

**An empty translation is a failure, not a clean success.** Not in the matrix, and it is the
failure the Intent section opens by naming -- "a rate-limited source quietly producing a clean
result". A parser that finds nothing in a body the source served no longer matches its source,
and a `succeeded` run with no evidence is indistinguishable on every read surface from a
package nothing has gone wrong with. It writes an `error` row and finalizes `failed`.

**The transport takes four decisions the spec did not name, all in the module that owns the
boundary.** A scheme allowlist and a host requirement, so a `file://` locator assembled from
configuration cannot read the filesystem through a seam that exists to read the network.
Redirects are not followed -- a redirect is a third-party registry instructing this process to
fetch something else, which is how a call aimed at a package index reaches `169.254.169.254`.
The body is decoded from the charset the source declared and from UTF-8 when it declared none,
rather than through `requests`' ISO-8859-1 fallback, which would write mojibake into an
append-only row that can never be corrected. And a `timeout` above `MAX_TIMEOUT` is refused,
because `requests` applies the value per connect *and* per read *and* again per attempt, so it
multiplies against the inherited Celery limits.

## Review Triage Log

### 2026-09-04 -- Review pass 1

- intent_gap: 0
- bad_spec: 0
- patch: 30 (high 5, medium 15, low 10)
- defer: 6: (high 1, medium 5, low 0)
- reject: 2 (recorded by the coordinator, not acted on)

**All five HIGH findings changed shipped behaviour rather than a test.**

- `[high]` The AC 4 audit missed `with transaction.atomic(), collection_run(...) as run:` --
  one `ast.With` holds both items, so a detector reading the atomic's *body* never saw the
  recorder, and a formatter nudges toward exactly that spelling. Position within the statement
  now decides it (items are entered left to right, so an atomic before a recorder encloses it
  and a recorder before an atomic does not). Two further holes in the same detector went with
  it: relative imports were skipped outright, so `from ..core.ledger import collection_run` was
  invisible; and `BANNED_TRANSPORT_FORMS` listed client classes without module-level verbs, so
  `import httpx; httpx.get(url)` walked through the table whose stated purpose is that adding a
  transport is a failing gate. A property test now asserts every library in that table is
  listed more than once.
- `[high]` `CPM-AD-23`'s per-package transaction was pinned by nothing: deleting
  `with transaction.atomic():` from `_write_evidence` left the whole suite green, because the
  property it buys is invisible with one package. Both halves are now asserted -- a positive
  audit rule that every evidence write in `core/collection.py` is inside an atomic, and a
  two-package case where the second package's write is refused by the schema and the first
  package's evidence survives.
- `[high]` `translate` returning an empty sequence produced a `succeeded` run with zero
  evidence rows, contradicting `CollectionResult.evidence_rows`' own docstring and the module
  docstring's opening sentence. It is now a `failed` run with an `error` row.
- `[high]` Retries were not counted against the allowance, so a collector declaring sixty calls
  a minute could issue two hundred and forty requests. `acquire` takes a `cost`, `retries`
  joins the declared configuration, and the base charges `1 + retries` up front.
- `[high]` `bulk_create` bypassed `AppendOnlyModel.save()`'s naive-`observed_at` refusal on
  every write this base makes. The check is restored at the write and strengthened to require
  the exact instant the run was handed.

**The fifteen MEDIUM findings**, each addressed: the sentinel row is checked against the state
it was asked for; `evidence_model` must inherit `AppendOnlyModel`; every declaration is refused
for its *type* as well as its absence; all four event names are asserted through `capture_logs`
with the repository's rebind-and-control-event pattern; the ledger's `detail` is declared on
every terminal path and asserted equal to the returned result's; `window_key` refuses a naive
instant; the transport gained a scheme allowlist, a redirect refusal, an explicit charset
decision and a timeout ceiling; the retry policy is proved behaviourally against a local server
that answers `503`-then-`200` and `503`-always; `FixedLimiter` records every ask; the sentinel
write is wrapped so a database failure carries the original reason rather than replacing it;
`Collector` gained `close()` and a context manager that release only a transport it built;
`RunState.PARTIAL` is decided (excluded, with the reason) via a named `SUPPRESSING_STATES`; and
`NO_WINDOW` short-circuits rather than querying, because the inclusive boundary is unreachable
under `SystemClock` and exactly reproducible under the suite's `FixedClock`.

**The ten LOW findings**, each addressed: the two modules cite the same inherited Celery limits;
the backoff formula and its series are reconciled with a note saying why they differ at the
first term; `rate_limit.py`'s prose matches what `collection.py` writes; the timeout's
docstring says what it does and does not bound; `__all__` carries `NO_WINDOW` and
`INITIAL_COUNT`; `CollectorConfigurationError` and `RateLimitError` are both `ValueError`
(and `TransportError` deliberately is not); `sentinel_evidence` is keyword-only; the
registry-invisibility case moved to the unit tier; the transport cases use yielding fixtures so
a failure cannot leak a session; `RecordedTransport` raises instead of asserting; `cleared_cache`
is one helper both suites use; and the four event names are dotted and carry one key set.

## Design Notes

**How AC 4 is proven with no evidence table in the repository.** `CPM-AD-7` gives each
collector its own evidence table and puts the first in `CPM-EP-CURRENCY`; `CPM-EVIDENCE-S02`
was forbidden to create one for the same reason. So the base does not *own* an evidence
model -- it declares the contract (`evidence_model` plus `translate`) and drives the write,
and the guarantee is proven against fixture evidence models with real tables, exactly as
`tests/integration/django_apps/test_append_only_evidence.py` proves the append-only base
today. A table invented here would be one no collector wants and one the append-only audits
would then police forever.

**Why the ledger row must sit outside the transaction, restated as code.**
`core/ledger.py` records that the `running` row is only useful if it is *committed* before
the outbound call, that a caller wrapping the recorder in `transaction.atomic()` loses it,
and that no runtime guard was available because `django_db` runs every test inside such a
block. The guard that *is* available is a source sweep, and this is the story that has
something to sweep:

```python
with collection_run(collector=self.name, clock=clock, package_id=package_id) as run:
    payload = self._transport.fetch(...)          # outside any transaction
    with transaction.atomic():                    # nested, one package
        self.evidence_model.objects.bulk_create(self.translate(payload))
```

**Rate limiting reads the cache API and nothing below it.** `config/settings/local.py`
argues that the LocMem substitution is a substitution precisely because the cache *API* is
preserved, and that a call site branching on the backend turns it into a second code path
local runs never exercise. The limiter therefore uses `add`/`incr`/`get` only. The
consequence is worth stating rather than discovering: under LocMem the window is per
process, so a local run with two workers rate-limits twice as fast as production. That is a
property of the substitution, not of the limiter.

## Verification

**Commands:**
- `pixi run test` -- expected: the unit suite passes, no network opened.
- `pixi run test-integration` -- expected: passes, including the single real-transport case.
- `pixi run ci` -- expected: exits 0, coverage at or above 90%.
- `pixi run gate-postgres` -- expected: the suite passes against `postgres:17`.

## Auto Run Result

Status: done
Blocking condition: none

**Implemented.** One base in `core` owning the transport boundary, so a collector is a pure
translation from a recorded payload to evidence rows and needs no network to test
(`CPM-AD-27`). The base applies the timeout, the rate limit and retry-with-backoff, consults
the observation window, writes evidence inside a per-package transaction nested in the run
recorder, and finalizes the ledger row `CPM-EVIDENCE-S03` built.

**Files changed**

- `src/.../core/transport.py` -- new. The `Transport` protocol, the frozen `Payload`, and one `requests`-backed implementation with a required timeout, `urllib3` retry, a scheme allowlist, no redirect following, and explicit charset decoding.
- `src/.../core/rate_limit.py` -- new. `RateLimit`, the `RateLimiter` protocol, and a fixed-window cache-backed limiter that reads the cache API only.
- `src/.../core/collection.py` -- new. The `Collector` base: declared configuration checked at construction, three abstract methods, the window query, the `error`/`not_found` rule, and the orchestration.
- `tests/collectors.py` and five test modules -- fixtures, the four behavioural tiers, and the five-rule source audit.

**Review findings:** 30 patched (5 high, 15 medium, 10 low), 6 deferred, 2 rejected.

**Follow-up review recommended:** true. Patched counts by severity: high 5, medium 15, low 10.
Any high-severity patch fires the rule on its own; the score `3 x 15 + 1 x 10 = 55` also exceeds 5.

**This story satisfies three of `CPM-NFR-3`'s four clauses, not all four.** Rate limiting,
retries with backoff and request timeouts are here; **caching is not implemented**. The
omission originated in this spec, which never asked for it, and it is the first entry in
`deferred` above. The story header's "Satisfies: `CPM-NFR-3`" line must be read against that
entry rather than at face value.

**Verification.** `pixi run ci` exits 0 -- 2943 tests, coverage 97.70% against a 90% floor,
with `collection.py`, `rate_limit.py` and `transport.py` each at 100%. `pixi run gate-postgres`
exits 0 against `postgres:17`.

The two high-severity findings that mattered most were found by mutation before the review
layers reported, and re-verified by mutation after the fix rather than taken on report:

- Wrapping the recorder as `with transaction.atomic(), collection_run(...) as run:` -- the
  compact spelling of the exact violation AC 4 bans -- passed the audit before and fails it
  now.
- Deleting `with transaction.atomic():` from `_write_evidence` left all 144 cases passing
  before; it now fails four, including the new positive-direction rule. `CPM-AD-23`'s
  per-package transaction had been pinned by nothing.

**Residual risks.** The six deferred entries. The first is the one that changes what this
story may be said to have delivered: `CPM-NFR-3`'s caching clause is unmet. The second is a
semantic decision the spec did not make and the coordinator declined to make after the fact --
whether a spent rate limit should write an `error` evidence row at all, when `CPM-NFR-3` says
such a source "degrades to stale evidence". The third is `CPM-EVIDENCE-S03`'s commit-ordering
fact, still standing behind a static sweep rather than a runtime assertion.
