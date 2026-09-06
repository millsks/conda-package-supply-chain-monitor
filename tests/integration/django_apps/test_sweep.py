"""The full-inventory dispatch against real tables: what it enqueues, what it records, what it refuses.

`CPM-CURRENCY-S05`'s four acceptance criteria are all claims about a run, so they
are all here. `tests/unit/django_apps/test_sweep.py` holds what is decidable
without one -- the derived task name, the chunking, the constants and the four
selections read as queries -- and this module holds everything that needs a
ledger row.

**Two kinds of case, and the difference is deliberate.** The *dispatch's own*
contract -- how many tasks reached the broker, what the ledger row says when some
of them did not, what happens when a collector or a task is missing -- is proved
against fixture collectors and fixture tasks whose `apply_async` is substituted.
Nothing is collected in those, because a dispatch collects nothing: substituting
the enqueue is the only way to show that five packages were offered and three were
taken.

The *guarantees the dispatch inherits* -- AC 2's per-package transaction and AC
3's observation window -- are proved end to end against a **real** collector, its
real evidence table and the real per-package task, with only
`RequestsTransport.fetch` substituted. Those two criteria are about what the
enqueued collections do, and a fixture task that recorded a call would prove
nothing about either. The suite runs Celery eagerly
(`config/settings/test.py`), so an enqueue in those cases really is a collection.

**The ten-thousand-package case is the real collector's real selection**
(`CPM-NFR-1`, AC 4). Ten thousand package rows, the shipped `conda_package`
selection over them, and one assertion the count cannot make: the queryset the
dispatch was handed still has an empty result cache afterwards, which is what says
it was streamed rather than read into a list.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction.
`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.db.models import QuerySet
from django.test import override_settings
from structlog.testing import capture_logs

from conda_package_supply_chain_monitor.collectors.conda_package import CHANNELS_SETTING
from conda_package_supply_chain_monitor.collectors.conda_package import COLLECTOR_NAME as CONDA_PACKAGE_NAME
from conda_package_supply_chain_monitor.collectors.conda_package import PLATFORMS_SETTING
from conda_package_supply_chain_monitor.collectors.conda_package import CondaPackageCollector
from conda_package_supply_chain_monitor.collectors.feedstock import COLLECTOR_NAME as FEEDSTOCK_NAME
from conda_package_supply_chain_monitor.collectors.models import PyPIReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.pypi_release import COLLECTOR_NAME as PYPI_RELEASE_NAME
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_OBSERVATION_WINDOW
from conda_package_supply_chain_monitor.collectors.source_release import COLLECTOR_NAME as SOURCE_RELEASE_NAME
from conda_package_supply_chain_monitor.collectors.sweep import EVENT_KEYS
from conda_package_supply_chain_monitor.collectors.sweep import PACKAGE_EVENT_KEYS
from conda_package_supply_chain_monitor.collectors.sweep import PACKAGE_KWARG
from conda_package_supply_chain_monitor.collectors.sweep import RESERVED_COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.sweep import SELECTION_CHUNK
from conda_package_supply_chain_monitor.collectors.sweep import SWEEP_DISPATCHED_EVENT
from conda_package_supply_chain_monitor.collectors.sweep import SWEEP_PACKAGE_REFUSED_EVENT
from conda_package_supply_chain_monitor.collectors.sweep import SWEEP_REFUSED_EVENT
from conda_package_supply_chain_monitor.collectors.sweep import SWEEP_SKIPPED_EVENT
from conda_package_supply_chain_monitor.collectors.sweep import SWEEP_TASK_NAME
from conda_package_supply_chain_monitor.collectors.sweep import SweepDispatchError
from conda_package_supply_chain_monitor.collectors.sweep import collection_task_name
from conda_package_supply_chain_monitor.collectors.sweep import dispatch
from conda_package_supply_chain_monitor.collectors.tasks import COLLECTOR_NAME as INVENTORY_COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.tasks import InventoryIngestionCollector
from conda_package_supply_chain_monitor.collectors.tasks import collect_sweep
from conda_package_supply_chain_monitor.core.clock import SystemClock
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.core.transport import Payload
from conda_package_supply_chain_monitor.core.transport import RequestsTransport
from conda_package_supply_chain_monitor.core.transport import TransportError
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from conda_package_supply_chain_monitor.identity.models import MappingKind
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import PackageMapping
from config.celery_app import app
from tests.clocks import FIXED_INSTANT
from tests.collectors import FIXTURE_CADENCE
from tests.collectors import fixture_evidence_model
from tests.collectors import registered_collector
from tests.collectors import selectable_collector_class

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Sequence

#: The names the fixture collectors in this module register under. Distinct per
#: case group rather than shared, because the registry and Celery's task registry
#: are both process-global: two cases registering one name would be two cases
#: whose failure lands in whichever ran second.
AN_ORDINARY_COLLECTOR: Final[str] = "sweep_fixture_ordinary"
A_SECOND_COLLECTOR: Final[str] = "sweep_fixture_second"
A_TASKLESS_COLLECTOR: Final[str] = "sweep_fixture_taskless"

#: How many packages the partial-dispatch case offers, and how many of them the
#: broker refuses. Five and two, which is the matrix's own row -- and the numbers
#: matter to each other rather than in themselves: three enqueued and two refused
#: is the only shape in which `partial` is distinguishable from both `succeeded`
#: and `failed`.
A_SELECTION_SIZE: Final[int] = 5
A_REFUSAL_COUNT: Final[int] = 2

#: `CPM-NFR-1`'s inventory, and the number AC 4 is written about.
TEN_THOUSAND: Final[int] = 10_000

#: How many packages the interrupted-dispatch cases get through before the
#: interruption. Two, which is the smallest count that is neither "none" nor "all
#: of them" -- the only shape in which `partial` is distinguishable from both
#: `failed` and `succeeded`.
AN_INTERRUPTED_COUNT: Final[int] = 2


#: What the substituted broker raises when it refuses. A distinct type so the
#: `detail` assertion is about the reason this case configured rather than about
#: any exception that happened to escape.
class ABrokerRefusalError(RuntimeError):
    """The broker would not take this task."""


#: The PyPI project document the end-to-end cases are answered with. Minimal:
#: what those cases are about is the ledger and the evidence count, not the
#: parse, which `tests/unit/django_apps/test_pypi_release.py` owns.
A_PROJECT_DOCUMENT: Final[str] = (
    '{"info": {"version": "5.0.1", "requires_python": ">=3.10"}, '
    '"releases": {"5.0.1": [{"upload_time_iso_8601": "2026-09-01T10:00:00Z"}]}}'
)


class _Recorded(list[int]):
    """The package keys a dispatch offered, and the expiry each of them carried.

    A `list` subclass rather than a pair, so a case asserting *which* packages
    were offered writes the equality it would write against a plain list, while a
    case about `expires` reads one more attribute. The expiry is recorded rather
    than discarded because it is the whole of the guard that keeps an undrained
    sweep from queueing behind itself, and it is invisible in every count.
    """

    def __init__(self) -> None:
        """Start with nothing offered and nothing expiring."""
        super().__init__()
        self.expiries: list[object] = []


def _recording_enqueue(accepted: _Recorded, refused: frozenset[int]) -> Any:
    """Return a substitute for `Task.apply_async` that records rather than publishes.

    The enqueue is substituted rather than the broker, and that is the only seam
    that shows what this module is about: the suite runs Celery eagerly, so an
    unsubstituted `apply_async` would *run* the task rather than record that it
    was offered -- and a dispatch's whole contract is about what it offered.

    Args:
        accepted: The record the accepted package keys and their expiries are
            appended to, in the order they were offered.
        refused: The package keys this substitute refuses, so a case can
            construct the matrix's partial and total-refusal rows.

    Returns:
        The substitute, taking exactly the two keyword arguments the dispatch
        passes -- which is itself an assertion: a dispatch that stopped passing
        `expires` would fail every case here rather than silently enqueueing
        messages that never go stale.

    """

    def _apply_async(*, kwargs: dict[str, Any], expires: object = None) -> None:
        package_id = kwargs[PACKAGE_KWARG]
        if package_id in refused:
            message = f"the broker refused package {package_id}"
            raise ABrokerRefusalError(message)
        accepted.append(package_id)
        accepted.expiries.append(expires)

    return _apply_async


@contextmanager
def _enqueue_recorded(task_name: str, *, refuse: Sequence[int] = ()) -> Iterator[_Recorded]:
    """Register a fixture task under one name and record what a dispatch enqueues to it.

    For the fixture collectors, whose derived task names no real task holds. The
    registration is real -- `Celery.tasks` is one process-wide registry with no
    isolated view of it -- so the removal is this helper's responsibility and is
    in a `finally`, on the terms `tests/celery_tasks.py` records at length: a
    fixture task left behind is one every later case's registry sweep sees.

    Args:
        task_name: The task name to register, which is what the dispatch derives
            from the collector's own name.
        refuse: The package keys the substituted enqueue refuses.

    Yields:
        The package keys that were accepted, in the order they were offered.

    Raises:
        ValueError: When the registry already holds the name. A fixture that
            displaced a real task would take it away again on the way out,
            leaving a registry quieter than the one the session started with --
            `_enqueue_intercepted` is what a case wanting a *real* task uses.

    """
    if task_name in app.tasks:
        message = f"the celery registry already holds {task_name!r}; a fixture task must not displace a real one"
        raise ValueError(message)

    accepted = _Recorded()

    @app.task(name=task_name, shared=False)
    def _fixture(*, package_id: int) -> None:
        """Do nothing; the registration is what a dispatch looks for."""

    app.tasks[task_name].apply_async = _recording_enqueue(accepted, frozenset(refuse))
    try:
        yield accepted
    finally:
        app.tasks.pop(task_name, None)


@contextmanager
def _enqueue_intercepted(
    task_name: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    refuse: Sequence[int] = (),
) -> Iterator[_Recorded]:
    """Record what a dispatch enqueues to a task the component really ships.

    The counterpart to `_enqueue_recorded`, for the one case that dispatches a
    *real* collector at `CPM-NFR-1` volume: its task exists, so it is intercepted
    rather than registered, and `monkeypatch` puts the real `apply_async` back.
    Without the interception the eager suite would run ten thousand real
    collections.

    Args:
        task_name: The real task's declared name.
        monkeypatch: pytest's patcher, so the substitution is undone per case.
        refuse: The package keys the substituted enqueue refuses.

    Yields:
        The package keys that were accepted, in the order they were offered.

    """
    accepted = _Recorded()
    monkeypatch.setattr(
        app.tasks[task_name],
        "apply_async",
        _recording_enqueue(accepted, frozenset(refuse)),
    )
    yield accepted


def _a_package(name: str) -> Package:
    """Return a saved package with an established PyPI release-ecosystem identity.

    Args:
        name: The canonical name, unique per package.

    Returns:
        The saved row, selectable by `PyPIReleaseCollector`.

    """
    package = Package.objects.create(
        canonical_name=name,
        resolved_at=FIXED_INSTANT,
        primary_type="pypi",
        primary_purl=f"pkg:pypi/{name}",
    )
    PackageMapping.objects.create(
        package=package,
        kind=MappingKind.RELEASE_ECOSYSTEM.value,
        outcome=ESTABLISHED,
        resolved_at=FIXED_INSTANT,
    )
    return package


def _rows(collector: str) -> list[CollectionRun]:
    """Return one collector's ledger rows, newest last.

    Args:
        collector: The collector's declared name.

    Returns:
        Every `collection_runs` row that collector wrote, in insertion order.

    """
    return list(CollectionRun.objects.filter(collector=collector).order_by("pk"))


# ---------------------------------------------------------------------------
# The dispatch's own contract.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_ordinary_dispatch_enqueues_one_task_per_selected_package() -> None:
    """The matrix's first row: three selectable packages, three tasks, one ledger row.

    Three things are asserted because three could each be wrong on their own: the
    tasks reached the derived task name carrying one `package_id` each; the run
    ledger holds exactly one row for the dispatch and it is scoped to *no*
    package, which is what a run that is not about one package writes; and the
    `detail` says how many were enqueued, because the count is the only durable
    record of what the sweep offered.
    """
    selection = (11, 22, 33)
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=selection,
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == list(selection)
    assert outcome.state is RunState.SUCCEEDED
    assert outcome.enqueued == len(selection)
    assert outcome.refused == 0

    (row,) = _rows(AN_ORDINARY_COLLECTOR)
    assert row.status == RunState.SUCCEEDED.value
    assert row.package_id is None
    assert row.detail == outcome.detail
    assert str(len(selection)) in row.detail


@pytest.mark.django_db
def test_a_selection_that_matches_no_package_succeeds_and_says_the_selection_was_empty() -> None:
    """An empty inventory is not a failure, and the row has to say which it was.

    Recorded as `succeeded` with a `detail` naming the empty selection, so a
    component with nothing to sweep is distinguishable from one whose broker is
    down -- which is the other zero-enqueued row and is `failed`.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(),
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == []
    assert outcome.state is RunState.SUCCEEDED
    assert outcome.enqueued == 0
    assert "selected no packages" in outcome.detail

    (row,) = _rows(AN_ORDINARY_COLLECTOR)
    assert row.status == RunState.SUCCEEDED.value
    assert row.detail == outcome.detail


