---
title: 'CPM-EVIDENCE-S08: Conditional requests, cached responses, and one shared allowance'
type: 'feature'
created: '2026-09-04'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: true
baseline_revision: '915d555c4e174c3cf56776f61b0071c55d0de59e'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s05-collector-base-carrying-external-call.md
warnings: ['oversized']
deferred:
  - summary: >-
      A conditional request still costs the full `1 + retries` allowance, so this story saves
      bandwidth rather than rate limit -- which is not what its own user story promises.
    evidence: |-
      The Intent opens with "a daily sweep over ten thousand packages does not spend its rate
      limit re-reading bodies it already has", but the Never clause forbids changing "the
      allowance arithmetic S05 settled (a collection charges `1 + retries` up front, before any
      call, conditional or not)". Both are inside `<intent-contract>`, and they disagree. The
      limiter is charged before the call and never refunded for a `304`. GitHub -- named in
      `CPM-AD-20`'s own reasoning as why the rule exists -- does not count `304` responses
      against its primary rate limit at all, so the arithmetic is also wrong about the source
      that motivated it. Resolving it means either refunding a not-modified answer or amending
      the user story; neither is this story's to decide.
    severity: medium
  - summary: >-
      A source's own cacheability directives are ignored: no `Cache-Control`, no `Vary`.
    evidence: |-
      `core/response_cache.py` stores and replays a body for the collector-declared lifetime
      regardless of `no-store`, `no-cache` or `max-age`, and `Vary` is not considered at all.
      "No HTTP-caching library" is a deliberate scope decision the Intent takes, but the
      consequence -- that this product may cache what a source asked it not to -- is stated
      nowhere in the story, the module docstring or the matrix.
    severity: medium
  - summary: >-
      The cache key omits the declared headers, so changing a representation or an identity
      replays the previous body until the entry expires.
    evidence: |-
      `response_key(collector, source)` is built from the collector name and the locator only.
      A collector that changes its declared `Accept`, `Authorization` or `User-Agent` asks a
      different question and may get a different representation, but reads back the old one
      under the same key. Headers are class-level, so this bites on deploy -- which is exactly
      when nobody is looking for a stale body.
    severity: medium
  - summary: >-
      Nothing bounds the size of a remembered body.
    evidence: |-
      Whole response bodies are written to a shared Redis with no cap, truncation or recorded
      decision to decline one. The product's stated target is a daily sweep over ten thousand
      packages, and its sources include repodata-scale documents.
    severity: medium
  - summary: >-
      A cache-backend outage still fails a run in any environment that does not set
      `IGNORE_EXCEPTIONS`, which is production-only.
    evidence: |-
      `CacheResponseCache` catches only the `TypeError`/`ValueError` an unusable entry raises,
      so a `redis.ConnectionError` from `cache.get` propagates out of `collect()` after the
      `running` ledger row is committed. `config/settings/production.py` sets
      `IGNORE_EXCEPTIONS: True`, which is what actually delivers "caching only ever saves work";
      the gate's Redis-backed settings deliberately omit it. The docstring now names that
      mechanism rather than overclaiming, but the exposure is real wherever the flag is absent.
      `core/rate_limit.py` has the identical exposure and predates this story.
    severity: medium
  - summary: >-
      `response_key` does not normalize the collector name, which reaches the cache key raw.
    evidence: |-
      The locator is `sha256`-hashed precisely so no key can breach a backend's key rules, but
      the collector name is interpolated verbatim. `_require_name` in `core/collection.py`
      refuses only a blank name, so a name carrying a space or a control character produces the
      `CacheKeyWarning` the hashing exists to avoid. No collector exists yet, so the key format
      is still free to change; it will not be once eight of them depend on it.
    severity: low
  - summary: >-
      `scripts/gate-postgres.sh` has the cleanup gaps that were fixed in `gate-redis.sh`.
    evidence: |-
      The new script traps `EXIT INT TERM` and checks `docker run`'s exit status. Its older
      sibling does neither, so interrupting it leaves `pg-local` running with port 55432 bound,
      and a failed image pull surfaces thirty seconds later as "never became ready" rather than
      as the pull error it was. Left alone deliberately: changing it is not this story's work.
    severity: low
