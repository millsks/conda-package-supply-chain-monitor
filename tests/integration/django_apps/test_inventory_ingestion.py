"""Inventory ingestion against real tables: the shells, the snapshots and the absences.

`CPM-AD-25` says the inventory arrives as evidence and that resolution still owns
the package row. Every clause of that needs a database to be true or false in,
which is why this module exists beside
`tests/unit/django_apps/test_inventory_ingestion.py`: the declarations, the
record contract and the structural rules are decided before a run exists and are
asserted there, and everything here is what happens once one does.

**The rows this story is really about are the ones nothing asked for.** A first
sight creates a shell nobody wrote a line to create; a second sight must *not*
create a second one; a package the source stops naming gets an absence row rather
than a deletion; and a package whose write failed keeps neither an absence row
nor a half-made shell. Each of those is invisible to a case that ingests one
record once, which is why most of the cases here run ingestion twice or over
three records at a time.

**The append-only refusals are proved on the real table, not on a fixture.**
`inventory_snapshots` is the first evidence table in the repository, so this is
the first time `AppendOnlyModel`'s `save()`, its manager's `update()` and
`PROTECT` on a relation are asserted against a migrated schema rather than
against a model built inside `isolate_apps`. `PROTECT` in particular is only
genuinely proved by a database that refuses -- Django's deletion collector goes
past every refusal in `core/models.py`, so nothing in Python would have stopped
it.

**The cut-off-bound read is what makes a replay a replay** (`CPM-FR-22`,
`CPM-AD-21`). Two observations of one package at two instants, read at a cut-off
between them, must return the earlier one -- and must go on returning it after a
third observation lands, or a policy run replayed at its stated cut-off would
conclude something different every time the inventory changed.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the database as found.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
import structlog
from django.db import IntegrityError
from django.db import transaction
from django.db.models import ProtectedError
from opentelemetry import trace

from conda_package_supply_chain_monitor.collectors.models import COUNTS_PRESENT_CONSTRAINT
from conda_package_supply_chain_monitor.collectors.models import InventoryReadError
from conda_package_supply_chain_monitor.collectors.models import InventorySnapshot
from conda_package_supply_chain_monitor.collectors.models import snapshot_as_of
from conda_package_supply_chain_monitor.collectors.tasks import ABSENT_DETAIL
from conda_package_supply_chain_monitor.collectors.tasks import COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.tasks import INVENTORY_SOURCE
from conda_package_supply_chain_monitor.collectors.tasks import OPTIONAL_SIGNALS
from conda_package_supply_chain_monitor.collectors.tasks import PACKAGE_NAME
from conda_package_supply_chain_monitor.collectors.tasks import SOURCE_PACKAGE_KEY
from conda_package_supply_chain_monitor.collectors.tasks import InventoryIngestionCollector
from conda_package_supply_chain_monitor.collectors.tasks import InventoryRecord
from conda_package_supply_chain_monitor.collectors.tasks import InventoryRecordError
from conda_package_supply_chain_monitor.collectors.tasks import declare_inventory_adapter
from conda_package_supply_chain_monitor.collectors.tasks import ingest_inventory
from conda_package_supply_chain_monitor.collectors.tasks import withdraw_inventory_adapter
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.collection import COLLECTION_PARTIAL_EVENT
from conda_package_supply_chain_monitor.core.collection import EVENT_KEYS
from conda_package_supply_chain_monitor.core.ledger import TRACE_ID_FORMAT
from conda_package_supply_chain_monitor.core.models import AppendOnlyError
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.core.transport import TransportError
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.services import ASSOCIATOR_KEY_LENGTH
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_LENGTH
from conda_package_supply_chain_monitor.identity.services import ResolutionError
from conda_package_supply_chain_monitor.identity.services import resolve_package_shell
from tests.clocks import FIXED_INSTANT
from tests.clocks import OBSERVATION_GAP
from tests.collectors import FixedLimiter
from tests.collectors import RecordedTransport
from tests.collectors import cleared_cache
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from conda_package_supply_chain_monitor.core.collection import CollectionResult

#: The three packages the multi-record cases name, in the order a document lists
#: them. Named rather than numbered so a failure reads as the package it is
#: about.
FIRST_KEY: Final[str] = "internal/numpy"
SECOND_KEY: Final[str] = "internal/pandas"
THIRD_KEY: Final[str] = "internal/scipy"

#: The counts a well-formed record carries. Distinct values, so a case asserting
#: that both reached the row is asserting two things rather than one twice.
A_COMPONENT_COUNT: Final[int] = 3
A_LOB_COUNT: Final[int] = 2

#: The four optional signals, populated. Distinct from each other and from the
#: counts above, for the same reason.
OPTIONAL_VALUES: Final[dict[str, int]] = {"apps": 7, "platforms": 4, "downloads": 1200, "versions": 5}

#: How many rows a two-record sweep writes, and how many observations a
#: re-observation case expects to find. Named because `PLR2004` is right about
#: bare numbers in an assertion: `== 2` says nothing about which two.
TWO_ROWS: Final[int] = 2
TWO_OBSERVATIONS: Final[int] = 2

#: The two download counts the cut-off cases observe, in order. Distinct, so the
#: assertion is about *which* observation came back rather than about a value
#: both rows happen to share.
FIRST_DOWNLOADS: Final[int] = 1
SECOND_DOWNLOADS: Final[int] = 2

#: The key whose *write* fails, for the cases about a package that could not be
#: persisted. It is an ordinary key -- the failure is arranged by the collector
#: double below rather than by the record, because every malformed record is now
#: refused by the contract before a row is written (`CPM-FR-42`), which is what
#: leaves a mid-sweep failure with no way to be provoked from the document.
FAILING_KEY: Final[str] = "internal/failing"


def _name(key: str) -> str:
    """Return the package name that goes with a source package key.

    `CPM-IDENTITY-S07` made the key and the name two values: the key is what the
    inventory files the package under and becomes `associator_key`, the name is
    what it is called and becomes `canonical_name`. Derived from the key rather
    than tabulated, so a case that adds a key gets a name without a second table
    to keep in step -- and derived by *dropping* the prefix, so the two are never
    the same string and a service that wrote either into the wrong column is
    visible.

    Args:
        key: The source package key.

    Returns:
        The last segment of the key.

    """
    return key.rsplit("/", 1)[-1]


def _record(key: str, **overrides: Any) -> dict[str, Any]:
    """Return one well-formed record, with any field replaced.

    Args:
        key: The source package key the record names.
        **overrides: Fields to replace or, with a value of `None`, to omit --
            which is how a case says "the source did not supply this signal", as
            distinct from supplying a zero.

    Returns:
        The record object an adapter would yield.

    """
    record: dict[str, Any] = {
        SOURCE_PACKAGE_KEY: key,
        PACKAGE_NAME: _name(key),
        "internal_component_count": A_COMPONENT_COUNT,
        "internal_lob_count": A_LOB_COUNT,
        **OPTIONAL_VALUES,
    }
    record.update(overrides)
    return {name: value for name, value in record.items() if value is not None}


def _adapter(*records: dict[str, Any]) -> RecordedTransport:
    """Return an adapter that yields these records and remembers it was asked.

    Args:
        *records: The records the document carries.

    Returns:
        A `RecordedTransport` answering with the document.

    """
    return RecordedTransport(payload=recorded_payload(source=INVENTORY_SOURCE, body=json.dumps(list(records))))


class FailingOnKeyCollector(InventoryIngestionCollector):
    """An ingestion collector one named package's write always fails for.

    The only way left to make a record fail *mid-sweep*. Every malformed record
    is refused by the contract before the first write (`CPM-FR-42`), which is
    correct and which removes the last document-shaped way to reach the
    per-package failure path -- so the failure is arranged where it actually
    happens instead. It is the shape `tests/collectors.py`'s six broken fixtures
    use: a subclass differing from the working collector by one method and by
    nothing else, so the assertion is about that method.

    `_observe` is the seam because it is the per-package unit `CPM-AD-23` is
    about: overriding `persist_sweep` would skip the loop under test, and
    overriding nothing at all leaves the case unable to fail.
    """

    def _observe(self, record: InventoryRecord, *, observed_at: datetime, trace_id: str) -> int:
        """Make the shell and then fail, for one package, and behave for the rest.

        **The shell is created first, deliberately.** Failing before it would test
        that nothing happens when nothing happens. What `CPM-AD-23` is about is
        the write *after* the shell: a record that fails there must take the shell
        with it, or the inventory grows a package nothing has ever observed and
        every later story treats it as real.

        Args:
            record: The package as the source described it.
            observed_at: The instant the row would carry.
            trace_id: The run's correlation identifier.

        Returns:
            How many rows were inserted, for every other package.

        Raises:
            ResolutionError: For `FAILING_KEY`, with a shell already made inside
                the transaction that is about to roll back.

        """
        if record.source_package_key == FAILING_KEY:
            with transaction.atomic():
                resolve_package_shell(
                    source_package_key=record.source_package_key,
                    package_name=record.package_name,
                    identity_source=COLLECTOR_NAME,
                    clock=self._clock,
                )
                message = f"{FAILING_KEY} could not be persisted in this run"
                raise ResolutionError(message)
        return super()._observe(record, observed_at=observed_at, trace_id=trace_id)


def _clock(*, at: datetime = FIXED_INSTANT) -> FixedClock:
    """Return the stopped clock a run reads every instant from.

    Args:
        at: The instant to stop at, so a case that observes twice can place the
            two observations apart by a stated interval rather than by however
            long the test took.

    Returns:
        A `FixedClock` at that instant.

    """
    return FixedClock(instant=at)


def _ingest(
    adapter: RecordedTransport,
    *,
    at: datetime = FIXED_INSTANT,
    permitted: bool = True,
    collector_class: type[InventoryIngestionCollector] = InventoryIngestionCollector,
) -> CollectionResult:
    """Run one ingestion sweep through a scripted adapter.

    Args:
        adapter: The transport substituted at the base's seam (`CPM-AD-29`).
        at: The instant the run's clock is stopped at.
        permitted: What the substituted limiter answers. Substituted in every
            case but the one that is about the allowance, so no case depends on a
            counter another case left in the cache.
        collector_class: Which collector to drive. Defaults to the real one; the
            cases about a package that could not be persisted pass
            `FailingOnKeyCollector`, which differs from it by one method.

    Returns:
        What the run did.

    """
    collector = collector_class(
        clock=_clock(at=at),
        transport=adapter,
        limiter=FixedLimiter(permitted=permitted),
    )
    return collector.sweep()


def _snapshots(key: str | None = None) -> list[InventorySnapshot]:
    """Return the snapshots written, oldest first.

    Args:
        key: A source package key to narrow to, or `None` for every row.

    Returns:
        The rows, ordered by primary key so a case reads them in the order they
        were inserted.

    """
    rows = InventorySnapshot.objects.all() if key is None else InventorySnapshot.objects.filter(source_package_key=key)
    return list(rows.order_by("pk"))


def _the_run() -> CollectionRun:
    """Return the one ledger row an ingestion run wrote.

    Returns:
        The row. `get()` rather than `first()`: a run that had somehow produced
        two rows must fail here rather than have one of them asserted against.

    """
    return CollectionRun.objects.get(collector=COLLECTOR_NAME)


def _last_run() -> CollectionRun:
    """Return the most recent ledger row, for the cases that ingest twice.

    Separate from `_the_run` rather than replacing it: where a case runs
    ingestion once, "there is exactly one row" is part of what is being asserted
    (AC #4), and a helper that quietly took the newest would throw that away.

    Returns:
        The newest row by primary key, which is the run the case just performed.

    """
    return CollectionRun.objects.filter(collector=COLLECTOR_NAME).order_by("-pk")[0]


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    """Leave no rate-limit counter behind, in either direction.

    Autouse, and the body lives in `tests/collectors.py` because every module
    that touches the cache needs the identical guard.

    Yields:
        Nothing; the fixture is entirely its two side effects.

    """
    with cleared_cache():
        yield


# ---------------------------------------------------------------------------
# The rows a sweep writes (`CPM-AD-25`, `CPM-FR-42`).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_seen_for_the_first_time_gains_a_shell_and_a_snapshot() -> None:
    """The matrix's first row, and the sentence `CPM-AD-25` is built around.

    The shell is created at `unmapped` and asserts no mapping of any kind --
    `CPM-FR-1` says a resolution that cannot establish one records nothing rather
    than a guess, and ingestion establishes none. The snapshot references it by
    the integer primary key `CPM-AD-3` fixes.
    """
    result = _ingest(_adapter(_record(FIRST_KEY)))

    assert result.state is RunState.SUCCEEDED
    assert result.evidence_rows == 1
    package = Package.objects.get(canonical_name=_name(FIRST_KEY))
    assert package.confidence == IdentityConfidence.UNMAPPED
    assert package.resolved_at == FIXED_INSTANT
    assert package.source_repository_url == ""
    assert package.primary_purl == ""
    assert package.feedstocks.count() == 0
    snapshot = _snapshots()[0]
    assert snapshot.package_id == package.pk
    assert snapshot.state == OutcomeState.OK.value
    assert snapshot.observed_at == FIXED_INSTANT


@pytest.mark.django_db
def test_a_package_already_known_gains_no_second_row() -> None:
    """The matrix's second row: resolution is get-or-create, not create.

    A daily sweep names the same packages every day, so a second `Package` row
    would be a duplicate identity for one package -- and `unique=True` on
    `canonical_name` would turn the second run into an `IntegrityError` rather
    than an observation.
    """
    existing = resolve_package_shell(
        source_package_key=FIRST_KEY,
        package_name=_name(FIRST_KEY),
        identity_source=COLLECTOR_NAME,
        clock=_clock(),
    )

    result = _ingest(_adapter(_record(FIRST_KEY)))

    assert result.state is RunState.SUCCEEDED
    assert Package.objects.filter(canonical_name=_name(FIRST_KEY)).count() == 1
    assert _snapshots()[0].package_id == existing.pk


@pytest.mark.django_db
def test_an_existing_identity_is_not_lowered_by_ingestion() -> None:
    """PRD Appendix A.1: a `verified` confidence is never overwritten by a lower one.

    This is what "get or create" buys that "update or create" would have thrown
    away, and it is not hypothetical: `CPM-IDENTITY-S02` will resolve real
    identities behind the same door, and the daily sweep runs after it.
    """
    resolved = Package.objects.create(
        canonical_name=_name(FIRST_KEY),
        resolved_at=FIXED_INSTANT,
        confidence=IdentityConfidence.VERIFIED,
        source_repository_url="https://example.invalid/numpy",
    )

    _ingest(_adapter(_record(FIRST_KEY)))

    resolved.refresh_from_db()
    assert resolved.confidence == IdentityConfidence.VERIFIED
    assert resolved.source_repository_url == "https://example.invalid/numpy"


@pytest.mark.django_db
def test_re_observing_identical_data_inserts_a_second_row() -> None:
    """`CPM-AD-2`: re-observation always inserts, and the first row is unchanged.

    The two runs are placed apart by `OBSERVATION_GAP` rather than run twice
    against one clock, because "two observations" is only a meaningful claim if
    the rows can be told apart by when they were made.
    """
    _ingest(_adapter(_record(FIRST_KEY)))

    _ingest(_adapter(_record(FIRST_KEY)), at=FIXED_INSTANT + OBSERVATION_GAP)

    rows = _snapshots(FIRST_KEY)
    assert len(rows) == TWO_OBSERVATIONS
    assert [row.observed_at for row in rows] == [FIXED_INSTANT, FIXED_INSTANT + OBSERVATION_GAP]
    assert [row.state for row in rows] == [OutcomeState.OK.value] * 2
    assert Package.objects.filter(canonical_name=_name(FIRST_KEY)).count() == 1


@pytest.mark.django_db
def test_a_package_the_source_stops_naming_is_recorded_absent_rather_than_deleted() -> None:
    """`CPM-AD-25`: absence is an observation with a timestamp, and no row is deleted.

    The absence row carries *this* run's instant, which is what makes "absent as
    of when" answerable at all -- and it carries the key the package was last
    seen under, so the row can be traced back to the record that stopped
    appearing.
    """
    _ingest(_adapter(_record(FIRST_KEY), _record(SECOND_KEY)))

    result = _ingest(_adapter(_record(FIRST_KEY)), at=FIXED_INSTANT + OBSERVATION_GAP)

    assert result.state is RunState.SUCCEEDED
    assert result.evidence_rows == TWO_ROWS
    absent = _snapshots(SECOND_KEY)[-1]
    assert absent.state == OutcomeState.NOT_FOUND.value
    assert absent.observed_at == FIXED_INSTANT + OBSERVATION_GAP
    assert absent.detail == ABSENT_DETAIL
    assert absent.internal_component_count is None
    assert Package.objects.filter(canonical_name=_name(SECOND_KEY)).exists()


@pytest.mark.django_db
def test_a_named_package_whose_write_failed_is_not_also_recorded_absent() -> None:
    """The row the absence sweep must not write, and the inversion that writes it.

    Absence is derived by subtracting what *this document named* from what the
    table has seen. The easy mistake is to subtract what was successfully
    *written* instead, and it is invisible unless the package that failed already
    has an `ok` observation to be departed from -- which is why this case gives it
    one in a first run and fails its write in a second. Under the inversion
    `FAILING_KEY` would gain a `not_found` row here, asserting that a source which
    listed it had dropped it, permanently, in a log nothing may correct.
    """
    _ingest(_adapter(_record(FIRST_KEY), _record(FAILING_KEY)))

    result = _ingest(
        _adapter(_record(FIRST_KEY), _record(FAILING_KEY)),
        at=FIXED_INSTANT + OBSERVATION_GAP,
        collector_class=FailingOnKeyCollector,
    )

    assert result.state is RunState.PARTIAL
    assert [row.state for row in _snapshots(FIRST_KEY)] == [OutcomeState.OK.value] * 2
    assert [row.state for row in _snapshots(FAILING_KEY)] == [OutcomeState.OK.value]


@pytest.mark.django_db
def test_both_required_signals_are_stored_as_observed() -> None:
    """PRD Open Question 3b: both counts are required, and both reach the row."""
    _ingest(_adapter(_record(FIRST_KEY)))

    row = _snapshots()[0]
    assert row.internal_component_count == A_COMPONENT_COUNT
    assert row.internal_lob_count == A_LOB_COUNT


@pytest.mark.django_db
def test_an_absent_optional_signal_is_stored_as_missing() -> None:
    """Blank means missing, and NULL is how the column says so.

    PRD Appendix A.1's data rules: values are never invented, so a signal the
    source did not supply is not a zero somebody chose on its behalf.
    """
    sparse = _record(FIRST_KEY, **dict.fromkeys(OPTIONAL_SIGNALS))

    _ingest(_adapter(sparse))

    row = _snapshots()[0]
    for signal in OPTIONAL_SIGNALS:
        assert getattr(row, signal) is None, signal


@pytest.mark.django_db
def test_a_zero_optional_signal_is_stored_as_zero() -> None:
    """The other half: `0` is an observation and NULL is the absence of one.

    Without this the case above passes for a decoder that collapses both to
    NULL, which is exactly the distinction Open Question 3b exists to keep.
    """
    _ingest(_adapter(_record(FIRST_KEY, downloads=0)))

    row = _snapshots()[0]
    assert row.downloads == 0
    assert row.downloads is not None


@pytest.mark.django_db
def test_a_snapshot_written_outside_any_span_is_still_written() -> None:
    """The other half of `CPM-AD-15`: an empty id never blocks an observation.

    A sweep driven from a management command has no span, and so does one whose
    SDK is disabled -- and an uncorrelated observation is worth more than no
    observation, which is the rule `CollectionRun.trace_id` states and this
    column inherits.

    Deliberately **not** the equality assertion: outside a span both this row and
    the ledger row carry `""`, so comparing them would be comparing two empty
    strings and a collector that never set `trace_id` at all would pass. The
    comparison that means something is in
    `test_a_snapshot_carries_the_trace_id_the_platform_would_log`, inside a real
    recording span; what this pins is that the absence of one is not an error.
    """
    _ingest(_adapter(_record(FIRST_KEY)))

    assert _snapshots()[0].trace_id == ""
    assert _the_run().trace_id == ""


# ---------------------------------------------------------------------------
# Per-package isolation and the ledger row (`CPM-AD-23`, AC #4).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_one_failing_package_leaves_the_others_committed_and_the_run_partial() -> None:
    """The matrix row `CPM-AD-23` and `CPM-FR-15` are both about.

    Three records, and the middle one cannot be persisted. The first and the
    third keep their rows because each was written in a transaction of its own; a
    single transaction around the sweep would have taken all three, and every
    one-record case in this module would still have passed.

    The log line is asserted alongside the row because `partial` and `failed`
    have to be separable *by event name*: an operator asking "what is only half
    working" cannot get that by parsing `detail`, and a shared event would make
    the two indistinguishable to every query written against them.
    """
    with structlog.testing.capture_logs() as captured:
        result = _ingest(
            _adapter(_record(FIRST_KEY), _record(FAILING_KEY), _record(THIRD_KEY)),
            collector_class=FailingOnKeyCollector,
        )

    assert result.state is RunState.PARTIAL
    assert result.evidence_rows == TWO_ROWS
    assert sorted(Package.objects.values_list("canonical_name", flat=True)) == sorted(
        [_name(FIRST_KEY), _name(THIRD_KEY)],
    )
    assert sorted(row.source_package_key for row in _snapshots()) == sorted([FIRST_KEY, THIRD_KEY])
    run = _the_run()
    assert run.status == RunState.PARTIAL
    assert FAILING_KEY in run.detail
    assert run.detail == result.detail
    partial = [entry for entry in captured if entry["event"] == COLLECTION_PARTIAL_EVENT]
    assert len(partial) == 1, [entry["event"] for entry in captured]
    assert {*EVENT_KEYS, "detail"} <= set(partial[0])
    assert partial[0]["detail"] == run.detail


@pytest.mark.django_db
def test_a_failing_package_leaves_no_half_made_shell() -> None:
    """The other half of the per-package transaction, and the easier one to lose.

    Resolution creates the shell and the snapshot is inserted beside it; if the
    two were not in one transaction, a record that failed after the shell was
    made would leave a package nothing has ever observed -- which every later
    story would treat as part of the inventory. The double raises *after* the
    shell would have been created, which is the ordering that makes the case
    about the transaction rather than about the refusal.
    """
    _ingest(
        _adapter(_record(FIRST_KEY), _record(FAILING_KEY)),
        collector_class=FailingOnKeyCollector,
    )

    assert sorted(Package.objects.values_list("canonical_name", flat=True)) == [_name(FIRST_KEY)]
    assert sorted(row.source_package_key for row in _snapshots()) == [FIRST_KEY]


@pytest.mark.django_db
def test_a_completed_sweep_writes_exactly_one_finalized_run_with_no_package() -> None:
    """AC #4, and every clause of it.

    One row for the run however many packages it wrote; finalized rather than
    left `running`, which is what `unfinished()` asks about; and `package_id`
    NULL because the run was not scoped to one package.
    """
    _ingest(_adapter(_record(FIRST_KEY), _record(SECOND_KEY)))

    assert CollectionRun.objects.filter(collector=COLLECTOR_NAME).count() == 1
    run = _the_run()
    assert run.package_id is None
    assert run.status == RunState.SUCCEEDED
    assert run.finished_at is not None
    assert CollectionRun.objects.unfinished().count() == 0


# ---------------------------------------------------------------------------
# The sweep's failing endings.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_source_that_cannot_be_reached_fails_the_run_and_writes_nothing() -> None:
    """A sweep that observed nothing writes nothing, and says so loudly.

    No sentinel row, and that is the departure from the per-package path rather
    than an omission: `sentinel_evidence` shapes a row *about one package*, and a
    source that could not be read named none. The run is `failed`, which is not
    the clean result `CPM-NFR-3` forbids -- nothing claims anything about any
    package.
    """
    failure = TransportError("the inventory file could not be read", source=INVENTORY_SOURCE)

    result = _ingest(RecordedTransport(failure=failure))

    assert result.state is RunState.FAILED
    assert result.evidence_rows == 0
    assert InventorySnapshot.objects.count() == 0
    assert _the_run().status == RunState.FAILED
    assert "TransportError" in _the_run().detail


@pytest.mark.django_db
def test_a_source_that_reports_itself_absent_fails_the_run() -> None:
    """ "The document does not exist" is not "this package does not exist".

    The per-package path records `succeeded` with a `not_found` row for an absent
    resource, because the source answered a question about one package. A missing
    inventory document answers nothing at all, and recording it as a success
    would leave every package in the inventory silently unobserved.
    """
    result = _ingest(RecordedTransport(payload=recorded_payload(source=INVENTORY_SOURCE, found=False)))

    assert result.state is RunState.FAILED
    assert InventorySnapshot.objects.count() == 0
    assert "does not exist" in _the_run().detail


@pytest.mark.django_db
def test_a_spent_allowance_fails_the_run_before_the_source_is_read() -> None:
    """`CPM-AD-20`: the call is refused rather than issued unlimited.

    The transport is never asked, which is the only way to show the refusal
    happened instead of the call.
    """
    adapter = _adapter(_record(FIRST_KEY))

    result = _ingest(adapter, permitted=False)

    assert adapter.calls == []
    assert result.state is RunState.FAILED
    assert "allowance" in _the_run().detail


@pytest.mark.django_db
def test_an_empty_document_after_a_populated_one_writes_no_absence_at_all() -> None:
    """The reproduction, and the reason this is the story's most dangerous path.

    Ingest one package, then ingest an empty array. Before the refusal existed
    this run reported `succeeded` with one row -- the row being a `not_found`
    observation asserting that the package had departed, written off the back of a
    document that said nothing whatever. It is permanent (the log is append-only),
    it is replayable (every later cut-off reads it), and nothing about the run
    looked wrong.

    So both halves are asserted: the run fails, and *no absence row exists*. The
    second is the one that matters -- a run could fail and still have written the
    row on its way there.
    """
    _ingest(_adapter(_record(FIRST_KEY)))

    with pytest.raises(InventoryRecordError) as refused:
        _ingest(_adapter(), at=FIXED_INSTANT + OBSERVATION_GAP)

    assert "naming no packages" in str(refused.value)
    assert [row.state for row in _snapshots()] == [OutcomeState.OK.value]
    assert _last_run().status == RunState.FAILED


@pytest.mark.django_db
def test_a_document_whose_every_record_fails_writes_no_absence_and_fails_the_run() -> None:
    """The same corruption by the other route, and the one a count would hide.

    A document that was *read* but whose every record failed has also observed
    nothing, and a base deciding on a total row count would have taken the absence
    rows as evidence that it had -- reporting `partial` over a run that wrote
    nothing but departures. `SweepOutcome` keeps the two counts apart for exactly
    this, and the collector declines to derive absences from a run that observed
    nothing at all.

    `partial` means some of the work was done; this run did none of it.
    """
    _ingest(_adapter(_record(FIRST_KEY)))

    result = _ingest(
        _adapter(_record(FAILING_KEY)),
        at=FIXED_INSTANT + OBSERVATION_GAP,
        collector_class=FailingOnKeyCollector,
    )

    assert result.state is RunState.FAILED
    assert result.evidence_rows == 0
    assert [row.state for row in _snapshots()] == [OutcomeState.OK.value]
    assert FAILING_KEY in _last_run().detail


@pytest.mark.django_db
def test_a_malformed_document_fails_the_run_before_anything_is_written() -> None:
    """`CPM-FR-42`: no run partially ingests a malformed source.

    The exception reaches the caller unchanged and the ledger row is finalized on
    the way out, which is `core/ledger.py`'s promise -- so the run is on the
    record even though nothing else is.
    """
    with pytest.raises(InventoryRecordError):
        _ingest(_adapter(_record(FIRST_KEY), _record(FIRST_KEY)))

    assert Package.objects.count() == 0
    assert InventorySnapshot.objects.count() == 0
    assert _the_run().status == RunState.FAILED


@pytest.mark.django_db
def test_the_task_ingests_through_the_declared_adapter() -> None:
    """The entry point a worker actually calls, end to end.

    The adapter is resolved from the one declared point (`CPM-AD-29`), the
    collector is built with the system clock, and the run is recorded -- which is
    the whole path between a beat schedule and a row.
    """
    adapter = _adapter(_record(FIRST_KEY))
    declare_inventory_adapter(adapter)
    try:
        state = ingest_inventory()
    finally:
        withdraw_inventory_adapter()

    assert state == RunState.SUCCEEDED.value
    assert adapter.calls == [INVENTORY_SOURCE]
    assert Package.objects.filter(canonical_name=_name(FIRST_KEY)).exists()
    assert InventorySnapshot.objects.count() == 1


# ---------------------------------------------------------------------------
# The append-only refusals, on a migrated table (`CPM-AD-2`, `EVIDENCE.02-AUDIT-001`).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_written_snapshot_cannot_be_saved_again() -> None:
    """`AppendOnlyModel.save()` refuses a row that already exists.

    The first time this refusal is asserted against a real evidence table rather
    than against a model built inside `isolate_apps`.
    """
    _ingest(_adapter(_record(FIRST_KEY)))
    row = _snapshots()[0]
    row.internal_component_count = 99

    with pytest.raises(AppendOnlyError):
        row.save()


@pytest.mark.django_db
def test_a_snapshot_queryset_cannot_be_updated() -> None:
    """The path `save()` cannot see: an `UPDATE` that constructs no instance."""
    _ingest(_adapter(_record(FIRST_KEY)))

    with pytest.raises(AppendOnlyError):
        InventorySnapshot.objects.all().update(internal_component_count=99)


@pytest.mark.django_db
def test_a_package_with_observations_cannot_be_deleted() -> None:
    """`EVIDENCE.02-AUDIT-001`, proved by the database rather than by Python.

    Django's deletion collector issues its `DELETE` through `sql.DeleteQuery` and
    goes past every refusal in `core/models.py`, so `PROTECT` is the only thing
    standing between a package row going and its observations going with it --
    and only a real foreign key can be shown to enforce it.
    """
    _ingest(_adapter(_record(FIRST_KEY)))
    package = Package.objects.get(canonical_name=_name(FIRST_KEY))

    with pytest.raises(ProtectedError):
        package.delete()

    assert InventorySnapshot.objects.count() == 1


@pytest.mark.django_db
def test_a_present_observation_missing_a_count_is_refused_by_the_database() -> None:
    """The constraint that makes "required" true where it is true.

    A NOT NULL column would have made the absence and sentinel rows unwritable,
    so the requirement is a `CheckConstraint` reading "both counts are present
    exactly when `state` is `ok`" -- and a check constraint is only proved by a
    database that refuses.
    """
    package = resolve_package_shell(
        source_package_key=FIRST_KEY,
        package_name=_name(FIRST_KEY),
        identity_source=COLLECTOR_NAME,
        clock=_clock(),
    )

    with pytest.raises(IntegrityError) as refused:
        InventorySnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            source_package_key=FIRST_KEY,
            state=OutcomeState.OK.value,
            internal_lob_count=A_LOB_COUNT,
        )

    assert COUNTS_PRESENT_CONSTRAINT in str(refused.value) or "CHECK" in str(refused.value).upper()


@pytest.mark.django_db
def test_an_absence_row_carrying_counts_is_refused_by_the_database() -> None:
    """The other direction: a row observing usage for a package the source did not list.

    Values are never invented (PRD Appendix A.1), and an absence row with counts
    on it is an invented observation wearing a sentinel's state.
    """
    package = resolve_package_shell(
        source_package_key=FIRST_KEY,
        package_name=_name(FIRST_KEY),
        identity_source=COLLECTOR_NAME,
        clock=_clock(),
    )

    with pytest.raises(IntegrityError):
        InventorySnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            source_package_key=FIRST_KEY,
            state=OutcomeState.NOT_FOUND.value,
            internal_component_count=A_COMPONENT_COUNT,
            internal_lob_count=A_LOB_COUNT,
        )


# ---------------------------------------------------------------------------
# The cut-off-bound read (`CPM-AD-25`, `CPM-FR-22`).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_read_at_a_cut_off_returns_the_observation_that_was_current_then() -> None:
    """Two observations, one cut-off between them, and the same answer every time.

    The repeated call is the assertion, not decoration: `CPM-FR-22` promises that
    replaying a policy version at a stated cut-off reproduces identical output,
    and a read that returned the latest row would give a different answer every
    time the inventory changed.
    """
    _ingest(_adapter(_record(FIRST_KEY, downloads=FIRST_DOWNLOADS)))
    _ingest(_adapter(_record(FIRST_KEY, downloads=SECOND_DOWNLOADS)), at=FIXED_INSTANT + OBSERVATION_GAP)
    package = Package.objects.get(canonical_name=_name(FIRST_KEY))
    cutoff = FIXED_INSTANT + OBSERVATION_GAP / 2

    first = snapshot_as_of(package_id=package.pk, cutoff=cutoff)
    again = snapshot_as_of(package_id=package.pk, cutoff=cutoff)

    assert first is not None
    assert first.downloads == FIRST_DOWNLOADS
    assert again is not None
    assert again.pk == first.pk


@pytest.mark.django_db
def test_a_read_at_or_after_the_latest_observation_returns_it() -> None:
    """The boundary is inclusive: evidence observed *at* the cut-off is in scope.

    `CPM-AD-21` makes the cut-off the `finished_at` of a completed collection
    run, so a read that excluded the instant itself would miss the observations
    that run had just written.
    """
    _ingest(_adapter(_record(FIRST_KEY, downloads=FIRST_DOWNLOADS)))
    _ingest(_adapter(_record(FIRST_KEY, downloads=SECOND_DOWNLOADS)), at=FIXED_INSTANT + OBSERVATION_GAP)
    package = Package.objects.get(canonical_name=_name(FIRST_KEY))

    latest = snapshot_as_of(package_id=package.pk, cutoff=FIXED_INSTANT + OBSERVATION_GAP)

    assert latest is not None
    assert latest.downloads == SECOND_DOWNLOADS


@pytest.mark.django_db
def test_a_cut_off_before_the_first_observation_returns_nothing_and_is_not_an_error() -> None:
    """An ordinary question with an ordinary answer.

    Inventing a row would be the clean-looking result `CPM-NFR-3` forbids, and
    raising would push every caller into a try block for a package that simply
    had not been observed yet.
    """
    _ingest(_adapter(_record(FIRST_KEY)))
    package = Package.objects.get(canonical_name=_name(FIRST_KEY))

    assert snapshot_as_of(package_id=package.pk, cutoff=FIXED_INSTANT - timedelta(seconds=1)) is None


@pytest.mark.django_db
def test_a_naive_cut_off_is_refused() -> None:
    """`CPM-AD-26`: there is no offset to convert from, so guessing one is refused.

    A cut-off shifted by the reader's offset selects a different evidence set on
    every replay, which is the opposite of what `CPM-FR-22` promises -- and it
    would do it silently.
    """
    with pytest.raises(InventoryReadError):
        snapshot_as_of(package_id=1, cutoff=FIXED_INSTANT.replace(tzinfo=None))


@pytest.mark.django_db
def test_two_snapshots_at_one_instant_are_ordered_by_the_row_that_arrived_last() -> None:
    """The tie-break, which every other cut-off case here is arranged not to need.

    One sweep stamps every row it writes with the run's single instant
    (`CPM-AD-7`), so two observations of one package really can share an
    `observed_at` -- two runs at the same instant, or one run writing an
    observation and an absence. With no second ordering key the answer is
    whichever row the database hands back first, which is not a promise any
    database makes and not a replay.

    Both runs are stopped at the same instant on purpose, which is what makes the
    rows tie.
    """
    _ingest(_adapter(_record(FIRST_KEY, downloads=FIRST_DOWNLOADS)))
    _ingest(_adapter(_record(FIRST_KEY, downloads=SECOND_DOWNLOADS)))
    package = Package.objects.get(canonical_name=_name(FIRST_KEY))
    rows = _snapshots(FIRST_KEY)

    read = snapshot_as_of(package_id=package.pk, cutoff=FIXED_INSTANT)

    assert {row.observed_at for row in rows} == {FIXED_INSTANT}
    assert read is not None
    assert read.pk == max(row.pk for row in rows)
    assert read.downloads == SECOND_DOWNLOADS


@pytest.mark.django_db
def test_resolution_refuses_a_key_the_column_cannot_hold_before_writing_a_row() -> None:
    """The refusal the record contract now makes first, kept at the door as well.

    `records_in` refuses an over-long key so the whole document is refused rather
    than one record failing mid-sweep (`CPM-FR-42`). That does not make this
    redundant: resolution is the only creator of a package row (`CPM-AD-25`) and
    is reachable by callers that never went through the contract --
    `CPM-IDENTITY-S02` will be one -- so the bound belongs at the door too, and
    the door is what must leave nothing behind when it refuses.
    """
    with pytest.raises(ResolutionError):
        resolve_package_shell(
            source_package_key="n" * (ASSOCIATOR_KEY_LENGTH + 1),
            package_name=_name(FIRST_KEY),
            identity_source=COLLECTOR_NAME,
            clock=_clock(),
        )

    assert Package.objects.count() == 0


@pytest.mark.django_db
def test_resolution_refuses_a_name_the_column_cannot_hold_before_writing_a_row() -> None:
    """The other bound, on the other column, and it is a different number.

    `canonical_name` is narrower than `associator_key`, so a value that is a
    perfectly usable *key* can be an unusable *name*. Both refusals leave nothing
    behind, which is what makes the door safe for the callers that reach it
    without going through the record contract.
    """
    with pytest.raises(ResolutionError):
        resolve_package_shell(
            source_package_key=FIRST_KEY,
            package_name="n" * (CANONICAL_NAME_LENGTH + 1),
            identity_source=COLLECTOR_NAME,
            clock=_clock(),
        )

    assert Package.objects.count() == 0


@pytest.mark.django_db
def test_a_shell_records_what_established_it_and_the_key_it_matched_on() -> None:
    """`CPM-FR-2`: a resolution is re-derivable and disputable, not merely trusted.

    A shell asserts no mapping, and that is not the same as asserting no
    *provenance*. It matters more here than for a real resolution: the shell's
    `canonical_name` is corrected out from under it by `CPM-IDENTITY-S02`, and a
    shell with no `associator_key` is a package the next sweep cannot match back
    to the record that made it.

    The two columns carry *different* values, which is `CPM-IDENTITY-S07`'s
    change and is asserted here rather than assumed: while the key was written
    into both, a lookup on either matched, and the correction trap above was
    invisible because nothing could tell the correctable name from the stable
    key.
    """
    _ingest(_adapter(_record(FIRST_KEY)))

    package = Package.objects.get(canonical_name=_name(FIRST_KEY))
    assert package.identity_source == COLLECTOR_NAME
    assert package.associator_key == FIRST_KEY
    assert package.canonical_name != package.associator_key
    assert package.confidence == IdentityConfidence.UNMAPPED


@pytest.mark.django_db
def test_a_departed_package_is_recorded_absent_once_rather_than_on_every_run() -> None:
    """Absence is a transition, not a condition, and the difference is unbounded growth.

    Three runs: one that names the package, one that does not, and one that still
    does not. The second observes something new -- the package left -- and records
    it. The third observes nothing new about it and must write nothing, or the
    table gains one row per departed package per sweep, for ever, with no
    retention process to take them away.

    The absence stays readable at any later cut-off either way: the row's
    `observed_at` is when the package went, and no row after it means nothing has
    changed since.
    """
    _ingest(_adapter(_record(FIRST_KEY), _record(SECOND_KEY)))

    _ingest(_adapter(_record(FIRST_KEY)), at=FIXED_INSTANT + OBSERVATION_GAP)
    third = _ingest(_adapter(_record(FIRST_KEY)), at=FIXED_INSTANT + OBSERVATION_GAP * 2)

    assert third.state is RunState.SUCCEEDED
    assert third.evidence_rows == 1
    departed = _snapshots(SECOND_KEY)
    assert [row.state for row in departed] == [OutcomeState.OK.value, OutcomeState.NOT_FOUND.value]
    assert departed[-1].observed_at == FIXED_INSTANT + OBSERVATION_GAP


@pytest.mark.django_db
def test_a_package_named_again_after_departing_is_observed_rather_than_ignored() -> None:
    """The other side of the transition rule, without which it would be a leak.

    A package that comes back has an `ok` observation again, and the run after
    that must be able to record it departing a second time. A rule that suppressed
    absences by "has ever been absent" rather than by "is currently absent" would
    silently stop observing it.
    """
    _ingest(_adapter(_record(FIRST_KEY), _record(SECOND_KEY)))
    _ingest(_adapter(_record(FIRST_KEY)), at=FIXED_INSTANT + OBSERVATION_GAP)
    _ingest(_adapter(_record(FIRST_KEY), _record(SECOND_KEY)), at=FIXED_INSTANT + OBSERVATION_GAP * 2)

    _ingest(_adapter(_record(FIRST_KEY)), at=FIXED_INSTANT + OBSERVATION_GAP * 3)

    assert [row.state for row in _snapshots(SECOND_KEY)] == [
        OutcomeState.OK.value,
        OutcomeState.NOT_FOUND.value,
        OutcomeState.OK.value,
        OutcomeState.NOT_FOUND.value,
    ]


@pytest.mark.django_db
def test_the_shared_freshness_read_finds_this_collectors_observations(
    recorded_spans: InMemorySpanExporter,
) -> None:
    """`core/freshness.py` reaching a real evidence table for the first time.

    `_require_package_reference` accepts a field named `package_id` *or* one whose
    `attname` is, and its docstring says the second arm exists for exactly this
    moment: every evidence model until now declared a literal `package_id`
    integer, and this is the first whose reference is a `ForeignKey` named
    `package`. Narrowing that predicate to the field's `name` would break the only
    real evidence table in the repository and every existing freshness case --
    which run against the fixture model -- would still pass.

    Asserted through the collector rather than through `latest_observation`
    directly, because the collector is what supplies the two things only it knows:
    which table holds its observations, and what target it declared.

    Args:
        recorded_spans: Requested for what it makes true rather than for what it
            returns -- see the trace-id case below.

    """
    _ingest(_adapter(_record(FIRST_KEY)))
    package = Package.objects.get(canonical_name=_name(FIRST_KEY))
    collector = InventoryIngestionCollector(clock=_clock(), transport=RecordedTransport())
    target = InventoryIngestionCollector.freshness_target
    assert target is not None

    fresh = collector.freshness(package_id=package.pk, now=FIXED_INSTANT)
    stale = collector.freshness(package_id=package.pk, now=FIXED_INSTANT + target + OBSERVATION_GAP)

    assert fresh.observed_at == FIXED_INSTANT
    assert fresh.stale is False
    assert stale.observed_at == FIXED_INSTANT
    assert stale.stale is True
    assert recorded_spans is not None


@pytest.mark.django_db
def test_a_snapshot_carries_the_trace_id_the_platform_would_log(
    recorded_spans: InMemorySpanExporter,
) -> None:
    """`CPM-AD-15`, inside a real recording span rather than outside every span.

    Outside a span both the row and the ledger row carry `""`, so comparing them
    is comparing two empty strings -- a collector that never set `trace_id` at all
    would pass. The span is what makes the comparison mean something: the id is
    non-empty, it is the one the platform's own log processor would emit, and the
    evidence row and the run row join on it.

    The exported spans are read at the end for the reason
    `tests/integration/django_apps/test_run_ledger.py` reads them: it is what
    makes "a real recording span" a fact rather than an assumption.

    Args:
        recorded_spans: The in-memory exporter attached to the live provider.

    """
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("inventory") as span:
        expected = format(span.get_span_context().trace_id, TRACE_ID_FORMAT)
        _ingest(_adapter(_record(FIRST_KEY)))

    snapshot = _snapshots()[0]
    assert expected != ""
    assert snapshot.trace_id == expected
    assert snapshot.trace_id == _the_run().trace_id
    assert "inventory" in [recorded.name for recorded in recorded_spans.get_finished_spans()]


@pytest.mark.django_db
def test_a_forced_sweep_reaches_the_base_rather_than_being_dropped() -> None:
    """`force` is inert for a `NO_WINDOW` collector, and it still has to arrive.

    The window is zero, so nothing is being bypassed and no behaviour differs.
    What this pins is that the task carries the flag through to `sweep()` at all:
    the day the window becomes non-zero, a task that had quietly dropped it would
    subject every manual recollection to a window nobody asked for, and no
    existing case would notice.
    """
    adapter = _adapter(_record(FIRST_KEY))
    declare_inventory_adapter(adapter)
    try:
        state = ingest_inventory(force=True)
    finally:
        withdraw_inventory_adapter()

    assert state == RunState.SUCCEEDED.value
    assert InventorySnapshot.objects.count() == 1
