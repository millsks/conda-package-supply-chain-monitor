"""The transport seam's declared shape, proved without opening a connection.

Three claims, and they are the three `CPM-AD-27` and `CPM-NFR-3` rest on.

**A timeout has no default-less path.** `RequestsTransport` takes it as a
required keyword argument and refuses anything that is not a positive finite
number, so there is no way to reach this class without stating one -- which is
what makes `tests/unit/django_apps/test_collector_base_audit.py`'s sweep a
complete story rather than half of one.

**The retry policy is mounted, not merely constructed.** A `Retry` built and left
in a local is a policy that never runs, and the call that carries it looks
identical to the call that does not. So the assertions read the adapter off the
session and check what `urllib3` was actually given, on both schemes.

**A payload is a record.** `fetch` is annotated to return `Payload`, and `Payload`
is a frozen dataclass of plain data. That is the whole of the seam's value: a
collector handed one cannot tell a literal in a unit test from a real answer, so
parse, `not_found` and `error` handling stay in this tier instead of behind the
network. `tests/integration/django_apps/test_collection.py` proves the transport
itself, once, against a local `http.server`, which is exactly the division
`CPM-AD-27` asks for.

No network is opened here. `requests.Session()` builds a connection pool and
contacts nothing; every case that would make a call lives in the integration
tier.
"""

from __future__ import annotations

import dataclasses
from http import HTTPStatus
from math import inf
from math import nan
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from typing import get_type_hints

import pytest
import requests

from conda_package_supply_chain_monitor.core.transport import ABSENT_STATUSES
from conda_package_supply_chain_monitor.core.transport import ALLOWED_SCHEMES
from conda_package_supply_chain_monitor.core.transport import DEFAULT_BACKOFF_FACTOR
from conda_package_supply_chain_monitor.core.transport import DEFAULT_ENCODING
from conda_package_supply_chain_monitor.core.transport import DEFAULT_RETRIES
from conda_package_supply_chain_monitor.core.transport import DEFAULT_RETRY_STATUSES
from conda_package_supply_chain_monitor.core.transport import FOLLOW_REDIRECTS
from conda_package_supply_chain_monitor.core.transport import MAX_TIMEOUT
from conda_package_supply_chain_monitor.core.transport import MOUNTED_PREFIXES
from conda_package_supply_chain_monitor.core.transport import NOT_MODIFIED_STATUS
from conda_package_supply_chain_monitor.core.transport import RETRIED_METHODS
from conda_package_supply_chain_monitor.core.transport import Payload
from conda_package_supply_chain_monitor.core.transport import RequestsTransport
from conda_package_supply_chain_monitor.core.transport import Transport
from conda_package_supply_chain_monitor.core.transport import TransportError
from conda_package_supply_chain_monitor.core.transport import _declared_charset

if TYPE_CHECKING:
    from collections.abc import Iterator

    from requests.adapters import Retry

#: An ordinary timeout, in seconds. Any positive finite number would do; naming
#: it keeps the assertions about the *refusals* from also being about the value.
A_TIMEOUT: Final[float] = 7.5

#: A status that is neither a success nor an absence, for the case that asserts
#: `TransportError` carries what it was given.
A_FAILING_STATUS: Final[int] = 503

#: The two statuses that mean "the source answered, and the thing is not there".
NOT_FOUND: Final[int] = 404
GONE: Final[int] = 410

#: A source locator. Unreachable by construction -- `.invalid` is reserved --
#: which is a second guarantee beside "no case here opens a socket".
A_SOURCE: Final[str] = "https://fixture.invalid/packages/1"

#: The two validators, written as a source sends them: an entity tag is quoted
#: and an HTTP date is RFC 7231's format. Asserted verbatim, because a validator
#: this transport re-spelled would stop matching the next time it was sent.
AN_ETAG: Final[str] = '"a1b2c3d4"'
A_DATE: Final[str] = "Wed, 03 Sep 2026 12:00:00 GMT"

#: A declared request header, of the kind conda-forge, PyPI and GitHub all
#: expect and some enforce.
AN_AGENT: Final[str] = "cpm-collector/1.0"

#: Bytes that are valid ISO-8859-1 and are not valid UTF-8. Served with no
#: charset declared, they are what a `304` must never try to read: decoding them
#: raises, so a transport that reached the decoder would turn a perfectly good
#: answer into an `error` row.
UNDECODABLE_BODY: Final[bytes] = b"\xff\xfe maintainer"