@pytest.mark.django_db
def test_a_broker_that_refuses_some_packages_records_partial_and_keeps_the_rest_enqueued() -> None:
    """AC 1, and `CPM-FR-15`'s partial success on the dispatch path.

    Five offered, two refused, three enqueued -- and the three that were enqueued
    stay enqueued, which is the half a dispatch that abandoned its selection on
    the first refusal would fail. `partial`, never `failed`: "some of the work was
    done" and "none of it was" are different operational facts and a reader must
    never have to infer which from a count.
    """
    selection = tuple(range(1, A_SELECTION_SIZE + 1))
    refused = selection[:A_REFUSAL_COUNT]
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=selection,
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR), refuse=refused) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == list(selection[A_REFUSAL_COUNT:])
    assert outcome.state is RunState.PARTIAL
    assert outcome.enqueued == A_SELECTION_SIZE - A_REFUSAL_COUNT
    assert outcome.refused == A_REFUSAL_COUNT

    (row,) = _rows(AN_ORDINARY_COLLECTOR)
    assert row.status == RunState.PARTIAL.value
    assert row.detail == outcome.detail
    assert ABrokerRefusalError.__name__ in row.detail


@pytest.mark.django_db
def test_a_broker_that_refuses_every_package_records_failed_and_names_the_reason() -> None:
    """The other zero-enqueued row, and the one that is a failure.

    Nothing was dispatched, so nothing will be collected, and a `succeeded` row
    here would make an unreachable broker look like an empty inventory on every
    surface that reads the ledger.
    """
    selection = (7, 8, 9)
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=selection,
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR), refuse=selection) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == []
    assert outcome.state is RunState.FAILED
    assert outcome.refused == len(selection)

    (row,) = _rows(AN_ORDINARY_COLLECTOR)
    assert row.status == RunState.FAILED.value
    assert "Nothing was dispatched" in row.detail
    assert ABrokerRefusalError.__name__ in row.detail


