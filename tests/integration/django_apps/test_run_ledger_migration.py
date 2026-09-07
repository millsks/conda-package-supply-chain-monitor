"""`CPM-EVIDENCE-S09` AC 2, run rather than read: a populated table survives the conversion.

The acceptance criterion's Given is "an existing `collection_runs` table carrying
rows" and its Then is "no row is lost and the column is preserved rather than
dropped and re-added". Nothing about that is a claim about source text, so this
module migrates `core` back to `0003_package_health`, fills the table, migrates
forward again and reads what is there.

`tests/unit/django_apps/test_run_ledger_migration.py` is the other half and
neither replaces the other. It reads the migration's operations, which a run
cannot: `RemoveField` plus `AddField` produces the same final schema as the safe
sequence, so a case that ran the migration against an *empty* table would pass
over the destructive spelling without noticing. This module is what notices when
the table is not empty.

**It runs on both backends, which is the whole reason it is an integration case.**
`pixi run ci` runs it on the SQLite substitution and `pixi run gate-postgres`
runs it on `postgres:17`, and the two do genuinely different things here: SQLite
rebuilds the table and copies the rows across, PostgreSQL renames the column in
place and validates the new constraint against what is already there. A
conversion that lost rows on one of them would pass on the other.

**The orphan row is the case a fresh database cannot produce.** Until this
migration `core/ledger.py` accepted any non-negative integer as a package key, so
a table written under the old contract can hold references naming no package --
and the foreign key cannot be added over them. The migration's `RunPython` clears
those, and this is where that is asserted: the row survives with a NULL
reference, which is what "not scoped to one package" already meant.

**Everything here runs outside a test transaction**, through
`django_db_blocker.unblock()` and with no `django_db` marker on the migrating
cases. That is forced rather than chosen, for the reason
`tests/integration/django_apps/test_append_only_evidence.py` records at length:
SQLite's schema editor refuses to open inside a multi-statement transaction, so a
migration driven from inside `@pytest.mark.django_db` fails on every developer
machine. `transaction=True` is not the alternative --
`tests/integration/test_prune_command.py` records why: it truncates the tables
the group-provisioning migrations wrote.

**Which database an unblocked case reaches is not obvious, and getting it wrong
destroys the developer's own.** pytest-django's `django_db_setup` decides *which
aliases to create* by scanning the collected items for the `django_db` marker and
for the `db` fixture (`fixtures._get_databases_for_setup`). A session in which
nothing is marked sets up no alias at all -- and `django_db_blocker.unblock()`
then hands out a connection to whatever `settings.DATABASES` names, which on a
developer machine is the working `db.sqlite3`. A module of unmarked cases run on
its own would migrate that database up and down and write rows into it. Two
things stop it here, and both are needed:

* `test_the_conversion_is_recorded_as_applied_before_anything_unapplies_it` is
  marked, which is what makes pytest-django create the test database when this
  module is run by itself. It is a real vacuity guard as well -- a module that
  rolls a migration back should say the migration was there.
* `_refuse_a_database_the_test_runner_did_not_prepare` compares the connection's
  database against the one `settings` named at import time, which happens during
  collection and therefore before any of that setup runs. If the two are still
  equal, nothing was prepared, and the fixture refuses instead of writing.

The rows are removed by hand rather than rolled back, and the fixture removes
them *before* it migrates forward: with the orphan gone the restoring migration
cannot fail, so a failed case leaves the schema at `core`'s leaf rather than
stranding a `--reuse-db` database at `0003` for every later run. It also clears any rows a
previous run left, for the reason `evidence_table` drops a stale table rather
than colliding with it -- a run killed mid-fixture is what leaves them.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.runs import RunState
from tests.clocks import FIXED_INSTANT

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.apps.registry import Apps
    from pytest_django import DjangoDbBlocker

#: The two migration states this module moves between. `BEFORE` is the last state
#: in which the package reference is a plain integer; `AFTER` is the conversion.
BEFORE: Final[tuple[str, str]] = ("core", "0003_package_health")
AFTER: Final[tuple[str, str]] = ("core", "0004_collection_run_package")

#: What `settings.DATABASES` names before anything replaces it.
#:
#: Read at import time on purpose. A test module is imported during collection,
#: and `django_db_setup` is a session fixture that runs at the first case's
#: setup -- so this is the *configured* database, which on a developer machine is
#: the working `db.sqlite3` and in the gate is the real one. The guard below is
#: the whole reason it is captured: if the connection still points here when a
#: case is about to migrate, no test database was created and the migration would
#: be applied to the developer's own.
CONFIGURED_DATABASE: Final[str] = str(settings.DATABASES[DEFAULT_DB_ALIAS]["NAME"])

#: The package a surviving run points at. Deliberately far from the keys the
#: other `core` modules use: those roll back with their transactions and these do
#: not, so a collision here would surface as a failure in an unrelated module.
A_REAL_PACKAGE_ID: Final[int] = 81001

#: A key naming no package, of exactly the shape the old recorder permitted and
#: wrote. Never created, which is the point.
AN_ORPHANED_PACKAGE_ID: Final[int] = 81002

#: What the package this module creates is called. Prefixed so it cannot collide
#: with a name another module chose, and unique because `packages` says so.
A_PACKAGE_NAME: Final[str] = "cpm-migration-check-package"

#: The collector the written runs name. A plain `CharField` the ledger never
#: validates, so any string does; this one says which module wrote the rows, and
#: it is what the cleanup filters on.
A_COLLECTOR: Final[str] = "migration-check"

#: How many rows the case writes, and therefore how many must come back. Named so
#: the assertion reads as "every row survived" rather than as a magic number.
THREE_RUNS: Final[int] = 3


def _refuse_a_database_the_test_runner_did_not_prepare() -> None:
    """Refuse to migrate anything unless a test database was actually created.

    See the module docstring for the failure this prevents: an unblocked
    connection in a session that set up no alias is a connection to the
    developer's working database, and everything below would then roll a
    migration back on it and write rows into it.

    Raises:
        RuntimeError: When the connection still names the database `settings`
            named at import time, which means nothing replaced it.

    """
    if connection.settings_dict["NAME"] == CONFIGURED_DATABASE:
        message = (
            f"this module is about to migrate {CONFIGURED_DATABASE!r}, which is the database settings named "
            f"before the test runner ran -- so no test database was created and this is the working one. "
            f"pytest-django creates an alias only when some collected case is marked django_db or requests "
            f"the db fixture; this module keeps one marked case for exactly that reason, and it has been "
            f"removed or renamed."
        )
        raise RuntimeError(message)


def _the_state_the_session_must_be_returned_to() -> list[tuple[str, str]]:
    """Return every leaf in the migration graph, which is where the teardown restores to.

    Resolved from the graph rather than named as a constant, and the distinction
    is the whole of this function. `AFTER` is the conversion this module is
    *about*, and it was also `core`'s leaf on the day the module was written --
    but `MigrationExecutor.migrate` unapplies everything after its target, so
    restoring to a fixed name undoes every migration added since. It leaves them
    undone for the rest of the session, because nothing re-applies them, and the
    symptom lands nowhere near here: the cases asserting on `stage_two`'s
    unapplied-migration refusal start reporting `DATABASES['default']` instead of
    the alias they configured. `CPM-IDENTITY-S05` is where that happened.

    **Every leaf, not `core`'s.** This asked the graph for `core`'s single leaf
    until `CPM-CURRENCY-S07`, and that was a narrower claim than the teardown
    needs: rolling `core` back to `BEFORE` unapplies every migration that
    *depends* on the ones it undoes, in any application, and restoring `core`'s
    own leaf puts none of those back. `policies.0002_package_feedstock_presence`
    is the migration that found it. That one now depends only on what it
    references, which is the rule `policies.0001` already stated -- but the
    teardown should not have needed it to: restoring what the loader calls the
    end of the graph is the state `migrate` with no arguments produces, and it is
    the only description of "fully migrated" that stays true as applications are
    added.

    Returns:
        The `(app_label, name)` of every leaf migration in the graph.

    Raises:
        RuntimeError: When the graph has no leaves at all -- an empty or
            unreadable migration graph, which would make the teardown a no-op
            that silently left the database at `BEFORE`. And when any single
            application carries more than one leaf, which is a conflicted graph
            `migrate` itself cannot order: restoring to both would apply two
            divergent states and restoring to one would leave the other's
            migrations undone for the rest of the session, which is the failure
            this whole function exists to prevent. That check was here when this
            read `leaf_nodes("core")` and it is kept: widening the restore to
            every application widened what a conflict can be, it did not remove
            the possibility.

    """
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes()
    if not leaves:
        message = "the migration graph has no leaf nodes, so there is no state to restore the session's database to"
        raise RuntimeError(message)
    by_application = Counter(app_label for app_label, _ in leaves)
    conflicted = sorted(app for app, count in by_application.items() if count > 1)
    if conflicted:
        message = (
            f"{conflicted} each carry more than one leaf migration ({sorted(leaves)}), so there is no single "
            f"state to restore the session's database to"
        )
        raise RuntimeError(message)
    return leaves


def _migrate_to(*targets: tuple[str, str]) -> None:
    """Move the database to one or more migration states, forwards or backwards.

    A fresh executor per call rather than one reused: the recorder's table
    changes with every step, and an executor holding a graph built before the
    move would plan the next one from a state the database has left.

    Args:
        *targets: The `(app_label, migration_name)` states to end at. One when
            moving to `BEFORE` or `AFTER`; every leaf when restoring, which is
            what `migrate` with no arguments does.

    """
    MigrationExecutor(connection).migrate(list(targets))


def _the_applied_state() -> Apps:
    """Return the model registry as the database actually stands, right now.

    The rows have to be written through models that match the schema of the day
    -- at `BEFORE` the package reference is a plain integer attribute named
    `package_id`, and the real `CollectionRun` has been a relation since. Reading
    a historical registry is how a data migration does it, and it is how this
    module arranges the same thing.

    **Built from what is applied, not from `BEFORE`'s ancestors, and the
    difference is a defect this once had.** `project_state(BEFORE)` renders every
    app at whatever state `core.0003` *depends on* -- `identity` at `0001`, in
    particular -- while `_migrate_to(BEFORE)` unapplies only what comes after
    `core.0003` and leaves every other application at its leaf. The two agreed
    for as long as `identity` had not changed since, and stopped agreeing the
    moment `CPM-CURRENCY-S06` added a NOT NULL `version_authority_order` to
    `packages`: an insert through the rendered `Package` omitted a column the
    real table requires, and a delete through it walked a `package_health` that
    was missing a column the real one has. Asking for the *applied* set makes the
    registry describe the database rather than a state the database was never in.

    Must be called after every `_migrate_to`, for the reason `_migrate_to` builds
    a fresh executor each time: the applied set changes with every move, and a
    loader built before one is describing a schema the database has left.

    Returns:
        A registry whose models declare the columns that exist right now.

    """
    loader = MigrationExecutor(connection).loader
    return loader.project_state(list(loader.applied_migrations)).apps


def _write_the_rows_the_old_contract_permitted(historical: Apps) -> None:
    """Fill `collection_runs` with the three references a converted table can hold.

    One naming a real package, one naming none at all -- which is what an
    inventory-wide sweep writes and has always been legitimate -- and one naming
    a package that does not exist, which the old recorder permitted and the new
    foreign key does not.

    Args:
        historical: The registry as applied, whose `CollectionRun` still carries
            the plain integer.

    """
    package = historical.get_model("identity", "Package")
    collection_run = historical.get_model("core", "CollectionRun")
    package.objects.create(pk=A_REAL_PACKAGE_ID, canonical_name=A_PACKAGE_NAME, resolved_at=FIXED_INSTANT)
    for package_id in (A_REAL_PACKAGE_ID, None, AN_ORPHANED_PACKAGE_ID):
        collection_run.objects.create(
            collector=A_COLLECTOR,
            package_id=package_id,
            started_at=FIXED_INSTANT,
            finished_at=FIXED_INSTANT,
            status=RunState.SUCCEEDED,
        )


def _remove_the_rows(historical: Apps) -> None:
    """Delete everything this module writes, at whichever state the database is in.

    Through the `BEFORE` models, which name the same columns at both states, so
    this works whether or not the case got as far as migrating forward. The runs
    go before the packages: at `AFTER` the relation is `PROTECT`, and a package
    with a run against it is exactly what that refuses.

    Called at setup as well as at teardown. Nothing here rolls back, so a run
    killed between the write and the cleanup leaves rows that would make the next
    run's insert a duplicate-key failure inside a fixture -- the same hazard
    `evidence_table` answers by dropping a stale table rather than colliding with
    it.

    Args:
        historical: The registry as applied.

    """
    historical.get_model("core", "CollectionRun").objects.filter(collector=A_COLLECTOR).delete()
    historical.get_model("identity", "Package").objects.filter(pk=A_REAL_PACKAGE_ID).delete()


@pytest.fixture
def a_populated_ledger_before_the_conversion(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Roll `core` back to `0003`, fill the ledger, and restore `0004` afterwards.

    Args:
        django_db_setup: pytest-django's session-scoped database setup, so the
            test database exists and is fully migrated before anything is undone.
            Requested rather than assumed -- and not sufficient on its own, which
            is what the guard below is for.
        django_db_blocker: The guard that keeps database access out of cases that
            did not ask for it. Unblocked around the whole case, because the
            migration and the assertions both run outside a transaction.

    Yields:
        Nothing. The arrangement is the fixture's side effects: the schema is at
        `BEFORE` and the table holds the three rows.

    """
    with django_db_blocker.unblock():
        _refuse_a_database_the_test_runner_did_not_prepare()
        _migrate_to(BEFORE)
        historical = _the_applied_state()
        _remove_the_rows(historical)
        try:
            _write_the_rows_the_old_contract_permitted(historical)
            yield
        finally:
            _remove_the_rows(historical)
            _migrate_to(*_the_state_the_session_must_be_returned_to())