---

<intent-contract>

## Intent

**Problem:** `CPM-EVIDENCE-S05` built the collector base and delivered three of `CPM-NFR-3`'s
four clauses -- rate limiting, retry with backoff, request timeouts -- and recorded the
fourth, caching, as unmet in its `deferred` list. A daily sweep over ten thousand packages
therefore re-transfers every body whether or not it changed, and `Transport.fetch` takes a
bare `source: str` with no way for a collector to send the `User-Agent`, `Authorization` or
conditional-request header its source expects.

**Approach:** Widen the transport seam to carry request headers, teach it that `304` is an
answer rather than a failure, add one `core` module that remembers a response and its
validator through `django.core.cache`'s public API, and have the collector base compose the
conditional request and replay the cached body into `translate` on a `304`. Separately, prove
against a real Redis that two worker *processes* share one rate-limit counter -- a property
the LocMem substitution cannot fail.

## Boundaries & Constraints

**Always:**
- Every cache read and write goes through `django.core.cache`'s public API. No call site names
  `CACHES`, a backend class, or branches on which backend is active -- the rule
  `core/rate_limit.py` already obeys and `tests/unit/django_apps/test_collector_base_audit.py`
  sweeps for.
- A `304` is an **observation**, never `not_found` and never `unknown` (`CPM-AD-5`, `R-01`). It
  writes evidence and finalizes a ledger row like any other successful run.
- Headers reach the socket only through the base (`CPM-AD-20`, `CPM-AD-27`). No collector opens
  a connection, builds a session, or sends a header itself.
- The response cache is written **only after** the evidence write for that payload succeeded. A
  body cached before translation would let a parser failure become permanent: the next run gets
  a `304` and replays the same unparseable body forever.
- Every refusal raises (inherited `CG-3`). Declaration defects are `ValueError` subclasses and
  are raised at construction wherever the answer exists then.
- Time comes from the injected clock (`CPM-AD-26`). No module calls `timezone.now()`.
- `pixi` is the only Python runner.

**Block If:**
- A cached response would have to be keyed on anything but the collector name and the locator
  it read -- that would be a per-package cache identity nothing in the spine decides.

**Never:**
- No concrete collector and no concrete evidence model (`CPM-AD-7` puts the first in
  `CPM-EP-CURRENCY`).
- No change to the observation window, the retry policy, or the allowance arithmetic S05
  settled (a collection charges `1 + retries` up front, before any call, conditional or not).
- No freshness-target or observation-window *values* (PRD Open Question 7).
- No HTTP-caching library and no new runtime dependency. `requests`, `django-redis` and
  `redis-py` are already declared.
- No `-m` on `test-cov`, and no lowering of the 90% floor.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First observation | No cache entry for `(collector, source)` | Unconditional `GET` carrying the declared headers; `200` parsed; entry written with body + `ETag`/`Last-Modified` **after** the evidence write | No error expected |
| Unchanged upstream | Entry holds an `ETag` | `If-None-Match` sent; source answers `304` with no body; cached body replayed through `translate`; evidence rows written; run `succeeded`; entry's TTL refreshed | No error expected |
| Unchanged, date validator only | Entry holds only `Last-Modified` | `If-Modified-Since` sent; same as above | No error expected |
| Declared headers | Collector declares `User-Agent` / `Authorization` | Header travels through the base to the socket, merged under the base's conditional headers | No error expected |
| Collector forges a validator | Collector declares `If-None-Match` | Refused at construction: the base owns conditional headers | `CollectorConfigurationError` |
| `304` with nothing cached | Source answers `304` to a request carrying no validator | Run `failed`, `error` evidence row: there is no body, so no observation can be recorded | Detail names the source and the misbehaviour |
| Unusable cache entry | Stored value is not the recorded shape (a rolling deploy, a key collision) | Logged under `response_cache.unusable_entry`, entry forgotten, treated as a miss -- an unconditional fetch follows | Never raises; a cache is not an authority |
| Caching disabled | `response_cache_ttl` is `NO_CACHE` | No cache read, no cache write, no conditional header; every run fetches | No error expected |
| Absent resource | Source answers `404`/`410` | `not_found` evidence as today, and the cached entry is forgotten | No error expected |
| Translation fails after `200` | Parser raises or returns nothing | `error` evidence and a `failed` run as today, and **no** cache write | Reason preserved |
| Retry policy given `304` | `retry_statuses` includes `304` | Refused at construction: retrying an answer spends allowance re-asking | `ValueError` |
| Two processes, real Redis | Both `acquire` for one collector in one window | The counter is shared; the allowance is granted the declared number of times **across** the two processes | No error expected |
| Two processes, LocMem | The default suite | Case is not run; it names the env var it needs | Recorded exemption in `test_suite_policy.py` |