@pytest.fixture
def transport() -> Iterator[RequestsTransport]:
    """A transport built with the default retry policy, released afterwards.

    Yields rather than returns: a plain `transport.close()` written after the
    code under test is skipped by any earlier failure, and every case that leaks
    a session leaks it for the whole run. The fixture closes on the way out
    whatever the case did.

    Yields:
        A `RequestsTransport` whose session exists and has contacted nothing.

    """
    built = RequestsTransport(timeout=A_TIMEOUT)
    try:
        yield built
    finally:
        built.close()


def test_a_transport_cannot_be_built_without_a_timeout() -> None:
    """The one call this class does not offer.

    `timeout` is keyword-only and has no default, so omitting it is a
    `TypeError` from the interpreter rather than a transport that quietly
    inherits `requests`' own behaviour -- which is no timeout at all, and a
    worker blocked until something upstream gives up.
    """
    with pytest.raises(TypeError):
        RequestsTransport()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "timeout",
    [0, -1.0, inf, nan],
    ids=["zero", "negative", "infinite", "nan"],
)
def test_a_timeout_that_is_not_a_positive_finite_number_is_refused(timeout: float) -> None:
    """Four values that are spelled like a timeout and are not one.

    Zero and a negative are the obvious pair. `inf` is the interesting one: it
    is a perfectly good float, it compares greater than zero, and handed to
    `requests` it means exactly the unbounded wait the rule exists to forbid --
    so a check written as `timeout > 0` would let through the worst value in the
    set. `nan` compares false against everything, including `<= 0`, so it walks
    past that check as well.
    """
    with pytest.raises(ValueError, match="timeout"):
        RequestsTransport(timeout=timeout)


def test_a_timeout_above_the_declared_ceiling_is_refused() -> None:
    """The value multiplies, and the ceiling is where the multiplication is bounded.

    `requests` applies a scalar timeout per connect *and* per read, and a retry
    spends the budget again per attempt -- so four attempts at two minutes is
    sixteen minutes against an inherited five-minute hard limit (`CPM-AD-9`).
    The ceiling is the point at which the right answer is chunking rather than
    waiting, and refusing here is what makes that a decision somebody takes
    rather than a task the broker kills.
    """
    with pytest.raises(ValueError, match="above the"):
        RequestsTransport(timeout=MAX_TIMEOUT + 1)


def test_the_ceiling_itself_is_accepted() -> None:
    """The boundary belongs to the permitted side, so the bound is exact."""
    at_the_limit = RequestsTransport(timeout=MAX_TIMEOUT)

    assert at_the_limit.timeout == MAX_TIMEOUT
    at_the_limit.close()


def test_retrying_a_status_that_means_absence_is_refused() -> None:
    """`404` is an answer, and asking again spends the allowance re-asking it.

    The two decisions have to agree: `ABSENT_STATUSES` says a `404` means the
    resource does not exist, and a retry policy that replayed it would be the
    transport contradicting itself three times before recording the same answer.
    The default set is asserted disjoint elsewhere; this is the guard for a
    caller who passes their own.
    """
    with pytest.raises(ValueError, match="cannot be retried"):
        RequestsTransport(timeout=A_TIMEOUT, retry_statuses=(*DEFAULT_RETRY_STATUSES, NOT_FOUND))


def test_a_negative_retry_count_is_refused() -> None:
    """Zero means "try once" and is permitted; below zero means nothing."""
    with pytest.raises(ValueError, match="retried"):
        RequestsTransport(timeout=A_TIMEOUT, retries=-1)


def test_a_negative_backoff_factor_is_refused() -> None:
    """A backoff is a delay, and a negative delay is not a shorter one."""
    with pytest.raises(ValueError, match="backoff"):
        RequestsTransport(timeout=A_TIMEOUT, backoff_factor=-1.0)


def test_zero_retries_is_a_declaration_rather_than_an_omission(transport: RequestsTransport) -> None:
    """A collector that wants exactly one attempt says so, and is believed.

    The pair to the refusal above: the guard rejects what cannot be a retry
    count and accepts the value that says "do not retry", so a source that must
    not be replayed is expressible without going around this class.
    """
    once = RequestsTransport(timeout=A_TIMEOUT, retries=0)

    assert _mounted_retry(once).total == 0
    assert _mounted_retry(transport).total == DEFAULT_RETRIES


