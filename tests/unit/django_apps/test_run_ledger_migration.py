"""`CPM-EVIDENCE-S09` AC 2: the conversion preserves the column rather than replacing it.

The migration that turns `CollectionRun.package_id` into
`CollectionRun.package` is the one operation in this story that can destroy data,
and the destructive spelling is the one `makemigrations` writes by itself. The
attribute names differ -- `package_id` against `package` -- so the autodetector
reads the change as a field removed and a different field added, and
`RemoveField` followed by `AddField` drops the column and re-creates it empty.
Every recorded run's package reference goes with it, and nothing fails: the
schema afterwards is exactly the one the models declare, so
`tests/unit/django_apps/test_migration_completeness.py` is satisfied by the
destructive migration and by the safe one alike.

That is why this module asserts the *operations*. `RenameField` carries the
existing column across to the new attribute name, `RunPython` clears the
references the new constraint would reject, and `AlterField` then makes the
column the relation -- so the rows travel with the column. The claim is about the
source, so it is checked by reading the source.

**The behavioural half is `tests/integration/django_apps/test_run_ledger_migration.py`**,
which migrates a populated `collection_runs` back to `0003` and forward again and
reads what survived. The two are not duplicates and neither replaces the other: a
run says what happened to the rows on the backend it ran on -- and it runs on
both, under `pixi run ci` and under `pixi run gate-postgres` -- while this module
says the *source* still spells the safe sequence, which a run cannot, because a
`RemoveField` appended after a correct pair produces the same final schema on a
table that happens to be empty.

Imports one module and reads its declared operations: no database, no network,
no subprocess.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.db import migrations
from django.db import models

if TYPE_CHECKING:
    from types import ModuleType

MIGRATION_MODULE: Final[str] = "conda_package_supply_chain_monitor.core.migrations.0004_collection_run_package"

#: The model and column the conversion is about, spelled once so a case reads as
#: a claim about the run ledger rather than as three repeated literals.
LEDGER_MODEL: Final[str] = "collectionrun"
OLD_ATTRIBUTE: Final[str] = "package_id"
NEW_ATTRIBUTE: Final[str] = "package"

#: The operations that would lose the column's rows, and the reason the sequence
#: is asserted by name rather than by length. `RemoveField` drops the column;
#: `AddField` re-creates it empty; `DeleteModel` takes the whole table. Together
#: they are what `makemigrations` writes for this change and what a later
#: regeneration would write again -- and any one of them appended *after* a
#: correct pair passes a length check and empties the column just the same.
#:
#: `CreateModel` is deliberately not here: it is not destructive to a column that
#: already exists, and listing it would make this frozenset a list of operations
#: this migration happens not to use rather than a list of ones that would lose
#: data.
DESTRUCTIVE_OPERATIONS: Final[frozenset[str]] = frozenset({"RemoveField", "AddField", "DeleteModel"})

#: What the migration must run after. `core.0003` is the previous state of this
#: application's graph; `identity.0001` is where `packages` is created.
#:
#: The second is redundant and is declared anyway. `core.0003_package_health`
#: already depends on `identity.0001` -- it builds `package_health`, which
#: carries its own relation to the same table -- so the ordering holds
#: transitively today, and this migration would be correct without the line. It
#: is written out because *this* migration's correctness must not rest on a
#: dependency another migration happens to carry: a squash that folded `0003`
#: away, or a future `0003` that no longer needed `identity`, would silently free
#: the graph to add the foreign key before `packages` exists.
EXPECTED_DEPENDENCIES: Final[list[tuple[str, str]]] = [
    ("core", "0003_package_health"),
    ("identity", "0001_package_identity"),
]


@pytest.fixture
def migration() -> ModuleType:
    """The migration module, imported per case rather than at module scope.

    An import at module scope would make a broken migration fail *collection* of
    this file, which reports as an error with no test name attached and takes the
    other cases with it -- the reason `tests/unit/django_apps/test_role_migration.py`
    imports its own module the same way.

    Returns:
        The imported migration module.

    """
    return import_module(MIGRATION_MODULE)


def test_the_column_is_carried_across_rather_than_dropped_and_re_added(migration: ModuleType) -> None:
    """AC 2: a rename, a data step and an alter, in that order and no others.

    The order is the assertion as much as the sequence is. `AlterField` before
    the rename would be altering a field the new state does not have; a rename
    *after* the relation existed would be renaming a column Django had already
    named for it; and the data step has exactly one place it can go -- after the
    rename, because it addresses the column by its new attribute name, and before
    the alter, because its whole purpose is to make the rows acceptable to the
    constraint the alter adds.
    """
    operations = migration.Migration.operations

    assert [type(operation).__name__ for operation in operations] == ["RenameField", "RunPython", "AlterField"]


def test_the_data_step_clears_the_references_the_constraint_would_reject(migration: ModuleType) -> None:
    """The step that keeps `migrate` from failing on data the old contract permitted.

    Until this migration `core/ledger.py` accepted any non-negative integer as a
    package key, so a deployed table can hold references naming no package.
    PostgreSQL validates `ADD CONSTRAINT ... FOREIGN KEY` against the existing
    rows and SQLite's table rebuild runs its own check, so the foreign key cannot
    be added over them -- and a migration that fails halfway is the worst place
    to learn it.

    The reverse is a declared no-op rather than an omission: `RunPython` with no
    reverse makes the whole migration irreversible, which would take the ability
    to roll `core` back to `0003` with it -- and there is nothing to restore
    from, because the cleared value named no package.
    """
    step = migration.Migration.operations[1]

    assert isinstance(step, migrations.RunPython)
    assert step.code is migration.null_references_that_name_no_package
    assert step.reverse_code is migration.nothing_to_restore


def test_no_operation_would_lose_the_recorded_runs(migration: ModuleType) -> None:
    """The destructive spelling is absent, asserted by name.

    `makemigrations` writes `RemoveField` plus `AddField` for this change, so the
    failure this guards against is not an exotic one -- it is what happens when
    somebody regenerates the migration instead of keeping this one.
    """
    present = {type(operation).__name__ for operation in migration.Migration.operations}

    assert present & DESTRUCTIVE_OPERATIONS == set()


def test_the_rename_moves_the_ledgers_own_attribute(migration: ModuleType) -> None:
    """The rename is `package_id` to `package` on `CollectionRun`, and nothing else.

    Named explicitly because a rename of the right shape against the wrong model
    or the wrong attribute would satisfy the operation-list case above while
    leaving the ledger's column exactly where it was.
    """
    rename = migration.Migration.operations[0]

    assert isinstance(rename, migrations.RenameField)
    assert rename.model_name == LEDGER_MODEL
    assert rename.old_name == OLD_ATTRIBUTE
    assert rename.new_name == NEW_ATTRIBUTE


def test_the_altered_field_is_the_protected_nullable_relation(migration: ModuleType) -> None:
    """The migration's own copy of AC 1, frozen as a migration must freeze it.

    A migration records what the schema was asked to be and must not follow the
    model it can no longer see -- which is exactly why the declaration is written
    out here rather than imported from `core/models.py`, and exactly why it can
    silently disagree with the model. `test_migration_completeness.py` is what
    notices that; this case is what says the frozen copy is the *right* schema:
    the relation to `identity.Package`, `PROTECT` for `CPM-AD-25`, and nullable
    for the sweep that is scoped to no package.
    """
    alter = migration.Migration.operations[2]

    assert isinstance(alter, migrations.AlterField)
    assert alter.model_name == LEDGER_MODEL
    assert alter.name == NEW_ATTRIBUTE
    assert isinstance(alter.field, models.ForeignKey)
    assert alter.field.remote_field.model == "identity.package"
    assert alter.field.remote_field.on_delete is models.PROTECT
    assert alter.field.null is True


def test_the_migration_runs_after_the_table_it_points_at_exists(migration: ModuleType) -> None:
    """Ordering, written out rather than inherited.

    `identity.0001_package_identity` creates `packages`, and the relation cannot
    be added before it exists. The line is not what makes that true today --
    `core.0003_package_health` already depends on the same migration, so the
    graph orders these correctly with or without it -- which is exactly why it is
    asserted: a dependency that is currently redundant is one a squash or a
    rewritten `0003` can quietly remove, and the failure then lands on a fresh
    database and nowhere else.
    """
    assert sorted(migration.Migration.dependencies) == sorted(EXPECTED_DEPENDENCIES)