@pytest.mark.django_db
def test_the_conversion_is_recorded_as_applied_before_anything_unapplies_it() -> None:
    """The module's vacuity guard, and what makes its other cases reach a test database.

    The guard half: every other case here rolls `core.0004` back and applies it
    again, which says nothing at all if the migration was not applied to begin
    with -- a database built with `--no-migrations` would let the rollback be a
    no-op and the forward step assert against a schema nothing converted.

    The other half is why this case is marked and the others are not.
    pytest-django creates a test database only for the aliases some *collected*
    case asks for, by the marker or by the `db` fixture, and it scans every
    collected item before the first one runs -- so one marked case anywhere in
    the module is enough, whichever order they run in. Without it, running this
    module on its own would unblock straight onto the developer's own database.
    The module docstring says the rest.
    """
    applied = MigrationRecorder(connection).applied_migrations()

    assert AFTER in applied
    assert BEFORE in applied


def test_the_module_restores_every_migration_it_unapplies(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    """Rolling `core` back and restoring it leaves nothing unapplied for later cases.

    Everything else in this module unapplies `core.0004` and puts it back, and
    none of it can tell the difference between a teardown that restores the
    application's current state and one that restores the state of the day it was
    written. Only the rest of the session can, and it reports the difference as
    its own failure: `tests/integration/test_release_stage.py` and
    `tests/integration/startup/test_stage_two_database_conditions.py` configure an
    unmigrated alias, and if `default` is unmigrated too the refusal names
    `default` first -- so their cases fail naming a fault this module left behind.

    Asserted as an empty plan rather than by comparing migration names, because
    the claim is "nothing is left unapplied" -- a name comparison would need
    updating by exactly the person this case exists to protect, which is how the
    pinned restore got there.

    A failure here strands the schema at `BEFORE`, which the next run of the
    fixture above repairs: its first action is to migrate there.

    Args:
        django_db_setup: pytest-django's session-scoped setup, so the test
            database exists and is fully migrated before anything is undone.
        django_db_blocker: Unblocked for the reason the fixture unblocks --
            SQLite's schema editor refuses to open inside a transaction.

    """
    with django_db_blocker.unblock():
        _refuse_a_database_the_test_runner_did_not_prepare()
        _migrate_to(BEFORE)
        _migrate_to(*_the_state_the_session_must_be_returned_to())

        executor = MigrationExecutor(connection)
        assert executor.migration_plan(executor.loader.graph.leaf_nodes()) == []


@pytest.mark.usefixtures("a_populated_ledger_before_the_conversion")
def test_the_conversion_keeps_every_row_and_the_column_it_was_written_in() -> None:
    """AC 2, on a table that is not empty.

    Three claims, and each one fails a different mistake. Every row is still
    there, which a `RemoveField` plus `AddField` would satisfy too -- the rows
    survive, it is the *column* that is emptied -- so the reference of the
    package-scoped run is asserted unchanged, which is what that pair would lose.
    The unscoped run's NULL is still NULL, so the conversion did not invent a
    reference for a sweep that never had one. And the orphan is NULL rather than
    absent: the migration cleared a value that named nothing, and kept the row
    that recorded a run really happening.

    Read back through the real `CollectionRun`, not a historical model, because
    the last claim is that the *converted* model reads the rows the old one
    wrote.
    """
    _migrate_to(AFTER)

    runs = CollectionRun.objects.filter(collector=A_COLLECTOR).order_by("pk")

    assert runs.count() == THREE_RUNS
    assert [row.package_id for row in runs] == [A_REAL_PACKAGE_ID, None, None]


@pytest.mark.usefixtures("a_populated_ledger_before_the_conversion")
def test_the_converted_column_is_still_called_package_id() -> None:
    """AC 2's second half, asked of the database rather than of the model.

    `test_the_relation_keeps_the_column_the_integer_had` in the unit module
    asserts that Django *intends* the column to be `package_id`. This asks the
    database what it actually built, which is the claim AC 2 makes -- and it is
    one a `RemoveField`/`AddField` pair would also satisfy, so it is asserted
    beside the rows rather than instead of them.

    Introspected rather than compared against a hand-written schema: the two
    backends spell types and defaults differently, and the column's *name* is the
    only part of it this criterion is about.
    """
    _migrate_to(AFTER)

    with connection.cursor() as cursor:
        columns = {column.name for column in connection.introspection.get_table_description(cursor, "collection_runs")}

    assert "package_id" in columns
    assert "package" not in columns