def test_the_timeout_is_carried_and_readable(transport: RequestsTransport) -> None:
    """The value the collector base declared is the value every call will carry."""
    assert transport.timeout == A_TIMEOUT


@pytest.mark.parametrize("prefix", MOUNTED_PREFIXES, ids=str)
def test_the_retry_policy_is_mounted_on_every_scheme(transport: RequestsTransport, prefix: str) -> None:
    """A policy built and not mounted is a policy that never runs.

    Both schemes, because an internal mirror served over plain HTTP -- and the
    local `http.server` the integration tier proves this against -- would
    otherwise silently get `urllib3`'s defaults while the HTTPS path got the
    declared policy. Two behaviours behind one spelling is exactly what
    `CPM-AD-20` puts these rules in one place to prevent.
    """
    adapter = transport._session.adapters[prefix]  # noqa: SLF001 - the mounted policy is not otherwise observable

    assert adapter.max_retries is not None


def test_the_mounted_policy_declares_the_shape_the_module_names(transport: RequestsTransport) -> None:
    """Retry count, backoff, retried statuses and retried methods, all four.

    `allowed_methods` is the one worth reading twice: `urllib3`'s own default
    includes `PUT` and `DELETE`, so a policy that accepted the default would
    replay writes. This transport reads sources, and the narrowed set says so.
    """
    retry = _mounted_retry(transport)

    assert retry.total == DEFAULT_RETRIES
    assert retry.backoff_factor == DEFAULT_BACKOFF_FACTOR
    assert tuple(retry.status_forcelist) == DEFAULT_RETRY_STATUSES
    assert retry.allowed_methods == RETRIED_METHODS


def test_an_exhausted_retry_reaches_the_caller_as_an_exception(transport: RequestsTransport) -> None:
    """`raise_on_status` stays at `urllib3`'s default, and that is load-bearing.

    With it off, a `503` that never recovered would come back as a *response*,
    and every caller would have to remember to check the status -- which is
    precisely the "degrades to a clean result" `CPM-NFR-3` forbids. Left on, an
    exhausted retry arrives as `RetryError`, which `fetch` turns into
    `TransportError`, which the collector base turns into an evidence row
    carrying `error`.
    """
    assert _mounted_retry(transport).raise_on_status is True


def test_the_two_absent_statuses_are_the_only_ones_that_mean_absence() -> None:
    """`not_found` is an answer; everything else outside `2xx` is a failure.

    `CPM-AD-5` keeps "we looked and it is not there" separate from "looking
    failed", and this set is where that distinction is decided once for all
    eight collectors. A `503` sliding into it would turn a source that is down
    into a source that says the package does not exist -- a clean-looking
    negative, which is the same false-clean family as `R-01`.
    """
    assert {NOT_FOUND, GONE} == ABSENT_STATUSES
    assert A_FAILING_STATUS not in ABSENT_STATUSES


def test_the_retried_statuses_are_all_statements_about_the_moment() -> None:
    """A retry is only meaningful where asking again could answer differently.

    Rate limiting and the gateway faults are transient; a `400` or a `403` would
    answer identically however many times it were asked, and retrying one wastes
    the allowance the rate limiter is guarding.
    """
    assert set(DEFAULT_RETRY_STATUSES) == {429, 500, 502, 503, 504}
    assert not set(DEFAULT_RETRY_STATUSES) & ABSENT_STATUSES


