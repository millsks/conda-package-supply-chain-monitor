"""The collector base's response cache, and the second module that touches the cache.

`CPM-AD-20`: "rate limiting, retry with backoff, timeouts and caching live in a
shared collector base in `core`, not per collector". `core/rate_limit.py` is the
rate-limiting half; this is the caching half, and it is a separate module for the
reason those two are separate clauses -- one owns *how many requests may be
issued*, this one owns *what a request need not ask for again*. They share a
backend and share nothing else: no key space, no expiry, no failure mode.

**What is cached is the response, not only the validator.** A validator-only
cache would make a `304` unusable: the run would have confirmed the fact still
holds and would have nothing to write, which is `CPM-NFR-3`'s "never no row"
failing quietly. Caching the body is what lets a `304` replay through the
collector's ordinary `translate` and produce the evidence a `200` would have,
stamped with *this* run's `observed_at`. Re-observation inserts (`CPM-AD-2`), so
a confirmed-unchanged fact is a new row -- which is what makes freshness advance
without the body crossing the network again.

**An entry with no validator is refused at construction.** A body cached with
neither an `ETag` nor a `Last-Modified` can never produce a conditional request,
so it can never be revalidated and would only ever be served blind -- which is a
cache of stale evidence rather than a cache of confirmed evidence, and this
product's whole subject is telling those two apart. `CachedResponse` therefore
raises rather than storing one, on the same terms every other declaration defect
in `CPM-EP-EVIDENCE` does.

**The key hashes the locator, and that is not decoration.**
`BaseCache.validate_key` *warns* on control characters, on spaces and on keys
past memcached's 250-byte limit -- it does not refuse them. A registry URL
carrying a query string reaches all three, and a warning is not a refusal, so the
entry would be written under a key some backends mangle and would simply never be
found again. A `sha256` hexdigest under a named prefix has none of those
properties, is the same length for every locator, and keys equal locators
equally. It is a cache key and not a secret: the hash is there for shape, not for
concealment.

**A cache is not an authority, so an entry it cannot understand is forgotten
rather than raised over.** A rolling deploy that changes the stored shape, or a
key collision, produces a value this module did not write. It is logged under
`RESPONSE_CACHE_UNUSABLE_EVENT`, deleted, and reported as a miss -- an
unconditional fetch follows and the run proceeds. Raising would turn a *stored
value* into a failed run. Nothing is swallowed: the entry is logged with the key
that held it.

**That covers the content of an entry and not the availability of the backend,
and the difference is worth stating rather than implying.** A Redis that is down
raises from `cache.get` itself, and this module does not catch it -- a broad
`except Exception` around a cache read is how a genuine misconfiguration becomes
a collector that silently transfers every body forever. What makes an outage
degrade instead of failing the run is `IGNORE_EXCEPTIONS` in
`config/settings/production.py`, which is `django_redis`' own switch and is set
there deliberately. So "caching never decides an outcome" is a property of the
deployed configuration, not of this module: an environment that does not set it
-- the suite under `pixi run gate-redis` is one, and deliberately, because a
gate that swallowed a Redis error would report a pass for a service that never
came up -- will see a cache failure reach `collect()` and become an `error` row
like any other failure.

**It reads `django.core.cache` through its public API and nothing below it, and
that is a rule rather than a preference.** `config/settings/local.py` argues, in
its own words, that the LocMem substitution is a *substitution* precisely because
the cache API is preserved -- "no call site may branch on which backend is
active. The moment one does, this stops being a stand-in and becomes a second
code path that local runs never exercise." So this module calls `get`, `set` and
`delete` and nothing that would tell it what is underneath: no `settings.CACHES`,
no backend class, no `isinstance`.
`tests/unit/django_apps/test_response_cache.py` asserts the call set, and
`tests/unit/django_apps/test_collector_base_audit.py` asserts that the only
modules under `src/` reaching the cache at all are this one and the limiter.

**The consequence of the LocMem substitution, stated rather than discovered.**
Under LocMem each process holds its own entries, so a local run with two workers
caches twice and shares nothing. That is a property of the substitution, not of
this module, and the correct response to noticing it is not a branch here.

**Time to live is handed to the cache and is read from nowhere else.** This
module takes no clock (`CPM-AD-26` puts the injected one in the collector base)
because it makes no time comparison: expiry is the cache's, in whole seconds, and
the only instant that matters to an observation is the `observed_at` the base
stamps rows with.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Final
from typing import Protocol
from typing import runtime_checkable

import structlog
from django.core.cache import cache

from conda_package_supply_chain_monitor.core.transport import ETAG_HEADER
from conda_package_supply_chain_monitor.core.transport import IF_MODIFIED_SINCE_HEADER
from conda_package_supply_chain_monitor.core.transport import IF_NONE_MATCH_HEADER
from conda_package_supply_chain_monitor.core.transport import LAST_MODIFIED_HEADER

__all__ = [
    "BODY_FIELD",
    "ETAG_FIELD",
    "KEY_PREFIX",
    "LAST_MODIFIED_FIELD",
    "RECORDED_FIELDS",
    "RESPONSE_CACHE_UNUSABLE_EVENT",
    "CacheResponseCache",
    "CachedResponse",
    "ResponseCache",
    "ResponseCacheError",
    "conditional_headers",
    "response_key",
]

logger = structlog.get_logger(__name__)

#: The namespace every entry this module writes lives under.
#:
#: Distinct from `core/rate_limit.py`'s `cpm:rate-limit` and distinct on purpose:
#: two kinds of value with two different expiries sharing one prefix is one
#: `clear()` or one pattern delete away from a limiter losing its counters
#: because somebody wanted to drop a stale body.
KEY_PREFIX: Final[str] = "cpm:response"

#: The event an unusable entry is logged under. Dotted, as
#: `core/rate_limit.py`'s `rate_limit.window_expired` and
#: `config/health/drain.py`'s `drain.begin` are; named so the case that asserts
#: the log and the code that emits it cannot drift.
RESPONSE_CACHE_UNUSABLE_EVENT: Final[str] = "response_cache.unusable_entry"

#: The keys one stored entry is written under, and the exact set a read requires.
#:
#: A mapping of named fields rather than a pickled instance of `CachedResponse`:
#: a rolling deploy runs two versions of this code against one cache, and a
#: pickle carries the class it was written by. Named fields are readable by
#: whichever version finds them, and a value that does not have exactly these
#: three keys is a value this module did not write -- which is precisely the
#: condition the unusable-entry path exists to answer.
BODY_FIELD: Final[str] = "body"
ETAG_FIELD: Final[str] = "etag"
LAST_MODIFIED_FIELD: Final[str] = "last_modified"
RECORDED_FIELDS: Final[frozenset[str]] = frozenset({BODY_FIELD, ETAG_FIELD, LAST_MODIFIED_FIELD})


class ResponseCacheError(ValueError):
    """A cached response could not describe a revalidatable answer.

    A `ValueError` subclass rather than a bare one, matching
    `core/rate_limit.py`'s `RateLimitError` and `core/collection.py`'s
    `CollectorConfigurationError`: every "this declaration is unusable" in this
    product is a `ValueError`, so a caller catching one catches them all.
    `core/transport.py`'s `TransportError` is deliberately not one -- a source
    being unreachable is not a declaration defect.

    It is raised at construction, which is the only moment the answer exists: an
    entry carrying no validator is unusable the instant it is built, and
    discovering that at the next conditional request would mean a body already
    written to a cache that can never revalidate it.
    """


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """One source's last answer, with what is needed to ask whether it still holds.

    Frozen and slotted, holding only data, exactly as `core/transport.py`'s
    `Payload` is: what is stored is a record, and a record that could be mutated
    after it was read would be a body that no longer matches the validator
    beside it.

    Attributes:
        body: The response body as text, decoded by the transport from the
            charset the source declared. This is what a `304` replays through
            `translate`, so it is the whole body and not a summary of it.
        etag: The `ETag` the source declared, or `None`. The stronger validator:
            an entity tag is the source's own opinion about identity, and
            `If-None-Match` is an exact comparison rather than a date one.
        last_modified: The `Last-Modified` the source declared, or `None`. Kept
            as the source's own string and sent back verbatim -- parsing and
            re-formatting an HTTP date is how a conditional request quietly
            stops matching.

    """

    body: str
    etag: str | None = None
    last_modified: str | None = None

    def __post_init__(self) -> None:
        """Refuse an entry that could never be revalidated.

        Raises:
            ResponseCacheError: When neither validator is present. Such an entry
                can produce no conditional header, so it could only ever be
                served blind -- a cache of unconfirmed evidence, in a product
                whose subject is telling confirmed evidence from stale.

        """
        if not self.etag and not self.last_modified:
            message = (
                f"a cached response needs a validator; {self!r} carries neither an {ETAG_HEADER} nor a "
                f"{LAST_MODIFIED_HEADER}. Without one no conditional request can be made, so the entry could "
                f"only ever be replayed unconfirmed, which is stale evidence wearing a cache's name."
            )
            raise ResponseCacheError(message)


def response_key(*, collector: str, source: str) -> str:
    """Return the cache key holding one collector's last answer for one locator.

    Keyed on the collector name and the locator it read, and on nothing else --
    which is the identity the architecture actually decides. A key carrying a
    package would be a per-package cache identity nothing in the spine chooses,
    and two collectors reading one shared locator must not read each other's
    bodies, because what a body *means* is the collector's decision
    (`CPM-AD-27`).

    Args:
        collector: The collector's declared name, which is also what its ledger
            rows carry (`CPM-FR-39`).
        source: The locator that was read, verbatim.

    Returns:
        A key under `KEY_PREFIX`, naming the collector and a `sha256` hexdigest
        of the locator. Hashed rather than spelled: see the module docstring for
        what `BaseCache.validate_key` does and does not refuse.

    """
    digest = sha256(source.encode("utf-8")).hexdigest()
    return f"{KEY_PREFIX}:{collector}:{digest}"


def conditional_headers(entry: CachedResponse) -> dict[str, str]:
    """Return the headers that ask a source whether this entry still holds.

    Both are sent when both validators are known, which is what HTTP asks for: a
    source that honours only one of them still answers, and one that honours
    both compares the entity tag first. Sending only the date when an `ETag`
    exists would throw away the stronger comparison for no saving.

    Args:
        entry: The remembered response, which carries at least one validator by
            construction.

    Returns:
        The conditional request headers, keyed by the names
        `core/transport.py` declares.

    """
    headers: dict[str, str] = {}
    if entry.etag:
        headers[IF_NONE_MATCH_HEADER] = entry.etag
    if entry.last_modified:
        headers[IF_MODIFIED_SINCE_HEADER] = entry.last_modified
    return headers


@runtime_checkable
class ResponseCache(Protocol):
    """Something that can remember one source's answer and hand it back.

    Three methods, because three is what the collector base does with it: read
    what it has, write what it just learned, and forget what the source says is
    gone. A base that takes a `ResponseCache` declares that it caches responses
    and declares nothing else, and a test supplies one that answers from a
    dictionary without standing up a backend.

    `runtime_checkable` so a test can assert an implementation satisfies it.
    That check sees method *names* only, which is why
    `tests/unit/django_apps/test_response_cache.py` also pins what `read`
    returns.
    """

    def read(self, *, collector: str, source: str) -> CachedResponse | None:
        """Return what this collector last recorded for this locator.

        The docstring is the whole body, for the reason `core/clock.py`'s
        `Clock.now` gives: a protocol method is never executed, and an `...`
        would be a permanently uncovered line that only a banned `pragma` could
        excuse.

        Args:
            collector: The collector's declared name.
            source: The locator it is about to read.

        Returns:
            The remembered response, or `None` when there is none and when what
            was stored cannot be used. A cache is not an authority, so this
            never raises for a value it does not understand.

        """

    def write(self, *, collector: str, source: str, response: CachedResponse, ttl_seconds: int) -> None:
        """Remember one answer for a stated number of seconds.

        Args:
            collector: The collector's declared name.
            source: The locator that was read.
            response: The body and its validators.
            ttl_seconds: How long the entry may live.

        """

    def forget(self, *, collector: str, source: str) -> None:
        """Drop whatever is remembered for this locator.

        Args:
            collector: The collector's declared name.
            source: The locator to forget.

        """


class CacheResponseCache:
    """The shared response cache, over `django.core.cache`'s public API.

    Stateless: every instance reads the same cache, so a worker holding one per
    collector and a worker holding one for everything behave identically. What
    holds the state is the cache, which is what makes an entry written by one
    process readable by another wherever the backend is (Redis in a deployment;
    see the module docstring for what LocMem changes and why nothing here
    branches on it).
    """

    def read(self, *, collector: str, source: str) -> CachedResponse | None:
        """Return the remembered answer, or nothing at all.

        Args:
            collector: The collector's declared name.
            source: The locator it is about to read.

        Returns:
            The remembered response, or `None` for a miss *and* for a stored
            value this module did not write -- which is logged and deleted
            rather than raised over, because a cache that could fail a run would
            be a dependency rather than an optimization.

        """
        key = response_key(collector=collector, source=source)
        stored = cache.get(key)
        if stored is None:
            return None
        try:
            return _recovered(stored)
        except (TypeError, ValueError) as unusable:
            # Never swallowed and never raised: the entry is reported with the
            # key that held it, dropped so the next run does not meet it again,
            # and treated as a miss -- an unconditional fetch follows, which is
            # exactly what would have happened had the entry never existed.
            logger.info(
                RESPONSE_CACHE_UNUSABLE_EVENT,
                collector=collector,
                source=source,
                cache_key=key,
                detail=f"{type(unusable).__name__}: {unusable}",
            )
            cache.delete(key)
            return None

    def write(self, *, collector: str, source: str, response: CachedResponse, ttl_seconds: int) -> None:
        """Remember one answer under this collector's key for this locator.

        Written as named fields rather than as a pickled instance, so a rolling
        deploy running two versions of this code against one cache reads
        entries the other version wrote instead of failing to unpickle them.

        Args:
            collector: The collector's declared name.
            source: The locator that was read.
            response: The body and its validators.
            ttl_seconds: How long the entry may live, in whole seconds as the
                cache counts them.

        """
        cache.set(
            response_key(collector=collector, source=source),
            {
                BODY_FIELD: response.body,
                ETAG_FIELD: response.etag,
                LAST_MODIFIED_FIELD: response.last_modified,
            },
            ttl_seconds,
        )

    def forget(self, *, collector: str, source: str) -> None:
        """Drop this collector's entry for this locator.

        Called when the source says the resource is gone: a body kept past that
        answer would be replayed the day the locator came back, and what came
        back need not be what left.

        Args:
            collector: The collector's declared name.
            source: The locator to forget.

        """
        cache.delete(response_key(collector=collector, source=source))


def _recovered(stored: object) -> CachedResponse:
    """Rebuild a cached response from what the cache handed back.

    Args:
        stored: Whatever was under the key.

    Returns:
        The recovered entry.

    Raises:
        TypeError: When the stored value is not a mapping of exactly the
            recorded fields, or when a field is not the type it was written as.
            Caught by the caller and reported as a miss.
        ResponseCacheError: When the recovered entry carries no validator, which
            `CachedResponse` refuses for everybody.

    """
    if not isinstance(stored, dict) or set(stored) != RECORDED_FIELDS:
        message = f"a response-cache entry is a mapping of {sorted(RECORDED_FIELDS)}; found {stored!r}"
        raise TypeError(message)
    body = stored[BODY_FIELD]
    etag = stored[ETAG_FIELD]
    last_modified = stored[LAST_MODIFIED_FIELD]
    if not isinstance(body, str) or not _is_optional_text(etag) or not _is_optional_text(last_modified):
        message = f"a response-cache entry holds text and optional validators; found {stored!r}"
        raise TypeError(message)
    return CachedResponse(body=body, etag=etag, last_modified=last_modified)


def _is_optional_text(value: object) -> bool:
    """Report whether a recovered validator is a string or absent.

    Args:
        value: The recovered field.

    Returns:
        True when it is `None` or a string, which are the two shapes `write`
        can produce.

    """
    return value is None or isinstance(value, str)