</intent-contract>

## Code Map

- `src/.../core/transport.py` -- the seam to widen. `Transport.fetch` (protocol) and
  `RequestsTransport.fetch` both take `source: str` only; `Payload` is a frozen 4-field
  dataclass; `ABSENT_STATUSES`, `DEFAULT_RETRY_STATUSES` and the constructor's refusal of a
  retried absent status are the patterns `304` follows. `_decoded` must not run for a `304`.
- `src/.../core/rate_limit.py` -- the reference implementation for "reads the cache and nothing
  below it": `cache.add`/`incr`/`set`, `KEY_PREFIX`, a `Protocol` + a cache-backed class, and a
  module docstring stating what the LocMem substitution changes. Read only; the new cache
  module mirrors its shape. **Unchanged by this story** -- AC 4 proves what it already does.
- `src/.../core/collection.py` -- `Collector`'s six declared ClassVars and their
  `_require_*` module functions; `collect()`'s ordering (recorder outermost, window, limiter,
  fetch, `transaction.atomic()` around the write only); `COLLECTION_*_EVENT` names and
  `EVENT_KEYS`; `_write_evidence`/`_require_stamped`.
- `src/config/settings/test.py` -- pins `LocMemCache` deliberately; the place a Redis-backed
  run is selected from, in the shape `DATABASE_URL` already selects PostgreSQL.
- `src/config/settings/production.py` -- `django_redis.cache.RedisCache` + `DefaultClient`,
  the backend a Redis-backed test run must use for fidelity.
- `tests/unit/django_apps/test_collector_base_audit.py` -- `RECORDED_EXEMPTIONS` (counted per
  form per file), `THE_NEW_MODULES`, `CACHE_RECEIVERS`. A new cache-reading module fails this
  file until it is recorded.
- `tests/unit/django_apps/test_rate_limit.py` -- `PERMITTED_CACHE_CALLS`, `BACKEND_TELLS`, the
  public-API scan, the names-no-backend scan and its anti-vacuity guard. The template for the
  new module's own structural cases.
- `tests/collectors.py` -- `RecordedTransport.fetch(source)` (signature must widen),
  `recorded_payload`, `FixedLimiter`, `collector_class(declared_*)` factory, `cleared_cache`.
- `tests/integration/django_apps/test_collection.py` -- `_Handler` (a real `http.server`
  origin, one path per `fetch` outcome), the module-scoped `served_url` fixture on port 0.
- `tests/unit/test_suite_policy.py` -- `BANNED_MARKERS` includes `skipif`; `RECORDED_EXEMPTIONS`
  is counted per form per file and is asserted in both directions.
- `tests/unit/test_gate_contract.py` -- asserts the gate job's services and job-level env, and
  its `test_no_other_job_declares_a_database_service` docstring explicitly sanctions "a future
  non-database service -- a Redis ... say".
- `scripts/gate-postgres.sh` + `[feature.gate.tasks]` in `pixi.toml` -- the shape the Redis
  counterpart copies (docker readiness loop, throwaway container, non-default host port).