def test_a_payload_is_a_frozen_record_of_plain_data() -> None:
    """The seam's whole value: what a collector receives holds nothing live.

    Frozen, so a translation cannot mutate what it was handed and leave a later
    assertion reading a different payload; plain data, so a case can write one by
    hand and a collector cannot tell it from a real answer.
    """
    payload = Payload(source=A_SOURCE, found=True, body="{}", status_code=200)

    assert dataclasses.is_dataclass(payload)
    assert [field.name for field in dataclasses.fields(payload)] == [
        "source",
        "found",
        "body",
        "status_code",
        "not_modified",
        "etag",
        "last_modified",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        payload.body = "rewritten"  # type: ignore[misc]


def test_a_payload_records_an_ordinary_answer_by_default() -> None:
    """The three caching fields default to "the source said nothing about it".

    Every case written before `CPM-EVIDENCE-S08` builds a `Payload` from four
    arguments, and each of them must still describe an ordinary answer:
    `not_modified` defaulting to anything but `False` would make every one of
    them a replay of a cache entry that does not exist.
    """
    payload = Payload(source=A_SOURCE, found=True, body="{}")

    assert payload.not_modified is False
    assert payload.etag is None
    assert payload.last_modified is None


def test_fetch_is_declared_to_return_a_recorded_payload() -> None:
    """A `Response` in this signature would put the product's behaviour behind the network.

    Read off the annotation rather than off a call, because the claim is about
    the *contract*: a `fetch` that happened to return a `Payload` today while
    being typed to return a response would be one refactor from handing a
    collector a live object, and no test that called it would notice.
    """
    assert get_type_hints(RequestsTransport.fetch)["return"] is Payload
    assert get_type_hints(Transport.fetch)["return"] is Payload


def test_the_requests_transport_satisfies_the_protocol(transport: RequestsTransport) -> None:
    """The seam is a protocol, so a substitution needs no inheritance.

    `CPM-AD-29`'s inventory adapter is the first substitution that will use
    that: a file reader is a `Transport` by shape alone.
    """
    assert isinstance(transport, Transport)


def test_something_without_a_fetch_is_not_a_transport() -> None:
    """The negative control, and the bound of what `runtime_checkable` can see.

    It checks method *names* only, which is why
    `test_fetch_is_declared_to_return_a_recorded_payload` above pins the return
    type separately: a class whose `fetch` answered a live response would pass
    this check and defeat the seam entirely.
    """

    class NotATransport:
        """Something with no way to read a source."""

    assert not isinstance(NotATransport(), Transport)


def test_a_transport_error_carries_what_it_was_given() -> None:
    """A failure names the source and the status without the reader parsing prose."""
    failure = TransportError("it broke", source=A_SOURCE, status_code=A_FAILING_STATUS)
    silent = TransportError("nothing answered", source=A_SOURCE)

    assert failure.source == A_SOURCE
    assert failure.status_code == A_FAILING_STATUS
    assert silent.status_code is None


def test_the_locator_must_name_a_scheme_this_transport_will_open(transport: RequestsTransport) -> None:
    """A seam that exists to read the network must not be a way to read the disk.

    `file:///etc/passwd` is a perfectly well-formed locator, and a collector
    assembling one from configuration would otherwise reach the filesystem
    through the one component whose whole subject is outbound HTTP. Refused
    before a request is built, so nothing is issued at all.
    """
    for locator in ("file:///etc/passwd", "ftp://example.invalid/x", "https:///no-host"):
        with pytest.raises(TransportError, match="not a locator"):
            transport.fetch(locator)


def test_the_permitted_schemes_are_exactly_the_ones_an_adapter_is_mounted_on() -> None:
    """A scheme with no mounted adapter is a call with no declared retry policy.

    The two tables would otherwise be free to drift: adding `ftp` to the
    allowlist without mounting an adapter for it would produce calls that
    silently got `urllib3`'s defaults, which is the exact "two behaviours behind
    one spelling" the mounted-policy cases above exist to prevent.
    """
    assert {prefix.removesuffix("://") for prefix in MOUNTED_PREFIXES} == ALLOWED_SCHEMES


def test_redirects_are_not_followed(transport: RequestsTransport) -> None:
    """The decision, read off the module rather than inferred from a call.

    A redirect is the source instructing this process to fetch something else,
    which is how a request aimed at a package index arrives at RFC1918 space or
    at `169.254.169.254`. `tests/integration/django_apps/test_collection.py`
    proves the behaviour against a real server; this pins that the constant says
    what the behaviour is, so the two cannot drift.
    """
    assert FOLLOW_REDIRECTS is False


def test_a_body_with_no_declared_charset_is_read_as_utf_eight() -> None:
    """`requests`' own fallback would write mojibake into a row nothing can correct.

    Its `.text` decodes any `text/*` response carrying no charset as ISO-8859-1,
    which is an HTTP/1.1 rule the web abandoned -- and the sources this product
    reads serve UTF-8 JSON without one. The consequence lands in an append-only
    table, so the fallback is replaced rather than worked around at each call
    site.
    """
    assert _declared_charset({}) == DEFAULT_ENCODING
    assert _declared_charset({"Content-Type": "application/json"}) == DEFAULT_ENCODING


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/plain; charset=iso-8859-1", "iso-8859-1"),
        ('application/json; charset="utf-16"', "utf-16"),
        ("text/html;charset=Shift_JIS", "Shift_JIS"),
    ],
    ids=["declared", "quoted", "unspaced"],
)
def test_a_declared_charset_is_honoured(content_type: str, expected: str) -> None:
    """A source that says what it is sending is believed.

    Replacing `requests`' fallback must not mean ignoring the header: a source
    genuinely serving ISO-8859-1 and saying so would otherwise be decoded as
    UTF-8 and refused, which trades one corruption for one outage.
    """
    assert _declared_charset({"Content-Type": content_type}) == expected


