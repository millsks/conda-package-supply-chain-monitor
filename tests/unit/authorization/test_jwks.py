"""The key store's caching, refetch, rate limit and TTL -- the suite AC #5 assigns here.

AC #5 is explicit that these tests belong to *this* code rather than to PyJWT:
`PyJWKClient.cache_keys` defaults to False, its unknown-`kid` refetch has no rate
limiting, and its LRU has no TTL, so the policy AD-23 describes is component code
wrapping the library and the proof of it has to be too.

Nothing here opens a socket and nothing here sleeps. `JWKSKeyStore` takes both
its fetch callable and its clock as constructor arguments, so a test that reached
the network or waited out a sixty-second window would be a test that did not use
the seam. The one case that exercises the real fetch does so with
`requests.get` replaced.

The trust-anchor predicate is exercised in the same module because it is the same
module's export: AD-23's derivation rule is what decides *where* the fetch is
allowed to point, and separating it would put two halves of one rule in two
files.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import jwt
import pytest
import requests

from config.authorization import authentication as authentication_module
from config.authorization import jwks as jwks_module
from config.authorization.exceptions import JWKSKeyUnavailable
from config.authorization.jwks import JWKSKeyStore
from config.authorization.jwks import configured_jwks_url
from config.authorization.jwks import conventional_jwks_url
from config.authorization.jwks import fetch_jwks_document
from config.authorization.jwks import jwks_url_derives_from_issuer
from config.locality import RUNTIME_ENV_VAR
from tests.jwt_keys import FakeClock
from tests.jwt_keys import SigningKey
from tests.jwt_keys import StubFetch
from tests.jwt_keys import generate
from tests.jwt_keys import jwks_document

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django.fixtures import SettingsWrapper

# Windows the tests set explicitly rather than inheriting from the environment,
# so a developer with COMPONENT_JWKS_* exported cannot change what they assert.
TTL_SECONDS = 3600.0
MIN_REFETCH_SECONDS = 60.0

PUBLISHED_KID = "primary-2026"
ROTATED_KID = "rotated-2027"
UNPUBLISHED_KID = "never-published"

# How many distinct unpublished identifiers the amplification probe sprays. Any
# number above one shows the property; a few dozen makes the failure obvious.
SPRAY = 25

# The fetch count after the initial fetch plus exactly one refetch -- the number
# almost every case here asserts, named so that "2" never appears as a literal
# whose meaning has to be reconstructed from the case around it.
AFTER_ONE_REFETCH = 2

ISSUER = "https://idp.example.com/realms/main"

# The reasons the store names. Asserted as literals rather than imported from the
# module they are declared in: a test that imports the constant it compares
# against moves with the code and can detect no drift at all.
NO_KEY_FOR_KID = "no signing key published for the presented kid"
RATE_LIMITED = "refetch refused by the rate limit"
FETCH_FAILED = "the JWKS document could not be fetched from the IdP"

# `JWKSKeyUnavailable`'s docstring promises the reason distinguishes three
# situations. Three, not "at least two" -- the count is the assertion.
DISTINGUISHABLE_REASONS = 3

# The bound the fetch accepts, and a body comfortably past it. Written here as a
# literal for the same reason the reasons above are.
MAX_DOCUMENT_BYTES = 1_048_576

# The probe below fails by *being called*, so the exception is built once and
# raised rather than constructed at the raise site.
_NETWORK_AT_IMPORT = AssertionError("importing the Bearer modules reached the network")


#: How long the FIFO case waits before calling the fetch blocked. Generous
#: enough that a loaded CI runner does not report a hang that is really a
#: scheduling delay, short enough that a real hang is reported rather than
#: waiting out the suite timeout.
_FIFO_DEADLINE_SECONDS = 5.0


@pytest.fixture(scope="module")
def published_key() -> SigningKey:
    """The key the IdP publishes for the whole module."""
    return generate(PUBLISHED_KID)


@pytest.fixture(scope="module")
def rotated_key() -> SigningKey:
    """A second key, published only by the rotation cases."""
    return generate(ROTATED_KID)


@pytest.fixture(autouse=True)
def _windows(settings: SettingsWrapper) -> None:
    """Pin the TTL and the rate-limit window for every case in this module."""
    settings.JWKS_TTL_SECONDS = TTL_SECONDS
    settings.JWKS_MIN_REFETCH_SECONDS = MIN_REFETCH_SECONDS


@pytest.fixture
def fetch(published_key: SigningKey) -> StubFetch:
    """A fetch seam publishing one key and counting every call."""
    return StubFetch(jwks_document(published_key))


@pytest.fixture
def clock() -> FakeClock:
    """A monotonic clock the test moves by hand."""
    return FakeClock()


@pytest.fixture
def store(fetch: StubFetch, clock: FakeClock) -> JWKSKeyStore:
    """A store built around the two seams, holding nothing."""
    return JWKSKeyStore(fetch, clock=clock)


# ---------------------------------------------------------------------------
# AC #3 -- nothing fetches at construction, and nothing fetches at import.
# ---------------------------------------------------------------------------


def test_constructing_the_store_fetches_nothing(fetch: StubFetch, clock: FakeClock) -> None:
    """AD-23 and FR-23: `KEY_STORE` is built at import, so a fetch here is a boot-time fetch."""
    JWKSKeyStore(fetch, clock=clock)

    assert fetch.calls == 0


def test_importing_the_bearer_modules_reaches_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-23: nothing on the start path reaches the network, so neither module body may.

    Both modules are executed again from source under a throwaway name, with
    `requests.get` replaced by something that fails if it is ever called. Loading
    a fresh copy rather than reloading in place is deliberate: a reload would
    rebind the process's real `KEY_STORE` and leave every later test holding a
    different object than the authentication class does.
    """
    calls: list[tuple[Any, ...]] = []

    def refuse_to_reach_the_network(*args: Any, **kwargs: Any) -> None:
        calls.append(args)
        raise _NETWORK_AT_IMPORT

    monkeypatch.setattr(requests, "get", refuse_to_reach_the_network)

    for module in (jwks_module, authentication_module):
        path = Path(str(module.__file__))
        spec = importlib.util.spec_from_file_location(f"{path.stem}__import_probe", path)
        assert spec is not None
        assert spec.loader is not None
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)

    assert calls == [], "importing the Bearer modules called out to the network"


