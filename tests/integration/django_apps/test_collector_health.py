"""`CPM-FR-38`: a collection failure is answerable in the application, not only in the logs.

What the unit tier cannot show. `RunLedgerQuerySet.failed()` is a filter and an
ordering, and both are claims about what a *database* returns: that only the
failed runs come back, that the four other endings do not, and that the newest
ending is first. A queryset asserted without a database asserts the text of a
`filter()` call, which is the same thing written twice.

**Why the query exists at all.** `CPM-NFR-3` says the system "degrades to stale
evidence, never to a clean result", and `CPM-EVIDENCE-S06`'s story is that the
coverage view has to tell an operator what the monitor cannot see. A failure
that lives only in a log stream fails that twice over: it is not joinable to the
package it was about, and it is gone whenever log retention says it is. The row
already carries everything the surface needs -- `detail` says what went wrong and
`trace_id` leads to the span it went wrong in (`CPM-AD-15`) -- so this is a
query rather than a projection, and the only question is whether the query is
right.

**The blank `trace_id` is the case worth having.** `RunLedgerModel` declares the
column `blank=True, default=""` and says an absent span never blocks a run, so a
failure recorded outside a traced path carries an empty string. A `failed()`
that filtered those out -- by joining, by excluding blanks, by any of the shapes
that look like tidying -- would hide exactly the failures that happened where
tracing was not running, which is disproportionately where things go wrong.

**`partial` is asserted absent rather than left unmentioned.** A run that did
some of its work is a different operational fact from one that did none, and
`core/runs.py` keeps the four endings distinct precisely so nobody has to infer
which happened. (Four, not five: `RunState` has five members and `running` is not
an ending -- it is the absence of one, which is what `unfinished()` is for.)
Folding `partial` in here would be a judgement made in a queryset that the
vocabulary deliberately left to the caller.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction
the test runner discards, so the rows one case writes are invisible to the next.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest

from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.runs import RunState
from tests.clocks import FIXED_INSTANT

#: The collector the cases record against. A real-looking name rather than a
#: fixture prefix: `collector` is a plain `CharField` the ledger never validates,
#: and a name that looks like a source is what a failure row actually carries.
A_COLLECTOR: Final[str] = "pypi"

#: A second collector, for the row that proves `failed()` does not scope itself
#: to one. The query answers "what has broken lately" across the whole ledger;
#: narrowing to a collector is the caller's `filter()`, not this method's.
ANOTHER_COLLECTOR: Final[str] = "conda-forge"

#: The package a scoped run names. An integer, because `CPM-AD-3`'s package
#: table does not exist yet and `core/models.py` records why the column is not a
#: `ForeignKey`.
A_PACKAGE_ID: Final[int] = 4269

#: What a failed run's `detail` says. The transport's own failure shape, so the
#: assertion is about a string a real run would write rather than a placeholder.
A_FAILURE_DETAIL: Final[str] = "TransportError: the call to https://pypi.invalid/x produced no answer"

#: A second detail, so "each failure exposes its own detail" is a claim two rows
#: can disagree about. One detail asserted twice would pass against a query that
#: returned the same row twice.
ANOTHER_FAILURE_DETAIL: Final[str] = "ValueError: the payload for package 4269 is malformed"

#: The `trace_id` a traced failure carries, in the `032x` form
#: `core/ledger.py` formats and `RunLedgerModel` sizes the column for.
A_TRACE_ID: Final[str] = f"{7:032x}"

#: What an untraced failure carries. The column's own default, spelled here so
#: the case asserts the declared empty rather than a `None` that would mean the
#: column had been made nullable.
NO_TRACE_ID: Final[str] = ""

#: How many failures the ordering case writes.
THREE_FAILURES: Final[int] = 3


def _record(
    *,
    status: RunState,
    collector: str = A_COLLECTOR,
    detail: str = "",
    trace_id: str = NO_TRACE_ID,
    finished_offset: timedelta = timedelta(0),
) -> CollectionRun:
    """Write one finished ledger row directly, without going through the recorder.

    The recorder (`core/ledger.py`) is proved by its own integration module. What
    these cases need is a *ledger in a known state* -- several endings, several
    collectors, several finishing instants -- and driving that through the
    recorder would make each arrangement a second test of the recorder and would
    make the finishing instants whatever the clock happened to say.

    Args:
        status: The ending to record.
        collector: The collector name the row carries.
        detail: What the row says went wrong.
        trace_id: The span the failure belongs to, or the declared empty.
        finished_offset: How long after `FIXED_INSTANT` the run ended. Negative
            values land it earlier, which is how the ordering case arranges a
            chronology it can assert.

    Returns:
        The written row.

    """
    return CollectionRun.objects.create(
        collector=collector,
        package_id=A_PACKAGE_ID,
        status=status,
        detail=detail,
        trace_id=trace_id,
        started_at=FIXED_INSTANT + finished_offset - timedelta(seconds=1),
        finished_at=FIXED_INSTANT + finished_offset,
    )


@pytest.mark.django_db
def test_only_failed_runs_are_returned() -> None:
    """The filter, against every other ending the vocabulary has.

    All five states are written, so the case fails if `failed()` widens to
    anything else -- and, in the other direction, if it narrows to nothing. A
    case that wrote only a failure and a success would pass against a query that
    admitted `partial`, `skipped` or `running`, which are the three a reader is
    most likely to think of as "not really fine".
    """
    failure = _record(status=RunState.FAILED, detail=A_FAILURE_DETAIL)
    _record(status=RunState.SUCCEEDED)
    _record(status=RunState.PARTIAL, detail="one of two sources answered")
    _record(status=RunState.SKIPPED, detail="inside the observation window")
    CollectionRun.objects.create(
        collector=A_COLLECTOR,
        package_id=A_PACKAGE_ID,
        status=RunState.RUNNING,
        started_at=FIXED_INSTANT,
    )

    assert [row.pk for row in CollectionRun.objects.failed()] == [failure.pk]


@pytest.mark.django_db
def test_each_failure_exposes_its_own_detail_and_trace_id() -> None:
    """AC 2's second half: the row carries what the surface has to show.

    Two failures with different details and different traces, because the claim
    is that each failure exposes *its own*. One row asserted twice would hold
    against a query that returned a single row duplicated, and against a
    projection that collapsed the detail to whichever one it met first.
    """
    _record(
        status=RunState.FAILED,
        detail=A_FAILURE_DETAIL,
        trace_id=A_TRACE_ID,
        finished_offset=-timedelta(minutes=1),
    )
    _record(
        status=RunState.FAILED,
        collector=ANOTHER_COLLECTOR,
        detail=ANOTHER_FAILURE_DETAIL,
        trace_id=f"{8:032x}",
    )

    reported = {(row.collector, row.detail, row.trace_id) for row in CollectionRun.objects.failed()}

    assert reported == {
        (A_COLLECTOR, A_FAILURE_DETAIL, A_TRACE_ID),
        (ANOTHER_COLLECTOR, ANOTHER_FAILURE_DETAIL, f"{8:032x}"),
    }


@pytest.mark.django_db
def test_a_failure_with_no_trace_is_still_returned() -> None:
    """The row a tidier query would drop, and the one it is worst to drop.

    `RunLedgerModel` declares `trace_id` `blank=True, default=""` and says an
    absent span never blocks a run, so a failure recorded outside a traced path
    carries the empty string. Excluding it -- by a join, by a truthiness filter,
    by any shape that reads like tidying -- would hide the failures that happened
    where tracing was not running, which is disproportionately where things go
    wrong.
    """
    untraced = _record(status=RunState.FAILED, detail=A_FAILURE_DETAIL, trace_id=NO_TRACE_ID)

    returned = list(CollectionRun.objects.failed())

    assert [row.pk for row in returned] == [untraced.pk]
    assert returned[0].trace_id == NO_TRACE_ID


@pytest.mark.django_db
def test_failures_are_ordered_by_their_ending_newest_first() -> None:
    """"What has broken lately" is the question, so the order is part of the answer.

    Written deliberately out of chronological order, and with the *earliest*
    failure inserted last, so a query that returned the database's own arbitrary
    order -- which for a fresh table is insertion order -- would produce exactly
    the reverse of what is asserted. An unordered page of failures is a different
    answer on every read, which is the shape of bug nobody reports because it
    never looks broken twice the same way.
    """
    middle = _record(status=RunState.FAILED, detail="second", finished_offset=-timedelta(hours=1))
    newest = _record(status=RunState.FAILED, detail="third", finished_offset=timedelta(0))
    oldest = _record(status=RunState.FAILED, detail="first", finished_offset=-timedelta(hours=2))

    ordered = list(CollectionRun.objects.failed())

    assert len(ordered) == THREE_FAILURES
    assert [row.pk for row in ordered] == [newest.pk, middle.pk, oldest.pk]


@pytest.mark.django_db
def test_a_ledger_with_runs_but_no_failures_reports_none() -> None:
    """A working monitor, which is the state the surface renders most of the time.

    Named for what it actually arranges. An earlier version of this called itself
    the empty-ledger case while writing a succeeded row first, which is a
    different claim wearing the wrong name -- and the genuinely empty table was
    then covered nowhere. Both are worth having and neither substitutes for the
    other: this one shows the filter rejecting rows that exist, and the case
    below shows the query surviving having nothing to reject.
    """
    _record(status=RunState.SUCCEEDED)

    assert list(CollectionRun.objects.failed()) == []


@pytest.mark.django_db
def test_an_empty_ledger_reports_no_failures() -> None:
    """The boundary the surface meets first, and the one a `.get()` would break on.

    A deployment that has never run a collection is the state every one of them
    starts in, and the collector-health view renders it before it renders
    anything else. `failed()` answers an empty queryset rather than raising,
    which is what lets the caller iterate without a length check.
    """
    assert CollectionRun.objects.exists() is False
    assert list(CollectionRun.objects.failed()) == []