def test_closing_releases_the_session(monkeypatch: pytest.MonkeyPatch, transport: RequestsTransport) -> None:
    """The session is long-lived by design, so dropping it is something to be able to say.

    Patched on `requests.Session` rather than on the instance, so the case reads
    the same whether or not the transport keeps its session in the attribute this
    module happens to use today.
    """
    closed: list[bool] = []
    monkeypatch.setattr(requests.Session, "close", lambda _self: closed.append(True))

    transport.close()

    assert closed == [True]


def test_retrying_the_not_modified_status_is_refused() -> None:
    """`304` is an answer, exactly as `404` is, and retrying it spends the allowance.

    The whole point of a conditional request is to *save* a request; a retry
    policy that replayed the answer would spend three more asking a question the
    source has already answered, which is caching costing traffic. Refused on
    the same terms and at the same moment as an absent status, because the two
    mistakes are one mistake.
    """
    with pytest.raises(ValueError, match="cannot be retried"):
        RequestsTransport(timeout=A_TIMEOUT, retry_statuses=(*DEFAULT_RETRY_STATUSES, NOT_MODIFIED_STATUS))


def test_the_default_retry_set_contains_no_answer_at_all() -> None:
    """The two refusals above, asserted against the set this module actually ships.

    Each guards a caller who passes their own statuses; this is the check that
    the default set -- the one every collector gets by declaring nothing -- has
    neither an absence nor a confirmation in it.
    """
    assert not set(DEFAULT_RETRY_STATUSES) & (ABSENT_STATUSES | {NOT_MODIFIED_STATUS})


def test_the_declared_headers_reach_the_request_unaltered(
    monkeypatch: pytest.MonkeyPatch,
    transport: RequestsTransport,
) -> None:
    """The base composes headers and this module applies them, adding nothing.

    Read off the call rather than off a socket: what the integration tier proves
    is that a header survives the wire, and what this proves is that the mapping
    the collector base handed over is the mapping `requests` was given. A
    transport that quietly merged a default set of its own would be a second
    composition point, which is exactly what `CPM-AD-20` puts every external-call
    rule in one base to prevent.
    """
    sent = _capture_request(monkeypatch, transport, _answer(HTTPStatus.OK, body=b"{}"))

    transport.fetch(A_SOURCE, headers={"User-Agent": AN_AGENT})

    assert sent[0]["headers"] == {"User-Agent": AN_AGENT}


def test_a_call_with_no_headers_sends_none_rather_than_an_empty_mapping(
    monkeypatch: pytest.MonkeyPatch,
    transport: RequestsTransport,
) -> None:
    """The unconditional call `CPM-EVIDENCE-S05` issued, unchanged by this story.

    `requests` merges a per-request mapping over its session defaults, and an
    empty mapping is not the same instruction as no mapping -- it is the shape
    that would, with one refactor toward `headers.setdefault`, start deleting
    session defaults. The seam widened; the default call did not change.
    """
    sent = _capture_request(monkeypatch, transport, _answer(HTTPStatus.OK, body=b"{}"))

    transport.fetch(A_SOURCE)

    assert sent[0]["headers"] is None


def test_a_not_modified_answer_is_recorded_rather_than_refused(
    monkeypatch: pytest.MonkeyPatch,
    transport: RequestsTransport,
) -> None:
    """`304` is neither a failure nor an absence, and the payload says which it is.

    It is the third answer: the source was asked whether its validator still
    held, and said yes. `found` stays `True` -- the resource exists, that is
    what was confirmed -- and `not_modified` is what tells the collector base to
    replay what it cached rather than to parse an empty body.
    """
    answer = _answer(HTTPStatus.NOT_MODIFIED, headers={"ETag": AN_ETAG, "Last-Modified": A_DATE})
    _capture_request(monkeypatch, transport, answer)

    payload = transport.fetch(A_SOURCE, headers={"If-None-Match": AN_ETAG})

    assert payload.not_modified is True
    assert payload.found is True
    assert payload.body == ""
    assert payload.status_code == NOT_MODIFIED_STATUS
    assert payload.etag == AN_ETAG
    assert payload.last_modified == A_DATE