@pytest.mark.django_db
def test_one_collectors_dispatch_failing_leaves_every_other_collectors_dispatch_untouched() -> None:
    """AC 1, and the reason it is structural rather than defended.

    The first collector's dispatch raises -- Celery holds no task for it -- and
    the second's runs afterwards, records its own `succeeded` row and enqueues its
    own packages. Neither ledger row mentions the other, which is the assertion
    that would fail if the two dispatches shared anything but the ledger table.
    """
    failing = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=A_TASKLESS_COLLECTOR,
        selection=(1, 2, 3),
    )
    working = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=A_SECOND_COLLECTOR,
        selection=(4, 5),
    )

    with (
        registered_collector(failing),
        registered_collector(working),
        _enqueue_recorded(collection_task_name(A_SECOND_COLLECTOR)) as accepted,
    ):
        with pytest.raises(SweepDispatchError):
            dispatch(collector=A_TASKLESS_COLLECTOR, clock=SystemClock())

        outcome = dispatch(collector=A_SECOND_COLLECTOR, clock=SystemClock())

    assert accepted == [4, 5]
    assert outcome.state is RunState.SUCCEEDED

    (failed_row,) = _rows(A_TASKLESS_COLLECTOR)
    (succeeded_row,) = _rows(A_SECOND_COLLECTOR)
    assert failed_row.status == RunState.FAILED.value
    assert succeeded_row.status == RunState.SUCCEEDED.value
    assert A_SECOND_COLLECTOR not in failed_row.detail
    assert A_TASKLESS_COLLECTOR not in succeeded_row.detail


