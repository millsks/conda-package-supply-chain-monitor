"""Shape and authorship assertions for the role-group migration. No database.

Four properties, none of which a run of the migration would demonstrate:

* it is **not elidable**, so a future squash cannot take the guarantee that the
  role groups exist away with it;
* it **depends on the one writer's own migration**, so the mechanism it calls has
  already run against the database before any role group is asked for;
* it **creates no `Group` of its own**, which is a property of the source rather
  than of any run -- a second writer is wrong the moment it is written, whether
  or not a test ever executes it;
* it **names no group**, for the reason `roles.py` names none: the names are the
  operator's and a literal here would be a second, silent source for one.

The scan for the third is `tests/group_writers.py`, the shared detector
`tests/unit/users/test_provisioning.py` runs over the whole of `src/`. It is
asked again here, of this one file, because a migration that creates groups
inline is the exact shape AD-27 was written against -- so the failure should name
this story's file rather than only the repository-wide audit.

The behavioural half -- the rows that appear, the collision with a designated
group, and the rollback -- is in
`tests/integration/django_apps/test_role_groups.py`.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.db import migrations

from tests.group_writers import group_creation_verbs

if TYPE_CHECKING:
    from types import ModuleType

MIGRATION_MODULE = "conda_package_supply_chain_monitor.core.migrations.0001_provision_role_groups"

# `auth` carries `Group`; `users.0003` is the one writer's own migration.
EXPECTED_DEPENDENCIES = [
    ("auth", "0012_alter_user_first_name_max_length"),
    ("users", "0003_provision_designated_groups"),
]


@pytest.fixture
def migration() -> ModuleType:
    """The migration module, imported per case rather than at module scope.

    An import at module scope would make a broken migration fail *collection* of
    this file, which reports as an error with no test name attached and takes the
    other cases with it.
    """
    return import_module(MIGRATION_MODULE)


@pytest.fixture
def migration_source(migration: ModuleType) -> Path:
    """The migration's own file, resolved from the imported module.

    Read off `__file__` rather than rebuilt from `settings.BASE_DIR` and the
    second import root's layout: that layout is
    `tests/unit/test_import_roots.py`'s to assert, a hand-built path is a second
    copy of it, and a guessed path that stopped existing would need a guard of
    its own to keep the scan below from passing vacuously.
    """
    assert migration.__file__ is not None
    return Path(migration.__file__)


def test_the_migration_is_a_single_run_python_operation(migration: ModuleType) -> None:
    """One data operation, forward and reverse, and no schema change.

    `core` has no models, so a schema operation appearing here would mean a model
    was added without its own migration alongside it.
    """
    operations = migration.Migration.operations

    assert [type(operation).__name__ for operation in operations] == ["RunPython"]
    operation = operations[0]
    assert isinstance(operation, migrations.RunPython)
    assert operation.code is migration.forward
    assert operation.reverse_code is migration.reverse


def test_the_migration_is_not_elidable(migration: ModuleType) -> None:
    """Squashing it away would take the only guarantee the role groups exist.

    An asserted role would then resolve to no row, be ignored and logged under
    AD-12, and the person would authenticate with no access at all.
    """
    assert migration.Migration.operations[0].elidable is False


def test_the_migration_depends_on_the_one_writers_own_migration(migration: ModuleType) -> None:
    """Ordering, not decoration.

    `users.0003_provision_designated_groups` is where the provisioning mechanism
    first runs against a database. Depending on it means the platform's own
    groups exist before the product's do, in one `migrate` invocation, in a
    declared order rather than in whichever order the graph happened to resolve.
    """
    assert sorted(migration.Migration.dependencies) == sorted(EXPECTED_DEPENDENCIES)


def test_the_migration_creates_no_group_of_its_own(migration_source: Path) -> None:
    """AD-27: group creation has exactly one call site, and this is not it."""
    assert group_creation_verbs(migration_source) == set()


def test_the_migration_names_no_group(migration_source: Path) -> None:
    """No configured group name appears anywhere in the migration's source.

    The same assertion `tests/unit/users/test_provisioning.py` makes about the
    platform's provisioning module and `test_roles.py` makes about `roles.py`,
    asked of the third file that could hold one. A literal here would survive
    every rename of the environment variables, and would be provisioned once and
    then never corrected -- the migration is applied exactly once.
    """
    source = migration_source.read_text(encoding="utf-8")
    contract = settings.ROLE_CONTRACT

    for name in (contract.security_reviewer, contract.packaging_engineer, contract.leadership):
        assert name, "the suite must run against a configured role contract for this to mean anything"
        assert name not in source, f"the migration hardcodes the configured group name {name!r}"