def test_a_not_modified_body_is_never_decoded(
    monkeypatch: pytest.MonkeyPatch,
    transport: RequestsTransport,
) -> None:
    """The rule stated as the failure it prevents, not as a call that is not made.

    A `304` carries no body -- that saving is the whole point -- so anything in
    the buffer is not an observation. These bytes are undecodable, so a
    transport that read them would raise `TransportError` and the run would
    record an `error` for a source that had answered perfectly. The assertion is
    that it does not: the status is checked before anything can reach `_decoded`.
    """
    answer = _answer(HTTPStatus.NOT_MODIFIED, body=UNDECODABLE_BODY, headers={"ETag": AN_ETAG})
    _capture_request(monkeypatch, transport, answer)

    payload = transport.fetch(A_SOURCE)

    assert payload.body == ""


def test_a_successful_answer_records_the_validators_the_source_declared(
    monkeypatch: pytest.MonkeyPatch,
    transport: RequestsTransport,
) -> None:
    """Captured on the `200`, because that is the only moment they are offered.

    A validator recorded nowhere is a conditional request that can never be
    made, so caching would be built and would save nothing: every run would
    fetch a whole body and every source would answer `200` forever.
    """
    answer = _answer(HTTPStatus.OK, body=b"{}", headers={"ETag": AN_ETAG, "Last-Modified": A_DATE})
    _capture_request(monkeypatch, transport, answer)

    payload = transport.fetch(A_SOURCE)

    assert payload.etag == AN_ETAG
    assert payload.last_modified == A_DATE


def test_a_source_that_offers_no_validator_records_none(
    monkeypatch: pytest.MonkeyPatch,
    transport: RequestsTransport,
) -> None:
    """Absent is `None`, not an empty string, and the difference decides a write.

    `core/response_cache.py` refuses an entry carrying no validator, and it
    tells the two apart by truthiness -- so a transport that recorded `""` for a
    header the source never sent would be handing the cache something that looks
    like a validator and would produce conditional requests carrying nothing.
    """
    _capture_request(monkeypatch, transport, _answer(HTTPStatus.OK, body=b"{}"))

    payload = transport.fetch(A_SOURCE)

    assert payload.etag is None
    assert payload.last_modified is None


def _answer(
    status: HTTPStatus,
    *,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """Build the response a patched session hands back.

    A real `requests.Response` rather than a stub: `fetch` reads `is_redirect`,
    `ok` and `headers` off it, and a stub that answered those three would be a
    second implementation of the class under test.

    Args:
        status: The status the source answered with.
        body: The bytes in the buffer, which for a `304` is what must never be
            read.
        headers: The response headers.

    Returns:
        A response carrying exactly that, with no connection behind it.

    """
    answered = requests.Response()
    answered.status_code = int(status)
    answered.url = A_SOURCE
    answered.headers.update(headers or {})
    answered._content = body  # noqa: SLF001 - `requests` offers no public way to build a response
    return answered


def _capture_request(
    monkeypatch: pytest.MonkeyPatch,
    transport: RequestsTransport,
    answer: requests.Response,
) -> list[dict[str, Any]]:
    """Answer this transport's next calls from a literal, recording what was asked.

    No socket is opened: the session's `get` is replaced, which is the same
    substitution the rest of this module makes at the `Transport` seam, one
    layer lower -- here because the subject *is* what this class asks
    `requests` for.

    Args:
        monkeypatch: pytest's patcher, which restores the session afterwards.
        transport: The transport whose session is patched.
        answer: What every call is answered with.

    Returns:
        The keyword arguments of each call, in order.

    """
    sent: list[dict[str, Any]] = []

    def _get(source: str, **kwargs: Any) -> requests.Response:
        sent.append({"source": source, **kwargs})
        return answer

    monkeypatch.setattr(transport._session, "get", _get)  # noqa: SLF001 - the session is the thing being substituted
    return sent


def _mounted_retry(transport: RequestsTransport) -> Retry:
    """Return the retry policy the transport's HTTPS adapter carries.

    Args:
        transport: The transport to read.

    Returns:
        The `Retry` `urllib3` was handed, which is the only place the declared
        policy is observable -- `requests` exposes no accessor for it.

    """
    return transport._session.adapters["https://"].max_retries  # noqa: SLF001 - see the module docstring
