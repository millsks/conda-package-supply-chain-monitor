"""Every model change in this repository has a migration, asserted in the gate.

`pixi run ci` runs precommit, build, typecheck, lint and the suite. It does not
run `makemigrations --check`, and nothing else does either -- so a field added,
widened, renamed or given a new `db_index` reaches `main` with no migration
behind it, and the failure surfaces at `migrate` on somebody else's machine or,
worse, at the first query against a column the database does not have.

The gap is not hypothetical here. `core/models.py` declares its column widths as
`_STATUS_LENGTH`, `_TRACE_ID_LENGTH` and `_NAME_LENGTH`, and
`core/migrations/0002_run_ledger.py` carries the numbers `16`, `32` and `128`
frozen into `AlterField`-shaped literals. That is exactly right -- a migration
records what the schema *was* asked to be, and must not follow a constant it can
no longer see -- and it means the two can silently disagree the moment somebody
edits a constant. This case is what notices.

**The autodetector, not a management command.** `MigrationLoader(None)` reads the
migration files from disk with no connection, so the comparison is between the
declared models and the migration graph: no database, no subprocess, and it runs
in the unit tier where a developer sees it in under a second. Shelling out to
`manage.py makemigrations --check` would give the same answer through a second
configuration of the thing being checked, which
`tests/unit/test_typing_policy.py` argues against for mypy on the same grounds.

**Scoped to this repository's own applications.** A third-party package shipping
a model whose migrations lag its declarations is not this product's defect to
fail on, and an audit that failed on one would be switched off within a day --
the scope predicate is `tests/model_registry.py`'s, the same one the three
registry audits use.

Reads migration files and the model registry: no database, no network, no
subprocess.
"""

from __future__ import annotations

from django.apps import apps
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.questioner import NonInteractiveMigrationQuestioner
from django.db.migrations.state import ProjectState

from tests.model_registry import first_party_app_names
from tests.model_registry import first_party_models


def unmigrated_changes() -> dict[str, list[str]]:
    """Return every model change this repository has not written a migration for.

    Returns:
        App label to the operations `makemigrations` would have generated, for
        this repository's own applications only. Empty when the migration graph
        already describes every declared model.

    """
    loader = MigrationLoader(None, ignore_no_migrations=True)
    autodetector = MigrationAutodetector(
        loader.project_state(),
        ProjectState.from_apps(apps),
        NonInteractiveMigrationQuestioner(specified_apps=set(), dry_run=True),
    )
    in_scope = {name.rpartition(".")[2] for name in first_party_app_names()}
    changes = autodetector.changes(graph=loader.graph, convert_apps=in_scope, migration_name="audit")
    return {
        app_label: [type(operation).__name__ for migration in migrations for operation in migration.operations]
        for app_label, migrations in changes.items()
        if app_label in in_scope
    }


def test_the_check_has_applications_and_models_to_look_at() -> None:
    """The vacuity guard: a scope that had narrowed to nothing reports a clean tree.

    `unmigrated_changes` filters by app label, so a scope predicate that returned
    an empty set would make the assertion below pass by comparing nothing against
    nothing -- which is indistinguishable from a repository whose migrations are
    complete.
    """
    assert first_party_app_names() != set()
    assert first_party_models() != []


def test_every_declared_model_change_has_a_migration() -> None:
    """`makemigrations` would generate nothing, which is the whole assertion.

    The failure this catches is a model edited without its migration -- a widened
    `max_length`, a new field, a dropped `db_index`, a changed `db_table`. Each
    of them passes every other test in this project, because the test database is
    built from the migrations *and* the models agree with themselves in memory;
    only a comparison of the two notices.
    """
    assert unmigrated_changes() == {}
