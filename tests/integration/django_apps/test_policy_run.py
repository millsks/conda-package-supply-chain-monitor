"""The orchestration against a real database: the cut-off, the order, and the partial ending.

`CPM-AD-21` is four claims and none of them can be shown without a database. The
cut-off is a query over the run ledger. The ordered read is a pass looking at
rows another pass wrote *in this run*. The per-package transaction boundary is
only real if a rollback actually rolls something back. And the `partial` ending is
a column on a row the recorder's `finally` wrote.

**The cut-off is the part worth stating twice.** `CPM-AD-21` names exactly one
forbidden value, the current time, because a cut-off of *now* silently includes
evidence from a collection run still in flight -- so the same version replayed
against the same nominal cut-off reads a different evidence set and answers
differently, which is precisely what `CPM-FR-22` promises cannot happen. A ledger
with nothing completed has no correct cut-off, so the run refuses rather than
inventing one, and it refuses *before* opening a ledger row: a run that cannot
read evidence correctly should leave no row claiming it tried.

**Time comes from stopped clocks, never from the wall.** `tests/clocks.py` owns
the instants and derives the later one from the earlier, so the ordering the
cut-off cases assert cannot drift.

Every case here rolls back. `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the database as found; the fixture derived tables are built
once for the session by `conftest.py` and only their rows roll back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest
import structlog

from conda_package_supply_chain_monitor.core import policy_run as policy_run_module
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.core.policy_run import EVALUATION_FAILED_EVENT
from conda_package_supply_chain_monitor.core.policy_run import PolicyRunError
from conda_package_supply_chain_monitor.core.policy_run import choose_evidence_cutoff
from conda_package_supply_chain_monitor.core.policy_run import execute_policy_run
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.core.tasks import run_policy
from conda_package_supply_chain_monitor.identity.models import Package
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.clocks import OBSERVATION_GAP
from tests.passes import A_VERDICT
from tests.passes import FIRST_DOMAIN
from tests.passes import SECOND_DOMAIN
from tests.passes import failing_pass_class
from tests.passes import fixture_derived_models
from tests.passes import reading_pass_class
from tests.passes import registered_pass
from tests.passes import undeclared_contribution_pass_class
from tests.passes import working_pass_class

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from django.db import models
    from structlog.typing import EventDict

#: The event the capture fixture logs to prove the capture is live before a case
#: asserts over what it caught. `tests/integration/django_apps/test_run_ledger.py`
#: establishes the pattern and the reason: `capture_logs` binds a proxy into its
#: own processor chain, so a module-scope logger created earlier is invisible to
#: it, and an assertion over an empty list would pass for the wrong reason.
CAPTURE_CONTROL: Final[str] = "policy-run-capture-control"

#: The policy version every case records. `CPM-AD-8` makes the version data an
#: operator supplies rather than a constant this product ships, so any stable
#: string does here -- what the cases assert is that it reaches the ledger row
#: and the rollup's per-domain map.
A_POLICY_VERSION: Final[str] = "cpm-fixture-policy-1"

#: The collector name the fixture collection runs carry. Prefixed so it cannot be
#: confused with a real collector's the day one exists.
A_COLLECTOR: Final[str] = "cpm-fixture-collector"

#: How much later the second fixture collection run ends. Derived from
#: `OBSERVATION_GAP` rather than written out, so the two instants cannot drift
#: into an ordering nobody intended.
A_LATER_ENDING: Final = OBSERVATION_GAP * 2


def a_package(name: str) -> Package:
    """Create one package with a resolved identity.

    Args:
        name: Its canonical name, which is unique.

    Returns:
        The saved `Package`. `resolved_at` comes from `tests.clocks.FIXED_INSTANT`
        rather than from the wall clock, exactly as `CPM-AD-26` requires of every
        writer.

    """
    return Package.objects.create(canonical_name=name, resolved_at=FIXED_INSTANT)


def an_ended_collection_run(finished_at: datetime) -> CollectionRun:
    """Record a collection run that has ended.

    Written directly rather than through `core/ledger.py`'s recorder, because
    what these cases need is a row with a *chosen* `finished_at`: the recorder
    reads its own clock, and a case that wound one forward to place two endings
    would be asserting against the fixture rather than against the query.

    Args:
        finished_at: When the run ended.

    Returns:
        The saved row.

    """
    return CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=FIXED_INSTANT,
        finished_at=finished_at,
        status=RunState.SUCCEEDED,
    )


def a_running_collection_run(started_at: datetime) -> CollectionRun:
    """Record a collection run that has started and not finished.

    Args:
        started_at: When the run began. This is the instant that bounds the
            cut-off: no in-flight run can write evidence from before it started.

    Returns:
        The saved row.

    """
    return CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=started_at,
        status=RunState.RUNNING,
    )


@pytest.mark.django_db
def test_the_cutoff_is_the_newest_ending_a_run_still_going_cannot_write_behind() -> None:
    """`CPM-AD-21`: the cut-off is a completed collection run's `finished_at`.

    Three rows: an older ending, a newer one, and a run still `running` that
    started *after* both of them ended. That last detail is the whole case. A
    run in flight can only write evidence from instants after it began, so one
    that began after the newest ending cannot have written behind it -- and the
    newest ending is therefore safe. The unfinished row contributes nothing, and
    the next case is the one where it does.
    """
    an_ended_collection_run(FIXED_INSTANT)
    newest = an_ended_collection_run(FIXED_INSTANT + A_LATER_ENDING)
    a_running_collection_run(FIXED_INSTANT + A_LATER_ENDING + OBSERVATION_GAP)

    assert choose_evidence_cutoff() == newest.finished_at
    assert newest.finished_at is not None
    assert newest.finished_at > FIXED_INSTANT


@pytest.mark.django_db
def test_a_run_still_going_bounds_the_cutoff_back_to_before_it_began() -> None:
    """The hazard the newest ending alone walks straight into.

    A run that started at `FIXED_INSTANT` and has not finished is free to write
    evidence stamped at any instant after that -- including instants *behind* a
    later run's ending. Take the cut-off as that later ending and a pass reads
    rows the in-flight run is still adding to, so the same version replayed
    against the same nominal cut-off answers differently every time, which is
    exactly what `CPM-FR-22` promises cannot happen.

    So the cut-off is bounded to the newest ending at or before the earliest
    still-running start: `safe` here, and not `unsafe`, even though `unsafe` is
    newer. The two endings straddle the in-flight run's start, which is the only
    arrangement that can tell a bounded cut-off from an unbounded one.
    """
    safe = an_ended_collection_run(FIXED_INSTANT - OBSERVATION_GAP)
    a_running_collection_run(FIXED_INSTANT)
    unsafe = an_ended_collection_run(FIXED_INSTANT + A_LATER_ENDING)

    chosen = choose_evidence_cutoff()

    assert chosen == safe.finished_at
    assert chosen != unsafe.finished_at
    assert unsafe.finished_at is not None
    assert chosen < unsafe.finished_at


@pytest.mark.django_db
def test_an_ending_entirely_behind_a_run_still_going_is_no_cutoff_at_all() -> None:
    """A stuck collection run holds policy runs back rather than letting them read half-written evidence.

    The consequence of the bound, stated as its own case because it is the one
    an operator meets: with the only ending *after* the earliest in-flight start,
    there is no instant this run can read as of, so it refuses. That is the
    correct trade -- `CPM-NFR-3` degrades to stale evidence, and a policy run that
    does not happen leaves the previous rollup standing, where one reading a
    half-written collection would replace it with an answer no replay reproduces.
    """
    a_running_collection_run(FIXED_INSTANT)
    an_ended_collection_run(FIXED_INSTANT + A_LATER_ENDING)

    with pytest.raises(PolicyRunError, match="no evidence cut-off"):
        choose_evidence_cutoff()


@pytest.mark.django_db
def test_a_run_that_failed_after_writing_still_gives_a_cutoff() -> None:
    """The cut-off query is the mirror of `unfinished()`, and does not read `status`.

    A collection run that failed *after* writing some evidence has still ended,
    and its rows are in the ledger. Choosing a cut-off earlier than evidence the
    system holds would hide those rows from every pass -- which is a quieter
    failure than the one the cut-off exists to prevent, and just as wrong.
    """
    CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=FIXED_INSTANT,
        finished_at=LATER_INSTANT,
        status=RunState.FAILED,
    )

    assert choose_evidence_cutoff() == LATER_INSTANT


@pytest.mark.django_db
def test_a_ledger_with_nothing_completed_refuses_rather_than_using_now() -> None:
    """The one value `CPM-AD-21` forbids, refused rather than defaulted to.

    Two states in one case because they are the same state: an empty ledger and a
    ledger holding only a `running` row both have no completed run behind them.
    The refusal happens before the recorder opens, so no `policy_runs` row is
    left claiming a run that could not read evidence.
    """
    with pytest.raises(PolicyRunError, match="no evidence cut-off"):
        choose_evidence_cutoff()

    a_running_collection_run(FIXED_INSTANT)

    with pytest.raises(PolicyRunError, match="no evidence cut-off"):
        execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    assert PolicyRun.objects.count() == 0, "a run that could not choose a cut-off must leave no ledger row"


@pytest.mark.django_db
def test_a_run_records_its_version_and_its_cutoff_and_finalizes_succeeded() -> None:
    """The ordinary path, which every other case here is a deviation from."""
    an_ended_collection_run(FIXED_INSTANT)
    a_package("numpy")

    summary = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    row = PolicyRun.objects.get(pk=summary.policy_run.pk)
    assert row.policy_version == A_POLICY_VERSION
    assert row.evidence_cutoff == FIXED_INSTANT
    assert row.status == RunState.SUCCEEDED
    assert row.started_at == LATER_INSTANT
    assert row.finished_at == LATER_INSTANT
    assert summary.failed_packages == ()


@pytest.mark.django_db
def test_each_pass_writes_only_its_own_table_keyed_to_the_package_and_the_run(
    derived_tables: tuple[type[models.Model], type[models.Model]],
) -> None:
    """`CPM-AD-21`: a pass owns one per-domain table, keyed `(package, policy_run)`.

    Two passes, two domains, two packages: four derived rows, each naming the
    package it is about and the run that computed it. A table keyed on the
    package alone would be indistinguishable here until the second run
    overwrote the first, which is exactly the history loss the key exists to
    prevent.
    """
    first_model, second_model = derived_tables
    an_ended_collection_run(FIXED_INSTANT)
    packages = [a_package("numpy"), a_package("scipy")]

    with (
        registered_pass(working_pass_class(name=FIRST_DOMAIN, derived_model=first_model)),
        registered_pass(working_pass_class(name=SECOND_DOMAIN, derived_model=second_model)),
    ):
        summary = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    for model in (first_model, second_model):
        rows = model.objects.filter(policy_run_id=summary.policy_run.pk)
        assert rows.count() == len(packages)
        assert sorted(rows.values_list("package_id", flat=True)) == sorted(package.pk for package in packages)
        assert set(rows.values_list("verdict", flat=True)) == {A_VERDICT}


@pytest.mark.django_db
def test_a_later_pass_reads_an_earlier_passs_rows_for_this_run(
    derived_tables: tuple[type[models.Model], type[models.Model]],
) -> None:
    """The ordered read, asserted through the database the run wrote.

    The second pass records how many of the first pass's rows it could see for
    the same package and the same run. One means the passes executed in declared
    order *and* that a later pass can read an earlier one's work inside the
    package's transaction. Zero would mean either had failed, and no other column
    would show which.
    """
    first_model, second_model = derived_tables
    an_ended_collection_run(FIXED_INSTANT)
    package = a_package("numpy")

    with (
        registered_pass(working_pass_class(name=FIRST_DOMAIN, derived_model=first_model)),
        registered_pass(reading_pass_class(name=SECOND_DOMAIN)),
    ):
        execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    assert second_model.objects.get(package_id=package.pk).saw_earlier == 1


@pytest.mark.django_db
def test_one_package_failing_rolls_back_only_that_package_and_finalizes_partial(
    derived_tables: tuple[type[models.Model], type[models.Model]],
) -> None:
    """`CPM-AD-23`: one package is the atomic unit, and the run says so.

    The failing pass writes its row *before* raising, so the rollback is
    observable: if the transaction boundary were anywhere but around one package,
    that row would be there. Three assertions, each about a different half of the
    rule -- the failing package's derived row is gone, the other package's
    survives, and the run finalizes `partial` rather than `failed`, because a run
    that did some of its work is a different operational fact from one that did
    none.
    """
    _first_model, second_model = derived_tables
    an_ended_collection_run(FIXED_INSTANT)
    doomed = a_package("numpy")
    surviving = a_package("scipy")

    with registered_pass(failing_pass_class(name=SECOND_DOMAIN, failing=[doomed.pk])):
        summary = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    assert summary.failed_packages == (doomed.pk,)
    assert second_model.objects.filter(package_id=doomed.pk).count() == 0
    assert second_model.objects.filter(package_id=surviving.pk).count() == 1
    assert PolicyRun.objects.get(pk=summary.policy_run.pk).status == RunState.PARTIAL
    assert PackageHealth.objects.filter(package=doomed).count() == 0
    assert PackageHealth.objects.filter(package=surviving).count() == 1


@pytest.mark.django_db
def test_a_pass_returning_a_column_it_never_declared_fails_that_package(
    derived_tables: tuple[type[models.Model], type[models.Model]],
) -> None:
    """The runtime half of the single-owner rule.

    Registration checks what a pass *claims*; this is what checks what it
    returned. A pass that declared nothing and wrote into another pass's column
    would otherwise walk past every static check there is.

    Every package fails here, because the broken pass is broken for all of them
    -- so the ending is `failed` rather than `partial`, which is the case below's
    subject and is asserted there. What this one is about is that the *reason*
    reaches the refusal at all.
    """
    first_model, _second_model = derived_tables
    an_ended_collection_run(FIXED_INSTANT)
    package = a_package("numpy")

    with registered_pass(undeclared_contribution_pass_class(name=FIRST_DOMAIN)):
        summary = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    assert summary.failed_packages == (package.pk,)
    assert first_model.objects.count() == 0
    assert PackageHealth.objects.count() == 0


@pytest.mark.django_db
def test_a_run_in_which_every_package_failed_finalizes_failed_not_partial() -> None:
    """A run that accomplished nothing is `failed`, and the distinction is queryable.

    `core/runs.py` keeps the four endings distinct so a reader never has to infer
    which happened, and `RunLedgerQuerySet.failed()` deliberately excludes
    `partial` -- so a run that wrote no rollup row at all and recorded itself
    `partial` is invisible to the one query `CPM-FR-38` exists to make
    answerable. Two packages, both failing, so the case is about the *proportion*
    rather than about there being only one package to fail.
    """
    an_ended_collection_run(FIXED_INSTANT)
    doomed = [a_package("numpy"), a_package("scipy")]

    with registered_pass(failing_pass_class(name=SECOND_DOMAIN, failing=[package.pk for package in doomed])):
        summary = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    assert summary.rollup_rows == 0
    assert sorted(summary.failed_packages) == sorted(package.pk for package in doomed)
    row = PolicyRun.objects.get(pk=summary.policy_run.pk)
    assert row.status == RunState.FAILED
    assert row in PolicyRun.objects.failed()
    assert str(len(doomed)) in row.detail


@pytest.mark.django_db
def test_an_empty_inventory_completes_having_written_nothing() -> None:
    """No packages is not a failure; it is a monitor with nothing to monitor yet.

    `CPM-AD-25` creates package rows from the inventory, and there is a state
    before the first one. A run that refused here would make the very first
    deployment look broken.
    """
    an_ended_collection_run(FIXED_INSTANT)

    summary = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    assert summary.rollup_rows == 0
    assert PackageHealth.objects.count() == 0
    assert PolicyRun.objects.get(pk=summary.policy_run.pk).status == RunState.SUCCEEDED


@pytest.mark.django_db
def test_the_run_is_not_wrapped_in_a_transaction_that_could_take_its_row_away() -> None:
    """`core/ledger.py`'s ordering guarantee, asserted from the orchestration's side.

    The row exists with status `running` *before* the work happens, which is the
    whole reason the ledger is in a database: a worker killed mid-run leaves a row
    that `unfinished()` finds. A pass is what looks, because a pass runs between
    the insert and the finalization -- and because a source scan
    (`tests/unit/django_apps/test_collector_base_audit.py`) can only show that no
    `transaction.atomic()` encloses the recorder in *this* module, not that the
    row is really committed by then.
    """
    an_ended_collection_run(FIXED_INSTANT)
    a_package("numpy")
    seen: list[str] = []

    class LookingPass(working_pass_class()):  # type: ignore[misc] - a fixture built from a fixture
        """A pass that reads its own run's ledger row while the run is in flight."""

        def evaluate(self, package, *, policy_run, evidence_cutoff):  # type: ignore[no-untyped-def] - the base's signature, read for one value
            """Record the status the ledger holds for this run right now."""
            seen.append(PolicyRun.objects.get(pk=policy_run.pk).status)
            return {}

    with registered_pass(LookingPass):
        summary = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    assert seen == [RunState.RUNNING]
    assert PolicyRun.objects.get(pk=summary.policy_run.pk).status == RunState.SUCCEEDED