@pytest.mark.django_db
def test_a_run_scoped_collector_is_refused_by_name_rather_than_silently_skipped() -> None:
    """A collector with no selection is not a collector with an empty one.

    Inventory ingestion reads one document naming many packages (`CPM-AD-25`) and
    refuses all three per-package hooks, so dispatching it per package would ask
    it for a locator it will not name. Refused by name, because a schedule entry
    firing a per-package dispatch at a run-scoped collector would otherwise look
    exactly like a collector nothing ever ran.
    """
    with pytest.raises(SweepDispatchError, match="selectable_packages"):
        dispatch(collector=INVENTORY_COLLECTOR_NAME, clock=SystemClock())

    (row,) = _rows(INVENTORY_COLLECTOR_NAME)
    assert row.status == RunState.FAILED.value
    assert InventoryIngestionCollector.__name__ in row.detail
    assert row.package_id is None


@pytest.mark.django_db
def test_a_collector_nothing_registered_is_refused_and_the_ledger_says_so() -> None:
    """A beat entry naming a collector this component has not adopted.

    Refused rather than shrugged at: a dispatch that skipped it would leave the
    surface it was meant to observe silently unobserved, and the message names
    what *is* registered because "no such collector" tells an operator nothing
    they can act on.
    """
    absent = "sweep_fixture_never_registered"

    with pytest.raises(SweepDispatchError, match="no collector is registered"):
        dispatch(collector=absent, clock=SystemClock())

    (row,) = _rows(absent)
    assert row.status == RunState.FAILED.value
    assert PYPI_RELEASE_NAME in row.detail


@pytest.mark.django_db
def test_a_collector_whose_task_celery_does_not_hold_is_refused_before_anything_is_enqueued() -> None:
    """A dispatch never invents a task name it cannot find.

    Publishing into a name nothing consumes is silent non-delivery: the messages
    are accepted, nothing runs them, and every surface reads exactly as it would
    if the source had answered nothing.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=A_TASKLESS_COLLECTOR,
        selection=(1, 2),
    )

    with registered_collector(collector), pytest.raises(SweepDispatchError) as refused:
        dispatch(collector=A_TASKLESS_COLLECTOR, clock=SystemClock())

    assert collection_task_name(A_TASKLESS_COLLECTOR) in str(refused.value)

    (row,) = _rows(A_TASKLESS_COLLECTOR)
    assert row.status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_blank_collector_name_is_refused_before_a_ledger_row_exists() -> None:
    """The one refusal that leaves nothing behind, and it is the right one.

    A name is what a run is traced to (`CPM-FR-39`); a blank one has nothing to
    open a row against, so the refusal comes before the recorder rather than from
    inside it.
    """
    with pytest.raises(SweepDispatchError, match="names nothing"):
        dispatch(collector="   ", clock=SystemClock())

    assert CollectionRun.objects.count() == 0


@pytest.mark.django_db
def test_the_dispatch_task_returns_the_state_its_ledger_row_carries() -> None:
    """The task is the only path beat takes, so its wiring is asserted through it.

    A task that dropped the collector keyword, or returned something other than
    the run state, would leave every scheduled sweep reporting a result nothing
    could be read from -- and neither is observable through `dispatch` itself.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(41, 42),
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        returned = collect_sweep(collector=AN_ORDINARY_COLLECTOR)

    assert returned == RunState.SUCCEEDED.value
    assert accepted == [41, 42]


# ---------------------------------------------------------------------------
# AC 4: ten thousand packages, streamed.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ten_thousand_packages_are_enqueued_from_one_tick_with_no_operator_batching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CPM-NFR-1` and AC 4, against the shipped collector's own shipped selection.

    Two claims, and the second is the one a count cannot make. Ten thousand tasks
    are enqueued from one scheduled dispatch, with no operator batching anywhere.
    And the queryset the dispatch was handed is still unevaluated afterwards --
    its result cache is empty -- which is what says the dispatch *streamed* it
    rather than reading it.

    **The hook is wrapped rather than replaced**, which is the difference between
    this case and one that proves only that `.iterator()` was called somewhere: the
    selection the dispatch consumes is exactly what
    `CondaPackageCollector.selectable_packages` returns, and the wrapper only
    keeps a reference so the cache can be read afterwards. A collector that began
    returning `list(queryset)` would fail here, because a list has no cache to be
    empty and the `_streamed` guard refuses it outright.

    The channels and platforms are declared, because the shipped empty
    declaration now selects *nothing* -- which is its own case above.
    """
    Package.objects.bulk_create(
        Package(canonical_name=f"sweep-package-{index}", resolved_at=FIXED_INSTANT) for index in range(TEN_THOUSAND)
    )
    consumed: list[object] = []
    shipped = CondaPackageCollector.selectable_packages.__func__  # type: ignore[attr-defined]

    def _capturing(cls: type) -> object:
        selection = shipped(cls)
        consumed.append(selection)
        return selection

    monkeypatch.setattr(CondaPackageCollector, "selectable_packages", classmethod(_capturing))

    with (
        override_settings(**{CHANNELS_SETTING: ("conda-forge",), PLATFORMS_SETTING: ("linux-64",)}),
        _enqueue_intercepted(collection_task_name(CONDA_PACKAGE_NAME), monkeypatch) as accepted,
    ):
        outcome = dispatch(collector=CONDA_PACKAGE_NAME, clock=SystemClock())

    assert outcome.state is RunState.SUCCEEDED
    assert outcome.enqueued == TEN_THOUSAND
    assert len(accepted) == TEN_THOUSAND
    assert len(set(accepted)) == TEN_THOUSAND
    assert TEN_THOUSAND > SELECTION_CHUNK

    (streamed,) = consumed
    assert isinstance(streamed, QuerySet)
    assert streamed._result_cache is None  # noqa: SLF001 - the empty cache is the claim


@pytest.mark.django_db
def test_an_undeclared_component_selects_nothing_rather_than_failing_every_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped state, and the reason the one selection that could not narrow had to.

    `CPM_MONITORED_CHANNELS` and `CPM_MONITORED_PLATFORMS` ship empty (PRD Open
    Question 4) and this collector's `source_for` then refuses *every* package
    equally. A selection that offered the inventory anyway would have the
    scheduled sweep write one `failed` collection per package per day out of the
    box -- ten thousand of them, from the settings this repository ships, before
    an operator has done anything wrong. So the selection is empty until the
    surfaces are declared and the dispatch records one honest `succeeded` row.
    """
    Package.objects.create(canonical_name="undeclared-component", resolved_at=FIXED_INSTANT)

    with _enqueue_intercepted(collection_task_name(CONDA_PACKAGE_NAME), monkeypatch) as accepted:
        outcome = dispatch(collector=CONDA_PACKAGE_NAME, clock=SystemClock())

    assert accepted == []
    assert outcome.state is RunState.SUCCEEDED
    assert outcome.enqueued == 0
    assert "selected no packages" in outcome.detail
    assert not CollectionRun.objects.filter(collector=CONDA_PACKAGE_NAME, package__isnull=False).exists()


