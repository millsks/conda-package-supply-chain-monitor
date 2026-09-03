"""The JWKS key store: lazy, `kid`-keyed, rate-limited, and this component's own.

AD-23 is the whole of this module. JWKS material is fetched **lazily on the first
Bearer request that needs it, never at import and never at boot** -- FR-23 makes a
boot-time network call a defect, because Epic 3's clone-and-run contract and
NFR-1's "startup makes no network call" both rest on it. So `KEY_STORE` below is
constructed at import and fetches nothing; the first `get_signing_key` is the
first request out.

**Two forms of the location rule, and why.** `configured_jwks_url` reads
`django.conf.settings`, so it is unusable at settings-import time -- and that is
exactly when Epic 4's stage-1 trust-anchor refusal has to answer, because
`django.conf.settings` is not populated while a settings module is still
executing. `resolve_jwks_url` is the pure half: the same explicit-or-conventional
fallback over two values the caller has already read. The refusal calls it with
the names taken off the settings module being composed, so the check and the
fetch cannot disagree about which location is in force. Do not re-derive the
fallback in `config/startup/`; AD-1 gives it one declaration site and this is it.

**Why `PyJWKClient` is not used.** Verified against PyJWT's own source rather than
re-derived, because "the library already does this" is precisely the assumption
AD-23 exists to prevent:

1. `PyJWKClient.__init__` defaults `cache_keys=False`. The per-`kid` LRU is
   opt-in; what is cached by default is the whole JWK Set response, at
   `lifespan=300`.
2. `get_signing_key` refetches **unconditionally** on an unmatched `kid` -- no
   rate limiting, no backoff, no circuit breaker. The Bearer path is
   unauthenticated at the moment the key is needed, so a caller sending tokens
   bearing random `kid` values produces one outbound JWKS fetch per request. That
   is an amplification vector pointed at the IdP's JWKS endpoint.
3. The Tier-2 LRU has **no time-based expiration**. Entries evict only when the
   cache exceeds `max_cached_keys` (default 16); `lifespan` does not apply to it.
   A key rotated *in place* -- same `kid`, new material -- is served stale
   indefinitely, which is exactly what a TTL is supposed to backstop. This is why
   the TTL here is real and PyJWT's is not.

Two PyJWT behaviours this deliberately matches: the constructor rejects
non-`http(s)` URIs, which is what blocks a `jku`-header-driven local file read,
and a fetch writes the cache **only on success**, so a transient IdP outage
cannot evict a good JWKS.

The one place this departs from PyJWT is a `file://` location accepted **where
locality is local and nowhere else** (FR-20), so a developer's own keypair can be
published to the component without an IdP running. That is a decision this
module is entitled to take precisely because retrieval is its own code rather
than PyJWT's, and it is not the `jku` hole PyJWT's constructor closes: the
location comes from settings, never from a token header, so nothing a caller
sends can steer the read. See `_LOCAL_FILE_SCHEME` for why the locality gate is
load-bearing today rather than belt-and-braces.

django-allauth also ships a JWKS-by-`kid` implementation
(`allauth/socialaccount/internal/jwtkit.py`). AD-23 is *choosing* to build this
rather than being forced to: the choice buys the rate limiting neither library
provides. Do not "simplify" this module by delegating to either.

**Why this cache is process-local and the epoch record is not.** AD-10 forces the
credential-epoch record into a database table because two of the six declared
combinations ship no Redis, and a per-process cache would degrade "first
sighting" to first-sighting-per-worker-per-restart -- a *correctness* failure.
The reasoning does not transfer here and the shape is the opposite: this caches
**public** key material, and a per-worker duplicate costs one extra outbound
fetch, never a wrong authorization decision. It stays in process memory. Do not
move it into `django.core.cache` "for consistency with the epoch record", and do
not put it in the database.
"""

from __future__ import annotations

import json
import threading
from enum import Enum
from enum import auto
from math import inf
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from urllib.parse import SplitResult
from urllib.parse import urlsplit
from urllib.request import url2pathname

import jwt
import requests
import structlog
from django.conf import settings
from jwt import PyJWK
from jwt.exceptions import PyJWKSetError

from config.authorization.exceptions import JWKSKeyUnavailable
from config.locality import is_local

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

