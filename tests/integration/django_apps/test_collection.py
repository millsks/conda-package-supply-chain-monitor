"""The collector base against real tables, and the transport against a real server.

`tests/unit/django_apps/test_collection.py` proves what the base decides before
it commits to a run -- the six declarations and the window's query. This module
proves what happens once it does, and everything here needs a database by
construction: `collect()` opens `core/ledger.py`'s recorder, whose first act is
to insert a `running` row.

**Every row of the I/O matrix that writes something is here.** A fresh run, a run
inside the window, a forced recollection, a window that ignores another package,
another collector, a failure and a `partial`, a source that is unavailable, a
source that says the resource is absent, a rate limit that is spent, a
translation that raises and one that quietly finds nothing. Each asserts three
things where they apply: what the ledger row says, what evidence exists, and --
for the negative rows -- that the transport was never called. The last is what a
fake transport is for: only it can say it was not asked.

**Two properties here cannot be proved with one package, and both are load
bearing.** `CPM-AD-23`'s per-package transaction is only observable when package
*N*'s write fails and package *N*-1's evidence survives; delete the
`transaction.atomic()` and every single-package case still passes.
`tests/unit/django_apps/test_collector_base_audit.py` holds the structural half
and `test_a_failed_write_for_one_package_leaves_the_earlier_packages_evidence`
holds this one.

**The subclass mistakes that type-check.** A `sentinel_evidence` that ignores the
state it was asked for writes a clean row on every failing path; a `translate`
that ignores the `observed_at` it was handed writes a mis-stamped row into a
table nothing may correct, and `bulk_create` never calls the `save()` that would
have refused it. Both are checked by the base and both are exercised here against
a real table, because a guard on a write is only a guard if the write is real.

**The transport is proved against a local `http.server`.** That is exactly the
division `CPM-AD-27` asks for: parse, `not_found` and `error` handling belong to
the fast tier through a recorded payload, and what remains for the integration
tier is that the recording is faithful -- a real request, over a real socket,
answered by a real server, and turned into the `Payload` the rest of the suite
takes for granted. That includes the retry policy *working*, not merely being
mounted: a path that answers `503` once and then `200` proves recovery, and one
that always answers `503` proves the `RetryError` becomes a `TransportError`. No
HTTP-mocking library arrives to do any of it: `http.server` is in the standard
library, so this costs no dependency (`CPM-EVIDENCE-S05` forbids one).

**The evidence table is built once for the session, outside every test's
transaction**, exactly as `tests/integration/django_apps/test_append_only_evidence.py`
builds its own and for the identical reason: SQLite's schema editor refuses to
open inside a multi-statement transaction, and this suite runs on SQLite locally
and on PostgreSQL in the gate. What rolls back per test is the rows.

Every test here rolls back. `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the database as found; the server fixture shuts its thread
down on the way out.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
import structlog
from django.db import connection

from conda_package_supply_chain_monitor.core import collection
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.collection import COLLECTION_FAILED_EVENT
from conda_package_supply_chain_monitor.core.collection import COLLECTION_REFUSED_EVENT
from conda_package_supply_chain_monitor.core.collection import COLLECTION_SKIPPED_EVENT
from conda_package_supply_chain_monitor.core.collection import EVENT_KEYS
from conda_package_supply_chain_monitor.core.collection import NO_WINDOW
from conda_package_supply_chain_monitor.core.collection import CollectionWriteError
from conda_package_supply_chain_monitor.core.collection import CollectorConfigurationError
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.rate_limit import RateLimit
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.core.transport import RequestsTransport
from conda_package_supply_chain_monitor.core.transport import TransportError
from tests.clocks import FIXED_INSTANT
from tests.collectors import DETERMINATE_VALUE
from tests.collectors import FIXTURE_COLLECTOR
from tests.collectors import FIXTURE_REQUEST_COST
from tests.collectors import FIXTURE_SOURCE_PREFIX
from tests.collectors import FIXTURE_TABLE
from tests.collectors import FIXTURE_TIMEOUT
from tests.collectors import FIXTURE_WINDOW
from tests.collectors import OTHER_FIXTURE_COLLECTOR
from tests.collectors import FixedLimiter
from tests.collectors import RecordedTransport
from tests.collectors import breaking_collector_class
from tests.collectors import cleared_cache
from tests.collectors import collector_class
from tests.collectors import empty_translation_collector_class
from tests.collectors import fixture_evidence_model
from tests.collectors import lying_sentinel_collector_class
from tests.collectors import recorded_payload
from tests.collectors import unstamped_collector_class
from tests.collectors import unwritable_collector_class
from tests.collectors import unwritable_sentinel_collector_class
from tests.collectors import working_collector

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django import DjangoDbBlocker
    from structlog.typing import EventDict

    from conda_package_supply_chain_monitor.core.collection import Collector
    from conda_package_supply_chain_monitor.core.models import AppendOnlyModel

#: The package every case collects. One arbitrary primary key.
A_PACKAGE: Final[int] = 7

#: A second package, for the rows where another package is involved.
ANOTHER_PACKAGE: Final[int] = 8

#: How far inside the window a prior run is placed. Half the declared window, so
#: the case is not sitting on the boundary -- the boundary itself is the unit
#: tier's assertion about `finished_at__gte`.
INSIDE_THE_WINDOW: Final[timedelta] = FIXTURE_WINDOW / 2

#: How far outside it the "window ignores this" cases place theirs.
OUTSIDE_THE_WINDOW: Final[timedelta] = FIXTURE_WINDOW * 2

#: The paths the local server answers, and what each answers with. One per branch
#: of `RequestsTransport.fetch`, plus the two the retry policy needs.
PRESENT_PATH: Final[str] = "/present"
ABSENT_PATH: Final[str] = "/absent"
REFUSED_PATH: Final[str] = "/refused"
MOVED_PATH: Final[str] = "/moved"
UNDECODABLE_PATH: Final[str] = "/undecodable"
FLAKY_PATH: Final[str] = "/flaky"
BROKEN_PATH: Final[str] = "/broken"

#: What the local server says on the success path. Deliberately not ASCII: the
#: encoding decision in `core/transport.py` is only observable on a body whose
#: UTF-8 and ISO-8859-1 readings differ.
SERVED_BODY: Final[str] = '{"maintainer": "Ana Muñoz", "version": "2.4.0"}'

#: Bytes that are valid ISO-8859-1 and are not valid UTF-8, served with no
#: charset declared. `requests`' own `.text` would hand these back as a string of
#: the wrong characters; this transport refuses instead, because the string would
#: land in a row nothing may ever correct.
UNDECODABLE_BODY: Final[bytes] = b"\xff\xfe maintainer"

#: Where a redirect points. Never followed, so nothing serves it.
REDIRECT_TARGET: Final[str] = "http://169.254.169.254/latest/meta-data/"

#: An address nothing listens on, for the case where no answer arrives at all.
#: Port 1 is privileged and unbound, so the connection is refused immediately
#: rather than timing out -- which keeps the case fast and keeps it about the
#: failure rather than about the timeout.
AN_UNREACHABLE_URL: Final[str] = "http://127.0.0.1:1/anything"

#: The transports the server cases build declare no retries unless the case is
#: about retrying. A retried `503` spends the backoff schedule -- three seconds --
#: which is worth paying once, in the two cases that are about it, and nowhere
#: else.
NO_RETRIES: Final[int] = 0

#: How many attempts the two retry cases allow. One retry: enough to prove
#: recovery and exhaustion, and one backoff interval rather than three.
ONE_RETRY: Final[int] = 1

#: The event the capture fixture emits to prove it can see the base's logger.
_CAPTURE_CONTROL: Final[str] = "collection.capture_control"

#: How many attempts the flaky path has seen, so it can fail once and then
#: recover. A module-level counter rather than handler state: the handler class
#: is instantiated per request, so there is nowhere else to keep it.
_flaky_attempts: dict[str, int] = {}


class _Handler(BaseHTTPRequestHandler):
    """The local origin the real calls are made against.

    Six answers, because `fetch` has that many outcomes worth proving over a
    socket. Nothing here is a fixture of the *product*: it stands in for a
    source, and what is under test is what this repository does with what it
    says.
    """

    def do_GET(self) -> None:
        """Answer according to the path, with a body only where there is one."""
        if self.path == FLAKY_PATH:
            seen = _flaky_attempts.get(FLAKY_PATH, 0)
            _flaky_attempts[FLAKY_PATH] = seen + 1
            status = HTTPStatus.OK if seen else HTTPStatus.SERVICE_UNAVAILABLE
        else:
            status = {
                PRESENT_PATH: HTTPStatus.OK,
                ABSENT_PATH: HTTPStatus.NOT_FOUND,
                REFUSED_PATH: HTTPStatus.FORBIDDEN,
                MOVED_PATH: HTTPStatus.FOUND,
                BROKEN_PATH: HTTPStatus.SERVICE_UNAVAILABLE,
                UNDECODABLE_PATH: HTTPStatus.OK,
            }.get(self.path, HTTPStatus.NOT_FOUND)
        if self.path == UNDECODABLE_PATH:
            body = UNDECODABLE_BODY
        else:
            body = SERVED_BODY.encode() if status is HTTPStatus.OK else b""
        self.send_response(status)
        if status is HTTPStatus.FOUND:
            self.send_header("Location", REDIRECT_TARGET)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Say nothing.

        The default writes a line to stderr per request, which would put server
        chatter in the middle of a failure report. Overridden with `*args` so it
        stays compatible whatever signature the base class settles on.

        Args:
            args: The format string and its arguments, discarded.

        """