# ---------------------------------------------------------------------------
# AC 2 and AC 3, end to end through the real collector and the real task.
# ---------------------------------------------------------------------------


@pytest.fixture
def _no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer every fetch the enqueued collections make, without opening one.

    The per-package tasks build their own transport from the collector's declared
    timeout and retry count -- that is the whole point of the base owning the call
    -- so the seam these two cases reach through is the transport's own `fetch`.
    Substituting it leaves everything else real: the real collector, the real
    evidence table, the real ledger, the real observation window.

    A locator naming a package whose canonical name ends in `-broken` raises,
    which is the failure AC 2 is written around; every other locator is answered
    with the project document above.

    Args:
        monkeypatch: pytest's patcher, so the substitution is undone per case.

    """

    def _fetch(_self: RequestsTransport, source: str, *, headers: object = None) -> Payload:
        if "-broken" in source:
            message = f"the source at {source} is unreachable"
            raise TransportError(message, source=source)
        return Payload(source=source, found=True, body=A_PROJECT_DOCUMENT, not_modified=False)

    monkeypatch.setattr(RequestsTransport, "fetch", _fetch)


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_socket")
def test_a_package_whose_collection_fails_leaves_every_other_packages_evidence_committed() -> None:
    """AC 2: the transaction boundary is one package, and it is structural.

    The dispatch enqueues three collections and the middle one's source is
    unreachable. Because each is its own task, its own ledger row and its own
    transaction, the two that answered have their rows and the one that did not
    has an `error` row of its own -- nothing is rolled back and nothing is lost.
    A dispatch that collected inside one transaction would leave three rows or
    none.

    Asserted per package rather than by total, because a count of three would be
    satisfied by the wrong three.
    """
    packages = [_a_package(name) for name in ("alpha", "beta-broken", "gamma")]

    outcome = dispatch(collector=PYPI_RELEASE_NAME, clock=SystemClock())

    assert outcome.state is RunState.SUCCEEDED
    assert outcome.enqueued == len(packages)

    states = {row.package_id: row.state for row in PyPIReleaseSnapshot.objects.filter(package__in=packages)}
    assert states[packages[0].pk] == OutcomeState.OK.value
    assert states[packages[1].pk] == OutcomeState.ERROR.value
    assert states[packages[2].pk] == OutcomeState.OK.value

    collections = {
        row.package_id: row.status
        for row in CollectionRun.objects.filter(collector=PYPI_RELEASE_NAME, package__isnull=False)
    }
    assert collections[packages[1].pk] == RunState.FAILED.value
    assert collections[packages[0].pk] == RunState.SUCCEEDED.value
    assert collections[packages[2].pk] == RunState.SUCCEEDED.value


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_socket")
def test_a_dispatch_repeated_inside_the_observation_window_writes_no_second_evidence_row() -> None:
    """AC 3: the window is the collectors', and this asserts it across a dispatch.

    The same dispatch runs twice within the observation window. The second one
    enqueues the same packages -- a dispatch selects, it does not decide whether a
    collection is due -- and each of those runs records `skipped` with no evidence
    row, so the evidence count after the second dispatch is what it was after the
    first. That is `CPM-AD-7`'s idempotency asserted rather than reimplemented,
    which is what the story asks for.
    """
    packages = [_a_package(name) for name in ("delta", "epsilon")]

    first = dispatch(collector=PYPI_RELEASE_NAME, clock=SystemClock())
    after_first = PyPIReleaseSnapshot.objects.count()

    second = dispatch(collector=PYPI_RELEASE_NAME, clock=SystemClock())

    # The two dispatches run milliseconds apart, so they are inside the window by
    # construction -- asserted rather than assumed, because a collector that
    # declared `NO_WINDOW` would make the whole case vacuous while every count
    # below still matched.
    assert timedelta(0) < PYPI_RELEASE_OBSERVATION_WINDOW

    assert first.enqueued == len(packages)
    assert second.enqueued == len(packages)
    assert after_first == len(packages)
    assert PyPIReleaseSnapshot.objects.count() == after_first

    skipped = CollectionRun.objects.filter(
        collector=PYPI_RELEASE_NAME,
        package__isnull=False,
        status=RunState.SKIPPED.value,
    )
    assert skipped.count() == len(packages)


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_socket")
def test_the_shipped_selection_offers_only_packages_the_collector_can_answer_about() -> None:
    """The precondition four stories deferred, closed and observable.

    A package whose release-ecosystem mapping resolution has not reached is what
    `CPM-CURRENCY-S02` recorded: offered every package, this collector would fail
    every run for every one of them. The dispatch enqueues the resolved package
    and not the unresolved one, so the unresolved package has no ledger row at all
    -- which is the difference between a sweep that works and one whose ledger
    fills with `failed` runs for every package nobody has mapped.
    """
    answerable = _a_package("zeta")
    unresolved = Package.objects.create(canonical_name="eta", resolved_at=FIXED_INSTANT)
    PackageMapping.objects.create(
        package=unresolved,
        kind=MappingKind.RELEASE_ECOSYSTEM.value,
        outcome=OutcomeState.UNKNOWN.value,
        resolved_at=FIXED_INSTANT,
    )

    outcome = dispatch(collector=PYPI_RELEASE_NAME, clock=SystemClock())

    assert outcome.enqueued == 1
    assert CollectionRun.objects.filter(collector=PYPI_RELEASE_NAME, package=answerable).exists()
    assert not CollectionRun.objects.filter(collector=PYPI_RELEASE_NAME, package=unresolved).exists()


# ---------------------------------------------------------------------------
# What bounds a dispatch: the soft limit, the expiry, the overlap.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_enqueued_message_expires_at_the_collectors_own_cadence() -> None:
    """A collection nobody consumed before the next tick is stale by construction.

    The next dispatch offers the same package again, so a message still queued
    when that happens is work that has been superseded -- and left unexpired it
    sits in front of the fresher one. `expires` is the collector's own cadence
    rather than a number this module chose, because "how long is this worth
    running" is the same question "how often is it collected" answers.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(1, 2),
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == [1, 2]
    assert accepted.expiries == [FIXTURE_CADENCE.total_seconds()] * 2