__all__ = [
    "KEY_STORE",
    "JWKSKeyStore",
    "configured_jwks_url",
    "conventional_jwks_url",
    "fetch_jwks_document",
    "jwks_url_derives_from_issuer",
    "resolve_jwks_url",
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The two schemes a JWKS location may use *over the network*. PyJWT's own client
#: rejects everything else, and this wrapper must not be weaker than the thing it
#: replaces: a `file://` location turns a `jku`-header-driven fetch into a local
#: file read.
_PERMITTED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

#: The one further scheme this module accepts, and only where locality is local
#: (FR-20). Local development mints tokens with a keypair generated on the
#: developer's own machine, and the JWKS document publishing its public half is a
#: file rather than an endpoint -- there is no IdP running to serve it. Because
#: retrieval here is *this component's* code rather than PyJWT's, accepting the
#: scheme is a decision this module gets to take (AD-23) rather than a bypass of
#: one PyJWT took for it.
#:
#: **The locality gate below is load-bearing and is not defence in depth.**
#: AD-23's stage-1 refusal of a JWKS location not derived from the issuer is
#: Epic 4's, and `jwks_url_derives_from_issuer` has no consumer in `src/` yet. If
#: this branch were reachable in a deployed component, that component would read
#: its trust anchor off local disk with nothing refusing it. The gate is that
#: obligation met by the module that owns the read; it does not discharge Epic 4
#: from declaring the refusal, and `jwks_url_derives_from_issuer` still answers
#: `False` for every `file://` location.
_LOCAL_FILE_SCHEME: Final = "file"

#: The hosts a `file://` location may name. A `file://` URL's authority is either
#: empty or the local machine; anything else is a UNC path or a typo, and reading
#: a trust anchor off a network share is the thing this scheme is not for.
_PERMITTED_FILE_HOSTS: Final[frozenset[str]] = frozenset({"", "localhost"})

#: The ports the two permitted schemes imply, so that `https://idp.example.com`
#: and `https://idp.example.com:443` are one origin rather than two. Compared as
#: parsed components; a substring comparison would make
#: `idp.example.com.evil.test` a match for `idp.example.com`.
_DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}

#: The conventional path a JWKS document is published at, appended to the
#: issuer when no explicit location is configured. It is a *convention* and not a
#: guarantee -- Keycloak publishes at `/protocol/openid-connect/certs`, which is
#: what `COMPONENT_OIDC_JWKS_URL` exists to express.
_CONVENTIONAL_JWKS_PATH: Final = "/.well-known/jwks.json"

#: Connect and read timeouts for the JWKS fetch, in seconds. Explicit because an
#: IdP that accepts a connection and never answers would otherwise hold a worker
#: thread for as long as the socket stays open -- and this fetch happens under
#: the store's lock, so one hung request would stall every concurrent Bearer
#: request in the process rather than only its own.
_FETCH_TIMEOUT: Final[tuple[float, float]] = (5.0, 5.0)

#: How long a fetched JWK Set is served before a refetch is attempted. Its
#: **only** job is to notice a key that was *removed* at the IdP; rotation is
#: handled by the uncached-`kid` refetch below, not by this. Shortening it does
#: not catch rotation faster and does not shorten R-2's revocation window -- it
#: governs key material, not authorization.
_DEFAULT_TTL_SECONDS: Final = 3600.0

#: The shortest interval between two outbound fetches. The Bearer path is
#: unauthenticated at the moment a key is needed, so without this a caller
#: sending random `kid` values produces one fetch per request, aimed at the IdP.
_DEFAULT_MIN_REFETCH_SECONDS: Final = 60.0

#: The largest JWK Set this module will accept, in bytes, and the chunk it reads
#: towards that bound. A JWK Set holding a handful of RSA keys is a few kilobytes,
#: so a megabyte is far above any real document and far below "unbounded". The
#: bound is not about memory: the fetch runs **under the store's lock**, and the
#: read timeout is inter-byte rather than total, so a body dripped one byte at a
#: time under the timeout would otherwise stall every concurrent Bearer request in
#: the process for as long as the sender cared to keep sending.
_MAX_DOCUMENT_BYTES: Final = 1_048_576
_DOCUMENT_CHUNK_BYTES: Final = 65_536

