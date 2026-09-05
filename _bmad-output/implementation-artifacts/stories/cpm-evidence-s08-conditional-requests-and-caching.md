# CPM-EVIDENCE-S08: Conditional requests, cached responses, and one shared allowance

Status: ready-for-dev

Epic: `CPM-EP-EVIDENCE` — An evidence log that cannot lie

## Story

As a platform lead,
I want the collector base to ask sources what changed rather than re-fetching what did not, and one allowance shared across workers,
so that a daily sweep over ten thousand packages does not spend its rate limit re-reading bodies it already has.

## Acceptance Criteria

1. **Given** a source that answered before with a validator
   **When** the collector runs again and the source still holds that validator
   **Then** the request is conditional, the source answers "not modified", and no body is transferred
   **And** the run still records evidence and a ledger row, because a confirmed-unchanged fact is an observation

2. **Given** a transport that must send a `User-Agent`, an `Authorization` header or a conditional-request header
   **When** a collector declares what it needs
   **Then** the header travels with the request through the base, and no collector opens a connection to send it

3. **Given** the response cache
   **When** it is read or written
   **Then** it goes through `django.core.cache`'s public API and no call site branches on the backend,
   exactly as `core/rate_limit.py` does

4. **Given** two worker processes sharing one allowance
   **When** both collect for the same collector inside one window
   **Then** the counter is shared and the allowance is spent once, proven against a real Redis
   rather than the in-process substitution

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.

## Dev Notes

**Satisfies:** the caching half of `CPM-NFR-3`, and completes it.

**Governed by:**

- `CPM-AD-20` — rate limiting, retry with backoff, timeouts **and caching** live in the shared collector base
- `CPM-AD-27` — the collector base owns the transport seam
- `CPM-AD-7` — collectors share nothing but the log; evidence always inserts

**Why this story exists at all.** `CPM-EVIDENCE-S05` built the collector base and delivered
three of `CPM-NFR-3`'s four clauses — rate limiting, retry with backoff, request timeouts —
and recorded the fourth as unmet in its `deferred` list rather than leaving the omission
inside a satisfied-requirement claim. The omission originated in S05's own spec, which never
asked for caching. This story is that debt, paid before the collectors arrive.

**Why the header affordance is in the same story.** A conditional request *is* a header
(`If-None-Match`, `If-Modified-Since`), so caching cannot be delivered without widening
`Transport.fetch`, which today takes a bare `source: str`. The same widening is what lets a
collector send the `User-Agent` conda-forge, PyPI and GitHub all expect, and the
`Authorization` GitHub requires at sweep volume — GitHub's rate limits being part of why
`CPM-AD-20` exists. Widening a protocol after eight collectors depend on it is the expensive
version of this change.

**Why the observation window is not a substitute.** It suppresses *runs*, not responses. When
a run is genuinely due — the window has passed — the window saves nothing, and the body is
fetched again whether or not it changed. Caching is what makes a due run cheap when the
upstream is unchanged. The two mechanisms compose; neither replaces the other.

**"Not modified" is an observation, not an absence.** A `304` means the source confirmed the
fact still holds, which is a determinate answer and must be recorded as one. It is never
`unknown` (we never looked) and never `not_found` (we looked and it is gone) — the
distinction `CPM-AD-5` and `R-01` exist to preserve. What the evidence row carries is the
collector's to shape through `sentinel_evidence`'s sibling path; what it must not be is
absent.

**Why AC 4 is here rather than left alone.** `core/rate_limit.py` uses `cache.add` then
`cache.incr` — never `set` — specifically so that two processes racing a new window both
increment one counter instead of one resetting the other. `config/settings/test.py` pins
`LocMemCache`, so that reasoning is unproven by the suite: under LocMem each process has its
own counter and the shared-counter property cannot fail. `pixi run gate-postgres` already
establishes the pattern for proving a backend-dependent property against a real service, and
a `redis:7` container is the same move.

**Not in scope.** No concrete collector and no concrete evidence model — `CPM-AD-7` still puts
the first in `CPM-EP-CURRENCY`. No change to the observation window, the retry policy or the
allowance arithmetic S05 settled (a run charges `1 + retries` up front). No freshness-target
or window *values*; those remain PRD Open Question 7.

### Project Structure Notes

- The transport seam is `core/transport.py`; the limiter is `core/rate_limit.py`; the
  orchestration is `core/collection.py`. All three are `CPM-EVIDENCE-S05`'s and all three are
  at 100% line coverage, so a regression is visible.
- Every refusal raises rather than warning (inherited `CG-3`).

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- `pixi run gate-postgres` must exit 0; AC 4 adds a Redis-backed counterpart in the same shape.
- Time comes from the injected clock in `core` (`CPM-AD-26`); no module calls `timezone.now()`.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-EVIDENCE-S08]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-20]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-27]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-3]
- [Source: _bmad-output/implementation-artifacts/stories/cpm-evidence-s05-collector-base-carrying-external-call.md] — the `deferred` entries this story pays down

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
