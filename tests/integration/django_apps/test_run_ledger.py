"""`EVIDENCE.03-INT-002`: a run that dies mid-call still leaves a row behind.

What the unit tests cannot show. `tests/unit/django_apps/test_run_ledger.py`
proves the handle's state machine and the models' declared shape, and it proves
them without a database because none of that reaches one. The *ordering* is the
other half, and it is only true if a real table shows it: the row has to be
readable while the run is still in flight, and it has to survive the body
raising.

That is `R-05`, and it is not a foregone conclusion. Evidence is written at the
end of a successful run, so the obvious way to write a ledger row is the same
way -- at which point a worker killed between the outbound call and the insert is
indistinguishable from a run that never started, and "started and never
finished" cannot be asked at all. `CPM-AD-2` therefore fixes the order: insert
`running` *before* the first outbound call, finalize in a `finally`.
`CPM-FR-38` needs the failure visible in the application rather than in logs and
`CPM-FR-39` needs every run traceable to the process that performed it.

**The killed worker is modelled by not finalizing, which is the honest stand-in.**
A test cannot `SIGKILL` its own process and then assert against the database, and
one that spawned a worker to kill would be testing the spawn. What a killed
worker leaves is a row that was inserted and never updated, so that is exactly
what the case below leaves: the recorder is entered, the row is read, and the
assertion is made before the `finally` runs.

**Time comes from a stopped clock and correlation from a real span.**
`FixedClock` (`CPM-AD-26`) is what makes "`finished_at` came from the injected
clock" an assertion rather than a tolerance -- with a wall clock the only
available check is "recent", which passes for a value nothing controls. The
`trace_id` half needs the opposite: a *real* recording span, because the claim is
that the row carries what the platform's own log processor would emit
(`CPM-AD-15`), and a fabricated span context could satisfy both sides of a
comparison this module wrote itself. `recorded_spans` supplies the real one.

Every test here rolls back. `@pytest.mark.django_db` wraps each in a
transaction, which is what leaves the database as found -- and it is also why
`core/ledger.py` records the autocommit constraint in prose rather than guarding
it: pytest runs every case inside exactly the atomic block a caller must not
open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest
import structlog
from django.db import DatabaseError
from opentelemetry import trace

from conda_package_supply_chain_monitor.core import ledger
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.ledger import FINALIZATION_FAILED_EVENT
from conda_package_supply_chain_monitor.core.ledger import collection_run
from conda_package_supply_chain_monitor.core.ledger import policy_run
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.core.runs import RunLedgerError
from conda_package_supply_chain_monitor.core.runs import RunState
from config.observability.logging import add_otel_context
from tests.clocks import FIXED_INSTANT

if TYPE_CHECKING:
    from collections.abc import Iterator

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from structlog.typing import EventDict

#: The collector name the cases record, and the package key a scoped run uses.
#: An integer rather than a relation, because `CPM-AD-3`'s package table does not
#: exist yet -- `core/models.py` records why the column is not a `ForeignKey`.
A_COLLECTOR: Final[str] = "pypi"
A_PACKAGE_ID: Final[int] = 4269

#: The policy version and cut-off a recorded policy run carries. The cut-off is
#: the stopped clock's instant, which is what `CPM-AD-21` makes it in production:
#: the `finished_at` of a completed collection run, not the moment the pass runs.
A_POLICY_VERSION: Final[str] = "licence-2026.09"

#: How many rows two recorded runs must leave behind, named so the assertion
#: reads as a count rather than as a magic number.
TWO_RUNS: Final[int] = 2

#: A falsy package key that is nonetheless a key. `0` is what a guard written as
#: `if package_id:` silently drops, and the column is `PositiveBigIntegerField`,
#: which permits it.
A_FALSY_PACKAGE_ID: Final[int] = 0

#: The event `_capture_control` logs to prove the capture is live before a case
#: asserts over what it caught. `tests/unit/test_drain.py` establishes the
#: pattern and the reason: `capture_logs` binds a proxy into its own processor
#: chain, so a module-scope logger created earlier is invisible to it, and an
#: assertion over an empty list would pass for the wrong reason.
CAPTURE_CONTROL: Final[str] = "run-ledger-capture-control"


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EventDict]]:
    """Capture what `core/ledger.py` logs, with the two guards the plain helper lacks.

    The reasoning is `tests/unit/test_drain.py`'s and is not restated: the
    module-scope logger is rebound so `capture_logs` binds a fresh proxy inside
    its own processor chain, and a control event proves the capture is live
    before the case runs.

    Args:
        monkeypatch: pytest's patcher, which restores the module's own logger.

    Yields:
        The captured events, in order.

    """
    monkeypatch.setattr(ledger, "logger", structlog.get_logger(ledger.__name__))
    with structlog.testing.capture_logs() as captured:
        ledger.logger.warning(CAPTURE_CONTROL)
        assert [event["event"] for event in captured] == [CAPTURE_CONTROL], (
            "structlog.testing.capture_logs() cannot see core.ledger's logger, so every assertion "
            "over what it logged would be vacuous"
        )
        captured.clear()
        yield captured


@pytest.fixture
def failing_finalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the *finalizing* write fail, leaving the opening insert alone.

    The realistic shape of this is a body raising `IntegrityError`, which marks
    the connection for rollback so the finalizing `save()` raises
    `TransactionManagementError`. Reproducing that faithfully would need a real
    constraint violation inside the test's own transaction, which then has to be
    unwound before any assertion can query -- so the failure is injected at the
    second `save()` instead. What is under test is the recorder's handling, and
    that is identical either way.

    Args:
        monkeypatch: pytest's patcher, which puts `save` back.

    """
    original = CollectionRun.save
    calls = {"count": 0}

    def flaky(self: CollectionRun, *args: object, **kwargs: object) -> None:
        calls["count"] += 1
        if calls["count"] > 1:
            message = "current transaction is aborted, commands ignored until end of transaction block"
            raise DatabaseError(message)
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(CollectionRun, "save", flaky)