#: The reasons this module refuses to produce a key. Constants rather than
#: literals at the `raise`, and none of them carries a `kid` value -- the caller
#: logs that as its own field.
#:
#: `_NO_KEY_FOR_KID` and `_JWKS_FETCH_FAILED` are deliberately distinct. A refusal
#: that says "the IdP publishes no such kid" when the IdP was in fact unreachable
#: sends whoever reads the log to the wrong system -- they go looking at key
#: rotation when the answer is a network path or an unconfigured location.
_NO_KEY_FOR_KID: Final = "no signing key published for the presented kid"
_JWKS_FETCH_FAILED: Final = "the JWKS document could not be fetched from the IdP"
_REFETCH_RATE_LIMITED: Final = "refetch refused by the rate limit"
_NO_JWKS_LOCATION: Final = "no JWKS location is configured"
_UNPERMITTED_SCHEME: Final = "JWKS location uses a scheme that is not http or https"
_LOCAL_FILE_WHILE_DEPLOYED: Final = (
    "a file JWKS location is permitted only where the component runtime declares itself local"
)
_UNPERMITTED_FILE_HOST: Final = "a file JWKS location may not name a host"
_LOCAL_DOCUMENT_UNREADABLE: Final = "the file JWKS location could not be read"
_NOT_A_JSON_OBJECT: Final = "the JWKS location did not answer with a JSON object"
_DOCUMENT_TOO_LARGE: Final = "the JWKS location answered with a body above the accepted bound"
_MALFORMED_KEY_SET: Final = "the JWKS document is not a usable JWK Set"
_NO_KEYS_INDEXED: Final = "the JWKS document published no key carrying a kid"


class _Refresh(Enum):
    """What one refresh attempt actually did.

    A bool cannot carry this: "a fetch was attempted" and "a fetch succeeded" are
    different facts, and the caller reports a different refusal for each.
    """

    FETCHED = auto()
    FAILED = auto()
    RATE_LIMITED = auto()


#: The refusal each outcome produces when the `kid` is still not held afterwards.
#: A table rather than a conditional so adding an outcome without giving it a
#: reason is a `KeyError` at the raise rather than a silently reused string.
_REFUSAL_FOR: Final[dict[_Refresh, str]] = {
    _Refresh.FETCHED: _NO_KEY_FOR_KID,
    _Refresh.FAILED: _JWKS_FETCH_FAILED,
    _Refresh.RATE_LIMITED: _REFETCH_RATE_LIMITED,
}


def conventional_jwks_url(issuer: str) -> str:
    """Derive the conventional JWKS location for an issuer.

    Args:
        issuer: The configured OIDC issuer, which AD-23 makes the single trust
            anchor. May be the empty string when the component is unconfigured,
            in which case so is the result.

    Returns:
        The issuer with the conventional JWKS path appended, or the empty string
        when the issuer is empty. Any trailing slash on the issuer is dropped
        first, so `https://idp.example.com/` and `https://idp.example.com` derive
        the same location rather than one with a doubled separator.

    """
    trimmed = issuer.strip().rstrip("/")
    return f"{trimmed}{_CONVENTIONAL_JWKS_PATH}" if trimmed else ""


def resolve_jwks_url(explicit: str, issuer: str) -> str:
    """Apply the explicit-or-conventional fallback to two already-read values.

    The pure form of `configured_jwks_url` below, and the reason it exists is
    Epic 4: `configured_jwks_url` reads `django.conf.settings`, which is not yet
    populated while a settings module is still executing, so stage 1 of the
    refusal contract cannot call it. Stage 1 reads the two values off the
    settings module being composed and hands them here instead.

    Extracted rather than re-derived in `config/startup/`. The fallback -- unset
    location means *derived from the issuer*, not *unconfigured* -- is a rule
    `config/settings/local.py` is written against and that
    `tests/unit/test_settings.py` pins; a second spelling of it inside the
    refusal would let the startup check and the fetch disagree about which
    location is in force, which is the failure AD-1 is about.

    Args:
        explicit: Whatever `COMPONENT_OIDC_JWKS_URL` supplied, possibly empty.
        issuer: The configured OIDC issuer, possibly empty.

    Returns:
        The explicit location when one was supplied, the conventional derivation
        from the issuer otherwise, and the empty string when neither is
        configured. Whitespace is stripped before the test, so a variable
        exported as spaces is read as unset rather than as a location.

    """
    return explicit.strip() or conventional_jwks_url(issuer)


