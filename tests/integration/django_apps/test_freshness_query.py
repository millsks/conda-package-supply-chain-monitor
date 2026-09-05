"""AC 1's read path against a real table: which observation is the latest, and is it old.

What the unit tier cannot show. `tests/unit/django_apps/test_freshness.py` proves
the comparison -- `is_stale`, `freshness_of`, the boundary, the naive-instant
refusal -- and proves it without a database because none of it reaches one. What
it cannot reach is `latest_observation`, which is a `filter(...).aggregate(...)`
and therefore a claim about what a *database* returns. Its one appearance in that
module is inside a `pytest.raises`, where the model refusal fires before the
query is ever built.

**Two mutations this module exists to fail, both of which survive everything
else.** Dropping `filter(package_id=package_id)` makes the newest observation of
*any* package answer for every package -- a busy package would keep a neglected
one looking fresh forever. Swapping `Max` for `Min` compares the *oldest*
observation against the target, so a package re-observed this morning reports
stale for as long as it has any old row at all. Neither raises, neither changes a
row count, and both are one token.

**And the wiring, which is the other half of `CPM-AD-28`.**
`Collector.freshness()` is where the two things only a collector knows meet the
comparison: which table holds its observations (`CPM-AD-7`) and what target it
declared. Written against literals, `freshness_of` cannot tell whether the base
handed it the declared target or the observation window -- and `tests/collectors.py`
declares those an order of magnitude apart, so the substitution flips verdicts
rather than raising. The cases below drive the method itself for that reason.

Every test here rolls back. The fixture table is created once per session and
outside any transaction, for the reason
`tests/integration/django_apps/test_collection.py`'s equivalent records: SQLite's
schema editor refuses to open inside a multi-statement transaction.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.db import connection

from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.freshness import FreshnessReport
from conda_package_supply_chain_monitor.core.freshness import latest_observation
from tests.clocks import FIXED_INSTANT
from tests.collectors import DETERMINATE_VALUE
from tests.collectors import FIXTURE_FRESHNESS_TARGET
from tests.collectors import FIXTURE_TABLE
from tests.collectors import RecordedTransport
from tests.collectors import collector_class
from tests.collectors import fixture_evidence_model
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django import DjangoDbBlocker

    from conda_package_supply_chain_monitor.core.models import AppendOnlyModel

#: The package the cases ask about.
A_PACKAGE: Final[int] = 11

#: A second package, whose rows must not answer the first one's question. This is
#: the package that makes the `package_id` filter falsifiable: without it, a
#: query that ignored scoping would return the same instant and pass.
ANOTHER_PACKAGE: Final[int] = 12

#: A third, with no rows at all, for the never-observed answer.
AN_UNOBSERVED_PACKAGE: Final[int] = 13

#: How much older than the target the stale row is, so the case sits clear of the
#: boundary -- which the unit tier asserts on purpose and this tier must not
#: accidentally depend on.
A_MARGIN: Final[timedelta] = timedelta(hours=1)


@pytest.fixture(scope="session")
def evidence_table(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[type[AppendOnlyModel]]:
    """The fixture evidence model with a real table behind it.

    Session scoped and built outside every test's transaction, and a stale table
    is dropped rather than collided with -- `--reuse-db` means a run killed
    between the create and the drop leaves one behind.

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


def _observe(model: type[AppendOnlyModel], *, package_id: int, age: timedelta) -> None:
    """Write one evidence row aged a stated interval before the fixed instant.

    Args:
        model: The fixture evidence model.
        package_id: The package the observation is about.
        age: How long before `FIXED_INSTANT` the observation was made.

    """
    model.objects.create(
        observed_at=FIXED_INSTANT - age,
        package_id=package_id,
        state=DETERMINATE_VALUE,
        detail="",
        body="",
        source="",
    )