@pytest.fixture(scope="module")
def served_url() -> Iterator[str]:
    """A local HTTP origin, on a port the operating system chose.

    Port `0` rather than a fixed one: a fixed port is a test that fails on a
    machine where something else is already listening, which is exactly the
    environment-dependent flakiness this suite is written to avoid.

    Module scoped, because standing the server up per case would cost more than
    the cases do and nothing here mutates it beyond the flaky path's counter,
    which the case that uses it resets.

    Yields:
        The base URL, with no trailing slash.

    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def served_transport() -> Iterator[RequestsTransport]:
    """A transport for the server cases, released on the way out.

    Yields rather than returns: a `close()` written after the code under test is
    skipped by any earlier failure, and every case that leaks a session leaks it
    for the whole run.

    Yields:
        A transport that will not retry, which is what keeps the cases that are
        not about retrying fast.

    """
    built = RequestsTransport(timeout=FIXTURE_TIMEOUT, retries=NO_RETRIES)
    try:
        yield built
    finally:
        built.close()


@pytest.fixture(scope="session")
def evidence_table(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[type[AppendOnlyModel]]:
    """The fixture evidence model with a real table behind it.

    Session scoped and built outside every test's transaction, for the reason
    `tests/integration/django_apps/test_append_only_evidence.py`'s equivalent
    records at length: SQLite's schema editor refuses to open inside a
    multi-statement transaction, so creating the table per test would work in the
    gate and fail on every developer machine.

    A stale table is dropped rather than collided with -- `--reuse-db` means a
    run killed between the create and the drop leaves one behind -- and the name
    is declared explicitly so that drop can never land on a table a migration
    built.

    Args:
        django_db_setup: pytest-django's session-scoped database setup, so the
            test database exists before any DDL runs.
        django_db_blocker: The guard that keeps database access out of tests
            which did not ask for it; unblocked around the DDL.

    Yields:
        The model `tests/collectors.py` builds, with its table in place.

    """
    model = fixture_evidence_model()
    with django_db_blocker.unblock():
        if FIXTURE_TABLE in connection.introspection.table_names():
            with connection.schema_editor() as editor:
                editor.delete_model(model)
        with connection.schema_editor() as editor:
            editor.create_model(model)
    try:
        yield model
    finally:
        with django_db_blocker.unblock():
            if FIXTURE_TABLE in connection.introspection.table_names():
                with connection.schema_editor() as editor:
                    editor.delete_model(model)


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    """Leave no rate-limit counter behind, in either direction.

    Autouse, and the body lives in `tests/collectors.py` because the unit tier
    needs the identical guard: two `autouse` fixtures that can drift apart are
    exactly the duplication that module's own docstring argues against.

    Yields:
        Nothing; the fixture is entirely its two side effects.

    """
    with cleared_cache():
        yield


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EventDict]]:
    """Capture what the collector base logs, with the two guards the plain helper lacks.

    The reasoning is `tests/unit/test_health_views.py`'s and
    `tests/unit/test_drain.py`'s and is not restated: the module-scope logger is
    rebound so `capture_logs` binds a fresh proxy inside its own processor chain,
    and a control event proves the capture is live before the case runs, so an
    assertion over an empty list fails here and says why.

    Args:
        monkeypatch: pytest's patcher, which restores the module's own logger.

    Yields:
        The captured events, in order.

    """
    monkeypatch.setattr(collection, "logger", structlog.get_logger(collection.__name__))
    with structlog.testing.capture_logs() as captured:
        collection.logger.info(_CAPTURE_CONTROL)
        assert [event["event"] for event in captured] == [_CAPTURE_CONTROL], (
            "structlog.testing.capture_logs() cannot see core/collection.py's logger, so every "
            "assertion over what it logged would be vacuous"
        )
        captured.clear()
        yield captured


def _clock() -> FixedClock:
    """Return the stopped clock every case injects.

    Returns:
        A clock fixed at `FIXED_INSTANT`.

    """
    return FixedClock(instant=FIXED_INSTANT)


def _collector(transport: RecordedTransport, *, permitted: bool = True) -> Collector:
    """Build the ordinary fixture collector with a decided rate limit.

    Args:
        transport: The scripted transport.
        permitted: What the substituted limiter answers. Substituted in every
            case but the one that is *about* the real limiter, so that no case
            depends on a cache state another case left.

    Returns:
        A constructed collector.

    """
    return working_collector(clock=_clock(), transport=transport, limiter=FixedLimiter(permitted=permitted))


def _record_run(*, collector: str, package_id: int, state: RunState, ago: timedelta) -> CollectionRun:
    """Write a finished ledger row, as a previous run would have left it.

    Args:
        collector: Which collector the run belonged to.
        package_id: Which package it was scoped to.
        state: How it ended.
        ago: How long before `FIXED_INSTANT` it finished.

    Returns:
        The written row.

    """
    return CollectionRun.objects.create(
        collector=collector,
        package_id=package_id,
        started_at=FIXED_INSTANT - ago,
        finished_at=FIXED_INSTANT - ago,
        status=state,
    )


def _rows(model: type[AppendOnlyModel]) -> list[Any]:
    """Return every evidence row written, oldest first.

    Args:
        model: The fixture evidence model.

    Returns:
        The rows, ordered by primary key so a case can read them in the order
        they were inserted.

    """
    return list(model.objects.order_by("pk"))


def _finished_run() -> CollectionRun:
    """Return the one collection-run row this case wrote.

    Returns:
        The row. `get()` rather than `first()`: a case that had somehow produced
        two runs must fail here rather than assert against whichever came back.

    """
    return CollectionRun.objects.get(collector=FIXTURE_COLLECTOR)


@pytest.mark.django_db
def test_a_fresh_run_calls_the_source_and_writes_evidence(evidence_table: type[AppendOnlyModel]) -> None:
    """The ordinary path, and the shape every other case is a departure from.

    One call, one evidence row, and a ledger row that is finalized rather than
    left `running` -- which is the half `EVIDENCE.03-INT-002` is about, asserted
    here through the base that will actually be doing it. The row carries the
    payload's `source`, which is the field that exists so evidence can say where
    an observation came from.
    """
    payload = recorded_payload(body=SERVED_BODY)
    transport = RecordedTransport(payload=payload)

    result = _collector(transport).collect(package_id=A_PACKAGE)

    assert transport.calls == [f"{FIXTURE_SOURCE_PREFIX}{A_PACKAGE}"]
    assert result.state is RunState.SUCCEEDED
    assert result.evidence_rows == 1
    row = _rows(evidence_table)[0]
    assert row.state == DETERMINATE_VALUE
    assert row.body == SERVED_BODY
    assert row.source == payload.source
    assert row.observed_at == FIXED_INSTANT
    run = _finished_run()
    assert run.status == RunState.SUCCEEDED
    assert run.finished_at is not None
    assert run.detail == result.detail == ""


@pytest.mark.django_db
def test_the_limiter_is_asked_about_this_collector_at_this_instant_for_its_whole_budget(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """What the base actually charges, read off the ask rather than assumed.

    Three things could be wrong here and none of them would fail any other case:
    the collector's name, the instant (a wall-clock read would put the window
    somewhere the injected clock does not know about), and the cost. The cost is
    the one `CPM-AD-20` is about -- a limiter consulted once per collection while
    the transport retries underneath it does not bound requests at all.
    """
    limiter = FixedLimiter(permitted=True)
    collector = working_collector(
        clock=_clock(),
        transport=RecordedTransport(payload=recorded_payload()),
        limiter=limiter,
    )

    collector.collect(package_id=A_PACKAGE)

    assert len(limiter.asks) == 1
    name, limit, now, cost = limiter.asks[0]
    assert name == FIXTURE_COLLECTOR
    assert now == FIXED_INSTANT
    assert cost == FIXTURE_REQUEST_COST
    assert limit.calls > 0
    assert evidence_table.objects.count() == 1


@pytest.mark.django_db
def test_a_succeeded_run_inside_the_window_suppresses_the_next(
    evidence_table: type[AppendOnlyModel],
    captured_events: list[EventDict],
) -> None:
    """`CPM-AD-7`'s observation window, and the assertion only a fake can make.

    The ledger row reads `skipped` -- emphatically not a failure -- no evidence
    is written, and the transport was never asked. The third is the one that
    matters: a base that called the source and then discarded the answer would
    satisfy the first two and would still be hammering a rate-limited API.

    The log line is asserted too, because the skip and the refusal below are the
    two facts an operator has to be able to tell apart when asking why a
    collector produced nothing, and an unasserted event name can be swapped for
    the other with the suite green.
    """
    _record_run(collector=FIXTURE_COLLECTOR, package_id=A_PACKAGE, state=RunState.SUCCEEDED, ago=INSIDE_THE_WINDOW)
    transport = RecordedTransport(payload=recorded_payload())

    result = _collector(transport).collect(package_id=A_PACKAGE)

    assert transport.calls == []
    assert result.state is RunState.SKIPPED
    assert result.evidence_rows == 0
    assert evidence_table.objects.count() == 0
    run = CollectionRun.objects.get(collector=FIXTURE_COLLECTOR, status=RunState.SKIPPED)
    assert run.detail == result.detail
    assert [event["event"] for event in captured_events] == [COLLECTION_SKIPPED_EVENT]
    assert captured_events[0]["source"] == f"{FIXTURE_SOURCE_PREFIX}{A_PACKAGE}"


@pytest.mark.django_db
def test_a_forced_recollection_bypasses_the_window(evidence_table: type[AppendOnlyModel]) -> None:
    """`CPM-UJ-1`: a manually triggered recollection always bypasses and always writes.

    Same state as the case above, one argument different. That the two differ by
    exactly one parameter is the point -- a separate entry point for forced
    collection would be a second set of rules, and the window is not the only one
    it would eventually skip.
    """
    _record_run(collector=FIXTURE_COLLECTOR, package_id=A_PACKAGE, state=RunState.SUCCEEDED, ago=INSIDE_THE_WINDOW)
    transport = RecordedTransport(payload=recorded_payload())

    result = _collector(transport).collect(package_id=A_PACKAGE, force=True)

    assert transport.calls != []
    assert result.state is RunState.SUCCEEDED
    assert evidence_table.objects.count() == 1


@pytest.mark.django_db
def test_a_zero_window_never_suppresses_even_at_the_same_instant(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The boundary case a stopped clock makes reachable and a wall clock hides.

    `finished_at__gte` is inclusive, so with `NO_WINDOW` a prior run finishing at
    exactly this instant would suppress -- impossible under `SystemClock` and
    exactly reproducible under the `FixedClock` every case here injects, which is
    the worst combination: a defect that is a property of the test suite. The
    base short-circuits a zero window rather than querying, and this is that
    decision observed.
    """
    _record_run(collector=FIXTURE_COLLECTOR, package_id=A_PACKAGE, state=RunState.SUCCEEDED, ago=NO_WINDOW)
    built = collector_class(declared_model=fixture_evidence_model(), declared_window=NO_WINDOW)
    transport = RecordedTransport(payload=recorded_payload())
    collector = built(clock=_clock(), transport=transport, limiter=FixedLimiter(permitted=True))

    result = collector.collect(package_id=A_PACKAGE)

    assert transport.calls != []
    assert result.state is RunState.SUCCEEDED
    assert evidence_table.objects.count() == 1