def configured_jwks_url() -> str:
    """Read the JWKS location in force, explicit or derived.

    Returns:
        `settings.OIDC_JWKS_URL` when it is configured, and the conventional
        derivation from `settings.OIDC_ISSUER` otherwise. There is no second
        issuer setting to fall back to: AD-23 makes `COMPONENT_OIDC_ISSUER` the
        single trust anchor, and a component with two answers to "who signs these
        tokens" has none.

        The rule itself lives in `resolve_jwks_url`; this function is the
        settings-reading half of it and nothing else.

    """
    explicit: str = getattr(settings, "OIDC_JWKS_URL", "") or ""
    return resolve_jwks_url(explicit, getattr(settings, "OIDC_ISSUER", "") or "")


def jwks_url_derives_from_issuer(issuer: str, jwks_url: str) -> bool:
    """Report whether a JWKS location is derived from the configured issuer.

    **This check is syntactic and can be nothing else.** It is a string-derivation
    rule over the configured issuer -- same scheme, same host, same port, and a
    path at or beneath the issuer's -- and never a comparison against the
    issuer's published discovery document, because reading `jwks_uri` out of
    discovery would require the boot-time network fetch FR-23 forbids.

    The consequence, stated rather than left to be discovered: an issuer whose
    real `jwks_uri` does **not** match this derivation surfaces on the first
    Bearer request, not at boot (AD-23, recorded as L-4). "Derived from" is not
    "confirmed against", and a reader who takes the startup refusal built on this
    predicate as proof of a working JWKS location has misread it. What the check
    does buy is the thing that matters at startup: a JWKS location pointing at a
    host the issuer does not control is refused before it can ever be trusted to
    sign anything.

    The **startup refusal** itself is Epic 4's (FR-13, condition 4 of the refusal
    table). This story exports the predicate; Epic 4 wires the
    `ImproperlyConfigured`.

    Args:
        issuer: The configured OIDC issuer.
        jwks_url: The JWKS location in force, explicit or derived.

    Returns:
        True when `jwks_url` is derived from `issuer`. False when either is
        empty, when either uses a scheme outside `http`/`https` -- a `file://`
        location is refused here rather than at fetch time -- or when scheme,
        host, port or path prefix differ. Compared as parsed `urlsplit`
        components and never as substrings: `https://idp.example.com.evil.test`
        contains `idp.example.com` and is a different host.

        **This predicate never raises.** `urlsplit` and `SplitResult.port` both
        raise `ValueError` on an authority they cannot parse -- a non-integer
        port, a port outside 0-65535, an unclosed IPv6 literal -- and a
        configuration typo must arrive at Epic 4's refusal as a refusal, not as a
        traceback out of a predicate annotated `-> bool`.

    """
    if not issuer.strip() or not jwks_url.strip():
        return False
    try:
        anchor = urlsplit(issuer.strip())
        candidate = urlsplit(jwks_url.strip())
        if anchor.scheme not in _PERMITTED_SCHEMES or candidate.scheme not in _PERMITTED_SCHEMES:
            return False
        anchor_origin = _origin(anchor)
        candidate_origin = _origin(candidate)
    except ValueError:
        # Handled and reported by the return value, which is the whole contract
        # of this function: an unparseable authority is a location that does not
        # derive from the issuer, and the caller refuses it as such.
        return False
    # A hostless location has no origin, and two of them are not evidence of a
    # shared one -- `None == None` would otherwise make `https:///path` derive
    # from `https:///`, which anchors the trust decision on nothing at all.
    if anchor_origin is None or anchor_origin != candidate_origin:
        return False
    return _path_is_under(anchor.path, candidate.path)


def _origin(parts: SplitResult) -> tuple[str, str, int] | None:
    """Reduce a parsed URL to the triple that decides whether two locations share an origin.

    Args:
        parts: The `urlsplit` result to reduce.

    Returns:
        Scheme, lowercased host and port, with the scheme's default port
        substituted when none was given. None when the URL carries no host at
        all, which never equals another origin -- including another hostless one,
        because two locations neither of which names a host are not evidence of
        anything.

    """
    host = parts.hostname
    if not host:
        return None
    port = parts.port
    return (parts.scheme, host.lower(), port if port is not None else _DEFAULT_PORTS[parts.scheme])