@pytest.fixture
def stopped_clock() -> FixedClock:
    """A clock stopped at `tests.clocks.FIXED_INSTANT`.

    The unit suite's `fixed_clock` fixture is deliberately not shared here --
    `tests/unit/conftest.py` says why: time is a *parameter*, and an integration
    case constructs its clock and passes it exactly as production code does.
    This fixture exists only so that every case in this module stops at the same
    instant, which is what makes two failures comparable.

    Returns:
        A `FixedClock` every reader handed it observes the same instant from.

    """
    return FixedClock(instant=FIXED_INSTANT)


@pytest.mark.django_db
def test_a_completed_run_is_finalized_from_the_injected_clock(stopped_clock: FixedClock) -> None:
    """The ordinary path: entered `running`, left `succeeded`, both instants the clock's.

    `finished_at` equals `started_at` here because one stopped clock answers both
    calls, and that is the point rather than an artefact: a `finished_at` taken
    from the wall clock would differ from `FIXED_INSTANT` by however long the
    test took, so this assertion can only pass if the recorder read the clock it
    was handed.
    """
    with collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_PACKAGE_ID):
        pass

    row = CollectionRun.objects.get()

    assert row.status == RunState.SUCCEEDED
    assert row.collector == A_COLLECTOR
    assert row.package_id == A_PACKAGE_ID
    assert row.started_at == FIXED_INSTANT
    assert row.finished_at == FIXED_INSTANT
    assert row.detail == ""