@pytest.mark.django_db
def test_the_latest_observation_is_the_newest_row_for_that_package(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """Both halves of the query, and each is one token from being wrong.

    Three rows for the package, written oldest-last so that a query returning
    whatever the database offers first would answer the oldest. `Min` for `Max`
    fails here. A fourth row for another package, newer than all of them, so a
    query that dropped `filter(package_id=...)` answers *that* instant and fails
    here too -- which is the mutation that would otherwise let a busy package
    keep a neglected one looking permanently fresh.
    """
    _observe(evidence_table, package_id=A_PACKAGE, age=timedelta(days=2))
    _observe(evidence_table, package_id=A_PACKAGE, age=timedelta(days=5))
    newest_for_the_package = FIXED_INSTANT - timedelta(hours=6)
    _observe(evidence_table, package_id=A_PACKAGE, age=timedelta(hours=6))
    _observe(evidence_table, package_id=ANOTHER_PACKAGE, age=timedelta(minutes=1))

    assert latest_observation(evidence_table, package_id=A_PACKAGE) == newest_for_the_package


@pytest.mark.django_db
def test_a_package_with_no_rows_has_no_latest_observation(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """`None` rather than a raise, because never-observed is an answer.

    A table holding rows for other packages, so the case is about the *scoping*
    answering nothing rather than about an empty table. `freshness_of` turns this
    into `unknown`, which is what the vocabulary has for "we never looked".
    """
    _observe(evidence_table, package_id=ANOTHER_PACKAGE, age=timedelta(minutes=1))

    assert latest_observation(evidence_table, package_id=AN_UNOBSERVED_PACKAGE) is None


@pytest.mark.django_db
def test_a_collector_reports_its_own_evidence_as_stale_past_its_declared_target(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The wiring: this collector's table, this collector's target, one instant.

    The row is older than the declared freshness target and *younger* than
    nothing else that matters -- but it is far older than `FIXTURE_WINDOW`, which
    `tests/collectors.py` declares an order of magnitude shorter. So a base that
    passed the observation window where the target belongs would still report
    stale here and the case would pass for the wrong reason; the not-stale twin
    below is what closes that, because a row inside the target but outside the
    window reports stale under the substitution and fresh under the correct
    wiring.

    The status is carried through untouched, which is the separation the whole
    story rests on: `ok` and stale at the same time is exactly the state
    `CPM-SM-C1` describes and `CPM-AD-5` refuses to collapse into one field.
    """
    aged = FIXTURE_FRESHNESS_TARGET + A_MARGIN
    _observe(evidence_table, package_id=A_PACKAGE, age=aged)
    built = collector_class(declared_model=evidence_table)
    collector = built(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=RecordedTransport(payload=recorded_payload()),
    )

    report = collector.freshness(package_id=A_PACKAGE, now=FIXED_INSTANT, status=DETERMINATE_VALUE)

    assert report == FreshnessReport(status=DETERMINATE_VALUE, stale=True, observed_at=FIXED_INSTANT - aged)


@pytest.mark.django_db
def test_a_collector_reports_evidence_inside_its_target_as_fresh(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The twin that makes the case above about the *target* rather than about age.

    The row is deliberately older than `FIXTURE_WINDOW` and younger than
    `FIXTURE_FRESHNESS_TARGET`. Under the correct wiring it is fresh; under a
    base that compared against the observation window it is stale. One assertion
    separates the two, and without it both cases pass whichever value the base
    reaches for.
    """
    inside = FIXTURE_FRESHNESS_TARGET - A_MARGIN
    _observe(evidence_table, package_id=A_PACKAGE, age=inside)
    built = collector_class(declared_model=evidence_table)
    collector = built(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=RecordedTransport(payload=recorded_payload()),
    )

    report = collector.freshness(package_id=A_PACKAGE, now=FIXED_INSTANT, status=DETERMINATE_VALUE)

    assert report == FreshnessReport(status=DETERMINATE_VALUE, stale=False, observed_at=FIXED_INSTANT - inside)


@pytest.mark.django_db
def test_a_collector_with_no_evidence_for_a_package_reports_unknown(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The never-observed answer through the collector, not through the free function.

    A caller holding no observation supplies no status, and what comes back is
    `unknown` and not stale -- never `ok`, which would read as clean, and never
    stale, which would read as an old observation that does not exist.
    """
    _observe(evidence_table, package_id=ANOTHER_PACKAGE, age=timedelta(minutes=1))
    built = collector_class(declared_model=evidence_table)
    collector = built(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=RecordedTransport(payload=recorded_payload()),
    )

    report = collector.freshness(package_id=AN_UNOBSERVED_PACKAGE, now=FIXED_INSTANT)

    assert report == FreshnessReport(status="unknown", stale=False, observed_at=None)