@pytest.mark.django_db
def test_a_recent_run_for_another_package_does_not_suppress_this_one(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The window is per package, proved against a row rather than against a `Q`.

    A window that had lost its `package_id` would suppress every package the
    moment any one of them was collected -- and a suite that collected one
    package per case would never notice.
    """
    _record_run(
        collector=FIXTURE_COLLECTOR,
        package_id=ANOTHER_PACKAGE,
        state=RunState.SUCCEEDED,
        ago=INSIDE_THE_WINDOW,
    )
    transport = RecordedTransport(payload=recorded_payload())

    result = _collector(transport).collect(package_id=A_PACKAGE)

    assert result.state is RunState.SUCCEEDED
    assert evidence_table.objects.count() == 1


@pytest.mark.django_db
def test_a_recent_run_for_another_collector_does_not_suppress_this_one(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The window is per collector as well as per package.

    Eight collectors will share this base and the `collection_runs` table. A
    window keyed on the package alone would let the first collector of the day
    silence the other seven.
    """
    _record_run(
        collector=OTHER_FIXTURE_COLLECTOR,
        package_id=A_PACKAGE,
        state=RunState.SUCCEEDED,
        ago=INSIDE_THE_WINDOW,
    )
    transport = RecordedTransport(payload=recorded_payload())

    result = _collector(transport).collect(package_id=A_PACKAGE)

    assert result.state is RunState.SUCCEEDED
    assert evidence_table.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("state", [RunState.FAILED, RunState.PARTIAL], ids=["failed", "partial"])
def test_a_recent_run_that_did_not_succeed_does_not_suppress_the_next_attempt(
    evidence_table: type[AppendOnlyModel],
    state: RunState,
) -> None:
    """Only a `succeeded` run suppresses, and both exclusions matter.

    A window that counted failures would leave a package uncollected for as long
    as its source stayed broken, and the coverage view would show a monitor that
    had stopped looking -- `CPM-SM-C1` arriving through the freshness mechanism
    itself. `partial` is the quieter one: `CPM-AD-23` writes it when a sweep
    committed some packages and not others, so a `partial` run may never have
    observed *this* package at all.
    """
    _record_run(collector=FIXTURE_COLLECTOR, package_id=A_PACKAGE, state=state, ago=INSIDE_THE_WINDOW)
    transport = RecordedTransport(payload=recorded_payload())

    result = _collector(transport).collect(package_id=A_PACKAGE)

    assert result.state is RunState.SUCCEEDED
    assert evidence_table.objects.count() == 1


@pytest.mark.django_db
def test_a_succeeded_run_outside_the_window_does_not_suppress(evidence_table: type[AppendOnlyModel]) -> None:
    """The window has a far edge, and evidence goes stale past it.

    The pair to the suppression case: a base whose window never expired would
    observe each package once and never again, which is the same silence as one
    with no window at all.
    """
    _record_run(collector=FIXTURE_COLLECTOR, package_id=A_PACKAGE, state=RunState.SUCCEEDED, ago=OUTSIDE_THE_WINDOW)
    transport = RecordedTransport(payload=recorded_payload())

    result = _collector(transport).collect(package_id=A_PACKAGE)

    assert result.state is RunState.SUCCEEDED
    assert evidence_table.objects.count() == 1


@pytest.mark.django_db
def test_a_source_that_never_answers_writes_error_evidence(
    evidence_table: type[AppendOnlyModel],
    captured_events: list[EventDict],
) -> None:
    """`CPM-NFR-3` in one case: degrades to `error`, never to a clean result and never to no row.

    Three assertions, and the third is the one the requirement is written in its
    own words about: no row carries the determinate value. A base that wrote
    nothing on failure would leave the package looking exactly like one whose
    source said everything was fine. The ledger's detail and the returned
    result's detail are the same words, which is what `CollectionResult.detail`
    promises.
    """
    transport = RecordedTransport(failure=TransportError("nothing answered", source=FIXTURE_SOURCE_PREFIX))

    result = _collector(transport).collect(package_id=A_PACKAGE)

    assert result.state is RunState.FAILED
    rows = _rows(evidence_table)
    assert [row.state for row in rows] == [OutcomeState.ERROR.value]
    assert DETERMINATE_VALUE not in {row.state for row in rows}
    run = _finished_run()
    assert run.status == RunState.FAILED
    assert run.detail == result.detail
    assert "nothing answered" in run.detail
    assert [event["event"] for event in captured_events] == [COLLECTION_FAILED_EVENT]


@pytest.mark.django_db
def test_a_source_that_says_the_resource_is_absent_writes_not_found(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """ "We looked and it is not there" is an observation, not a failure.

    `CPM-AD-5` keeps `not_found` and `error` separate so a reader is never asked
    to infer which happened, and the ledger row says `succeeded` because the run
    did its work: it asked, and it recorded the answer. The detail is declared to
    the ledger as well as returned, so a `succeeded` row is not silent about
    having found nothing.
    """
    transport = RecordedTransport(payload=recorded_payload(found=False, body=""))

    result = _collector(transport).collect(package_id=A_PACKAGE)

    assert result.state is RunState.SUCCEEDED
    assert [row.state for row in _rows(evidence_table)] == [OutcomeState.NOT_FOUND.value]
    run = _finished_run()
    assert run.status == RunState.SUCCEEDED
    assert run.detail == result.detail
    assert run.detail != ""


@pytest.mark.django_db
def test_a_spent_rate_limit_refuses_the_call_and_still_writes_a_row(
    evidence_table: type[AppendOnlyModel],
    captured_events: list[EventDict],
) -> None:
    """The matrix's rate-limit row: never issued unlimited, and recorded on the ledger.

    The call is not made -- the transport says so -- and the run is not silent
    either: a `failed` ledger row naming the allowance, and an `error` evidence
    row, so the coverage view shows a package the monitor could not look at
    rather than a package that was fine. The refusal is logged under its own
    event, distinct from a failure: the call was never issued, which is a
    different operational fact from a source that answered badly.
    """
    transport = RecordedTransport(payload=recorded_payload())

    result = _collector(transport, permitted=False).collect(package_id=A_PACKAGE)

    assert transport.calls == []
    assert result.state is RunState.FAILED
    assert [row.state for row in _rows(evidence_table)] == [OutcomeState.ERROR.value]
    run = _finished_run()
    assert run.detail == result.detail
    assert "allowance" in run.detail
    assert [event["event"] for event in captured_events] == [COLLECTION_REFUSED_EVENT]
    assert captured_events[0]["cost"] == FIXTURE_REQUEST_COST


@pytest.mark.django_db
def test_the_real_limiter_refuses_the_second_call_within_its_window(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The limiter the base actually builds, exercised end to end rather than substituted.

    Every other case here substitutes the limiter so that no case depends on a
    cache state another left behind. That leaves one thing unproved -- that the
    base consults the real one at all -- and this is it: an allowance of exactly
    one collection's worth of requests, two forced collections, and the second is
    refused. The allowance is derived from the retry budget rather than written
    as `1`, which is also the assertion that the two agree.
    """
    built = collector_class(
        declared_model=fixture_evidence_model(),
        declared_rate_limit=RateLimit(calls=FIXTURE_REQUEST_COST, per=timedelta(minutes=1)),
    )
    transport = RecordedTransport(payload=recorded_payload())
    collector = built(clock=_clock(), transport=transport)

    first = collector.collect(package_id=A_PACKAGE, force=True)
    second = collector.collect(package_id=A_PACKAGE, force=True)

    assert first.state is RunState.SUCCEEDED
    assert second.state is RunState.FAILED
    assert transport.calls == [f"{FIXTURE_SOURCE_PREFIX}{A_PACKAGE}"]
    assert {row.state for row in _rows(evidence_table)} == {DETERMINATE_VALUE, OutcomeState.ERROR.value}


@pytest.mark.django_db
def test_a_translation_that_raises_still_leaves_an_error_row_and_a_finalized_ledger(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The matrix's last row: the row is written, the ledger is final, the exception escapes.

    All three, because dropping any one of them is a plausible implementation.
    Swallowing the exception hides a broken parser; skipping the row leaves the
    package looking clean; and leaving the ledger row `running` is exactly the
    "started and never finished" state `CPM-EVIDENCE-S03` built the recorder to
    make visible -- here it must say `failed`, because it did.
    """
    built = breaking_collector_class(declared_model=fixture_evidence_model())
    transport = RecordedTransport(payload=recorded_payload())
    collector = built(clock=_clock(), transport=transport, limiter=FixedLimiter(permitted=True))

    with pytest.raises(ValueError, match="malformed"):
        collector.collect(package_id=A_PACKAGE)

    assert [row.state for row in _rows(evidence_table)] == [OutcomeState.ERROR.value]
    run = _finished_run()
    assert run.status == RunState.FAILED
    assert run.finished_at is not None
    assert "ValueError" in run.detail


@pytest.mark.django_db
def test_a_translation_that_finds_nothing_is_a_failure_rather_than_a_clean_success(
    evidence_table: type[AppendOnlyModel],
    captured_events: list[EventDict],
) -> None:
    """The silent mismatch, which is the failure this module's own docstring opens by naming.

    A source that changed shape, or a selector that no longer matches, produces
    zero rows and no exception. Left alone that is a `succeeded` run with no
    evidence -- indistinguishable, on every read surface, from a package nothing
    has gone wrong with, which is the `R-01` ambiguity the outcome vocabulary
    exists to remove. So it is a `failed` run carrying an `error` row, and the
    detail says the parser no longer matches its source.
    """
    built = empty_translation_collector_class(declared_model=fixture_evidence_model())
    collector = built(
        clock=_clock(), transport=RecordedTransport(payload=recorded_payload()), limiter=FixedLimiter(permitted=True)
    )

    result = collector.collect(package_id=A_PACKAGE)

    assert result.state is RunState.FAILED
    assert result.evidence_rows == 1
    assert [row.state for row in _rows(evidence_table)] == [OutcomeState.ERROR.value]
    run = _finished_run()
    assert run.detail == result.detail
    assert "no evidence rows" in run.detail
    assert [event["event"] for event in captured_events] == [COLLECTION_FAILED_EVENT]


@pytest.mark.django_db
def test_a_sentinel_that_ignores_the_state_it_was_asked_for_is_refused(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """ "Never a clean result" cannot depend on eight subclasses behaving.

    A `sentinel_evidence` that discarded its argument and wrote the determinate
    value would type-check, would write a row on every failing path so "never no
    row" still held, and would report every unreachable source as a clean
    observation. The base checks the row rather than trusting it -- `CPM-AD-24`
    requires the value to be emitted verbatim, which is exactly what makes the
    check possible -- and nothing is written.
    """
    built = lying_sentinel_collector_class(declared_model=fixture_evidence_model())
    transport = RecordedTransport(failure=TransportError("nothing answered", source=FIXTURE_SOURCE_PREFIX))
    collector = built(clock=_clock(), transport=transport, limiter=FixedLimiter(permitted=True))

    with pytest.raises(CollectorConfigurationError, match="carrying no field with that value"):
        collector.collect(package_id=A_PACKAGE)

    assert evidence_table.objects.count() == 0
    assert _finished_run().status == RunState.FAILED


@pytest.mark.django_db
def test_a_row_stamped_from_anywhere_but_the_run_is_refused(evidence_table: type[AppendOnlyModel]) -> None:
    """The refusal `bulk_create` walks around, restored where the base writes.

    `core/models.py` calls `save()` "the one place every evidence write passes
    through" and refuses a naive `observed_at` there at length -- and
    `bulk_create` does not call `save()`, so every write this base makes would
    have gone around it. The consequence lands far away and cannot be undone:
    a naive instant is stored as if it were UTC, and every freshness comparison
    and observation window is then wrong by the writer's offset, in an
    append-only table nothing may correct.
    """
    built = unstamped_collector_class(declared_model=fixture_evidence_model())
    collector = built(
        clock=_clock(), transport=RecordedTransport(payload=recorded_payload()), limiter=FixedLimiter(permitted=True)
    )

    with pytest.raises(CollectorConfigurationError, match="observed_at it was handed"):
        collector.collect(package_id=A_PACKAGE)

    assert evidence_table.objects.count() == 0


@pytest.mark.django_db
def test_a_failed_write_for_one_package_leaves_the_earlier_packages_evidence(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """`CPM-AD-23`, and the only shape that can show it.

    Every single-package case passes with the `transaction.atomic()` deleted:
    one package still writes its rows, and the property the transaction buys --
    a later package's failure not reaching an earlier package's evidence -- is
    invisible until there are two. So package A is collected normally, package B
    produces a row the schema refuses, and A's evidence is still there
    afterwards. Without the per-package boundary the rollback would reach past B.

    The ledger is checked too: B's run finalizes rather than being left
    `running`, which is what the savepoint rollback makes possible -- an aborted
    connection would take the finalizing write with it.
    """
    working = working_collector(
        clock=_clock(),
        transport=RecordedTransport(payload=recorded_payload()),
        limiter=FixedLimiter(permitted=True),
    )
    working.collect(package_id=A_PACKAGE)

    built = unwritable_collector_class(declared_model=fixture_evidence_model())
    failing = built(
        clock=_clock(), transport=RecordedTransport(payload=recorded_payload()), limiter=FixedLimiter(permitted=True)
    )

    with pytest.raises(Exception, match=r"(?i)not null|integrity|constraint"):
        failing.collect(package_id=ANOTHER_PACKAGE)

    surviving = _rows(evidence_table)
    assert [row.package_id for row in surviving] == [A_PACKAGE]
    assert surviving[0].state == DETERMINATE_VALUE
    assert CollectionRun.objects.filter(package_id=ANOTHER_PACKAGE, status=RunState.FAILED).count() == 1


@pytest.mark.django_db
def test_the_evidence_write_leaves_the_ledger_row_committed(evidence_table: type[AppendOnlyModel]) -> None:
    """The ordering `CPM-EVIDENCE-S03` deferred, observed rather than swept for.

    `tests/unit/django_apps/test_collector_base_audit.py` proves no
    `transaction.atomic()` encloses the recorder, which is the guard that
    survives refactoring. This is the property that guard exists to protect,
    asserted from the outside: after a run, the ledger row and the evidence rows
    are both there, and nothing is left unfinished.

    It cannot assert the *commit* itself: `django_db` wraps the case in a
    transaction, which is precisely why `core/ledger.py` says no runtime guard
    was available and why the audit is a source sweep.
    """
    transport = RecordedTransport(payload=recorded_payload())

    _collector(transport).collect(package_id=A_PACKAGE)

    run = _finished_run()
    assert run.started_at == FIXED_INSTANT
    assert CollectionRun.objects.unfinished().count() == 0
    assert evidence_table.objects.count() == 1


def test_the_transport_records_what_a_real_server_said(
    served_url: str,
    served_transport: RequestsTransport,
) -> None:
    """The one real call, and what `CPM-AD-27` buys with it.

    A real request over a real socket to a real server, turned into the
    `Payload` every other case in this repository hands the base by hand. That
    equivalence is the whole argument for the seam: prove the recording once
    here, and the eight collectors' parsing is unit-testable forever.

    The body is not ASCII, deliberately. `requests`' `.text` would decode a
    `text/*` body with no charset as ISO-8859-1 and hand back mojibake, and the
    row it landed in could never be corrected; the assertion is on the exact
    string the server sent.
    """
    payload = served_transport.fetch(f"{served_url}{PRESENT_PATH}")

    assert payload.found is True
    assert payload.body == SERVED_BODY
    assert payload.status_code == HTTPStatus.OK
    assert payload.source == f"{served_url}{PRESENT_PATH}"


def test_the_transport_reports_an_absent_resource_as_an_answer(
    served_url: str,
    served_transport: RequestsTransport,
) -> None:
    """A `404` is the source saying the thing is not there, and is recorded as such.

    Against a real server rather than a constructed payload, because the mapping
    from a status to `found=False` is the one decision `fetch` makes that a fake
    transport can only assume.
    """
    payload = served_transport.fetch(f"{served_url}{ABSENT_PATH}")

    assert payload.found is False
    assert payload.body == ""
    assert payload.status_code == HTTPStatus.NOT_FOUND


def test_the_transport_refuses_to_hand_back_a_body_with_a_failing_status(
    served_url: str,
    served_transport: RequestsTransport,
) -> None:
    """The third outcome, and the one `CPM-NFR-3` is written about.

    A `403` is neither a success nor an absence. Returning its body for a
    collector to parse is how a source that is broken -- or that has started
    refusing this component -- comes to look like a source that answered
    cleanly.
    """
    with pytest.raises(TransportError) as refused:
        served_transport.fetch(f"{served_url}{REFUSED_PATH}")

    assert refused.value.status_code == HTTPStatus.FORBIDDEN
    assert refused.value.source == f"{served_url}{REFUSED_PATH}"


def test_a_redirect_is_recorded_rather_than_followed(
    served_url: str,
    served_transport: RequestsTransport,
) -> None:
    """The source does not get to choose what this process fetches next.

    The `Location` this server sends is `169.254.169.254`, which is not a
    hypothetical: it is the cloud metadata endpoint, and following a redirect
    from a third-party registry is exactly how a request aimed at a package index
    reaches it. The redirect becomes an `error`, and the collector that meets a
    source which has genuinely moved declares the new locator.
    """
    with pytest.raises(TransportError, match="does not follow redirects") as moved:
        served_transport.fetch(f"{served_url}{MOVED_PATH}")

    assert moved.value.status_code == HTTPStatus.FOUND


def test_a_retried_call_recovers_when_the_source_does(served_url: str) -> None:
    """The retry policy doing its job, which nothing else in the suite observes.

    Every other server case declares no retries, and the unit tier can only read
    the policy's declared shape off the adapter. This is the behaviour: the
    server answers `503` once and `200` next, and the call succeeds -- which is
    the whole reason a collector does not become an `error` row for a source
    having a bad second.
    """
    _flaky_attempts.clear()
    transport = RequestsTransport(timeout=FIXTURE_TIMEOUT, retries=ONE_RETRY)

    try:
        payload = transport.fetch(f"{served_url}{FLAKY_PATH}")
    finally:
        transport.close()

    assert payload.found is True
    assert payload.body == SERVED_BODY
    assert _flaky_attempts[FLAKY_PATH] > 1


def test_a_retry_that_never_recovers_becomes_a_transport_error(served_url: str) -> None:
    """The other half: `raise_on_status` left at its default, observed rather than read.

    With it off, an exhausted retry would come back as a *response* and every
    caller would have to remember to check the status -- the "degrades to a clean
    result" `CPM-NFR-3` forbids. Left on, `urllib3` raises, `requests` wraps it,
    and `fetch` turns it into the one type the collector base knows how to
    record.
    """
    transport = RequestsTransport(timeout=FIXTURE_TIMEOUT, retries=ONE_RETRY)

    try:
        with pytest.raises(TransportError, match="produced no answer") as exhausted:
            transport.fetch(f"{served_url}{BROKEN_PATH}")
    finally:
        transport.close()

    assert exhausted.value.status_code is None


def test_a_call_that_gets_no_answer_at_all_becomes_a_transport_error(
    served_transport: RequestsTransport,
) -> None:
    """No server, no response, and still no exception the caller has to know about.

    Every `requests` failure -- a refused connection, a DNS failure, a timeout --
    arrives as one type, because the collector base's response to all of them is
    the same: an evidence row carrying `error` and a `failed` ledger row.
    """
    with pytest.raises(TransportError) as unreachable:
        served_transport.fetch(AN_UNREACHABLE_URL)

    assert unreachable.value.status_code is None
    assert unreachable.value.source == AN_UNREACHABLE_URL


@pytest.mark.django_db
def test_a_write_that_fails_while_recording_a_failure_keeps_the_original_reason(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The ordering hazard, and why the sentinel write is wrapped rather than left bare.

    On a failing path the base already knows *why* -- the source was unreachable
    -- and then writes the row that records it. An exception from that write
    reaches `core/ledger.py`'s recorder and becomes the ledger row's `detail`,
    replacing the reason with a message about the write; a reader is left with
    the epitaph and not the death. The wrapper carries both, in that order, so
    the row says what happened and then says that it could not be recorded.

    This is the same hazard `core/ledger.py` records for its own finalization,
    resolved the same way: never swallowed, and never allowed to displace the
    more useful of the two messages.
    """
    built = unwritable_sentinel_collector_class(declared_model=fixture_evidence_model())
    transport = RecordedTransport(failure=TransportError("nothing answered", source=FIXTURE_SOURCE_PREFIX))
    collector = built(clock=_clock(), transport=transport, limiter=FixedLimiter(permitted=True))

    with pytest.raises(CollectionWriteError) as unwritten:
        collector.collect(package_id=A_PACKAGE)

    assert "nothing answered" in str(unwritten.value)
    assert "could not be written" in str(unwritten.value)
    assert unwritten.value.detail.startswith("TransportError")
    assert evidence_table.objects.count() == 0
    run = _finished_run()
    assert run.status == RunState.FAILED
    assert "nothing answered" in run.detail


@pytest.mark.django_db
def test_every_event_the_base_emits_is_dotted_and_carries_the_same_keys(
    evidence_table: type[AppendOnlyModel],
    captured_events: list[EventDict],
) -> None:
    """The repository's own log shape, applied to the four names this story added.

    `drain.begin`, `health.readiness_refused_draining`,
    `local_dev.seeding_complete`: a dotted prefix is what lets an operator select
    a subsystem's lines without matching prose, and a flat sentence is invisible
    to that query. The shared key set is the other half -- a `detail` that were an
    exception's `"Type: message"` on one path and a sentence on another would be
    two schemas wearing one name.

    Driven through a real run rather than asserted against the constants alone,
    so the keys checked are the keys actually emitted.
    """
    for event in (COLLECTION_SKIPPED_EVENT, COLLECTION_REFUSED_EVENT, COLLECTION_FAILED_EVENT):
        assert event.split(".")[0] == "collection", event

    _record_run(collector=FIXTURE_COLLECTOR, package_id=A_PACKAGE, state=RunState.SUCCEEDED, ago=INSIDE_THE_WINDOW)
    _collector(RecordedTransport(payload=recorded_payload())).collect(package_id=A_PACKAGE)
    _collector(RecordedTransport(payload=recorded_payload()), permitted=False).collect(package_id=ANOTHER_PACKAGE)

    assert [entry["event"] for entry in captured_events] == [COLLECTION_SKIPPED_EVENT, COLLECTION_REFUSED_EVENT]
    for entry in captured_events:
        assert {*EVENT_KEYS, "detail"} <= set(entry), entry
    assert evidence_table.objects.count() == 1


def test_a_body_that_will_not_decode_is_an_error_rather_than_a_string(
    served_url: str,
    served_transport: RequestsTransport,
) -> None:
    """The last thing `requests`' `.text` would have done quietly.

    Its fallback decodes any `text/*` body with no charset as ISO-8859-1, which
    never raises -- every byte sequence is valid in it -- so a body that is not
    what it claims comes back as a perfectly ordinary string of the wrong
    characters. Written into an append-only row that is the end of the matter:
    nothing may update it and nothing may delete it. So the decode is strict and
    a failure is an `error`, which the collector base records as such.
    """
    with pytest.raises(TransportError, match="will not decode") as undecodable:
        served_transport.fetch(f"{served_url}{UNDECODABLE_PATH}")

    assert undecodable.value.status_code == HTTPStatus.OK