@pytest.mark.django_db
def test_the_row_is_running_and_readable_before_the_run_finishes(stopped_clock: FixedClock) -> None:
    """The ordering guarantee, and the closest a test gets to a killed worker.

    Read from the database rather than off the in-memory instance: the claim is
    that the row is *committed to the table* before the outbound call, so an
    assertion against the object the recorder is holding would pass even if
    nothing had been written.

    What a killed worker leaves is exactly this state -- inserted, never
    finalized -- and `unfinished()` is what makes it answerable.
    """
    with collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_PACKAGE_ID):
        in_flight = CollectionRun.objects.get()

        assert in_flight.status == RunState.RUNNING
        assert in_flight.finished_at is None
        assert list(CollectionRun.objects.unfinished()) == [in_flight]

    assert list(CollectionRun.objects.unfinished()) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "raised",
    [
        RuntimeError("the socket closed mid-call"),
        SystemExit("the worker was asked to stop"),
        TimeoutError(),
    ],
    ids=["exception", "base-exception", "no-message"],
)
def test_a_raising_body_finalizes_the_row_and_re_raises_unchanged(
    stopped_clock: FixedClock,
    raised: BaseException,
) -> None:
    """`EVIDENCE.03-INT-002`, both halves in one case, across the exception hierarchy.

    The row is never absent: it exists, it says `failed`, its `finished_at` came
    from the injected clock, and its detail carries the exception's type and
    message so a reader is not sent to the logs for the one fact the row could
    have held. `TimeoutError()` is here because `raise TimeoutError` with no
    message is ordinary, and the type is then the only fact there is.

    And the caller still gets *its own* exception -- the identity check is the
    assertion, not the type: a recorder that caught, recorded and re-raised a new
    error of the same class would satisfy `pytest.raises` and lose the traceback,
    the arguments and any exception the caller was matching on. Inherited `CG-3`
    is what forbids swallowing it; this is what proves it was not.

    **`SystemExit` is the case that pins `except BaseException`.** It is not a
    subclass of `Exception`, and neither is Celery's soft-time-limit signal --
    both are how a worker is *asked* to stop, which is the closest thing to the
    killed worker this ledger exists for that leaves an exception behind at all.
    Narrow the catch to `Exception` and this row finalizes `succeeded` with an
    empty detail: a run that died recorded as a run that worked, which is the
    single worst row this table could hold. Without this parameter that narrowing
    passes the entire suite.
    """
    with (
        pytest.raises(type(raised)) as refusal,
        collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_PACKAGE_ID),
    ):
        raise raised

    row = CollectionRun.objects.get()

    assert refusal.value is raised
    assert row.status == RunState.FAILED
    assert row.finished_at == FIXED_INSTANT
    assert row.detail == f"{type(raised).__name__}: {raised}"
    assert row.detail.startswith(f"{type(raised).__name__}:")


@pytest.mark.django_db
def test_an_exception_overrides_an_ending_the_body_had_already_declared(stopped_clock: FixedClock) -> None:
    """The one case where a second state replaces the first rather than being refused.

    A body that declared `partial` and then raised did not complete partially --
    it failed -- so the exception is the more truthful record of what happened.
    Asserted at the recorder rather than on a bare handle, because the override
    is the recorder's to make: `RunHandle._raised` is private precisely so a body
    cannot reach it.
    """
    raised = RuntimeError("the fourth source never answered")

    def declare_partial_then_raise() -> None:
        with collection_run(collector=A_COLLECTOR, clock=stopped_clock) as run:
            run.partial(detail="3 of 5 sources answered")
            raise raised

    with pytest.raises(RuntimeError):
        declare_partial_then_raise()

    row = CollectionRun.objects.get()

    assert row.status == RunState.FAILED
    assert row.detail == "RuntimeError: the fourth source never answered"