def _path_is_under(anchor_path: str, candidate_path: str) -> bool:
    """Report whether one URL path sits at or beneath another.

    Args:
        anchor_path: The issuer's path component.
        candidate_path: The JWKS location's path component.

    Returns:
        True when the candidate equals the anchor or continues it at a segment
        boundary. The boundary is what stops `/realms/main-evil/certs` passing as
        a path under `/realms/main`. False whenever either path carries a `..`
        segment: `urlsplit` does not normalize, so `/realms/main/../../other`
        starts with `/realms/main/` and names something else entirely.

    """
    anchor = anchor_path.rstrip("/")
    candidate = candidate_path.rstrip("/")
    if _escapes_its_prefix(anchor) or _escapes_its_prefix(candidate):
        return False
    if not anchor:
        return True
    return candidate == anchor or candidate.startswith(f"{anchor}/")


def _escapes_its_prefix(path: str) -> bool:
    """Report whether a URL path carries a segment that walks back out of it.

    Args:
        path: The path component to inspect.

    Returns:
        True when any segment is `..`. Refused rather than normalized: a location
        that has to be rewritten before it derives from the issuer is a location
        nobody wrote on purpose, and normalizing it here would make this
        predicate's answer depend on a resolution the fetch does not repeat.

    """
    return any(segment == ".." for segment in path.split("/"))


def fetch_jwks_document() -> Mapping[str, Any]:
    """Fetch the JWK Set document from the configured location.

    The default fetch seam. It is a module-level function taken as a constructor
    argument rather than a method, so a test supplies its own callable and no
    test in this repository ever opens a socket.

    Returns:
        The parsed JWK Set document.

    Raises:
        JWKSKeyUnavailable: The configured location is unusable -- unset, carrying
            a scheme outside `http`/`https`, or naming a local file where locality
            is not local -- or the answer is unusable: not JSON, not a JSON
            *object*, or larger than the accepted bound. Every one of these is a
            problem with the *document* rather than with the connection, and it is
            raised as this type rather than as a `RequestException` so the failure
            event names the right system: a payload-shape problem logged as a
            `RequestException` is indistinguishable from the IdP being
            unreachable.
        requests.RequestException: The IdP could not be reached or answered a
            non-2xx status. Caught by the store, which leaves the previously
            cached keys intact.

    """
    url = configured_jwks_url()
    if not url:
        raise JWKSKeyUnavailable(_NO_JWKS_LOCATION)
    location = urlsplit(url)
    if location.scheme == _LOCAL_FILE_SCHEME:
        body = _local_document(location)
    elif location.scheme in _PERMITTED_SCHEMES:
        body = _fetched_document(url)
    else:
        raise JWKSKeyUnavailable(_UNPERMITTED_SCHEME)
    try:
        document: Any = json.loads(body)
    except json.JSONDecodeError as malformed:
        # Handled and reported through the store's own failure path rather than
        # silently producing an empty key set, which would look exactly like a
        # rotation that removed every key.
        raise JWKSKeyUnavailable(_NOT_A_JSON_OBJECT) from malformed
    if not isinstance(document, dict):
        raise JWKSKeyUnavailable(_NOT_A_JSON_OBJECT)
    return document


def _fetched_document(url: str) -> bytes:
    """Read the JWK Set over the network.

    Args:
        url: The location, already established as `http` or `https`.

    Returns:
        The response body, within the accepted bound.

    Raises:
        JWKSKeyUnavailable: The body exceeded the bound.
        requests.RequestException: The IdP could not be reached or answered a
            non-2xx status.

    """
    # `allow_redirects=False`: a 30x would otherwise move the signing-key fetch to
    # a host `jwks_url_derives_from_issuer` never validated, which is the whole of
    # what the origin pinning buys. `stream=True` so the body is read under the
    # bound rather than in one unbounded call.
    response = requests.get(url, timeout=_FETCH_TIMEOUT, allow_redirects=False, stream=True)
    try:
        response.raise_for_status()
        return _bounded_body(response)
    finally:
        response.close()


