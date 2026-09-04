"""`EVIDENCE.02-INT-001`: re-observing an unchanged fact writes a second row.

What the unit tests cannot show. `tests/unit/django_apps/test_append_only_model.py`
proves every refusal, and it proves them without a database precisely because a
refusal happens before any statement is compiled. The *permission* is the other
half, and it is only true if a real table accepts it: two observations of the
same fact, identical in every column but `observed_at`, must both land.

That is not a foregone conclusion. A unique constraint anywhere across the
observed fact turns the second insert into an `IntegrityError`, and the collector
that meets one has two bad options -- swallow it, which silently drops the
observation, or fall back to `update_or_create`, which is `R-06` arriving by the
front door. `CPM-AD-7` therefore says evidence is *always* inserted and no
evidence table carries a constraint that suppresses an insert;
`tests/unit/django_apps/test_evidence_constraint_audit.py` audits the
declaration, and this module checks what the database actually built.

**The table is built once for the session, outside every test's transaction.**
`CPM-EVIDENCE-S02` is forbidden to create a concrete evidence model --
`CPM-AD-7` gives each collector its own, and the first arrives with
`CPM-EP-CURRENCY` -- so the fixture model is registered by `isolate_apps` and its
table is built by `connection.schema_editor()`. It is *not* built per test and
does not vanish with a rollback: SQLite's schema editor refuses to open inside a
transaction, and this suite runs on SQLite locally and on PostgreSQL in the gate.
The `evidence_table` fixture says why at length. What rolls back per test is the
rows, which is all these cases write.

**The database this touches is the test database.** `--reuse-db` is in `addopts`,
so the fixture's table can outlive a killed run; every name it uses is prefixed
so that it cannot be confused with, or collide with, a table a migration built.

**Time comes from two stopped clocks, never from the wall.** `FixedClock` is
frozen (`core/clock.py` says why), so a case needing two instants constructs two
clocks rather than winding one forward, and `tests/clocks.py` derives the second
from the first so the ordering cannot drift. This is `CPM-AD-26`'s first real
consumer: the assertion is that the second row's `observed_at` is later by
exactly `OBSERVATION_GAP`, which is a statement about the writer rather than
about how long the test took.

Every test here rolls back. `@pytest.mark.django_db` wraps each in a
transaction, which is what leaves the database as found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.db import connection
from django.db import models
from django.test.utils import isolate_apps

from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.models import AppendOnlyError
from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.clocks import OBSERVATION_GAP
from tests.model_registry import A_FACT
from tests.model_registry import FIXTURE_APP
from tests.model_registry import FIXTURE_LABEL

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django import DjangoDbBlocker

    from conda_package_supply_chain_monitor.core.clock import Clock

#: The table name the fixture model is given, rather than the `core_observation`
#: Django would derive from `core` and `Observation`.
#:
#: Load-bearing, not cosmetic. The fixture drops a stale table of this name at
#: session start -- `--reuse-db` means a run killed between the create and the
#: drop leaves one behind -- and a derived name would make that drop land on a
#: genuine migrated table the day `core` declares an `Observation` of its own.
#: The prefix says what it is and belongs to nothing a migration builds.
FIXTURE_TABLE: Final[str] = "cpm_fixture_append_only_observation"

#: How many rows two observations of one fact must leave behind.
OBSERVATIONS: Final[int] = 2

#: The index the fixture model declares on `observed_at`.
#:
#: It is the neighbouring shape that must stay *permitted*: an index is what
#: makes a freshness or window query answerable, and `EVIDENCE.02-AUDIT-003`
#: bans unique constraints without banning indexes. Declaring one here is what
#: gives the constraint case below something to distinguish -- a table with no
#: declarations at all could only fail if Django invented a constraint by itself.
FIXTURE_INDEX: Final[str] = "cpm_fixture_observed_at"


@pytest.fixture(scope="session")
def evidence_table(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[type[AppendOnlyModel]]:
    """An evidence model with a real table behind it, dropped at the end of the session.

    **Session-scoped, and the DDL runs outside every test's transaction.** That
    is forced rather than chosen: SQLite cannot toggle foreign-key enforcement
    inside a multi-statement transaction, so its schema editor refuses to open
    within one, and this repository runs the suite on SQLite locally and on
    PostgreSQL in the gate (`.github/workflows/ci.yml`). Creating the table per
    test would therefore work in the gate and fail on every developer machine,
    which is the backend-specific behaviour `tests/unit/test_suite_policy.py`
    exists to keep out of this suite. The rows still roll back per test:
    `@pytest.mark.django_db` wraps each case, and only the empty table outlives
    it.

    **`isolate_apps` is exited before the table is built,** so the patched
    registry is not held open across the whole session. The class survives its
    block -- it keeps a reference to the registry it was defined in -- and it
    declares no relation, so nothing it does needs to look another model up.

    **A stale table is dropped rather than collided with, and the name it drops
    is one nothing else can own.** `--reuse-db` is in `addopts`, so a run killed
    between the create and the drop would otherwise leave a table that makes
    every later run fail in the fixture. `db_table` is declared explicitly for
    that drop's sake: Django would derive `core_observation` from the app label
    and the class name, and the day `core` declares an `Observation` of its own
    this fixture would drop a genuine migrated table at session start.

    **The teardown checks the table is there before dropping it.** A
    `create_model` that failed -- a name already taken, a backend that refused --
    would otherwise be followed by a `delete_model` that raises on the way out,
    and the error a reader is shown is the teardown's rather than the one that
    actually broke the run.

    Args:
        django_db_setup: pytest-django's session-scoped database setup, so the
            test database exists before any DDL runs.
        django_db_blocker: The guard that keeps database access out of tests
            which did not ask for it; unblocked around the DDL.

    Yields:
        A concrete subclass of `AppendOnlyModel` whose table exists for the
        session.

    """
    with isolate_apps(FIXTURE_APP):

        class Observation(AppendOnlyModel):
            fact = models.CharField(max_length=64)

            class Meta:
                app_label = FIXTURE_LABEL
                db_table = FIXTURE_TABLE
                indexes = (models.Index(fields=["observed_at"], name=FIXTURE_INDEX),)

    with django_db_blocker.unblock():
        if FIXTURE_TABLE in connection.introspection.table_names():
            with connection.schema_editor() as editor:
                editor.delete_model(Observation)
        with connection.schema_editor() as editor:
            editor.create_model(Observation)
    try:
        yield Observation
    finally:
        with django_db_blocker.unblock():
            if FIXTURE_TABLE in connection.introspection.table_names():
                with connection.schema_editor() as editor:
                    editor.delete_model(Observation)


def observe(model: type[AppendOnlyModel], clock: Clock, fact: str) -> AppendOnlyModel:
    """Write one observation, stamping it from the clock it was given.

    This is the shape every collector's writer takes under `CPM-AD-26`: the
    instant is a parameter of the write rather than something the write goes and
    reads. `observed_at` has no default precisely so that omitting this is an
    error rather than a row stamped with whichever process happened to run.

    Args:
        model: The evidence model to write to.
        clock: The clock the instant comes from.
        fact: What was observed.

    Returns:
        The inserted row.

    """
    return model.objects.create(observed_at=clock.now(), fact=fact)


@pytest.mark.django_db
def test_re_observing_an_unchanged_fact_inserts_a_second_row(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """`EVIDENCE.02-INT-001`, and the criterion `CPM-FR-36` exists for.

    Two writes, one fact, two clocks. Both rows survive, they carry the same
    fact, and they differ by exactly the interval between the two clocks -- which
    is what makes "what did the system know at 12:00" a question the table can
    answer at all.
    """
    first = observe(evidence_table, FixedClock(instant=FIXED_INSTANT), A_FACT)
    second = observe(evidence_table, FixedClock(instant=LATER_INSTANT), A_FACT)

    rows = list(evidence_table.objects.order_by("observed_at"))

    assert len(rows) == OBSERVATIONS
    assert first.pk != second.pk
    assert [row.fact for row in rows] == [A_FACT, A_FACT]
    assert [row.observed_at for row in rows] == [FIXED_INSTANT, LATER_INSTANT]
    assert rows[1].observed_at - rows[0].observed_at == OBSERVATION_GAP


@pytest.mark.django_db
def test_the_table_carries_no_unique_constraint_beyond_its_primary_key(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The other half of the same guarantee, read off the database rather than the model.

    `test_evidence_constraint_audit.py` audits what the *declaration* says. This
    reads what the backend built, which is the thing an insert actually meets.

    **Which backend, stated rather than implied.** This runs on whichever one the
    run configured -- SQLite on a developer machine and in the compatibility
    jobs, PostgreSQL in the gate (`.github/workflows/ci.yml`) -- so it is not a
    statement about PostgreSQL's catalogue. What it is a statement about is
    Django's schema editor: that the DDL it emits for a model declaring no
    uniqueness adds none of its own.

    **The index is why the case can fail at all.** A fixture declaring nothing
    could only fail if Django invented a constraint unprompted. This one declares
    an `Index` on `observed_at` -- the neighbouring shape, and the one every
    evidence table will want -- so the assertion is the meaningful one: an index
    is built and is *not* counted as a unique constraint. A backend or a
    Django release that started emitting `CREATE UNIQUE INDEX` for
    `Meta.indexes`, or an introspection that stopped telling the two apart, fails
    here.

    The primary key is asserted by name rather than by counting, so a table that
    had somehow lost its surrogate key would fail here too.
    """
    table = evidence_table._meta.db_table  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)

    unique = {
        name: detail["columns"]
        for name, detail in constraints.items()
        if detail["unique"] and not detail["primary_key"]
    }
    primary = [detail["columns"] for detail in constraints.values() if detail["primary_key"]]
    indexed = {name: detail["columns"] for name, detail in constraints.items() if detail["index"]}

    assert table == FIXTURE_TABLE
    assert unique == {}, f"{table} carries a unique constraint that would suppress a re-observation: {unique}"
    assert primary == [["id"]]
    assert indexed.get(FIXTURE_INDEX) == ["observed_at"], indexed