@pytest.mark.django_db
def test_the_fixture_derived_tables_are_the_ones_the_passes_write(
    derived_tables: tuple[type[models.Model], type[models.Model]],
) -> None:
    """The anti-vacuity guard for every case above that counts derived rows.

    A fixture whose tables were built from different classes than the passes
    write to would make every "the rollback removed the row" assertion pass by
    counting an empty table nothing ever wrote to.
    """
    assert derived_tables == fixture_derived_models()
    for model in derived_tables:
        assert model.objects.count() == 0


@pytest.mark.django_db
def test_the_beat_scheduled_task_runs_the_whole_thing() -> None:
    """`CPM-AD-20`: beat schedules the run, and the run is what the task is.

    The task is the one seam between a `django_celery_beat` row and this
    orchestration, and everything above it calls `execute_policy_run` directly --
    so a task that passed the wrong argument, built no clock, or called nothing
    at all would leave every case above green. Called as a plain function rather
    than through `.delay()`, because `CELERY_TASK_ALWAYS_EAGER` short-circuits to
    `apply()` anyway and the extra layer would only obscure which half failed.

    The version reaching the ledger row is the assertion that matters: it is the
    value an operator sets on the beat row, and `CPM-AD-8` makes it data rather
    than a constant this module could have supplied for itself.
    """
    an_ended_collection_run(FIXED_INSTANT)
    package = a_package("numpy")

    written = run_policy(A_POLICY_VERSION)

    assert written == 1
    assert PolicyRun.objects.get().policy_version == A_POLICY_VERSION
    assert PackageHealth.objects.get(package=package).evidence_cutoff == FIXED_INSTANT


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[EventDict]]:
    """Capture what `core/policy_run.py` logs, with the two guards the plain helper lacks.

    The reasoning is `tests/unit/test_drain.py`'s and is not restated: the
    module-scope logger is rebound so `capture_logs` binds a fresh proxy inside
    its own processor chain, and a control event proves the capture is live
    before the case runs.

    Args:
        monkeypatch: pytest's patcher, which restores the module's own logger.

    Yields:
        The captured events, in order.

    """
    monkeypatch.setattr(policy_run_module, "logger", structlog.get_logger(policy_run_module.__name__))
    with structlog.testing.capture_logs() as captured:
        policy_run_module.logger.warning(CAPTURE_CONTROL)
        assert [event["event"] for event in captured] == [CAPTURE_CONTROL], (
            "structlog.testing.capture_logs() cannot see core.policy_run's logger, so every assertion "
            "over what it logged would be vacuous"
        )
        captured.clear()
        yield captured


@pytest.mark.django_db
def test_a_failing_pass_is_logged_with_the_package_and_the_run(captured_events: list[EventDict]) -> None:
    """The count in the ledger row says how many; this line says which.

    `EVALUATION_FAILED_EVENT` is the only operational record of *which* package a
    pass broke on. The ledger's `detail` carries "n of m", and an operator handed
    a number and no names has to walk the whole inventory to find the one that
    failed -- so the constant's claim that it is asserted somewhere has to be
    true. The traceback is asserted too: `logger.exception` is what puts the
    pass's own error in the record, and `logger.error` would look identical here
    while losing it.
    """
    an_ended_collection_run(FIXED_INSTANT)
    doomed = a_package("numpy")
    a_package("scipy")

    with registered_pass(failing_pass_class(name=SECOND_DOMAIN, failing=[doomed.pk])):
        summary = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    failures = [event for event in captured_events if event["event"] == EVALUATION_FAILED_EVENT]
    assert len(failures) == 1
    assert failures[0]["package_pk"] == doomed.pk
    assert failures[0]["policy_run_pk"] == summary.policy_run.pk
    assert failures[0]["exc_info"] is True, "the pass's own traceback is the half a bare error() would lose"