def _local_document(location: SplitResult) -> bytes:
    """Read the JWK Set from a local file, where locality permits it (FR-20).

    Args:
        location: The already-split `file://` location.

    Returns:
        The file's contents, within the accepted bound.

    Raises:
        JWKSKeyUnavailable: The run is not local, the location names a host, the
            location is not a regular file, the file could not be read, or its
            contents exceed the bound. Every one of these is raised as this type
            rather than propagating an `OSError`, so the store's failure path
            treats an unreadable local document exactly as it treats an
            unreachable IdP: refuse this request, keep whatever keys are already
            cached.

    """
    # The gate, not a check. See `_LOCAL_FILE_SCHEME`: until Epic 4 declares the
    # stage-1 trust-anchor refusal, this line is the only thing standing between a
    # deployed component and a trust anchor read off local disk.
    if not is_local():
        raise JWKSKeyUnavailable(_LOCAL_FILE_WHILE_DEPLOYED)
    if location.netloc.lower() not in _PERMITTED_FILE_HOSTS:
        raise JWKSKeyUnavailable(_UNPERMITTED_FILE_HOST)
    # `url2pathname` rather than taking `location.path` as written: on `win-64`,
    # a declared platform, the path of `file:///C:/keys/jwks.json` is
    # `/C:/keys/jwks.json`, which is not a path any filesystem call resolves.
    path = Path(url2pathname(location.path))
    # Insisted on before opening, because this branch has no counterpart to
    # `_FETCH_TIMEOUT` and runs under the store's lock. A FIFO left by a stray
    # `mkfifo`, an editor artefact, or a hung network mount blocks `read()`
    # forever, and with the lock held every concurrent Bearer request in the
    # process blocks behind it -- the dev server stops answering with no error,
    # no timeout and no log line. `is_file()` follows symlinks and answers False
    # for anything that is not a regular file, including a directory and a
    # missing path, so the refusal below is what a caller sees instead.
    if not path.is_file():
        raise JWKSKeyUnavailable(_LOCAL_DOCUMENT_UNREADABLE)
    try:
        # One byte past the bound, so "too large" is decided by what was read
        # rather than by a `stat` the file could have grown past afterwards.
        with path.open("rb") as document:
            body = document.read(_MAX_DOCUMENT_BYTES + 1)
    # `ValueError` alongside `OSError`. A path carrying a percent-encoded NUL
    # survives `url2pathname` and raises `ValueError: embedded null byte` out of
    # `open` -- not an `OSError`, so it would escape the store's handler as a 500
    # on a request that should be a 401. The `is_file()` guard above answers
    # False for that path today and reaches it first; this catch is what keeps
    # the guarantee if the file is replaced between the check and the open, which
    # is a window `is_file()` cannot close.
    except (OSError, ValueError) as unreadable:
        raise JWKSKeyUnavailable(_LOCAL_DOCUMENT_UNREADABLE) from unreadable
    if len(body) > _MAX_DOCUMENT_BYTES:
        raise JWKSKeyUnavailable(_DOCUMENT_TOO_LARGE)
    return body


def _bounded_body(response: requests.Response) -> bytes:
    """Read a response body up to the accepted bound and no further.

    Args:
        response: The streamed response to read.

    Returns:
        The body, when it fits.

    Raises:
        JWKSKeyUnavailable: The body exceeded `_MAX_DOCUMENT_BYTES`. Read
            incrementally and refused as soon as the bound is crossed, rather
            than measured afterwards: the point is to stop reading, because this
            runs under the store's lock.

    """
    body = bytearray()
    for chunk in response.iter_content(chunk_size=_DOCUMENT_CHUNK_BYTES):
        body.extend(chunk)
        if len(body) > _MAX_DOCUMENT_BYTES:
            raise JWKSKeyUnavailable(_DOCUMENT_TOO_LARGE)
    return bytes(body)