@pytest.mark.django_db
def test_declaring_two_endings_inside_a_recorder_finalizes_the_row_as_failed(stopped_clock: FixedClock) -> None:
    """Matrix row 8 at the recorder surface, where the refusal meets the `finally`.

    `RunHandle` refuses the second declaration and raises `RunLedgerError` at the
    call site -- which is what
    `tests/unit/django_apps/test_run_ledger.py` asserts. Inside a recorder that
    refusal is *itself* an exception leaving the body, so it is caught, recorded
    and re-raised like any other: a run whose body genuinely succeeded is written
    down as `failed`, with the refusal in `detail`.

    That is the right outcome and it is not the obvious one, so it is pinned
    here rather than left to be discovered. A contradiction in the recording code
    means the run's own account of itself cannot be trusted, and `failed` with
    the reason attached is the honest row; silently keeping the first declaration
    would write `succeeded` for a run nobody can vouch for.
    """

    def declare_two_endings() -> None:
        with collection_run(collector=A_COLLECTOR, clock=stopped_clock) as run:
            run.succeeded()
            run.failed(detail="on second thoughts")

    with pytest.raises(RunLedgerError, match="already declared succeeded"):
        declare_two_endings()

    row = CollectionRun.objects.get()

    assert row.status == RunState.FAILED
    assert row.detail.startswith("RunLedgerError:")
    assert row.finished_at == FIXED_INSTANT


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("declare", "expected"),
    [("partial", RunState.PARTIAL), ("skipped", RunState.SKIPPED), ("failed", RunState.FAILED)],
    ids=["partial", "skipped", "failed"],
)
def test_a_declared_ending_reaches_the_row_with_its_detail(
    stopped_clock: FixedClock,
    declare: str,
    expected: RunState,
) -> None:
    """The three endings a body declares for itself, each landing in the table.

    `partial` is `CPM-AD-23`'s partial success, `skipped` is `CPM-AD-7`'s
    observation window declining to observe again, and `failed` is a failure the
    body handled rather than raised. None of the three is an exception, so none
    of them would be recorded by a recorder that only watched for one.
    """
    detail = "3 of 5 sources answered"

    with collection_run(collector=A_COLLECTOR, clock=stopped_clock) as run:
        getattr(run, declare)(detail=detail)

    row = CollectionRun.objects.get()

    assert row.status == expected
    assert row.detail == detail
    assert row.finished_at == FIXED_INSTANT


@pytest.mark.django_db
def test_a_run_with_no_package_writes_null_and_stays_answerable(stopped_clock: FixedClock) -> None:
    """The I/O matrix's "Run not package-scoped" row, and AC 5.

    A sweep across the whole inventory is not scoped to one package, so the
    column is NULL -- not `0`, not a sentinel row, and not the first package the
    sweep happened to reach. And the run is still a run: it appears in
    `unfinished()` beside a package-scoped one, because the package column says
    nothing about whether the run finished.
    """
    with collection_run(collector=A_COLLECTOR, clock=stopped_clock):
        unscoped = CollectionRun.objects.get()

        assert unscoped.package_id is None
        assert list(CollectionRun.objects.unfinished()) == [unscoped]

        with collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_PACKAGE_ID):
            unfinished = CollectionRun.objects.unfinished().order_by("pk")

            assert [row.package_id for row in unfinished] == [None, A_PACKAGE_ID]
            assert unfinished.count() == TWO_RUNS


@pytest.mark.django_db
def test_a_falsy_package_key_is_a_key_and_an_absent_one_is_not_refused(stopped_clock: FixedClock) -> None:
    """`0` is a perfectly good primary key, and `None` is a legitimate run.

    The refusal of a negative key is unit-tested; this is the other side of it,
    and the two values that a guard written as `if package_id:` would collapse
    together. `0` must reach the column and `None` must not be refused, because
    an inventory-wide sweep has no package and still has to be recordable.
    """
    with collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_FALSY_PACKAGE_ID):
        pass
    with collection_run(collector=A_COLLECTOR, clock=stopped_clock):
        pass

    assert [row.package_id for row in CollectionRun.objects.order_by("pk")] == [A_FALSY_PACKAGE_ID, None]


@pytest.mark.django_db
def test_unfinished_reads_the_finishing_instant_rather_than_the_status(stopped_clock: FixedClock) -> None:
    """The two spellings are different sets, and only one of them is the question.

    A row the recorder wrote never has a terminal status *and* a NULL
    `finished_at` -- the `finally` writes both together -- so on rows this module
    records the two filters agree, and a `unfinished()` implemented either way
    would pass every other case here. This is the row that tells them apart: it
    is written directly, with a terminal status and no finishing instant, which
    is what a partially-applied write or a later story's backfill would leave.

    `finished_at` is the authority because it is what the `finally` writes; the
    question is "did this run finish", and the status column answers "what did
    the run decide", which is not the same question.
    """
    stranded = CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=stopped_clock.now(),
        status=RunState.FAILED,
        finished_at=None,
    )

    assert list(CollectionRun.objects.unfinished()) == [stranded]
    assert list(CollectionRun.objects.filter(status=RunState.RUNNING)) == []