@pytest.mark.django_db
def test_bulk_create_writes_every_observation(evidence_table: type[AppendOnlyModel]) -> None:
    """The insert path the unit tests could only assert by identity.

    A collector observing a hundred packages in one pass writes them in one
    statement, and a base that refused `bulk_create` alongside `bulk_update`
    would push that collector toward raw SQL -- the one write path no guard in
    `core/models.py` can see.
    """
    clock = FixedClock(instant=FIXED_INSTANT)

    evidence_table.objects.bulk_create(
        [evidence_table(observed_at=clock.now(), fact=f"{A_FACT} #{index}") for index in range(OBSERVATIONS)],
    )

    assert evidence_table.objects.count() == OBSERVATIONS


@pytest.mark.django_db
def test_a_row_read_back_and_saved_leaves_the_stored_row_untouched(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The accidental path, against a real table, with the row checked afterwards.

    The unit case proves `save()` raises. What it cannot prove is that nothing
    reached the database on the way to raising -- a guard placed after the
    `UPDATE` was built would still raise, and would still have written. Read
    back, mutate, save, and the stored row is exactly as it was.
    """
    observe(evidence_table, FixedClock(instant=FIXED_INSTANT), A_FACT)
    loaded = evidence_table.objects.get()
    loaded.fact = "rewritten"

    with pytest.raises(AppendOnlyError):
        loaded.save()

    stored = evidence_table.objects.get()
    assert stored.fact == A_FACT
    assert stored.observed_at == FIXED_INSTANT


@pytest.mark.django_db
def test_a_queryset_mutation_leaves_every_row_where_it_was(
    evidence_table: type[AppendOnlyModel],
) -> None:
    """The bypass `save()` cannot see, refused with the rows still standing.

    `update()` and `delete()` compile a statement against the whole set rather
    than constructing an instance, so this is the one place their refusal can be
    checked against rows that actually exist: two observations go in, both
    mutations raise, and both rows are still there afterwards.
    """
    observe(evidence_table, FixedClock(instant=FIXED_INSTANT), A_FACT)
    observe(evidence_table, FixedClock(instant=LATER_INSTANT), A_FACT)

    with pytest.raises(AppendOnlyError):
        evidence_table.objects.update(fact="rewritten")
    with pytest.raises(AppendOnlyError):
        evidence_table.objects.all().delete()

    assert evidence_table.objects.count() == OBSERVATIONS
    assert set(evidence_table.objects.values_list("fact", flat=True)) == {A_FACT}