@pytest.mark.django_db
def test_a_dispatch_whose_previous_run_is_still_draining_skips_rather_than_enqueueing_again() -> None:
    """The overlap guard, and the unbounded queue it exists to prevent.

    The declared allowances cannot drain `CPM-NFR-1`'s inventory inside a cadence
    -- the story records that as deferred -- so without this every slow or missed
    tick would enqueue a second whole inventory behind the first, and the queue
    would grow without bound while each collection was refused by the very rate
    limiter that made the sweep slow. `django_celery_beat` fires on a schedule and
    has no notion of a previous run, so the guard is the dispatch's.

    `skipped` rather than `failed`: nothing went wrong, and the previous run's
    packages are still due.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(1, 2, 3),
    )
    CollectionRun.objects.create(
        collector=AN_ORDINARY_COLLECTOR,
        started_at=FIXED_INSTANT,
        status=RunState.RUNNING.value,
        trace_id="a-previous-dispatch",
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == []
    assert outcome.state is RunState.SKIPPED
    assert "has not finished" in outcome.detail

    skipped = CollectionRun.objects.get(collector=AN_ORDINARY_COLLECTOR, status=RunState.SKIPPED.value)
    assert skipped.detail == outcome.detail


@pytest.mark.django_db
def test_a_dispatch_whose_previous_run_has_finished_is_not_skipped() -> None:
    """The negative control: a guard that skipped on any earlier row would skip for ever.

    Only a run still `running` is an overlap. A finished one -- succeeded, partial,
    failed or skipped -- is history, and a dispatch that read it as an overlap
    would enqueue nothing again after its first tick.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(4,),
    )
    for finished in (RunState.SUCCEEDED, RunState.PARTIAL, RunState.FAILED, RunState.SKIPPED):
        CollectionRun.objects.create(
            collector=AN_ORDINARY_COLLECTOR,
            started_at=FIXED_INSTANT,
            finished_at=FIXED_INSTANT,
            status=finished.value,
            trace_id=f"a-{finished.value}-dispatch",
        )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == [4]
    assert outcome.state is RunState.SUCCEEDED