@pytest.mark.django_db
def test_finalization_writes_only_the_fields_it_names(stopped_clock: FixedClock) -> None:
    """`update_fields` is the narrower write, and the narrowness is load-bearing.

    The recorder holds the instance it inserted, from *before* the run. A full
    `save()` would write every column back from that stale copy, so anything the
    body changed on the row -- a collector correcting its own name, a later
    story's column -- would be silently undone by the act of finalizing, and the
    row would look exactly as though the change had never been made.

    `FINALIZED_FIELDS` carries the argument for this in prose; this is the case
    that makes removing `update_fields=` fail rather than merely contradict a
    comment.
    """
    rewritten = "pypi-mirror"

    with collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_PACKAGE_ID):
        elsewhere = CollectionRun.objects.get()
        elsewhere.collector = rewritten
        elsewhere.save(update_fields=["collector"])

    row = CollectionRun.objects.get()

    assert row.collector == rewritten
    assert row.status == RunState.SUCCEEDED
    assert row.finished_at == FIXED_INSTANT


@pytest.mark.django_db
@pytest.mark.usefixtures("failing_finalization")
def test_a_failing_finalization_is_logged_and_raised_when_nothing_else_is(
    stopped_clock: FixedClock,
    captured_events: list[EventDict],
) -> None:
    """Nothing is swallowed: with no body exception in flight, the failure propagates.

    This is the half that keeps the `DatabaseError` handling from being a
    `try/except/pass` with a comment on it. The run's body returned, so the only
    thing that went wrong is the write -- and a caller told nothing would believe
    a run was recorded that was not.
    """
    with (
        pytest.raises(DatabaseError, match="transaction is aborted"),
        collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_PACKAGE_ID),
    ):
        pass

    assert [event["event"] for event in captured_events] == [FINALIZATION_FAILED_EVENT]
    assert captured_events[0]["run_model"] == "CollectionRun"
    assert captured_events[0]["run_pk"] is not None
    assert captured_events[0]["body_error"] is None


@pytest.mark.django_db
@pytest.mark.usefixtures("failing_finalization")
def test_a_failing_finalization_never_replaces_the_bodys_own_exception(
    stopped_clock: FixedClock,
    captured_events: list[EventDict],
) -> None:
    """The case this module's promise would otherwise be false in.

    An exception raised inside a `finally` *replaces* the one propagating. A body
    raising `IntegrityError` marks the connection for rollback, so the finalizing
    `save()` raises `TransactionManagementError` -- and the caller would then see
    a plumbing error about transaction state instead of the failure that actually
    killed the run, in precisely the mid-call-death case this ledger exists for.

    So the finalization failure is logged, named alongside the body's exception
    so the two are correlatable, and *not* re-raised: the caller keeps its own
    exception, which is the one that says why the run died. Nothing is silent --
    the error is in the log with the row's pk beside it.
    """
    raised = RuntimeError("the socket closed mid-call")

    with (
        pytest.raises(RuntimeError) as refusal,
        collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_PACKAGE_ID),
    ):
        raise raised

    assert refusal.value is raised
    assert [event["event"] for event in captured_events] == [FINALIZATION_FAILED_EVENT]
    assert captured_events[0]["body_error"] == "RuntimeError"
    assert captured_events[0]["run_status"] == RunState.FAILED.value


