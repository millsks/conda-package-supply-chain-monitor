"""The one place this product opens a connection, and what it hands back instead.

`CPM-AD-27`: the transport boundary sits in the collector base, so a collector is
a pure translation from a *recorded* payload to evidence rows and is unit
testable without network access. This module is that boundary's near side --
the `Transport` protocol a collector base is handed, and the one `requests`-backed
implementation of it that this repository ships.

**What a collector never sees.** Not a socket, not a `Session`, not a `Response`,
not a retry policy and not a URL library. `fetch` returns a `Payload`: a frozen
record of what the source said, holding no reference to the connection that
produced it. That is the whole of `CPM-AD-27`'s value -- parse, `not_found`,
`error` and `not_applicable` handling is the majority of this product's
behaviour, and a `Response` in the signature would put every line of it behind
the network and into the integration tier. `ASR-2` is the decision; this is where
it becomes code.

**Every call carries a timeout, and there is no default-less path.** `timeout` is
a required keyword argument to `RequestsTransport.__init__`, is refused when it
is not a positive finite number at or below `MAX_TIMEOUT`, and is applied by
`fetch` to every request the transport issues. It is deliberately *not* a `fetch`
parameter: a per-call timeout is a per-call opportunity to omit one, and
`tests/unit/django_apps/test_collector_base_audit.py` would then have no shape to
sweep for. The collector declares the value as configuration
(`core/collection.py`), and the base builds this transport from it.

**What the timeout is and is not, because `requests` is easy to misread.** The
value is applied per connect and per read phase, not as a cap on the whole call:
a source dripping one byte inside the read timeout holds the connection
indefinitely, and a retried call spends the budget again per attempt. So the
worst case of one `fetch` is roughly `(1 + retries) * 2 * timeout` plus the
backoff schedule -- `worst_case_call_seconds` below computes it, so a collector's
declarations are reconciled against the inherited soft limit by arithmetic rather
than by a reader's head -- and `MAX_TIMEOUT` exists to keep that bounded against
the inherited Celery limits (`CPM-AD-9`: a 60-second soft limit and a 5-minute
hard one). A total-call cap is not something `requests` offers, and inventing one
here would mean a thread or a signal in a Celery worker; the bound is stated
instead of pretended.

**Retry with backoff is `urllib3`'s, reached through `requests`' own surface.**
`requests.adapters` re-exports `Retry`, so `HTTPAdapter(max_retries=Retry(...))`
mounted on the session brings no new runtime dependency -- `requests` is already
declared in `pixi.toml` and already carries this machinery. `raise_on_status`
stays at its default, which is what makes a retried status that never recovers
arrive as `RetryError` and therefore as `TransportError`, rather than as a
response the caller has to remember to check. A retried status may not be one of
`ABSENT_STATUSES`: an absence is an answer, and retrying it would spend the rate
limit re-asking a question the source has already answered.

**Two answers are not failures, and the difference is the point.** A `404` or a
`410` is the source saying *this does not exist*, which is an observation worth
recording (`not_found`); anything else outside `2xx` is a failed call
(`error`). `CPM-NFR-3` says the system "degrades to stale evidence, never to a
clean result", so the third possibility -- a non-`2xx` response returned as a
payload for a collector to parse -- is closed here rather than left to eight
collectors to each close the same way.

**A `304` is a third answer, and it is the reason this module carries headers at
all.** `CPM-NFR-3`'s fourth clause is caching, and the whole of HTTP caching is
one request header carrying a validator and one response status saying the
validator still holds. So `fetch` takes `headers`, records the `ETag` and
`Last-Modified` a source hands back, and reads `304` as an *answer*: the payload
says `not_modified` and carries no body, because there is no body -- that is the
saving. It is emphatically not a failure and not an absence
(`CPM-AD-5`, `R-01`); `core/collection.py` replays the body it already has
through the collector's ordinary `translate` and writes the same evidence a `200`
would have. The status is refused in `retry_statuses` on the same terms
`ABSENT_STATUSES` are: retrying an answer spends the allowance re-asking a
question the source has answered.

**The body of a `304` is never decoded, and that is a rule rather than an
optimization.** There is no body to decode -- an origin answering `304` sends
none -- so a `_decoded` call on that path would read an empty byte string as
though the source had served one, and a collector would be handed an empty
payload wearing a successful status. Every branch that could reach `_decoded`
therefore sits after the `304` check.

**Headers travel through this seam and are built by nobody else.** `CPM-AD-20`
and `CPM-AD-27` put every external-call rule in the collector base, so a
collector *declares* the `User-Agent` or `Authorization` its source expects and
the base composes the conditional headers on top; this module applies whatever
mapping it is handed to the request and nothing more. There is no per-call
session, no default header set assembled here, and no collector reaching a socket
of its own -- `tests/unit/django_apps/test_collector_base_audit.py` sweeps for
the second module that tries.

**Where a request may be aimed, and where it may be redirected to.** The scheme
is checked against `ALLOWED_SCHEMES` and the locator must name a host, so a
`file://` locator built from configuration cannot read the filesystem through a
seam that exists to read the network. **Redirects are not followed.** This
product fetches from third-party registries, and a redirect is that registry
telling the process to go and fetch something else -- which is how a request
aimed at a package index arrives at RFC1918 space or at `169.254.169.254`. A
`3xx` is therefore neither a success nor an absence and becomes a
`TransportError`; a collector whose source genuinely redirects declares the
redirected locator, which is a decision somebody makes rather than one the
transport takes on their behalf.

**The body is decoded from the charset the source declared, and from UTF-8 when
it declared none.** `requests`' own `.text` falls back to ISO-8859-1 for any
`text/*` response with no charset -- an HTTP/1.1 rule that the web abandoned --
so a UTF-8 body would arrive mojibake'd into an append-only row that by design
can never be corrected. A body that will not decode is a `TransportError`, not a
best-effort string: `errors="replace"` would write the corruption down as though
it were an observation.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

# Imported at run time rather than under `TYPE_CHECKING`, which is what the
# `noqa` is for. `fetch`'s annotations are read back by `get_type_hints` --
# `tests/unit/django_apps/test_transport.py` pins the return type that way,
# because a `fetch` typed to answer a live response would defeat `CPM-AD-27`
# whatever it returned today -- and that call evaluates every annotation in the
# signature against this module's globals. Under `TYPE_CHECKING` the name is
# absent at run time and the pin becomes a `NameError` instead of an assertion.
from collections.abc import Mapping  # noqa: TC003 - see above
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING
from typing import Final
from typing import Protocol
from typing import runtime_checkable
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

# Reached through `requests`' own module rather than through `urllib3` directly,
# and that is the point: `requests.adapters` binds `Retry` at import time and
# `HTTPAdapter(max_retries=Retry(...))` is the recipe both projects document, so
# no undeclared package appears in an import statement here (`pixi.toml` declares
# `requests` and not `urllib3`). The ignore is narrow and is about the stubs
# rather than the runtime: `types-requests` does not list `Retry` in the module's
# re-exports, so mypy refuses the name that the module unambiguously has.
from requests.adapters import Retry  # type: ignore[attr-defined]

if TYPE_CHECKING:
    from collections.abc import Collection

__all__ = [
    "ABSENT_STATUSES",
    "ALLOWED_SCHEMES",
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_ENCODING",
    "DEFAULT_RETRIES",
    "DEFAULT_RETRY_STATUSES",
    "ETAG_HEADER",
    "FOLLOW_REDIRECTS",
    "IF_MODIFIED_SINCE_HEADER",
    "IF_NONE_MATCH_HEADER",
    "LAST_MODIFIED_HEADER",
    "MAX_TIMEOUT",
    "MOUNTED_PREFIXES",
    "NOT_MODIFIED_STATUS",
    "RETRIED_METHODS",
    "Payload",
    "RequestsTransport",
    "Transport",
    "TransportError",
    "worst_case_call_seconds",
]

#: The statuses that mean "the source answered, and the thing is not there".
#:
#: `404` and `410`, and nothing else. They are the two an origin uses to say a
#: resource is absent rather than that the request failed, and `CPM-AD-5` has a
#: separate state for exactly that distinction: `not_found` is an informative
#: negative, while `error` is "looking failed". Folding them together would
#: destroy the difference `CPM-FR-6` exists to preserve.
ABSENT_STATUSES: Final[frozenset[int]] = frozenset({404, 410})

#: The status that means "the source answered, and nothing has changed".
#:
#: `304`, and it is an *answer* rather than a failure or an absence: the
#: validator this process sent still holds, so the source deliberately sent no
#: body. `core/collection.py` replays the body it already has and writes the
#: evidence a `200` would have written (`CPM-AD-5`, `R-01`). It is the whole of
#: `CPM-NFR-3`'s caching clause on the wire, which is why the constant lives
#: beside `ABSENT_STATUSES` rather than inside a branch.
NOT_MODIFIED_STATUS: Final[int] = 304

#: The two validators a source may hand back, and the two conditional headers
#: they are sent in. Named rather than spelled at the call site so the module
#: that composes a conditional request (`core/response_cache.py`) and the module
#: that issues it cannot come to disagree about capitalisation or spelling --
#: HTTP header names are case-insensitive on the wire and are exact dictionary
#: keys here.
ETAG_HEADER: Final[str] = "ETag"
LAST_MODIFIED_HEADER: Final[str] = "Last-Modified"
IF_NONE_MATCH_HEADER: Final[str] = "If-None-Match"
IF_MODIFIED_SINCE_HEADER: Final[str] = "If-Modified-Since"

#: The statuses worth trying again, in the order a reader meets them: rate
#: limiting, then the four gateway and availability faults. Each is a statement
#: about the *moment* rather than about the request, which is what makes a retry
#: meaningful; a `400` or a `403` would answer identically however many times it
#: were asked.
DEFAULT_RETRY_STATUSES: Final[tuple[int, ...]] = (429, 500, 502, 503, 504)

#: How many times a call is retried before it is a failure. Three, so a source
#: having a bad second does not become an `error` row. It is also the number the
#: collector base charges against the rate limit per collection
#: (`core/collection.py`), so raising it costs allowance rather than being free.
DEFAULT_RETRIES: Final[int] = 3

#: `urllib3`'s backoff multiplier. `urllib3` sleeps
#: `backoff_factor * 2 ** (attempt - 1)` before each retry and treats the first
#: retry's delay as zero, so half a second gives 0s, 1s, 2s across three retries.
#: The formula and the series disagree at the first term because `urllib3` says
#: they do; both are written out here because a reader checking one against the
#: other would otherwise conclude that one of them is wrong.
DEFAULT_BACKOFF_FACTOR: Final[float] = 0.5

#: The methods a retry may replay. `GET` only, and narrower than `urllib3`'s own
#: default set on purpose: this transport reads sources, and a retry policy that
#: silently permitted `PUT` or `DELETE` would be a replay of a write nobody asked
#: for. A collector that needs another method is a decision, not a default.
RETRIED_METHODS: Final[frozenset[str]] = frozenset({"GET"})

#: What `HTTPAdapter` is mounted against, which is every scheme the session can
#: reach. Both, so a source served over plain HTTP -- an internal mirror, the
#: local `http.server` the integration tier proves this against -- gets the same
#: retry policy as an HTTPS one rather than silently getting `urllib3`'s default.
#:
#: `NOSONAR` because `python:S5332` reads the `http://` here as a call made over
#: plain HTTP. It is not one: this is the prefix an adapter is *mounted* against,
#: and dropping it would not stop a plain-HTTP call, it would leave that call
#: with no declared retry policy. Which locators may actually be reached is
#: decided by `ALLOWED_SCHEMES` below and enforced in `_check_locator`.
MOUNTED_PREFIXES: Final[tuple[str, ...]] = ("http://", "https://")  # NOSONAR

#: The schemes a locator may name. The same two `MOUNTED_PREFIXES` covers, which
#: is not a coincidence: a scheme with no mounted adapter is a call with no
#: declared retry policy, and `file://`, `ftp://` and `data:` are not the network
#: this seam exists to read.
ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

#: Whether a redirect is followed. `False`, and see the module docstring for why
#: that is a decision rather than an oversight. Named rather than spelled at the
#: call site so the decision is greppable and so the case that asserts it and the
#: code that makes it cannot drift.
FOLLOW_REDIRECTS: Final[bool] = False

#: What a body is decoded as when the source declares no charset. UTF-8, not
#: `requests`' ISO-8859-1 fallback; the module docstring says why.
DEFAULT_ENCODING: Final[str] = "utf-8"

#: The longest timeout a transport may declare, in seconds. Thirty, because the
#: value is spent per connect and per read and again per attempt: at the default
#: three retries the worst case is already `4 * 2 * 30` seconds plus backoff,
#: which is well past the inherited five-minute hard limit (`CPM-AD-9`) and is
#: the point at which a collector should be chunking rather than waiting.
MAX_TIMEOUT: Final[float] = 30.0

#: The header a charset is declared in, and the parameter within it.
CONTENT_TYPE_HEADER: Final[str] = "Content-Type"
CHARSET_PARAMETER: Final[str] = "charset"


def worst_case_call_seconds(*, timeout: float, retries: int, backoff_factor: float = DEFAULT_BACKOFF_FACTOR) -> float:
    """Return the longest one collection's outbound call can take.

    The module docstring states the arithmetic in prose; this is the same
    arithmetic as a function, so the one thing a declared timeout has to be
    checked against -- the inherited Celery soft limit (`CPM-AD-9`) -- is a
    computation a case can make against the settings module's own declared limit
    rather than a sum a reader does in their head. It lives here rather than
    beside the first collector that needed it because every collector needs it
    and no collector may import another (`CPM-AD-7`).

    **It over-reports rather than under-reports, and the direction is the point.**
    `urllib3` caps each backoff at `Retry.DEFAULT_BACKOFF_MAX` (120 seconds), which
    this sum ignores: at the declared factor and retry count the schedule never
    approaches the cap, so ignoring it costs nothing today and keeps the
    arithmetic readable. Should either grow, this answers with a number larger
    than the real worst case -- which fails a reconciliation that would otherwise
    have passed, rather than passing one that should have failed.

    Args:
        timeout: Seconds a single connect or read phase may take. Must be
            positive.
        retries: How many times a failed request is tried again. Must not be
            negative.
        backoff_factor: `urllib3`'s backoff multiplier, in seconds. Must not be
            negative.

    Returns:
        The timeout spent per connect and per read on every attempt, plus
        `urllib3`'s backoff schedule between them. `urllib3` treats the first
        retry's delay as zero and then sleeps `backoff_factor * 2 ** (attempt - 1)`,
        which is why the sum below starts at the second retry -- and is why at
        three retries and half a second the schedule is `0s, 1s, 2s`, the series
        `DEFAULT_BACKOFF_FACTOR`'s comment writes out beside the formula it
        disagrees with at the first term.

    Raises:
        ValueError: When `timeout` is not positive, or when either count is
            negative. Refused rather than answered, because the answer would be
            zero or negative and would satisfy any ceiling it were compared
            against -- a reconciliation that passes because its input was
            nonsense is worse than no reconciliation.

    """
    if timeout <= 0:
        message = f"a call cannot be bounded by a timeout of {timeout!r}; every outbound call carries a positive one"
        raise ValueError(message)
    if retries < 0 or backoff_factor < 0:
        message = (
            f"a retry schedule cannot be built from retries={retries!r} and backoff_factor={backoff_factor!r}; "
            f"neither is a count or a delay."
        )
        raise ValueError(message)
    attempts = 1 + retries
    backoff = 0.0
    for attempt in range(2, retries + 1):
        backoff += backoff_factor * 2 ** (attempt - 1)
    return attempts * 2 * timeout + backoff


class TransportError(Exception):
    """An outbound call did not produce an answer this product can record.

    One type rather than a hierarchy, on the same terms as `core/models.py`'s
    `AppendOnlyError` and `core/runs.py`'s `RunLedgerError`: no caller branches
    on *why* the call failed. The collector base's response is the same for a
    timeout, a refused connection, an exhausted retry, a redirect and an
    undecodable body -- write an evidence row carrying `error` and finalize the
    run `failed` -- so the detail belongs in the message and in the attributes
    rather than in the class.

    It derives from `Exception` and not from `ValueError`, which is deliberate
    and is the line this module draws: a `ValueError` here means a *declaration*
    is unusable and is raised at construction (see `RequestsTransport.__init__`,
    and `core/collection.py`'s `CollectorConfigurationError`), while a
    `TransportError` means the world did not cooperate. A caller catching
    `ValueError` should not thereby catch a source being down.

    Attributes:
        source: What was being fetched, so a failure names it without the reader
            parsing the message.
        status_code: The status the source answered with, where it answered at
            all. `None` for a call that never got a response -- a timeout, a
            refused connection, a DNS failure, a locator this transport refused
            to issue at all.

    """

    def __init__(self, message: str, *, source: str, status_code: int | None = None) -> None:
        """Record the message, what was being fetched, and how it answered.

        Args:
            message: What was attempted and how it failed.
            source: The URL or other locator the transport was reading.
            status_code: The response status, or `None` when there was no
                response at all.

        """
        super().__init__(message)
        self.source = source
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class Payload:
    """What a source said, recorded, with nothing live left in it.

    Frozen and slotted, holding only data: a collector handed one of these can
    be given a literal in a unit test and cannot tell the difference from one a
    real call produced. That equivalence *is* `CPM-AD-27` -- it is what moves
    parsing, `not_found` handling and `error` handling into the fast tier.

    **`found` is the transport's judgement, not the collector's.** The mapping
    from a status to "this does not exist" is one decision and is made in one
    place (`ABSENT_STATUSES`), so eight collectors cannot come to disagree about
    whether a `410` means absent. What a collector decides is what the *body*
    means, which is the only question it is qualified to answer.

    Attributes:
        source: The URL or other locator that was read. Recorded so an evidence
            row can say where the observation came from without the collector
            reconstructing it.
        found: Whether the source says the resource exists. `False` is an
            answer, not a failure: it becomes an evidence row carrying
            `not_found` (`CPM-AD-5`).
        body: The response body as text, decoded from the charset the source
            declared. Empty for an absent resource, whose body is an error page
            nobody should parse.
        status_code: The HTTP status, where the source speaks HTTP. `None` for a
            transport substituted at this seam that does not -- the inventory
            file adapter `CPM-AD-29` describes is the first of those.
        not_modified: Whether the source answered that the validator this
            process sent still holds. `True` means `body` is empty *because
            there was nothing to send*, not because the source served nothing:
            the collector base replays the body it cached and writes the
            evidence a `200` would have. It is a third answer beside `found`,
            never a failure and never an absence.
        etag: The `ETag` the source declared, where it declared one. Recorded so
            the next request for this locator can carry it and be answered
            `304`; `None` where the source offers no entity tag. Read off a
            `304` as well as a `200`, because an origin is entitled to hand back
            a *new* entity tag when it revalidates, and `core/collection.py`
            refreshes the remembered entry with it -- a base that kept the old
            one would go on asking a question the source had already moved past.
        last_modified: The `Last-Modified` the source declared, where it
            declared one. The weaker of the two validators and the fallback when
            there is no `ETag`, kept as the source's own string rather than
            parsed: it is sent back verbatim, and re-formatting a date is how a
            conditional request quietly stops matching. Recorded off a `304` on
            the same terms as `etag`.

    """

    source: str
    found: bool
    body: str
    status_code: int | None = None
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None


@runtime_checkable
class Transport(Protocol):
    """Something that can be asked to read a source and record what it said.

    One method, because one method is the entire dependency. A collector base
    that takes a `Transport` declares that it reads the outside world and
    declares nothing else, and a test supplies a fake returning a literal
    `Payload` without knowing anything about HTTP.

    It is also the substitution seam `CPM-AD-29` needs: the inventory adapter is
    a `Transport` that reads a versioned watchlist file, and the ingestion
    collector is unchanged by which one is active.

    `runtime_checkable` so that a test can assert an implementation satisfies the
    protocol at all. That check sees method *names* only, which is why
    `tests/unit/django_apps/test_transport.py` also pins what `fetch` returns: a
    class whose `fetch` answers a live response passes `isinstance` and defeats
    the entire point of the seam.
    """

    def fetch(self, source: str, *, headers: Mapping[str, str] | None = None) -> Payload:
        """Read one source and record its answer.

        The docstring is the whole body, for the reason `core/clock.py`'s
        `Clock.now` gives: a protocol method is never executed, so an `...` here
        would be a permanently uncovered line and the only way to keep it out of
        the coverage floor would be a `pragma: no cover`, which
        `tests/unit/test_coverage_policy.py` bans outright.

        Args:
            source: The URL, path or other locator to read.
            headers: The request headers to send, composed by the collector base
                from what the collector declared and from the conditional
                request the response cache asks for. Keyword only and defaulted,
                so a substituted transport that speaks no HTTP -- `CPM-AD-29`'s
                inventory file adapter -- can accept and ignore them without the
                seam growing a second method.

        Returns:
            A `Payload` recording what the source said, including the case where
            it said the resource does not exist and the case where it said
            nothing has changed.

        Raises:
            TransportError: When the call produced no answer this product can
                record -- a timeout, a refused connection, an exhausted retry,
                or a status that is neither success, absence nor unchanged.

        """


class RequestsTransport:
    """The one implementation that opens a connection, and the only session here.

    Everything `CPM-NFR-3` asks of an outbound call is applied here and nowhere
    else: the timeout on every request, the retry policy mounted on the adapter,
    the scheme allowlist, the redirect refusal, and the refusal of a status that
    is neither success nor absence.
    `tests/unit/django_apps/test_collector_base_audit.py` sweeps the source tree
    for a second module doing any of it.

    **The session is per instance and is reused across calls.** That is what
    makes the mounted adapter -- and therefore the retry policy -- apply at all:
    a module-level `requests.get` builds a throwaway session with `urllib3`'s
    defaults, which is a call with no declared retry policy wearing the same
    spelling as one that has it. Reuse also keeps the connection pool, which
    matters for a sweep over thousands of packages against one host.

    **It is not thread-shared, and it is closable.** A collector instance owns
    one of these and a Celery worker owns a collector per task, which is the
    arrangement `requests`' own documentation asks for; `close()` releases the
    pool, and `core/collection.py`'s `Collector.close()` calls it for the
    transport it built itself.
    """

    def __init__(
        self,
        *,
        timeout: float,
        retries: int = DEFAULT_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        retry_statuses: Collection[int] = DEFAULT_RETRY_STATUSES,
    ) -> None:
        """Build the session, mount the retry policy, and fix the timeout.

        Args:
            timeout: Seconds any single connect or read phase may take.
                Required and keyword only: there is no default-less path and no
                way to reach this class without stating one. See the module
                docstring for what the value does and does not bound.
            retries: How many times a retryable failure is tried again. Zero is
                permitted and means "try once"; it is a declared decision rather
                than an omission.
            backoff_factor: `urllib3`'s backoff multiplier, in seconds.
            retry_statuses: The statuses a retry is attempted for.

        Raises:
            ValueError: When `timeout` is not a positive finite number at or
                below `MAX_TIMEOUT`, when `retries` is negative, when
                `backoff_factor` is negative, or when `retry_statuses` includes
                a status `ABSENT_STATUSES` has already decided is an answer.
                Refused at construction, so a collector configured with an
                unusable transport fails where it is built rather than in a
                worker halfway through a sweep.

        """
        if not isfinite(timeout) or timeout <= 0:
            message = (
                f"a transport needs a positive finite timeout; {timeout!r} is not one. Every outbound call "
                f"carries a timeout (CPM-NFR-3), and there is no default-less path to this class."
            )
            raise ValueError(message)
        if timeout > MAX_TIMEOUT:
            message = (
                f"a timeout of {timeout!r} seconds is above the {MAX_TIMEOUT} this transport permits. The value "
                f"is spent per connect, per read and again per attempt, so it multiplies against the inherited "
                f"Celery limits (CPM-AD-9); a source this slow wants chunking, not waiting."
            )
            raise ValueError(message)
        if retries < 0:
            message = f"a transport cannot be retried {retries!r} times; use 0 to declare that a call is tried once"
            raise ValueError(message)
        if backoff_factor < 0:
            message = f"a backoff factor is a delay in seconds and cannot be negative; {backoff_factor!r} was given"
            raise ValueError(message)
        retried = tuple(retry_statuses)
        absent_and_retried = sorted(set(retried) & ABSENT_STATUSES)
        if absent_and_retried:
            message = (
                f"{absent_and_retried} cannot be retried: this transport already reads it as the source saying "
                f"the resource does not exist, so retrying spends the rate limit re-asking a question that has "
                f"been answered (CPM-AD-5)."
            )
            raise ValueError(message)
        if NOT_MODIFIED_STATUS in retried:
            message = (
                f"{NOT_MODIFIED_STATUS} cannot be retried: it is the source answering that the validator this "
                f"transport sent still holds, which is an answer and not a fault of the moment. Retrying it "
                f"spends the allowance re-asking a question that has been answered, and caching exists to save "
                f"exactly those requests (CPM-NFR-3)."
            )
            raise ValueError(message)

        self._timeout = timeout
        self._retry = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=retried,
            allowed_methods=RETRIED_METHODS,
        )
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=self._retry)
        for prefix in MOUNTED_PREFIXES:
            self._session.mount(prefix, adapter)

    @property
    def timeout(self) -> float:
        """Return the timeout every request this transport issues carries.

        Returns:
            The seconds fixed at construction. Exposed so that a test, and a
            collector base validating what it was handed, can assert the value
            without reaching into the session.

        """
        return self._timeout

    def fetch(self, source: str, *, headers: Mapping[str, str] | None = None) -> Payload:
        """Read one source, retrying per the mounted policy, and record the answer.

        Args:
            source: The URL to read. Its scheme must be one of
                `ALLOWED_SCHEMES` and it must name a host.
            headers: The request headers to send, or `None` to send only what
                `requests` sends by default. They are applied as given: this
                module composes nothing, because `CPM-AD-20` puts that decision
                in the collector base and one composition point is the whole
                arrangement.

        Returns:
            A `Payload` carrying the decoded body for a successful call,
            `found=False` for a source that answered one of `ABSENT_STATUSES`,
            or `not_modified=True` with no body for a source that answered
            `NOT_MODIFIED_STATUS`.

        Raises:
            TransportError: When the locator is one this transport will not
                issue; when `requests` raised -- a timeout, a refused
                connection, an exhausted retry; when the source redirected; when
                the status is neither a success, an absence nor unchanged; or
                when the body will not decode. Never returns a payload for any
                of them: `CPM-NFR-3` requires degrading to `error`, and a body
                handed to a collector alongside a `500` is exactly the
                clean-looking result it forbids.

        """
        self._require_fetchable(source)
        try:
            response = self._session.get(
                source,
                timeout=self._timeout,
                allow_redirects=FOLLOW_REDIRECTS,
                headers=dict(headers) if headers else None,
            )
        except requests.RequestException as failure:
            message = (
                f"the call to {source} produced no answer after {self._retry.total} retries: "
                f"{type(failure).__name__}: {failure}"
            )
            raise TransportError(message, source=source) from failure

        status: int = response.status_code
        # First, and before anything that could read the body. A `304` carries
        # none -- that saving is the whole point of asking conditionally -- so a
        # decode here would hand a collector an empty string wearing a
        # successful status, which is the clean-looking result `CPM-NFR-3`
        # forbids arriving through the mechanism meant to prevent traffic.
        if status == NOT_MODIFIED_STATUS:
            return Payload(
                source=source,
                found=True,
                body="",
                status_code=status,
                not_modified=True,
                etag=response.headers.get(ETAG_HEADER),
                last_modified=response.headers.get(LAST_MODIFIED_HEADER),
            )
        if status in ABSENT_STATUSES:
            return Payload(source=source, found=False, body="", status_code=status)
        if response.is_redirect or response.is_permanent_redirect:
            message = (
                f"{source} answered {status} redirecting to {response.headers.get('Location')!r}, and this "
                f"transport does not follow redirects. A redirect is the source instructing this process to "
                f"fetch something else, which is how a call aimed at a registry reaches link-local metadata; "
                f"a collector whose source genuinely moves declares the new locator."
            )
            raise TransportError(message, source=source, status_code=status)
        if not response.ok:
            message = (
                f"{source} answered {status}, which is neither a success nor an absence. It is recorded as an "
                f"error rather than parsed: a body read alongside a failing status is how a source that is "
                f"broken comes to look clean (CPM-NFR-3)."
            )
            raise TransportError(message, source=source, status_code=status)
        return Payload(
            source=source,
            found=True,
            body=self._decoded(response),
            status_code=status,
            etag=response.headers.get(ETAG_HEADER),
            last_modified=response.headers.get(LAST_MODIFIED_HEADER),
        )

    def close(self) -> None:
        """Release the session's pooled connections.

        Offered because the session is long-lived by design: a caller that
        builds a transport for one sweep and drops it should be able to say so,
        rather than leaving the pool to a garbage collector whose timing is not
        a contract.
        """
        self._session.close()

    def _require_fetchable(self, source: str) -> None:
        """Refuse a locator this transport will not issue a request at.

        Args:
            source: The locator the caller asked for.

        Raises:
            TransportError: When the scheme is outside `ALLOWED_SCHEMES` or the
                locator names no host. Refused before a request is built, so a
                `file://` locator assembled from configuration cannot read the
                filesystem through a seam that exists to read the network.

        """
        parts = urlsplit(source)
        if parts.scheme not in ALLOWED_SCHEMES or not parts.netloc:
            message = (
                f"{source!r} is not a locator this transport will fetch. The scheme must be one of "
                f"{sorted(ALLOWED_SCHEMES)} and a host must be named; anything else is not the network this "
                f"seam exists to read."
            )
            raise TransportError(message, source=source)

    def _decoded(self, response: requests.Response) -> str:
        """Return the body as text, from the charset the source declared.

        Args:
            response: The successful response.

        Returns:
            The decoded body.

        Raises:
            TransportError: When the declared charset is one Python does not
                know, or when the bytes are not valid in it. Refused rather than
                replaced: `errors="replace"` writes the corruption into an
                append-only row that nothing may ever correct.

        """
        charset = _declared_charset(response.headers)
        try:
            return response.content.decode(charset)
        except (LookupError, UnicodeDecodeError) as undecodable:
            message = (
                f"{response.url} answered a body that will not decode as {charset!r}: "
                f"{type(undecodable).__name__}: {undecodable}. It is recorded as an error rather than decoded "
                f"with replacements, which would write the corruption into an append-only row."
            )
            raise TransportError(
                message,
                source=response.url,
                status_code=response.status_code,
            ) from undecodable


def _declared_charset(headers: Mapping[str, str]) -> str:
    """Return the charset a response declared, or `DEFAULT_ENCODING`.

    Read from the header rather than taken from `Response.encoding`, which is
    the whole point: `requests` fills that in with ISO-8859-1 for any `text/*`
    response carrying no charset, and this product's sources overwhelmingly
    serve UTF-8 JSON without one.

    Args:
        headers: The response headers.

    Returns:
        The declared charset, quotes stripped, or `DEFAULT_ENCODING` when none
        was declared.

    """
    content_type = headers.get(CONTENT_TYPE_HEADER, "")
    for parameter in content_type.split(";")[1:]:
        name, _, value = parameter.strip().partition("=")
        if name.strip().lower() == CHARSET_PARAMETER and value.strip():
            return value.strip().strip('"')
    return DEFAULT_ENCODING
