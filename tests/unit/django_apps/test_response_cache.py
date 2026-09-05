"""The response cache over a real cache, and the rule that it must not know which one.

`CPM-AD-20` puts caching in the shared collector base beside rate limiting, and
`CPM-EVIDENCE-S08` is where the fourth of `CPM-NFR-3`'s clauses arrives. What
makes it a single implementation rather than a shared *name* is the second half
of the rule, which `config/settings/local.py` states in its own words: the LocMem
substitution preserves the cache API precisely so that no call site branches on
the backend, and "the moment one does, this stops being a stand-in and becomes a
second code path that local runs never exercise."

So there are two kinds of case here, and both are necessary -- the same division
`tests/unit/django_apps/test_rate_limit.py` makes, for the same reason.

**The behaviour, against a real cache.** Not a mock: an entry is written to
`django.core.cache` and read back, so the round trip, the per-collector and
per-locator separation, the forgetting and the unusable-entry path are proved
through the same API a deployment uses. The backend under the suite is LocMem
(`config/settings/test.py` declares it deliberately rather than inheriting
Django's default), which is in-process memory -- no database, no network, so this
belongs in the unit tier.

**The rule, against the source.** A behavioural case cannot show that the module
does not branch: a branch on the backend would pass every assertion below,
because the suite only ever runs one backend. So the module is parsed, what it
calls on the cache is compared against the public API, and it is checked to
mention no backend at all.

`tests/unit/django_apps/test_collector_base_audit.py` holds the other direction:
that the only two modules under `src/` reaching the cache are this one's subject
and the limiter.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import ast
import warnings
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from typing import get_type_hints

import pytest
import structlog
from django.core.cache import DEFAULT_CACHE_ALIAS
from django.core.cache import cache
from django.core.cache import caches
from django.core.cache.backends.base import CacheKeyWarning

from conda_package_supply_chain_monitor.core import response_cache
from conda_package_supply_chain_monitor.core.rate_limit import KEY_PREFIX as LIMITER_KEY_PREFIX
from conda_package_supply_chain_monitor.core.response_cache import BODY_FIELD
from conda_package_supply_chain_monitor.core.response_cache import ETAG_FIELD
from conda_package_supply_chain_monitor.core.response_cache import KEY_PREFIX
from conda_package_supply_chain_monitor.core.response_cache import LAST_MODIFIED_FIELD
from conda_package_supply_chain_monitor.core.response_cache import RESPONSE_CACHE_UNUSABLE_EVENT
from conda_package_supply_chain_monitor.core.response_cache import CachedResponse
from conda_package_supply_chain_monitor.core.response_cache import CacheResponseCache
from conda_package_supply_chain_monitor.core.response_cache import ResponseCache
from conda_package_supply_chain_monitor.core.response_cache import ResponseCacheError
from conda_package_supply_chain_monitor.core.response_cache import conditional_headers
from conda_package_supply_chain_monitor.core.response_cache import response_key
from conda_package_supply_chain_monitor.core.transport import IF_MODIFIED_SINCE_HEADER
from conda_package_supply_chain_monitor.core.transport import IF_NONE_MATCH_HEADER
from tests.collectors import A_CACHED_BODY
from tests.collectors import A_LAST_MODIFIED
from tests.collectors import AN_ETAG
from tests.collectors import cleared_cache
from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from structlog.typing import EventDict

#: The module this file is about, relative to `src/`.
RESPONSE_CACHE_MODULE: Final[str] = "django_apps/conda_package_supply_chain_monitor/core/response_cache.py"

#: The cache methods the response cache is permitted to call.
#:
#: `get` reads an entry, `set` writes one with a time to live, and `delete`
#: drops one. All three are `BaseCache`'s own public API, offered identically by
#: every backend -- which is the property that makes LocMem a substitution rather
#: than a second code path.
PERMITTED_CACHE_CALLS: Final[frozenset[str]] = frozenset({"delete", "get", "set"})

#: Names that would mean the module knows what is underneath it. `CACHES` is the
#: settings table; the three class names are the backends `config/settings/*.py`
#: configure. Any of them appearing here would be the branch the rule forbids,
#: and a case that only ran one backend could never notice.
BACKEND_TELLS: Final[frozenset[str]] = frozenset({"CACHES", "LocMemCache", "RedisCache", "DummyCache"})

#: The collector names the cases key against. Two, because "one collector's
#: entry is not another's" is a claim about the key rather than about the value.
A_COLLECTOR: Final[str] = "cpm-fixture-cached"
ANOTHER_COLLECTOR: Final[str] = "cpm-fixture-other-cached"

#: The locators the cases read. The second is what a real registry URL looks
#: like -- a query string, a space, and enough length to matter -- and it is here
#: because `BaseCache.validate_key` *warns* about exactly those and does not
#: refuse them.
A_SOURCE: Final[str] = "https://fixture.invalid/packages/1"
ANOTHER_SOURCE: Final[str] = "https://fixture.invalid/packages/2"
AN_AWKWARD_SOURCE: Final[str] = f"https://fixture.invalid/search?q=a name with spaces&fields={'x' * 300}"

#: How long a written entry lives, in seconds. Any positive number would do;
#: naming it keeps the assertion about *the value reaching the cache* rather
#: than about the number.
A_TTL: Final[int] = 3600

#: The shape of the `set` call this module makes: key, value, time to live, in
#: that order and positionally. Named rather than reached for with `[-1]`,
#: because the index is the assertion -- a lifetime that moved to a keyword
#: would still be the last thing passed and would still satisfy a negative
#: index, while being a different call to a backend whose third positional is
#: what Django documents.
SET_ARGUMENTS: Final[int] = 3
TTL_ARGUMENT: Final[int] = 2

#: The event the capture fixture emits to prove it can see this module's logger.
_CAPTURE_CONTROL: Final[str] = "response_cache.capture_control"


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    """Start and end every case with nothing remembered.

    Autouse, and the body lives in `tests/collectors.py` because every module
    that touches the cache needs the identical guard: `autouse` fixtures that
    can drift apart are exactly the duplication that module's own docstring
    argues against. How many there are is deliberately not stated -- it has
    grown twice already.

    Yields:
        Nothing; the fixture is entirely its two side effects.

    """
    with cleared_cache():
        yield


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EventDict]]:
    """Capture what the response cache logs, with the two guards the plain helper lacks.

    The reasoning is `tests/unit/test_health_views.py`'s and
    `tests/unit/django_apps/test_rate_limit.py`'s and is not restated: the
    module-scope logger is rebound so `capture_logs` binds a fresh proxy inside
    its own processor chain, and a control event proves the capture is live
    before the case runs, so an assertion over an empty list fails here and says
    why rather than reporting that the module logged nothing.

    Args:
        monkeypatch: pytest's patcher, which restores the module's own logger.

    Yields:
        The captured events, in order.

    """
    monkeypatch.setattr(response_cache, "logger", structlog.get_logger(response_cache.__name__))
    with structlog.testing.capture_logs() as captured:
        response_cache.logger.info(_CAPTURE_CONTROL)
        assert [event["event"] for event in captured] == [_CAPTURE_CONTROL], (
            "structlog.testing.capture_logs() cannot see core/response_cache.py's logger, so every "
            "assertion over what it logged would be vacuous"
        )
        captured.clear()
        yield captured


def test_an_entry_with_no_validator_is_refused() -> None:
    """A body that can never be revalidated is stale evidence wearing a cache's name.

    Without an `ETag` or a `Last-Modified` there is no conditional request to
    make, so the entry could only ever be replayed unconfirmed -- which is
    precisely the thing this product exists to tell apart from a confirmed
    observation. Refused at construction, before anything writes it.
    """
    with pytest.raises(ResponseCacheError, match="needs a validator"):
        CachedResponse(body=A_CACHED_BODY)


def test_a_date_alone_is_a_validator() -> None:
    """The weaker validator is still one, and a great many sources offer only it.

    A static file server sends `Last-Modified` and no `ETag`. Refusing that
    entry would mean caching nothing for those sources at all, so the refusal
    above has to be about *neither*, not about the absence of the stronger one.
    """
    entry = CachedResponse(body=A_CACHED_BODY, last_modified=A_LAST_MODIFIED)

    assert entry.etag is None
    assert entry.last_modified == A_LAST_MODIFIED


def test_an_empty_validator_is_not_a_validator() -> None:
    """Empty strings are the shape a header that was never sent could arrive as.

    `core/transport.py` records an absent header as `None`, and this is the
    other end of that agreement: a conditional request carrying `If-None-Match:`
    with nothing after it asks a question no source can answer, so an entry that
    could only produce one is refused like an entry with no validator at all.
    """
    with pytest.raises(ResponseCacheError, match="needs a validator"):
        CachedResponse(body=A_CACHED_BODY, etag="", last_modified="")


def test_nothing_remembered_reads_as_nothing() -> None:
    """The first observation: a miss is `None`, which is what makes the fetch unconditional."""
    assert CacheResponseCache().read(collector=A_COLLECTOR, source=A_SOURCE) is None


def test_a_written_entry_is_read_back_whole() -> None:
    """The round trip, against a real cache rather than through a mock.

    The body is what a `304` replays and the validators are what earn the `304`,
    so all three have to survive: an implementation that stored the validators
    and dropped the body would revalidate perfectly and have nothing to write.
    """
    store = CacheResponseCache()
    written = CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG, last_modified=A_LAST_MODIFIED)

    store.write(collector=A_COLLECTOR, source=A_SOURCE, response=written, ttl_seconds=A_TTL)

    assert store.read(collector=A_COLLECTOR, source=A_SOURCE) == written


def test_one_collectors_entry_is_not_anothers() -> None:
    """Two collectors may read one locator and mean different things by it.

    What a body *means* is the collector's decision (`CPM-AD-27`), so a shared
    entry would let one collector's translation be driven by a body another
    collector's validator confirmed.
    """
    store = CacheResponseCache()
    store.write(
        collector=A_COLLECTOR,
        source=A_SOURCE,
        response=CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG),
        ttl_seconds=A_TTL,
    )

    assert store.read(collector=ANOTHER_COLLECTOR, source=A_SOURCE) is None


def test_one_locators_entry_is_not_anothers() -> None:
    """The other half of the key, and the one a bug would be catastrophic in.

    A cache keyed on the collector alone would answer every package with the
    body of whichever package was collected last -- and every one of those
    observations would be written, in an append-only table, as fact.
    """
    store = CacheResponseCache()
    store.write(
        collector=A_COLLECTOR,
        source=A_SOURCE,
        response=CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG),
        ttl_seconds=A_TTL,
    )

    assert store.read(collector=A_COLLECTOR, source=ANOTHER_SOURCE) is None


def test_forgetting_an_entry_leaves_nothing_behind() -> None:
    """What the base does when a source says the resource is gone.

    A body kept past that answer would be replayed the day the locator came
    back, and what comes back need not be what left.
    """
    store = CacheResponseCache()
    store.write(
        collector=A_COLLECTOR,
        source=A_SOURCE,
        response=CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG),
        ttl_seconds=A_TTL,
    )

    store.forget(collector=A_COLLECTOR, source=A_SOURCE)

    assert store.read(collector=A_COLLECTOR, source=A_SOURCE) is None


def test_forgetting_what_was_never_remembered_is_not_an_error() -> None:
    """The base forgets on every `not_found`, whether or not it had anything.

    A `delete` that raised on a miss would turn the ordinary case -- a package
    that has never been collected and does not exist -- into a failed run.
    """
    CacheResponseCache().forget(collector=A_COLLECTOR, source=A_SOURCE)

    assert CacheResponseCache().read(collector=A_COLLECTOR, source=A_SOURCE) is None


def test_the_time_to_live_reaches_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """The value the collector declared is the value the entry is written with.

    Expiry cannot be observed without waiting for it, and a case that slept
    would be a statement about how long the test took rather than about the
    rule. What is observable is the argument, and losing it is the plausible
    mistake: `set` with no timeout means the backend's default, which is five
    minutes on LocMem and forever on some others.

    Patched on the configured cache *instance* rather than on the `cache` proxy
    and rather than on a backend class. The proxy resolves an attribute set on
    it onto the underlying instance, so `monkeypatch.setattr(cache, "set", ...)`
    leaves a bound attribute on that instance which `monkeypatch.undo()` cannot
    see and does not remove -- a substituted `set` surviving into every case
    that runs afterwards, in whatever order the suite chose. Reaching the
    instance through `caches[DEFAULT_CACHE_ALIAS]` is still no statement about
    *which* backend is underneath, which is the rule this module also defends;
    it is a statement about which object is being restored.

    The time to live is asserted at its positional index rather than at `[-1]`.
    Both pass today; only one still fails if the argument moves to a keyword,
    and passing `timeout=` where Django expects the third positional is a change
    worth noticing rather than one to be agnostic about.
    """
    written: list[tuple[Any, ...]] = []
    monkeypatch.setattr(caches[DEFAULT_CACHE_ALIAS], "set", lambda *args: written.append(args))

    CacheResponseCache().write(
        collector=A_COLLECTOR,
        source=A_SOURCE,
        response=CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG),
        ttl_seconds=A_TTL,
    )

    assert len(written[0]) == SET_ARGUMENTS
    assert written[0][TTL_ARGUMENT] == A_TTL


def test_the_key_is_namespaced_and_hashes_the_locator() -> None:
    """Namespaced so it cannot collide, hashed so no backend can mangle it.

    The prefix is what keeps a response entry out of the limiter's key space --
    the two have different lifetimes and one `delete` between them would be a
    collector throttled for a body somebody wanted refreshed. The hash is what
    keeps the locator itself out of the key: see the case below for what that
    prevents.
    """
    key = response_key(collector=A_COLLECTOR, source=A_SOURCE)

    assert key.startswith(f"{KEY_PREFIX}:{A_COLLECTOR}:")
    assert A_SOURCE not in key
    assert key == response_key(collector=A_COLLECTOR, source=A_SOURCE)


def test_an_awkward_locator_produces_a_key_the_cache_does_not_complain_about() -> None:
    """`BaseCache.validate_key` warns rather than refuses, which is the whole hazard.

    A registry URL with a query string reaches all three of the conditions it
    warns about -- a space, control characters, and memcached's 250-byte limit --
    and a warning is not a refusal: the entry would be written under a key some
    backends mangle and would simply never be found again, so the cache would
    silently save nothing while looking like it worked. The hash makes every key
    the same shape and the same length.

    Asserted as "the cache raises no *key* warning", which is the property,
    rather than by measuring the digest -- a length assertion would pass for a
    key that was short and still had a space in it. Filtered to
    `CacheKeyWarning` specifically: a bare "nothing was warned about" makes this
    case fail on any unrelated `DeprecationWarning` a dependency starts emitting,
    which is a failure pointing at the wrong file entirely.
    """
    store = CacheResponseCache()

    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always")
        store.write(
            collector=A_COLLECTOR,
            source=AN_AWKWARD_SOURCE,
            response=CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG),
            ttl_seconds=A_TTL,
        )
        recovered = store.read(collector=A_COLLECTOR, source=AN_AWKWARD_SOURCE)

    complained = [str(warning.message) for warning in raised if issubclass(warning.category, CacheKeyWarning)]
    assert complained == []
    assert recovered is not None
    assert recovered.body == A_CACHED_BODY


@pytest.mark.parametrize(
    "stored",
    [
        "a body somebody stored as a bare string",
        {BODY_FIELD: A_CACHED_BODY},
        {BODY_FIELD: A_CACHED_BODY, ETAG_FIELD: AN_ETAG, LAST_MODIFIED_FIELD: None, "extra": 1},
        {BODY_FIELD: 7, ETAG_FIELD: AN_ETAG, LAST_MODIFIED_FIELD: None},
        {BODY_FIELD: A_CACHED_BODY, ETAG_FIELD: 7, LAST_MODIFIED_FIELD: None},
        {BODY_FIELD: A_CACHED_BODY, ETAG_FIELD: None, LAST_MODIFIED_FIELD: None},
    ],
    ids=["not-a-mapping", "missing-field", "extra-field", "body-not-text", "validator-not-text", "no-validator"],
)
def test_an_entry_this_module_did_not_write_is_forgotten_rather_than_raised_over(stored: object) -> None:
    """A cache is not an authority, so a value it cannot understand costs a fetch and nothing more.

    Every shape here is reachable: a rolling deploy runs two versions of this
    code against one cache, and a key collision puts somebody else's value under
    this key. Raising would turn a cache detail into a failed run and an `error`
    row in an append-only table -- a source reported as broken because of
    something on this side of the wire. Instead the entry is dropped and the run
    fetches unconditionally, which is exactly what would have happened had the
    entry never existed.

    The last shape is the one an older version of this module could genuinely
    have written: an entry with no validator, which is now refused at
    construction and must therefore be unreadable rather than crash the read.
    """
    store = CacheResponseCache()
    cache.set(response_key(collector=A_COLLECTOR, source=A_SOURCE), stored, A_TTL)

    assert store.read(collector=A_COLLECTOR, source=A_SOURCE) is None
    assert cache.get(response_key(collector=A_COLLECTOR, source=A_SOURCE)) is None


def test_an_unusable_entry_is_logged_under_the_name_the_module_declares(
    captured_events: list[EventDict],
) -> None:
    """The event constant says it exists so a case and the code cannot drift; this is the case.

    It is also the only record that a cache entry was silently discarded. A read
    that dropped an entry and said nothing would look, from every read surface,
    identical to a cache that was simply cold -- and the difference between
    those two is whether something is wrong.
    """
    cache.set(response_key(collector=A_COLLECTOR, source=A_SOURCE), "not an entry", A_TTL)

    CacheResponseCache().read(collector=A_COLLECTOR, source=A_SOURCE)

    assert [event["event"] for event in captured_events] == [RESPONSE_CACHE_UNUSABLE_EVENT]
    assert captured_events[0]["collector"] == A_COLLECTOR
    assert captured_events[0]["source"] == A_SOURCE
    assert captured_events[0]["detail"] != ""


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG), {IF_NONE_MATCH_HEADER: AN_ETAG}),
        (
            CachedResponse(body=A_CACHED_BODY, last_modified=A_LAST_MODIFIED),
            {IF_MODIFIED_SINCE_HEADER: A_LAST_MODIFIED},
        ),
        (
            CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG, last_modified=A_LAST_MODIFIED),
            {IF_NONE_MATCH_HEADER: AN_ETAG, IF_MODIFIED_SINCE_HEADER: A_LAST_MODIFIED},
        ),
    ],
    ids=["entity-tag", "date", "both"],
)
def test_a_conditional_request_asks_with_the_validators_it_has(
    entry: CachedResponse,
    expected: dict[str, str],
) -> None:
    """Each validator goes in its own header, and both go when both are known.

    A source that honours only one still answers, and one that honours both
    compares the entity tag first -- so sending only the date when an `ETag`
    exists throws away the stronger comparison for no saving at all.
    """
    assert conditional_headers(entry) == expected


def test_a_validator_travels_verbatim() -> None:
    """An entity tag is quoted and a date is formatted; neither may be tidied.

    A validator is compared byte for byte by the source. Stripping the quotes
    from an `ETag`, or re-formatting an HTTP date into ISO 8601, produces a
    conditional request that never matches -- so every response is a `200`, every
    body is transferred, and the cache reports a hit rate of zero with nothing
    failing.
    """
    entry = CachedResponse(body=A_CACHED_BODY, etag=AN_ETAG, last_modified=A_LAST_MODIFIED)

    assert conditional_headers(entry)[IF_NONE_MATCH_HEADER] == AN_ETAG
    assert conditional_headers(entry)[IF_MODIFIED_SINCE_HEADER] == A_LAST_MODIFIED


def test_the_cache_backed_store_satisfies_the_protocol() -> None:
    """The base takes a `ResponseCache`, so a test double needs no inheritance."""
    assert isinstance(CacheResponseCache(), ResponseCache)


def test_something_without_the_three_methods_is_not_a_response_cache() -> None:
    """The negative control for the protocol check above."""

    class NotAResponseCache:
        """Something with no way to remember an answer."""

    assert not isinstance(NotAResponseCache(), ResponseCache)


def test_read_is_declared_to_return_a_recorded_entry() -> None:
    """`runtime_checkable` sees method names only, so the contract is pinned separately.

    A `read` that answered a live cache handle would pass the `isinstance` check
    above and would hand the collector base something it must not have -- the
    same hazard `tests/unit/django_apps/test_transport.py` pins for `fetch`.
    """
    assert get_type_hints(CacheResponseCache.read)["return"] == CachedResponse | None
    assert get_type_hints(ResponseCache.read)["return"] == CachedResponse | None


def test_the_response_cache_calls_only_the_public_cache_api() -> None:
    """The rule a behavioural case cannot reach: no call site knows the backend.

    Read off the parsed module rather than by running it, because the suite runs
    exactly one backend: a branch on which one would pass every case above and
    would only be discovered in production, where the *other* branch is the live
    one.
    """
    called = _cache_calls(SRC_ROOT / RESPONSE_CACHE_MODULE)

    assert called != set(), "the response cache should reach the cache; a scan finding nothing proves nothing"
    assert called <= PERMITTED_CACHE_CALLS, f"it calls something outside the cache's public API: {called}"


def test_the_response_cache_names_no_cache_backend() -> None:
    """A backend named in code is the branch, whatever shape the branch takes.

    Names and attributes, never string literals: this module's own docstring
    explains at length what LocMem changes and why nothing here branches on it,
    and a detector that read prose would make the explanation an offence. What it
    reads instead is the two spellings a branch actually needs -- a bare name and
    an attribute access, which is what `settings.CACHES[...]` and an imported
    backend class each produce.
    """
    tree = parse(SRC_ROOT / RESPONSE_CACHE_MODULE)

    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in BACKEND_TELLS} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in BACKEND_TELLS
    }

    assert named == set(), f"the response cache names a cache backend: {sorted(named)}"


def test_the_backend_detector_would_notice_one() -> None:
    """The anti-vacuity guard for the case above.

    A detector that had stopped recognising a backend reference would report a
    clean module forever. Measured against source text parsed here rather than a
    file on disk: a fixture module under `src/` would be found by every other
    sweep in this repository and would need an exemption of its own.
    """
    branching = ast.parse(
        "from django.conf import settings\n"
        "if settings.CACHES['default']['BACKEND'].endswith('LocMemCache'):\n"
        "    pass\n",
    )

    named = {
        node.attr for node in ast.walk(branching) if isinstance(node, ast.Attribute) and node.attr in BACKEND_TELLS
    }

    assert named == {"CACHES"}


def test_every_event_name_this_module_declares_is_dotted() -> None:
    """The repository's own shape, applied to a name added by this story.

    `drain.begin`, `rate_limit.window_expired`, `collection.skipped_inside_window`:
    a dotted prefix is what lets an operator select a subsystem's lines without
    matching prose. A flat sentence reads fine in isolation and is invisible to
    that query.
    """
    assert "." in RESPONSE_CACHE_UNUSABLE_EVENT
    assert RESPONSE_CACHE_UNUSABLE_EVENT.split(".")[0] == "response_cache"


def test_the_two_key_prefixes_do_not_overlap() -> None:
    """One backend, two kinds of value, and neither may be inside the other's namespace.

    A counter and a body have different lifetimes and different consequences: a
    pattern delete aimed at stale bodies must not be able to reach a limiter's
    window, or clearing the cache of one becomes an allowance reset for the
    other.
    """
    assert not KEY_PREFIX.startswith(f"{LIMITER_KEY_PREFIX}:")
    assert not LIMITER_KEY_PREFIX.startswith(f"{KEY_PREFIX}:")
    assert KEY_PREFIX != LIMITER_KEY_PREFIX


def _cache_calls(path: Path) -> set[str]:
    """Return every method name called on the `cache` object in one module.

    Args:
        path: The module to read.

    Returns:
        The attribute names, so the caller can compare them against the public
        API. Matched on the receiver being spelled `cache`, which is what
        `from django.core.cache import cache` binds and what the audit in
        `test_collector_base_audit.py` resolves properly; here the module is
        known and the simpler match is enough.

    """
    tree = parse(path)
    return {
        dotted_name(node.func).rpartition(".")[2]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted_name(node.func).startswith("cache.")
    }