@pytest.mark.django_db
def test_the_row_carries_the_trace_id_the_platform_would_log(
    stopped_clock: FixedClock,
    recorded_spans: InMemorySpanExporter,
) -> None:
    """AC 2: the row's `trace_id` is the span's own, formatted as `CPM-AD-15` fixes.

    Checked against two independent sources rather than one. The span's context
    is what the row must carry; `add_otel_context` is what
    `config/observability/logging.py` puts on every log line inside that same
    span, and it is the value a person would pivot from. A row agreeing with the
    span but not with the log processor would still be unjoinable, so both are
    asserted.

    `recorded_spans` is requested for what it proves rather than for what it
    returns: it fails the case outright when no SDK provider is installed, which
    is the run in which a fabricated, always-invalid context would make this pass
    by comparing two empty strings. The exported span is read at the end for the
    same reason -- it is what makes "a real recording span" a fact rather than an
    intention.

    The `trace_id` key is asserted present before it is read, because
    `add_otel_context` adds nothing at all when no span is recording: indexing
    straight into the event dict would turn "the platform emitted nothing here"
    into a `KeyError` from the test's own frame rather than the finding it is.

    **The exported spans are checked by membership, never by equality, and the
    difference is a backend difference.** The gate runs on PostgreSQL (`FR-32`)
    where the psycopg instrumentor emits a span per statement, so the ledger's
    own `INSERT` and `UPDATE` are exported alongside `collection`; on the sqlite
    substitution the compatibility matrix runs, nothing instruments the driver
    and `collection` is exported alone. An equality assertion therefore passes
    locally and fails the gate, which is what it did. Membership is also all the
    docstring above claims: that a real recording span was exported.

    Asserting instead that every exported span carries this trace id would be
    wrong rather than merely stricter -- the `CollectionRun.objects.get()` below
    runs *outside* the span, so on PostgreSQL its `SELECT` is a root span with a
    trace id of its own.
    """
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("collection") as span:
        expected = format(span.get_span_context().trace_id, "032x")
        emitted = add_otel_context(structlog.get_logger(__name__), "info", {})
        with collection_run(collector=A_COLLECTOR, clock=stopped_clock, package_id=A_PACKAGE_ID):
            pass

    row = CollectionRun.objects.get()

    assert "trace_id" in emitted, "add_otel_context emitted no trace_id inside a recording span"
    assert row.trace_id == expected
    assert row.trace_id == emitted["trace_id"]
    assert "collection" in [recorded.name for recorded in recorded_spans.get_finished_spans()]


@pytest.mark.django_db
def test_a_run_outside_any_span_is_still_recorded(stopped_clock: FixedClock) -> None:
    """The I/O matrix's "No active span" row: an empty id never blocks the run.

    A collector driven from a management command has no span, and so does a
    process started with the SDK disabled. The run happened either way, and a
    recorder that refused to write without a correlation id would turn a
    telemetry gap into a lost run -- which is the failure this whole story exists
    to prevent, arrived at from the other direction.
    """
    with collection_run(collector=A_COLLECTOR, clock=stopped_clock):
        pass

    row = CollectionRun.objects.get()

    assert row.trace_id == ""
    assert row.status == RunState.SUCCEEDED


@pytest.mark.django_db
def test_a_policy_run_records_its_version_and_its_cut_off(stopped_clock: FixedClock) -> None:
    """The second ledger, on the same seam and in its own table.

    `CPM-AD-2` names `policy_runs` alongside `collection_runs`, and the recorder
    is the same one: a policy pass that dies mid-run is exactly as invisible as a
    collector that does. What differs is what the row carries -- the version of
    the rule data that ran (`CPM-AD-8`) and the cut-off it read evidence at
    (`CPM-AD-21`), which together are what `CPM-FR-22`'s replay needs.
    """
    with policy_run(policy_version=A_POLICY_VERSION, evidence_cutoff=FIXED_INSTANT, clock=stopped_clock):
        assert PolicyRun.objects.get().status == RunState.RUNNING
        assert CollectionRun.objects.count() == 0

    row = PolicyRun.objects.get()

    assert row.policy_version == A_POLICY_VERSION
    assert row.evidence_cutoff == FIXED_INSTANT
    assert row.status == RunState.SUCCEEDED
    assert row.finished_at == FIXED_INSTANT


@pytest.mark.django_db
def test_a_policy_run_that_raises_is_finalized_and_re_raises(stopped_clock: FixedClock) -> None:
    """The same guarantee for the second table, because one recorder serves both.

    Asserted rather than assumed: `_recorded` is shared, but "shared today" is
    not a property a later reader can rely on, and a policy run that failed
    silently would take a whole rollup's provenance with it.
    """
    raised = ValueError("the rule set does not parse")

    with (
        pytest.raises(ValueError, match="does not parse") as refusal,
        policy_run(policy_version=A_POLICY_VERSION, evidence_cutoff=FIXED_INSTANT, clock=stopped_clock),
    ):
        raise raised

    row = PolicyRun.objects.get()

    assert refusal.value is raised
    assert row.status == RunState.FAILED
    assert row.detail == "ValueError: the rule set does not parse"
    assert list(PolicyRun.objects.unfinished()) == []