# ---------------------------------------------------------------------------
# AC #4, #5 -- caching, the one refetch, and the rate limit that bounds it.
# ---------------------------------------------------------------------------


def test_the_first_lookup_triggers_exactly_one_fetch(store: JWKSKeyStore, fetch: StubFetch) -> None:
    """Lazily on the first Bearer request that needs it (AD-23) -- and once."""
    key = store.get_signing_key(PUBLISHED_KID)

    assert fetch.calls == 1
    assert key.key_id == PUBLISHED_KID


def test_a_second_lookup_of_a_cached_kid_triggers_no_fetch(store: JWKSKeyStore, fetch: StubFetch) -> None:
    """Keys are cached by `kid`: the hot path must not be one outbound request per request."""
    store.get_signing_key(PUBLISHED_KID)

    for _ in range(SPRAY):
        assert store.get_signing_key(PUBLISHED_KID).key_id == PUBLISHED_KID

    assert fetch.calls == 1


def test_an_uncached_kid_triggers_exactly_one_refetch(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """AC #4: an unknown `kid` is what makes a rotation visible, so it must refetch -- once."""
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(MIN_REFETCH_SECONDS)

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        store.get_signing_key(UNPUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH
    assert refusal.value.reason == NO_KEY_FOR_KID


def test_a_second_uncached_kid_inside_the_window_triggers_no_further_fetch(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """AC #4's whole point: the Bearer path is unauthenticated when the key is needed.

    Without the rate limit a caller sending random `kid` values produces one
    outbound JWKS fetch per request, aimed at the IdP -- an amplification vector
    that PyJWT's own client leaves wide open. This is the case that fails if the
    window is ever removed or driven to zero.
    """
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(MIN_REFETCH_SECONDS)
    with pytest.raises(JWKSKeyUnavailable):
        store.get_signing_key(UNPUBLISHED_KID)
    assert fetch.calls == AFTER_ONE_REFETCH

    for index in range(SPRAY):
        with pytest.raises(JWKSKeyUnavailable) as refusal:
            store.get_signing_key(f"{UNPUBLISHED_KID}-{index}")
        assert refusal.value.reason == RATE_LIMITED

    assert fetch.calls == AFTER_ONE_REFETCH, "a sprayed kid produced an outbound fetch"


def test_the_window_reopens_once_it_has_elapsed(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """A rate limit that never reopened would make the first rotation permanent."""
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(MIN_REFETCH_SECONDS / 2)
    with pytest.raises(JWKSKeyUnavailable):
        store.get_signing_key(UNPUBLISHED_KID)
    assert fetch.calls == 1

    clock.advance(MIN_REFETCH_SECONDS)
    with pytest.raises(JWKSKeyUnavailable):
        store.get_signing_key(UNPUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH


def test_the_attempt_is_stamped_before_the_request_so_a_failing_idp_is_not_a_loop(
    store: JWKSKeyStore,
    fetch: StubFetch,
) -> None:
    """An IdP that refuses must rate-limit the next caller by the attempt, not by its outcome."""
    fetch.failure = requests.ConnectionError()

    for index in range(SPRAY):
        with pytest.raises(JWKSKeyUnavailable):
            store.get_signing_key(f"{UNPUBLISHED_KID}-{index}")

    assert fetch.calls == 1


# ---------------------------------------------------------------------------
# AC #5 -- a failed fetch never evicts, and a malformed document never does either.
# ---------------------------------------------------------------------------


def test_a_failed_fetch_leaves_the_cached_keys_intact(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """A transient IdP outage must not turn a degraded dependency into a total one."""
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(TTL_SECONDS + 1)
    fetch.failure = requests.ConnectionError()

    key = store.get_signing_key(PUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH
    assert key.key_id == PUBLISHED_KID


def test_a_malformed_document_leaves_the_cached_keys_intact(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """A key set with nothing usable in it is a failure, not a rotation that removed everything."""
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(TTL_SECONDS + 1)
    fetch.document = {"keys": []}

    key = store.get_signing_key(PUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH
    assert key.key_id == PUBLISHED_KID


def test_a_document_whose_keys_carry_no_kid_leaves_the_cached_keys_intact(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
    published_key: SigningKey,
) -> None:
    """The eviction the `{"keys": []}` case above cannot catch, because that one raises.

    A JWK Set whose members carry no `kid` **parses cleanly** -- `PyJWKSet` is
    happy, every key gets `key_id is None` -- and then indexes to nothing at all,
    because this store's whole lookup is by `kid`. Swapping that empty index in
    would replace every good cached key with nothing while logging a successful
    fetch, which is exactly the eviction "written only on success" is supposed to
    make impossible. It is an unusable document, not a rotation that withdrew
    every key: no IdP publishes an empty signing set.
    """
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(TTL_SECONDS + 1)
    anonymous = published_key.public_jwk()
    del anonymous["kid"]
    fetch.document = {"keys": [anonymous]}

    key = store.get_signing_key(PUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH
    assert key.key_id == PUBLISHED_KID


def test_a_keys_array_holding_a_junk_element_is_a_failed_fetch_not_a_crash(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """`PyJWKSet.from_dict` is not total, and what it raises is not always a `PyJWKSetError`.

    A `keys` array holding a string raises `AttributeError` and one holding
    `null` the same -- neither under `PyJWKSetError`, both reached from an
    unauthenticated request, and both a 500 with a traceback unless the store
    translates them.
    """
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(TTL_SECONDS + 1)
    fetch.document = {"keys": ["not a jwk at all"]}

    key = store.get_signing_key(PUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH
    assert key.key_id == PUBLISHED_KID


# ---------------------------------------------------------------------------
# The refusal reason names the system that actually failed.
# ---------------------------------------------------------------------------


def test_a_reachable_idp_publishing_no_such_kid_says_so(
    store: JWKSKeyStore,
    clock: FakeClock,
) -> None:
    """The one case where "no signing key published for the presented kid" is true."""
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(MIN_REFETCH_SECONDS)

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        store.get_signing_key(UNPUBLISHED_KID)

    assert refusal.value.reason == NO_KEY_FOR_KID


def test_an_unreachable_idp_is_not_reported_as_a_kid_nobody_published(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """`JWKSKeyUnavailable` promises three distinguishable reasons, and this is the third.

    A refresh that *ran* is not a refresh that *succeeded*. Reporting an
    unreachable IdP as "no signing key published for the presented kid" sends
    whoever reads the log to look at key rotation when the answer is a network
    path, a non-2xx answer, or an unconfigured location.
    """
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(TTL_SECONDS + 1)
    fetch.failure = requests.ConnectionError()

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        store.get_signing_key(UNPUBLISHED_KID)

    assert refusal.value.reason == FETCH_FAILED
    assert refusal.value.reason != NO_KEY_FOR_KID


def test_a_refetch_the_rate_limit_refused_says_that_and_not_something_else(
    store: JWKSKeyStore,
    fetch: StubFetch,
) -> None:
    """The three reasons are pairwise distinct, which is the whole point of having three."""
    fetch.failure = requests.ConnectionError()
    with pytest.raises(JWKSKeyUnavailable) as first:
        store.get_signing_key(UNPUBLISHED_KID)

    with pytest.raises(JWKSKeyUnavailable) as second:
        store.get_signing_key(UNPUBLISHED_KID)

    assert first.value.reason == FETCH_FAILED
    assert second.value.reason == RATE_LIMITED
    assert len({FETCH_FAILED, RATE_LIMITED, NO_KEY_FOR_KID}) == DISTINGUISHABLE_REASONS


# ---------------------------------------------------------------------------
# AC #6 -- the TTL, and the one job it has.
# ---------------------------------------------------------------------------


def test_the_ttl_triggers_a_refetch_and_only_then(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """Nothing before the lifetime lapses, exactly one fetch after it."""
    store.get_signing_key(PUBLISHED_KID)

    clock.advance(TTL_SECONDS - 1)
    store.get_signing_key(PUBLISHED_KID)
    assert fetch.calls == 1

    clock.advance(2)
    store.get_signing_key(PUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH


def test_the_ttl_is_what_notices_a_key_removed_at_the_idp(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
    rotated_key: SigningKey,
) -> None:
    """AC #6: the lifetime exists *only* as a backstop for key removal, and this is it.

    Nothing else in the design would ever notice. An uncached `kid` triggers a
    refetch, but a key that has been withdrawn is one the cache still holds, so
    no lookup for it misses and no refetch is provoked.
    """
    store.get_signing_key(PUBLISHED_KID)
    fetch.document = jwks_document(rotated_key)

    clock.advance(TTL_SECONDS + 1)

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        store.get_signing_key(PUBLISHED_KID)
    assert refusal.value.reason == NO_KEY_FOR_KID


# ---------------------------------------------------------------------------
# AC #4 -- a rotation is survived without a restart.
# ---------------------------------------------------------------------------


def test_a_rotation_is_survived_without_a_restart(
    store: JWKSKeyStore,
    fetch: StubFetch,
    clock: FakeClock,
    published_key: SigningKey,
    rotated_key: SigningKey,
) -> None:
    """A token signed by a key published after this process started still verifies."""
    store.get_signing_key(PUBLISHED_KID)
    fetch.document = jwks_document(published_key, rotated_key)
    clock.advance(MIN_REFETCH_SECONDS)
    token = rotated_key.sign({"sub": "urn:example:principal:rotation"})

    key = store.get_signing_key(ROTATED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH
    assert jwt.decode(token, key=key.key, algorithms=["RS256"]) == {"sub": "urn:example:principal:rotation"}
    # The key that was already in use is still served, so a rotation does not
    # refuse every token minted a second before it.
    assert store.get_signing_key(PUBLISHED_KID).key_id == PUBLISHED_KID


def test_reset_clears_the_store_for_the_next_test(store: JWKSKeyStore, fetch: StubFetch) -> None:
    """The seam the integration suite uses so a module-level cache cannot leak between cases."""
    store.get_signing_key(PUBLISHED_KID)

    store.reset()
    store.get_signing_key(PUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH


# ---------------------------------------------------------------------------
# AD-23's trust anchor -- derived from the issuer, and compared as components.
# ---------------------------------------------------------------------------


def test_a_jwks_location_under_the_issuer_derives_from_it() -> None:
    assert jwks_url_derives_from_issuer(ISSUER, f"{ISSUER}/protocol/openid-connect/certs") is True


def test_the_issuer_itself_derives_from_the_issuer() -> None:
    """The path rule is "at or beneath", so an issuer that publishes at its own root passes."""
    assert jwks_url_derives_from_issuer(ISSUER, ISSUER) is True


@pytest.mark.parametrize(
    "location",
    [
        pytest.param("https://other.example.com/realms/main/certs", id="different-host"),
        pytest.param("https://idp.example.com.evil.test/realms/main/certs", id="lookalike-host"),
        pytest.param("https://idp.example.com:8443/realms/main/certs", id="different-port"),
        pytest.param("http://idp.example.com/realms/main/certs", id="different-scheme"),
        pytest.param("file:///etc/passwd", id="local-file"),
        pytest.param("file://idp.example.com/realms/main/certs", id="local-file-wearing-the-host"),
        pytest.param("https://idp.example.com/realms/main-evil/certs", id="path-sharing-a-prefix"),
        pytest.param("https://idp.example.com/realms/other/certs", id="different-path"),
        pytest.param("", id="unset"),
    ],
)
def test_a_jwks_location_not_derived_from_the_issuer_is_refused(location: str) -> None:
    """Compared as parsed components, never as substrings.

    The lookalike case is the one that decides it: `idp.example.com.evil.test`
    *contains* the issuer's host, so a substring rule would hand an attacker the
    right to publish this component's signing keys.
    """
    assert jwks_url_derives_from_issuer(ISSUER, location) is False


@pytest.mark.parametrize(
    "location",
    [
        pytest.param("https://idp.example.com:notaport/realms/main/certs", id="port-that-is-not-a-number"),
        pytest.param("https://idp.example.com:99999/realms/main/certs", id="port-out-of-range"),
        pytest.param("https://[idp.example.com/realms/main/certs", id="unclosed-ipv6-authority"),
        pytest.param("https://idp.example.com/realms/main/../../other/certs", id="path-walking-out-of-the-issuer"),
    ],
)
def test_an_unparseable_or_escaping_location_is_refused_rather_than_raised(location: str) -> None:
    """The predicate is annotated `-> bool` and Epic 4 builds a startup refusal on it.

    `urlsplit` raises `ValueError` on an unclosed IPv6 authority and
    `SplitResult.port` raises on a port that is not an integer or is out of
    range, so a typo in `COMPONENT_OIDC_JWKS_URL` would otherwise crash the check
    that exists to refuse it -- and crash it *before* it could refuse anything,
    which turns a configuration mistake into a traceback with no verdict.

    The dot-segment case is not a parse failure but the same class of miss:
    `urlsplit` does not normalize, so `/realms/main/../../other` starts with
    `/realms/main/` and passes a prefix rule while naming a path outside the
    issuer entirely.
    """
    assert jwks_url_derives_from_issuer(ISSUER, location) is False


def test_an_unparseable_issuer_anchors_nothing_either() -> None:
    """The guard covers the anchor as well as the candidate; either one can be the typo."""
    assert jwks_url_derives_from_issuer("https://idp.example.com:notaport/realms/main", f"{ISSUER}/certs") is False


def test_an_unset_issuer_anchors_nothing() -> None:
    """Unconfigured is not a licence: with no anchor, no location derives from it."""
    assert jwks_url_derives_from_issuer("", f"{ISSUER}/certs") is False


def test_an_issuer_with_no_host_anchors_nothing() -> None:
    """Two hostless locations are not evidence of a shared origin."""
    assert jwks_url_derives_from_issuer("https:///realms/main", "https:///realms/main/certs") is False


def test_an_issuer_at_the_host_root_anchors_every_path_on_that_host() -> None:
    """An issuer with no path of its own constrains the origin and nothing more.

    Auth0 and Okta issue at the host root, so this is the common shape rather
    than an edge: with no path to be beneath, the derivation rule reduces to
    scheme, host and port -- which is still the whole of what it can check.
    """
    assert jwks_url_derives_from_issuer("https://idp.example.com", "https://idp.example.com/.well-known/jwks.json")
    assert not jwks_url_derives_from_issuer("https://idp.example.com", "https://other.example.com/jwks.json")


def test_an_explicit_port_matching_the_scheme_default_is_the_same_origin() -> None:
    assert jwks_url_derives_from_issuer("https://idp.example.com:443/realms/main", f"{ISSUER}/certs") is True


@pytest.mark.parametrize(
    ("issuer", "expected"),
    [
        pytest.param(ISSUER, f"{ISSUER}/.well-known/jwks.json", id="plain"),
        pytest.param(f"{ISSUER}/", f"{ISSUER}/.well-known/jwks.json", id="trailing-slash"),
        pytest.param(f"  {ISSUER}  ", f"{ISSUER}/.well-known/jwks.json", id="padded"),
        pytest.param("", "", id="unset"),
    ],
)
def test_the_conventional_location_is_derived_from_the_issuer(issuer: str, expected: str) -> None:
    assert conventional_jwks_url(issuer) == expected


def test_the_conventional_derivation_is_what_an_unset_override_falls_back_to(settings: SettingsWrapper) -> None:
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = ""

    assert configured_jwks_url() == f"{ISSUER}/.well-known/jwks.json"


def test_an_explicit_location_overrides_the_derivation(settings: SettingsWrapper) -> None:
    """Keycloak does not publish at the conventional path, which is what the override is for."""
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"

    assert configured_jwks_url() == f"{ISSUER}/protocol/openid-connect/certs"


# ---------------------------------------------------------------------------
# The default fetch seam, with `requests.get` replaced. No socket is opened.
# ---------------------------------------------------------------------------


class _Answer:
    """The pieces of a `requests` response the fetch actually uses.

    The body is served through `iter_content` rather than `json()` because the
    fetch reads it incrementally under a size bound -- it runs inside the store's
    lock, and the read timeout is inter-byte rather than total, so an unbounded
    body would stall every concurrent Bearer request in the process.
    """

    def __init__(self, payload: Any, *, body: bytes | None = None) -> None:
        self.body = json.dumps(payload).encode() if body is None else body
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 1) -> Iterator[bytes]:
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class _Call:
    """One recorded `requests.get`, with the arguments the fetch's safety rests on."""

    def __init__(self, url: str, kwargs: dict[str, Any]) -> None:
        self.url = url
        self.kwargs = kwargs


def _record(monkeypatch: pytest.MonkeyPatch, answer: _Answer) -> list[_Call]:
    """Replace `requests.get` with something that records its call and answers.

    Args:
        monkeypatch: The patcher.
        answer: What the replacement returns.

    Returns:
        The list the calls are recorded into.

    """
    calls: list[_Call] = []

    def get(url: str, **kwargs: Any) -> _Answer:
        calls.append(_Call(url, kwargs))
        return answer

    monkeypatch.setattr(requests, "get", get)
    return calls


def test_the_default_fetch_returns_the_document_the_idp_served(
    settings: SettingsWrapper,
    monkeypatch: pytest.MonkeyPatch,
    published_key: SigningKey,
) -> None:
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = ""
    document = jwks_document(published_key)
    calls = _record(monkeypatch, _Answer(document))

    assert fetch_jwks_document() == document
    assert [call.url for call in calls] == [f"{ISSUER}/.well-known/jwks.json"]
    assert calls[0].kwargs["timeout"] == (5.0, 5.0), "the fetch must carry an explicit timeout"


def test_the_default_fetch_does_not_follow_a_redirect(
    settings: SettingsWrapper,
    monkeypatch: pytest.MonkeyPatch,
    published_key: SigningKey,
) -> None:
    """A 30x would move the signing-key fetch to a host the origin pinning never saw.

    `jwks_url_derives_from_issuer` validates the *configured* location against the
    issuer. `requests` follows redirects by default, so an IdP -- or anything able
    to answer for it -- could answer 302 and have this component fetch its trust
    material from somewhere the derivation rule was never applied to. The whole
    value of pinning the origin is lost in one header.
    """
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = ""
    calls = _record(monkeypatch, _Answer(jwks_document(published_key)))

    fetch_jwks_document()

    assert calls[0].kwargs["allow_redirects"] is False


def test_the_default_fetch_refuses_a_body_above_the_accepted_bound(
    settings: SettingsWrapper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read happens under the store's lock, and the timeout is inter-byte, not total."""
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = ""
    oversize = b'{"keys": [' + b"x" * (MAX_DOCUMENT_BYTES + 1)
    _record(monkeypatch, _Answer(None, body=oversize))

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert refusal.value.reason == "the JWKS location answered with a body above the accepted bound"


def test_an_oversize_body_leaves_the_cached_keys_intact(
    fetch: StubFetch,
    clock: FakeClock,
) -> None:
    """An over-size answer is a failed fetch like any other, and a failed fetch evicts nothing."""
    store = JWKSKeyStore(fetch, clock=clock)
    store.get_signing_key(PUBLISHED_KID)
    clock.advance(TTL_SECONDS + 1)
    fetch.failure = JWKSKeyUnavailable("the JWKS location answered with a body above the accepted bound")

    key = store.get_signing_key(PUBLISHED_KID)

    assert fetch.calls == AFTER_ONE_REFETCH
    assert key.key_id == PUBLISHED_KID


def test_the_default_fetch_refuses_an_unconfigured_location(settings: SettingsWrapper) -> None:
    settings.OIDC_ISSUER = ""
    settings.OIDC_JWKS_URL = ""

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert refusal.value.reason == "no JWKS location is configured"


@pytest.mark.parametrize(
    "location",
    [
        pytest.param("ftp://idp.example.com/certs", id="ftp"),
        pytest.param("data:application/json,{}", id="data"),
        pytest.param("gopher://idp.example.com/certs", id="gopher"),
    ],
)
def test_the_default_fetch_refuses_a_scheme_outside_http(settings: SettingsWrapper, location: str) -> None:
    """PyJWT's own client rejects these to block a `jku`-driven local file read."""
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = location

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert refusal.value.reason == "JWKS location uses a scheme that is not http or https"


# ---- The `file://` location (FR-20) ----
# The scheme this module accepts where locality is local and nowhere else, so a
# developer's own keypair can be published without an IdP running. These four
# cases are one rule: *local* decides whether the branch exists at all, and the
# host and the readability decide whether it answers.
#
# This suite runs in the `dev` environment, which declares
# COMPONENT_RUNTIME=local, so the deployed case is reached by deleting the
# variable rather than by setting it.


def test_a_file_location_is_read_where_locality_is_local(settings: SettingsWrapper, tmp_path: Path) -> None:
    """AC #1: local settings point the JWKS location at the generated key, and it resolves."""
    key = generate(PUBLISHED_KID)
    document = tmp_path / "jwks.json"
    document.write_text(json.dumps(jwks_document(key)), encoding="utf-8")
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = document.as_uri()

    fetched = fetch_jwks_document()

    assert [published["kid"] for published in fetched["keys"]] == [PUBLISHED_KID]


def test_a_file_location_is_refused_where_the_run_is_not_local(
    settings: SettingsWrapper,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate, not a nicety.

    AD-23's stage-1 trust-anchor refusal is Epic 4's and is not implemented yet,
    so until it lands this is the only thing standing between a deployed
    component and a trust anchor read off local disk.
    """
    document = tmp_path / "jwks.json"
    document.write_text(json.dumps(jwks_document(generate(PUBLISHED_KID))), encoding="utf-8")
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = document.as_uri()
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert (
        refusal.value.reason
        == "a file JWKS location is permitted only where the component runtime declares itself local"
    )


@pytest.mark.parametrize(
    "authority",
    [
        pytest.param("localhost", id="localhost"),
        pytest.param("LOCALHOST", id="localhost-uppercased"),
    ],
)
def test_a_file_location_may_name_the_local_machine(
    settings: SettingsWrapper,
    tmp_path: Path,
    authority: str,
) -> None:
    """`file://localhost/...` is the same location as `file:///...`, in any case.

    `Path.as_uri()` always renders an empty authority, so nothing else in this
    file reaches either the `"localhost"` member of the permitted set or the
    `.lower()` that normalizes the authority before the membership test. Without
    these two cases, narrowing the set to `{""}` or dropping the normalization
    would refuse a location RFC 8089 calls equivalent, and the whole suite would
    stay green.
    """
    key = generate(PUBLISHED_KID)
    document = tmp_path / "jwks.json"
    document.write_text(json.dumps(jwks_document(key)), encoding="utf-8")
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = f"file://{authority}{document.as_uri().removeprefix('file://')}"

    fetched = fetch_jwks_document()

    assert [published["kid"] for published in fetched["keys"]] == [PUBLISHED_KID]


def test_a_file_location_may_not_name_a_host(settings: SettingsWrapper) -> None:
    """Reading a trust anchor off a network share is what this scheme is not for."""
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = "file://fileserver.example.com/keys/jwks.json"

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert refusal.value.reason == "a file JWKS location may not name a host"


def test_a_directory_at_the_file_location_is_a_failed_fetch(
    settings: SettingsWrapper,
    tmp_path: Path,
) -> None:
    """A directory answers with the same refusal an absent file does.

    This pins the *refusal*, not the guard: `open` on a directory raises
    `IsADirectoryError`, which the handler below would catch anyway. The guard
    itself is pinned by the FIFO case, which is the one that cannot pass without
    it.
    """
    directory = tmp_path / "jwks.json"
    directory.mkdir()
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = directory.as_uri()

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert refusal.value.reason == "the file JWKS location could not be read"


def test_a_fifo_at_the_file_location_is_refused_without_blocking(
    settings: SettingsWrapper,
    tmp_path: Path,
) -> None:
    """The guard that keeps a FIFO from stalling every Bearer request in the process.

    The file branch has no counterpart to `_FETCH_TIMEOUT` and runs under the
    store's lock, so opening a FIFO with no writer blocks in `open` forever and
    every concurrent Bearer request blocks behind it -- the server stops
    answering with no error, no timeout and no log line.

    Driven on a thread with a join deadline rather than called directly, because
    the failure this guards against is a *hang*: a direct call would take the
    whole suite down with it instead of reporting. `os.mkfifo` is POSIX-only, and
    the branch is the same one `config/local_dev/keys.py` documents for the mode
    bits -- `tests/unit/test_suite_policy.py` bans `skipif`.
    """
    if os.name != "posix":
        return

    fifo = tmp_path / "jwks.json"
    os.mkfifo(fifo)
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = fifo.as_uri()
    outcome: list[object] = []

    def fetch() -> None:
        try:
            outcome.append(fetch_jwks_document())
        except JWKSKeyUnavailable as refusal:
            outcome.append(refusal)

    worker = threading.Thread(target=fetch, daemon=True)
    worker.start()
    worker.join(timeout=_FIFO_DEADLINE_SECONDS)

    assert not worker.is_alive(), "the fetch blocked on the FIFO instead of refusing it"
    assert isinstance(outcome[0], JWKSKeyUnavailable)
    assert outcome[0].reason == "the file JWKS location could not be read"


def test_an_unreadable_file_location_is_a_failed_fetch_rather_than_an_oserror(
    settings: SettingsWrapper,
    tmp_path: Path,
) -> None:
    """The store's failure path handles this exactly as it handles an unreachable IdP."""
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = (tmp_path / "never-generated.json").as_uri()

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert refusal.value.reason == "the file JWKS location could not be read"


def test_an_oversize_file_location_is_refused_at_the_same_bound(
    settings: SettingsWrapper,
    tmp_path: Path,
) -> None:
    """The bound is the document's, not the transport's -- both branches answer to it."""
    document = tmp_path / "jwks.json"
    document.write_bytes(b"x" * (jwks_module._MAX_DOCUMENT_BYTES + 1))  # noqa: SLF001 - the bound under test
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = document.as_uri()

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert refusal.value.reason == "the JWKS location answered with a body above the accepted bound"


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(_Answer(["not", "an", "object"]), id="json-that-is-not-an-object"),
        pytest.param(_Answer(None, body=b"<html>gateway timeout</html>"), id="not-json-at-all"),
    ],
)
def test_the_default_fetch_refuses_an_answer_that_is_not_a_json_object(
    settings: SettingsWrapper,
    monkeypatch: pytest.MonkeyPatch,
    answer: _Answer,
) -> None:
    """An HTML error page parsed as a key set would look like a rotation that removed everything.

    Raised as `JWKSKeyUnavailable` rather than as a `RequestException`: this is a
    problem with the *document*, and reporting it through the type that also
    carries "the IdP could not be reached" makes the failure event
    indistinguishable from a connection error for whoever has to act on it.
    """
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_JWKS_URL = ""
    _record(monkeypatch, answer)

    with pytest.raises(JWKSKeyUnavailable) as refusal:
        fetch_jwks_document()

    assert refusal.value.reason == "the JWKS location did not answer with a JSON object"