@pytest.mark.django_db
def test_another_collectors_running_dispatch_is_not_an_overlap() -> None:
    """The overlap is per collector, on the terms the observation window is per package.

    One dispatch per collector is what makes AC 1 structural; a guard that read
    *any* running dispatch as an overlap would make one slow collector suppress
    every other one -- which is precisely the failure this story is named for,
    reintroduced by its own bound.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(5,),
    )
    CollectionRun.objects.create(
        collector=A_SECOND_COLLECTOR,
        started_at=FIXED_INSTANT,
        status=RunState.RUNNING.value,
        trace_id="another-collectors-dispatch",
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == [5]
    assert outcome.state is RunState.SUCCEEDED


@pytest.mark.django_db
def test_the_soft_time_limit_ends_the_dispatch_partial_rather_than_counting_as_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SoftTimeLimitExceeded` is a plain `Exception`, and that is the whole hazard.

    Caught by the broad handler it would be counted as one more package the broker
    would not take, the loop would carry on to the next package and meet it again,
    and the worker would run to the *hard* limit and be killed -- leaving the
    ledger row `running` for ever, which is the one state
    `CPM-EVIDENCE-S03`'s recorder exists to make impossible. Caught by name it
    ends the run `partial` with a reason, and the packages already enqueued stay
    enqueued.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(1, 2, 3, 4, 5),
    )
    offered: list[int] = []

    def _apply_async(*, kwargs: dict[str, Any], expires: object = None) -> None:
        package_id = kwargs[PACKAGE_KWARG]
        if len(offered) >= AN_INTERRUPTED_COUNT:
            raise SoftTimeLimitExceeded
        offered.append(package_id)

    with registered_collector(collector), _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)):
        monkeypatch.setattr(app.tasks[collection_task_name(AN_ORDINARY_COLLECTOR)], "apply_async", _apply_async)
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert offered == [1, 2]
    assert outcome.state is RunState.PARTIAL
    assert outcome.enqueued == AN_INTERRUPTED_COUNT
    assert outcome.refused == 0
    assert "soft time limit" in outcome.detail

    (row,) = _rows(AN_ORDINARY_COLLECTOR)
    assert row.status == RunState.PARTIAL.value
    assert row.finished_at is not None


@pytest.mark.django_db
def test_a_selection_that_fails_partway_through_records_partial_rather_than_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented invariant, held on the one path that could break it.

    A database that drops a cursor mid-stream raises out of the *selection*, not
    out of any package's enqueue -- so an unguarded loop would let it escape, the
    recorder would finalize `failed`, and a dispatch that had already enqueued
    thousands would be on the record as having done none of it. That contradicts
    "`failed` is never reached by a dispatch that enqueued something" in as many
    words.
    """

    def _breaking() -> Iterator[int]:
        yield 1
        yield 2
        message = "the cursor went away"
        raise RuntimeError(message)

    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(),
    )
    monkeypatch.setattr(collector, "selectable_packages", classmethod(lambda _cls: _breaking()))

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == [1, 2]
    assert outcome.state is RunState.PARTIAL
    assert outcome.enqueued == AN_INTERRUPTED_COUNT
    assert "could not be read to the end" in outcome.detail
    assert "RuntimeError" in outcome.detail

    (row,) = _rows(AN_ORDINARY_COLLECTOR)
    assert row.status == RunState.PARTIAL.value


@pytest.mark.django_db
def test_a_selection_that_fails_before_anything_is_enqueued_records_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the same rule, and the reason the interruption is read against a count.

    Nothing was enqueued, so nothing was done, and `partial` here would say some
    of the work had been.
    """

    def _breaking() -> Iterator[int]:
        message = "the cursor went away"
        raise RuntimeError(message)
        yield  # pragma: no cover - unreachable, and required to make this a generator

    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(),
    )
    monkeypatch.setattr(collector, "selectable_packages", classmethod(lambda _cls: _breaking()))

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)) as accepted,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    assert accepted == []
    assert outcome.state is RunState.FAILED
    assert "enqueued nothing" in outcome.detail


@pytest.mark.django_db
def test_a_collector_registered_under_the_dispatch_tasks_own_name_is_refused() -> None:
    """`collection_task_name("sweep")` is `cpm.collect.sweep`, which is this task.

    Dispatching such a collector would enqueue the dispatch once per package, and
    each of those would do the same -- an exponential fan-out from one beat tick,
    against a queue that also carries every real collection.
    """
    with pytest.raises(SweepDispatchError, match="reserved"):
        dispatch(collector=RESERVED_COLLECTOR_NAME, clock=SystemClock())

    (row,) = _rows(RESERVED_COLLECTOR_NAME)
    assert row.status == RunState.FAILED.value
    assert SWEEP_TASK_NAME in row.detail


@pytest.mark.django_db
def test_a_selection_that_was_already_read_into_memory_is_refused() -> None:
    """The streaming property, defended by construction rather than by a docstring.

    A hook returning `list(queryset)` would satisfy every count in this module and
    would hold `CPM-NFR-1`'s ten thousand keys. There is no assertion that catches
    that from the outside, so the dispatch refuses it from the inside.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(),
    )
    collector.selectable_packages = classmethod(lambda _cls: [1, 2, 3])  # type: ignore[assignment, method-assign]

    with (
        registered_collector(collector),
        pytest.raises(SweepDispatchError, match="already been read into memory"),
    ):
        dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    (row,) = _rows(AN_ORDINARY_COLLECTOR)
    assert row.status == RunState.FAILED.value


# ---------------------------------------------------------------------------
# The events, which nothing else observes.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_dispatched_run_emits_its_event_carrying_the_keys_the_module_declares() -> None:
    """The log line is the operational surface, and it is asserted like the base's seven.

    `core/collection.py` fixes the keys its events carry so a log query does not
    have to know which path produced a line; the same argument binds these, and
    `detail` is *in* the key set because it is the value whose schema the fixing
    is about.
    """
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(1, 2),
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)),
        capture_logs() as captured,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    (line,) = [entry for entry in captured if entry["event"] == SWEEP_DISPATCHED_EVENT]
    assert set(EVENT_KEYS) <= set(line)
    assert line["collector"] == AN_ORDINARY_COLLECTOR
    assert line["task"] == collection_task_name(AN_ORDINARY_COLLECTOR)
    assert line["enqueued"] == AN_INTERRUPTED_COUNT
    assert line["refused"] == 0
    assert line["detail"] == outcome.detail