class JWKSKeyStore:
    """A process-local JWK Set, cached by `kid`, refetched under a rate limit.

    Construction fetches nothing (AD-23, FR-23). The first `get_signing_key` is
    the first request out, and every later one is served from the dict until
    either the TTL lapses or a `kid` arrives that the cache does not hold.

    Thread-safety is a lock around fetch-and-swap, so N concurrent requests in a
    threaded worker produce one fetch rather than N. The fetch happens under that
    lock deliberately -- releasing it around the request is what would let the
    N-fetch stampede back in -- which is why `_FETCH_TIMEOUT` is explicit.
    """

    def __init__(
        self,
        fetch: Callable[[], Mapping[str, Any]] = fetch_jwks_document,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        """Build an empty store around a fetch callable and a clock.

        Args:
            fetch: How to obtain the JWK Set document. A constructor argument
                rather than a module import so the caching, refetch and
                rate-limiting tests AC #5 assigns to this code have a seam that
                needs no patching of module internals. **Never called here** --
                a fetch in the constructor is the boot-time network call FR-23
                forbids, because `KEY_STORE` is built at import.
            clock: The monotonic clock the TTL and the rate limit are measured
                against. A seam for the same reason: a rate-limit test that
                sleeps sixty seconds is not a unit test. Monotonic rather than
                wall-clock so an NTP step cannot open the rate limit.

        """
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: dict[str, PyJWK] = {}
        # Negative infinity rather than zero for both: `monotonic()` has an
        # undefined origin and may legitimately return a value smaller than the
        # rate-limit window, which with a zero start would refuse the very first
        # fetch of the process and answer every Bearer request with a 401.
        self._fetched_at: float = -inf
        self._last_fetch_attempt: float = -inf

    def get_signing_key(self, kid: str) -> PyJWK:
        """Return the key a `kid` designates, fetching or refetching if it takes that.

        The one entry point. A cached, unexpired key is returned without touching
        the network; anything else attempts exactly one refetch, subject to the
        rate limit, and then looks again.

        Args:
            kid: The key identifier read from the token's *unverified* header.
                Unverified is not a weakness here -- it selects which published
                public key to check the signature against, and a wrong one fails
                verification.

        Returns:
            The key published under `kid`.

        Raises:
            JWKSKeyUnavailable: No key is available, and `reason` names which of
                the three situations produced that. The refetch ran and the IdP
                publishes no such `kid`; or the refetch ran and failed, because
                the IdP was unreachable, answered non-2xx, or is unconfigured; or
                the rate limit refused it -- which is the case that makes the
                endpoint un-amplifiable, so it is a refusal rather than an
                exemption. The three are distinguished because they send whoever
                reads the log to three different systems.

        """
        cached = self._unexpired(kid)
        if cached is not None:
            return cached

        outcome = self._refresh()

        with self._lock:
            # Read without the TTL gate this time. A refetch the rate limit
            # refused leaves the previous keys in place, and serving a key that
            # is merely past its TTL beats answering 401 for every request while
            # an IdP is unreachable -- the TTL is a backstop for key removal, not
            # a validity bound on the key.
            key = self._keys.get(kid)
        if key is not None:
            return key
        raise JWKSKeyUnavailable(_REFUSAL_FOR[outcome])

    def reset(self) -> None:
        """Clear every trace of previous use.

        **This exists for tests.** A module-level cache that leaks between cases
        is the most likely source of an order-dependent failure in this package,
        so the integration suite calls this in a fixture. No production path
        calls it, and none should: emptying the cache to "force a refresh" is how
        the amplification the rate limit prevents gets reintroduced by hand.
        """
        with self._lock:
            self._keys = {}
            self._fetched_at = -inf
            self._last_fetch_attempt = -inf

    def _unexpired(self, kid: str) -> PyJWK | None:
        """Return a cached key, unless the cache is past its TTL.

        Args:
            kid: The key identifier being looked for.

        Returns:
            The cached key, or None when the cache holds no such `kid` or the
            whole set is past its TTL and therefore due a refetch.

        """
        with self._lock:
            if self._clock() - self._fetched_at >= _ttl_seconds():
                return None
            return self._keys.get(kid)

    def _refresh(self) -> _Refresh:
        """Attempt one fetch, subject to the rate limit, and swap the cache on success.

        Three outcomes rather than a bool, because the caller turns this into the
        reason it reports and "a fetch was attempted" and "a fetch succeeded" are
        different facts. Collapsing them is what makes an unreachable IdP get
        reported as "no signing key published for the presented kid" -- a refusal
        that blames key rotation for a network problem.

        Returns:
            `FETCHED` when a fetch ran and produced a usable key set, `FAILED`
            when one ran and did not, and `RATE_LIMITED` when the window refused
            it.

        """
        with self._lock:
            now = self._clock()
            if now - self._last_fetch_attempt < _min_refetch_seconds():
                # Handled and reported, never swallowed. This is the event an
                # operator sees when an attacker is spraying `kid` values, and it
                # is also the event they see when a real rotation is waiting out
                # the window, so it is a warning rather than a debug line.
                # No `kid` field: this event is emitted from inside the lock,
                # where the identifier that triggered it is not in scope, and an
                # attacker who can cause the event at will could otherwise write
                # a string of their choosing into every line of it. The caller's
                # own refusal event carries the `kid` once, after the refusal.
                logger.warning("authorization.jwks_refetch_rate_limited", reason=_REFETCH_RATE_LIMITED)
                return _Refresh.RATE_LIMITED
            # Stamped *before* the request, so an IdP that fails slowly or
            # refuses outright does not turn into a fetch loop: the next caller
            # is rate-limited by the attempt, not by its outcome.
            self._last_fetch_attempt = now
            try:
                document = self._fetch()
                keys = _index_by_kid(document)
            except (requests.RequestException, JWKSKeyUnavailable, PyJWKSetError) as failure:
                # Handled and reported, never swallowed, and the cache is left
                # exactly as it was: a transient IdP outage must not evict a good
                # JWKS and turn a degraded dependency into a total one. The
                # exception's type rather than its message, which for a
                # connection error carries the resolved address.
                #
                # Three named types and no `ValueError`: that was wide enough to
                # swallow a programming error raised inside `_index_by_kid` and
                # report it as an IdP problem. `requests`' own JSONDecodeError
                # subclasses `RequestException`, and every malformed-document
                # verdict `_index_by_kid` reaches is raised as `PyJWKSetError`.
                logger.warning("authorization.jwks_fetch_failed", failure=type(failure).__name__)
                return _Refresh.FAILED
            if not keys:
                # A JWK Set that indexes to nothing is an unusable document, not
                # a rotation that removed every key -- no IdP publishes an empty
                # signing set, and a set whose keys carry no `kid` parses cleanly
                # and indexes to nothing at all. Treated as a failed fetch so the
                # "written only on success" rule below actually holds: swapping
                # this in would replace every good cached key with nothing, which
                # is precisely the eviction a failed fetch must never cause.
                logger.warning("authorization.jwks_fetch_failed", failure=_NO_KEYS_INDEXED)
                return _Refresh.FAILED
            # Written only on success, and replaced wholesale rather than
            # merged: a key removed at the IdP has to disappear here too, and a
            # merge would keep serving it forever.
            self._keys = keys
            self._fetched_at = self._clock()
            logger.info("authorization.jwks_fetched", key_count=len(keys))
            return _Refresh.FETCHED


def _index_by_kid(document: Mapping[str, Any]) -> dict[str, PyJWK]:
    """Parse a JWK Set document and index its keys by `kid`.

    Args:
        document: The fetched JWK Set.

    Returns:
        Every key that declares a `kid`, keyed by it. A key without one is
        dropped rather than given an invented identifier: this store's whole
        lookup is by `kid`, and a set that publishes exactly one anonymous key is
        not a case any rotation strategy produces. The result may therefore be
        empty, which the caller treats as a failed fetch rather than as a
        rotation that removed everything.

    Raises:
        PyJWKSetError: The document is not a usable JWK Set. PyJWT raises this
            itself when the `keys` member is absent, empty, or not a list, and
            everything else it raises on a malformed member is re-raised as this
            type. `PyJWKSet.from_dict` is not total: a `keys` array holding a
            string raises `AttributeError`, one holding `null` the same, and a
            member missing the field its `kty` requires raises `KeyError` -- none
            of which are under `PyJWKSetError`, and all of which would otherwise
            escape the store's narrow catch as a 500 on an unauthenticated path.

    """
    try:
        key_set = jwt.PyJWKSet.from_dict(dict(document))
    except PyJWKSetError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as malformed:
        # Handled and re-raised, never swallowed: translated to the one type this
        # function documents so the caller's catch can stay narrow enough to let
        # a genuine programming error through.
        raise PyJWKSetError(_MALFORMED_KEY_SET) from malformed
    return {key.key_id: key for key in key_set.keys if key.key_id}


def _ttl_seconds() -> float:
    """Read the cache lifetime in force.

    Returns:
        `settings.JWKS_TTL_SECONDS`, or the default hour. Read per call rather
        than captured at construction so the `settings` fixture can move it
        inside a test without rebuilding the store.

    """
    return float(getattr(settings, "JWKS_TTL_SECONDS", _DEFAULT_TTL_SECONDS))


def _min_refetch_seconds() -> float:
    """Read the rate-limit window in force.

    Returns:
        `settings.JWKS_MIN_REFETCH_SECONDS`, or the default minute.

    """
    return float(getattr(settings, "JWKS_MIN_REFETCH_SECONDS", _DEFAULT_MIN_REFETCH_SECONDS))


#: The process's key store, constructed at import and **empty**. Construction is
#: not a fetch: AD-23 and FR-23 both turn on the first outbound request happening
#: on the first Bearer request that needs one, so an eager warm-up here -- or in
#: an `AppConfig.ready()`, or in a Django system check -- is the boot-time
#: network call Epic 3's clone-and-run contract forbids.
KEY_STORE: Final = JWKSKeyStore()