- `.github/workflows/ci.yml` -- the `gate` job: `services:` and job-level `env:`.

## Tasks & Acceptance

**Execution:**
- `src/.../core/transport.py` -- widen `Transport.fetch` and `RequestsTransport.fetch` with a
  keyword-only `headers: Mapping[str, str] | None`; add `NOT_MODIFIED_STATUS`, `ETAG_HEADER`,
  `LAST_MODIFIED_HEADER`, `IF_NONE_MATCH_HEADER`, `IF_MODIFIED_SINCE_HEADER`; give `Payload`
  `not_modified`, `etag`, `last_modified`; return a not-modified payload for `304` before the
  redirect and `ok` checks and without decoding a body; refuse `NOT_MODIFIED_STATUS` in
  `retry_statuses` on the same terms as `ABSENT_STATUSES` -- caching cannot exist without a way
  to send a validator and read the answer.
- `src/.../core/response_cache.py` -- **new.** `ResponseCacheError`, frozen `CachedResponse`
  (`body`, `etag`, `last_modified`) refusing an entry carrying no validator, `response_key`
  (namespaced, with the locator hashed so no key can breach a backend's key rules),
  `conditional_headers`, the `ResponseCache` protocol (`read`/`write`/`forget`) and one
  `CacheResponseCache` over `cache.get`/`set`/`delete` -- one module owns the response cache,
  as one module owns the counter.
- `src/.../core/collection.py` -- add declared `headers` and `response_cache_ttl` ClassVars
  with `_require_headers`/`_require_cache_ttl` refusals (including a collector declaring a
  conditional-request header) and a `NO_CACHE` sentinel; take a `response_cache` constructor
  seam; in `collect()` read the entry, merge conditional headers under the declared ones, pass
  them to `fetch`, replay a `304`'s cached body into `translate`, fail a `304` that has no
  entry behind it, forget the entry on `not_found`, and write the entry only after the evidence
  write succeeded; add `COLLECTION_NOT_MODIFIED_EVENT` -- the base owns every external-call
  rule, and caching is the fourth.
- `tests/unit/django_apps/test_collector_base_audit.py` -- record the new module's cache calls
  in `RECORDED_EXEMPTIONS`, add it to `THE_NEW_MODULES`, and amend the docstring's "one module
  reads the cache" to name both and say why the split is by purpose -- an unrecorded cache
  reader must fail this file, and a stale exemption must fail it too.
- `tests/unit/django_apps/test_response_cache.py` -- **new.** Behavioural cases against the real
  cache plus the two structural scans `test_rate_limit.py` carries (public API only, names no
  backend, with its anti-vacuity guard).
- `tests/unit/django_apps/test_transport.py` -- cases for the header pass-through, the `304`
  payload, validator capture, the retry refusal, and that a `304` body is never decoded.
- `tests/unit/django_apps/test_collection.py` -- cases for the two new declaration refusals, the
  composed header set, the `304` replay, the `304`-with-no-entry failure, and the write-after-
  evidence ordering.
- `tests/collectors.py` -- widen `RecordedTransport.fetch` to record headers, add validator
  arguments to `recorded_payload`, add a recording `ResponseCache` fake, and add
  `declared_headers`/`declared_cache_ttl` to `collector_class`.
- `tests/integration/django_apps/test_collection.py` -- add a conditional path and a
  header-echo path to `_Handler`; prove a real `304` round trip and a real header over a socket.
- `tests/rate_limit_workers.py` -- **new.** The subprocess entry point AC 4 needs: configure
  Django from the environment, `acquire` once against a window named on the command line,
  report the verdict.
- `tests/integration/django_apps/test_shared_allowance.py` -- **new.** AC 4: two OS processes,
  one collector, one window, against a real Redis; the allowance is granted the declared number
  of times across both.
- `tests/unit/test_suite_policy.py` -- record the one `pytest.mark.skipif` the case above needs.
- `src/config/settings/test.py` -- select `django_redis.cache.RedisCache` when
  `CPM_TEST_REDIS_URL` is set, exactly as `DATABASE_URL` selects PostgreSQL.
- `scripts/gate-redis.sh` + `pixi.toml` -- a `gate-redis` task in the shape of `gate-postgres`,
  so the Redis proof is one command locally.
- `.github/workflows/ci.yml` -- a `redis:7` service on the gate job and `CPM_TEST_REDIS_URL` at
  job level, so AC 4 is proven on every pull request rather than only when someone remembers.
- `tests/unit/test_gate_contract.py` -- pin the Redis service, its health gate, and that
  `CPM_TEST_REDIS_URL` names it -- otherwise deleting the service would silently turn AC 4's
  proof back into a skip.
- `docs/development.md` -- document `gate-redis` beside `gate-postgres`.

**Acceptance Criteria:**
- Given a collector whose source answered before with a validator, when it collects again and
  the source still holds that validator, then the request carries `If-None-Match` (or
  `If-Modified-Since`), the source answers `304` with no body, evidence rows are written from
  the cached body and the ledger row is `succeeded`.
- Given a collector that declares a `User-Agent` or `Authorization` header, when it collects,
  then the header reaches the socket through the base, and no collector code opens a connection.
- Given the response cache, when it is read or written, then only `django.core.cache`'s public
  API is used and no call site names a backend -- asserted by scan, as the limiter's is.
- Given two worker processes collecting for one collector inside one window, when both ask for
  the allowance against a real Redis, then the counter is shared and the allowance is spent once
  across the pair.
- Given `pixi run ci`, when it runs, then it exits 0 with coverage at or above the 90% floor.

## Spec Change Log

**The three `collect()`-driven cases moved to the integration tier, and the
header composition became a module function so one of them could stay.** The
Execution list puts "the `304` replay, the `304`-with-no-entry failure, and the
write-after-evidence ordering" in `tests/unit/django_apps/test_collection.py`.
All three drive `collect()`, and `collect()` opens `core/ledger.py`'s recorder,
whose first act is to insert a `running` row -- so each touches a database by
construction, which is the identical split `CPM-EVIDENCE-S05` recorded for its
own matrix rows and resolved the same way. They are in
`tests/integration/django_apps/test_collection.py` with the rest of the matrix.
What stayed in the unit tier is what the base decides before it commits to a run:
the two new declaration refusals, and the composed header set -- which is
reachable there because `request_headers(declared=, entry=)` is a module function,
exactly as `window_query` is and for the same stated reason. A dictionary merge is
one keyword from losing a declaration or from letting a collector's header
overwrite the base's, and neither failure changes any behavioural assertion.

**`response_cache_ttl` is required; `headers` is not.** The Execution list asks
for `_require_headers`/`_require_cache_ttl` refusals without saying whether
either declaration may be omitted. They are treated differently because the two
absences mean different things. For the lifetime, `NO_CACHE` and "omitted" are
distinguishable statements -- one says "read a body every run" where a reader can
see it, the other says nothing -- so absence is refused on exactly the terms
`observation_window`'s is. For headers, an empty mapping and an omitted one are
the same statement, so the declaration defaults to an empty mapping and what is
refused is a mistyped one and a *conditional* one. The conditional refusal
matches header names case-insensitively, because `if-none-match` is the same
header and the same mistake.

**A `200` carrying no validator is remembered as nothing, and that is not a
failure.** The matrix does not name the case. `CachedResponse` refuses an entry
with neither an `ETag` nor a `Last-Modified` -- such an entry could only ever be
replayed unconfirmed, which is stale evidence wearing a cache's name -- so the
base catches that refusal at the write and remembers nothing. The collection
still succeeds: a source that offers no validator is a source this collector will
keep re-reading, which is what it would have to do anyway, not a defect to record
as an `error` row.

**The entry is keyed on the locator the run asked for, not on `payload.source`.**
Both are "the locator it read" as the Block If clause names it, and they are the
same string for `RequestsTransport`. They need not be for a substituted transport
-- `CPM-AD-29`'s inventory adapter is the first -- and a key built from a value
the transport supplied is a key a source could choose. The base passes the
locator `source_for` returned.

**AC 4 is two cases, because one arrangement cannot see both halves of the
sequence.** Two workers started *together* prove the counter is shared: against
LocMem both are permitted and the case fails, which is the property AC 4 states.
They cannot distinguish `add` from `set`, though -- overlapping processes both
write the counter to zero before either increments it, so it reaches two and one
is refused either way. The claim `core/rate_limit.py` actually makes in its own
words is that a process must not *reset* a window it did not start, and that is
visible only when the second worker arrives after the first has finished, which
is the ordinary shape of a sweep. Both cases are in
`tests/integration/django_apps/test_shared_allowance.py`; the second one fails
against an `add`-to-`set` mutation and the first does not.

**Two smaller mechanical decisions, recorded because each carries a `noqa`.**
`collections.abc.Mapping` is imported at run time in `core/transport.py` rather
than under `TYPE_CHECKING`: `tests/unit/django_apps/test_transport.py` pins
`fetch`'s return type through `get_type_hints`, which evaluates every annotation
in the signature, and a name absent at run time turns that pin into a
`NameError`. And `collect()` carries `# noqa: PLR0911` for its seventh return:
the returns are the matrix's terminal paths, each declaring the `detail` that its
ledger row and its returned result both carry, so collapsing two of them would
mean one explanation written for two different reasons -- and the alternative
shape, a helper returning `Payload | CollectionResult`, moves the ordering the
module docstring is written about out of the method it is written about.

**`gate-redis` runs `test-cov`, not only the case that needs Redis.** The Code
Map asks it to copy `gate-postgres`'s shape; it copies its scope too, and for the
same stated reason -- everything a backend can change lives in the suite, and
`precommit`, `build`, `typecheck` and `lint` open no connection. The whole suite
therefore runs against a real cache under that command, which is parity the story
did not ask for and does not cost anything.

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 21: (high 3, medium 12, low 6)
- defer: 7: (high 0, medium 5, low 2)
- reject: 4: (high 0, medium 2, low 2)
- addressed_findings:
  - `[high]` `[patch]` The one case driving the real cache through `collect()` could not fail:
    every assertion held identically if caching were inert, because the origin serves the same
    `SERVED_BODY` on a `200` as the replay produces. `_Handler` gained a served-body counter and
    the case now asserts the origin served a body exactly once and that
    `COLLECTION_NOT_MODIFIED_EVENT` fired. Mutation-verified against an inert default cache.
  - `[high]` `[patch]` A positive sub-second `response_cache_ttl` truncated to `0`, which Django
    reads as *do not cache* -- a collector declaring caching, passing construction, and caching
    nothing. `_require_cache_ttl` now refuses it, mirroring `RateLimit.per`.
  - `[high]` `[patch]` `_remember` caught `ResponseCacheError` and returned with no log.
    Declared `COLLECTION_NOT_REMEMBERED_EVENT` and logged it as `core/rate_limit.py` logs
    `WINDOW_EXPIRED_EVENT`; `_remember` now takes `package_id` so the line carries every key
    `EVENT_KEYS` promises.
  - `[medium]` `[patch]` A `304`'s validators were captured by the transport and then discarded,
    contradicting `Payload.etag`'s own docstring. A rotated validator now refreshes the entry.
  - `[medium]` `[patch]` The `not_found` branch forgot the entry *before* the evidence write,
    breaking the "cache write is last" rule the module docstring states universally. Moved after
    the write and pinned by a new case.
  - `[medium]` `[patch]` `_require_headers` accepted CR/LF in values (header injection through a
    declared `Authorization`) and names differing only in case (silent last-wins). Both refused.
  - `[medium]` `[patch]` Four docstrings were false after the change: `NO_CACHE` stated Django's
    timeout semantics backwards (`None` never-expires, `0` do-not-cache); `core/rate_limit.py`
    still called itself "the one module that touches the cache"; `_replayed` claimed the
    collector cannot tell a replay from a fetch while returning `not_modified=True`; and
    `core/response_cache.py` promised an outage guarantee that `IGNORE_EXCEPTIONS` actually
    delivers. All corrected.
  - `[medium]` `[patch]` Test-harness defects: `REDIS_URL_SCHEMES` admitted `unix` then required
    a hostname and port; the ttl case monkeypatched through Django's cache proxy and asserted by
    `[-1]`; the awkward-locator case failed on any unrelated warning; `CPM_TEST_REDIS_URL` leaked
    into the Django settings surface.
  - `[low]` `[patch]` `gate-redis.sh` gained an `EXIT INT TERM` trap and a `docker run` status
    check; `FIXTURE_HEADERS` became a `MappingProxyType`; the shared-allowance guard moved into
    the autouse fixture; stale "two autouse fixtures" prose corrected in four places; both gate
    tasks added to the docs table; the story's `## References` block restored; the `skipif`
    exemption prose corrected to say what the count actually constrains.

Two findings were raised by reviewers and rejected after tracing them:

- **"A `304` whose replayed body fails to parse pins the entry forever."** Raised independently
  by two layers, and wrong. Dropping the entry changes nothing: the next run would fetch
  unconditionally and receive the identical body -- an unchanged body is what `304` means -- and
  fail identically. If upstream ever changes, the validator changes and a `200` breaks the
  cycle. Keeping the entry is strictly cheaper, so no invalidation path was added.
- **"Guard against `not_modified=True` arriving with `found=False`."** Unreachable from
  `RequestsTransport`, whose `304` branch returns `found=True`. Only a deliberately broken fake
  transport produces it, and the base trusts the transport seam by design.

## Design Notes

**Why the body is cached and not only the validator.** A validator-only cache would make a
`304` unusable: the run would have confirmed the fact still holds and would have nothing to
write, which is the "never no row" guarantee failing quietly. Caching the response is what lets
a `304` replay through the collector's ordinary `translate` and produce the same evidence a
`200` would have, stamped with *this* run's `observed_at`. Re-observation inserts (`CPM-AD-2`),
so a confirmed-unchanged fact is a new row, which is what makes freshness advance.

**Why the cache write is last.** Ordering, five lines:

```python
payload = self._transport.fetch(source, headers=headers)   # conditional
...
evidence = self.translate(payload, ...)                    # may raise, may be empty
written = self._write_evidence(evidence, observed_at=observed_at)
self._remember(source, payload)                            # only now
```

Caching before the parse would let one malformed body become permanent: every later run sends
the validator, gets `304`, replays the same body, and fails identically without ever re-reading
the source.

**Why a `304` with no cached entry fails.** It is the source contradicting the request: nothing
asked it what changed. There is no body, so no observation exists to record, and inventing an
empty one is the clean-looking result `CPM-NFR-3` forbids.

**Why the key hashes the locator.** `BaseCache.validate_key` warns on control characters, spaces
and keys past memcached's 250-byte limit. A registry URL carrying a query string reaches all
three, and a warning is not a refusal -- the entry would be written to a key some backends
mangle. A `sha256` hexdigest under a named prefix has none of those properties and keys equal
locators equally.

**Why AC 4 needs two real processes.** `core/rate_limit.py`'s `add`-then-`incr` exists so two
processes racing a new window both increment one counter rather than one resetting the other.
Under `LocMemCache` each process holds its own counter, so the property cannot fail and the
reasoning is unproven. Two `subprocess` runs against a `redis:7` container is the same move
`gate-postgres` already makes for schema behaviour -- and putting the service on the CI gate
job means the proof runs on every pull request, not only when someone runs the script.

**Why one recorded `skipif`.** `tests/unit/test_suite_policy.py` bans skips so a CI-only
failure is fixed rather than dodged, and records the exceptions per file per form. A case that
needs a service is the shape its docstring names, the decision is recorded here and in that
table, and the gate job supplies the service -- so the case is skipped only on a developer's
machine with no Redis, never where it would be dodging anything.

## Verification

**Commands:**
- `pixi run ci` -- expected: exit 0. Five steps, coverage at or above 90%.
- `pixi run gate-postgres` -- expected: exit 0. The suite against `postgres:17`, unchanged by
  this story and asserted not to regress.
- `pixi run gate-redis` -- expected: exit 0, and the shared-allowance case **runs** rather than
  skipping. A run reporting it as skipped means the env var never reached pytest.

## References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S08]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-20]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-27]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-3]
- [Source: _bmad-output/implementation-artifacts/stories/cpm-evidence-s05-collector-base-carrying-external-call.md] -- the `deferred` entries this story pays down

## Auto Run Result

Status: done
Blocking condition: none

**What this completes.** `CPM-NFR-3`'s fourth clause. `CPM-EVIDENCE-S05` delivered rate
limiting, retry with backoff and request timeouts and recorded caching as unmet in its own
`deferred` list; that entry is now paid. The collector base composes a conditional request from
what it remembered, a `304` replays the cached body through the collector's ordinary `translate`
and writes the same evidence a `200` would have, and one new module -- `core/response_cache.py`
-- joins `core/rate_limit.py` as the only code under `src/` that touches `django.core.cache`.

**Files changed**

- `src/.../core/transport.py` -- `fetch` carries headers; `Payload` gained `not_modified`,
  `etag` and `last_modified`; `304` is an answer, checked before anything can decode a body, and
  refused in `retry_statuses` on the terms `ABSENT_STATUSES` are.
- `src/.../core/response_cache.py` -- new. `CachedResponse`, `response_key` (locator hashed),
  `conditional_headers`, the `ResponseCache` protocol and one implementation over
  `cache.get`/`set`/`delete`.
- `src/.../core/collection.py` -- `headers` and `response_cache_ttl` declarations and their
  refusals, the `response_cache` seam, the conditional request, the `304` replay, and the cache
  write placed after the evidence write.
- `src/config/settings/test.py`, `scripts/gate-redis.sh`, `pixi.toml`,
  `.github/workflows/ci.yml`, `docs/development.md` -- AC 4's harness, and a `redis:7` service on
  the gate job so the proof runs on every pull request rather than only on request.

**Review findings:** 21 patched (3 high, 12 medium, 6 low), 7 deferred, 4 rejected.

**Follow-up review recommended:** true. Three high-severity patches; any one fires the rule.

**The finding that mattered most was a hole in the proof, not a bug in the code.** The single
case that drove the real cache through `collect()` asserted only that both runs succeeded and
that both evidence rows carried the served body -- all of which held identically if caching were
entirely inert, because the origin serves the same string on a `200` as the replay produces.
Caching could have shipped completely dead with a green gate. The origin now counts the bodies
it serves and the case asserts that count is one; mutation against an inert default cache fails
it with `assert 2 == 1`.

**Verification.** `pixi run ci` exits 0 -- 3046 tests, coverage 97.81% against a 90% floor, with
`collection.py`, `response_cache.py`, `transport.py`, `rate_limit.py` and
`config/settings/test.py` each at 100%. `pixi run gate-redis` exits 0 with 3048 passed and
**nothing skipped**, so AC 4 is proven against a real `redis:7` rather than asserted. The suite
also passes against a local PostgreSQL 17.8, the gate's own major version.

**Residual risks.** The seven `deferred` entries. The first is the one that qualifies what this
story may be said to have delivered: a conditional request still spends the full `1 + retries`
allowance, so the saving is bandwidth rather than rate limit -- which is not what the story's own
opening sentence promises. The Intent's `Never` clause forbids touching that arithmetic, so the
two halves of the contract disagree and the disagreement is recorded rather than resolved here.
The next three -- ignored `Cache-Control`, a key blind to the declared headers, and no bound on a
remembered body -- are each a way a cache can be right about its mechanism and wrong about what
it stores.