@pytest.mark.django_db
def test_a_refused_run_emits_its_own_event_and_one_line_per_refused_package() -> None:
    """`CPM-FR-15` gives an operator a count; the log is what gives them a recovery path.

    A `detail` column cannot hold ten thousand primary keys, so a partial sweep's
    row says how many were refused and the first reason -- and each refusal is a
    log line naming its package. Without that an operator reading "9,998 of 10,000
    enqueued" has no way to find the two.

    The run-level event is the *refused* one rather than the dispatched one,
    because nothing was enqueued: an operator asking "why did nothing collect"
    reads a different line from one asking "what did this sweep do".
    """
    selection = (1, 2, 3)
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=selection,
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR), refuse=selection),
        capture_logs() as captured,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    (run_line,) = [entry for entry in captured if entry["event"] == SWEEP_REFUSED_EVENT]
    assert set(EVENT_KEYS) <= set(run_line)
    assert run_line["detail"] == outcome.detail
    assert run_line["enqueued"] == 0

    per_package = [entry for entry in captured if entry["event"] == SWEEP_PACKAGE_REFUSED_EVENT]
    assert [entry["package_id"] for entry in per_package] == list(selection)
    for entry in per_package:
        assert set(PACKAGE_EVENT_KEYS) <= set(entry)
        assert ABrokerRefusalError.__name__ in entry["detail"]


@pytest.mark.django_db
def test_a_skipped_run_emits_the_skip_event_rather_than_either_of_the_others() -> None:
    """Nothing went wrong, and a line saying "refused" would read as though something had."""
    collector = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name=AN_ORDINARY_COLLECTOR,
        selection=(1,),
    )
    CollectionRun.objects.create(
        collector=AN_ORDINARY_COLLECTOR,
        started_at=FIXED_INSTANT,
        status=RunState.RUNNING.value,
        trace_id="a-previous-dispatch",
    )

    with (
        registered_collector(collector),
        _enqueue_recorded(collection_task_name(AN_ORDINARY_COLLECTOR)),
        capture_logs() as captured,
    ):
        outcome = dispatch(collector=AN_ORDINARY_COLLECTOR, clock=SystemClock())

    events = {entry["event"] for entry in captured}
    assert SWEEP_SKIPPED_EVENT in events
    assert SWEEP_DISPATCHED_EVENT not in events
    assert SWEEP_REFUSED_EVENT not in events

    (line,) = [entry for entry in captured if entry["event"] == SWEEP_SKIPPED_EVENT]
    assert set(EVENT_KEYS) <= set(line)
    assert line["detail"] == outcome.detail


# ---------------------------------------------------------------------------
# The two remaining selections, proved behaviourally rather than by rendered SQL.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_socket")
def test_the_source_release_selection_offers_only_packages_with_a_source_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative half `tests/unit/django_apps/test_sweep.py` cannot make.

    A rendered-SQL assertion is satisfied by a selection that mentions the right
    column and filters on it the wrong way round, or that widens to an `OR`. What
    is not satisfied by any of those is a package the collector would refuse
    being absent from the queue: `source_for` raises for a blank
    `source_repository_url`, so a sweep that offered one would write a `failed`
    ledger row for it, and there is no such row.
    """
    answerable = Package.objects.create(
        canonical_name="with-a-repository",
        resolved_at=FIXED_INSTANT,
        source_repository_url="https://github.com/owner/with-a-repository",
    )
    unresolved = Package.objects.create(canonical_name="with-none", resolved_at=FIXED_INSTANT)

    with _enqueue_intercepted(collection_task_name(SOURCE_RELEASE_NAME), monkeypatch) as accepted:
        outcome = dispatch(collector=SOURCE_RELEASE_NAME, clock=SystemClock())

    assert accepted == [answerable.pk]
    assert outcome.enqueued == 1
    assert unresolved.pk not in accepted


@pytest.mark.django_db
def test_the_feedstock_selection_offers_only_packages_resolution_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same negative half for the mapping `CPM-UJ-2` is written about.

    Absence of a feedstock may not be claimed for a package whose identity is
    unresolved, so `source_for` refuses an `unknown` or `error` mapping -- and a
    selection widened to offer them would write one `failed` run per package per
    week, which is exactly what `CPM-CURRENCY-S03` deferred to this story. The
    reached outcomes are offered and the unreached one is not.
    """
    offered = []
    for name, outcome_value in (
        ("reached-established", ESTABLISHED),
        ("reached-not-found", OutcomeState.NOT_FOUND.value),
        ("reached-not-applicable", OutcomeState.NOT_APPLICABLE.value),
    ):
        package = Package.objects.create(canonical_name=name, resolved_at=FIXED_INSTANT)
        PackageMapping.objects.create(
            package=package,
            kind=MappingKind.FEEDSTOCK.value,
            outcome=outcome_value,
            resolved_at=FIXED_INSTANT,
        )
        offered.append(package.pk)

    unresolved = Package.objects.create(canonical_name="unreached", resolved_at=FIXED_INSTANT)
    PackageMapping.objects.create(
        package=unresolved,
        kind=MappingKind.FEEDSTOCK.value,
        outcome=OutcomeState.UNKNOWN.value,
        resolved_at=FIXED_INSTANT,
    )
    # A distractor of another kind on one of the offered packages: a selection
    # that dropped the `kind` filter would read this row and would still pass a
    # case in which every package carried exactly one mapping.
    PackageMapping.objects.create(
        package=unresolved,
        kind=MappingKind.RELEASE_ECOSYSTEM.value,
        outcome=ESTABLISHED,
        resolved_at=FIXED_INSTANT,
    )

    with _enqueue_intercepted(collection_task_name(FEEDSTOCK_NAME), monkeypatch) as accepted:
        outcome = dispatch(collector=FEEDSTOCK_NAME, clock=SystemClock())

    assert sorted(accepted) == sorted(offered)
    assert outcome.enqueued == len(offered)
    assert unresolved.pk not in accepted
