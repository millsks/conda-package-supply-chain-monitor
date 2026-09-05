"""AC #1: the package-identity application is installed, labelled and placed.

Shaped after `tests/unit/django_apps/test_core_app.py`, which is a template
rather than a sweep: it hardcodes `core` because the properties it asserts are
properties of *that* application's adoption, and the same is true here. A single
parametrized module over both applications would look like an economy and would
lose the thing that makes either useful -- the second application's adoption is
the one that can be forgotten in one of its two halves, and a sweep that iterated
`INSTALLED_APPS` would pass on whatever it happened to find.

What is deliberately *not* repeated from that module: `src/django_apps/` carrying
no `__init__.py`, and `django_apps` failing to import. Those are facts about the
import root rather than about an application, `CPM-PLATFORM-S01` owns them, and
asserting them twice would mean two modules to edit the day the root changes.
What *is* repeated is the resolution probe, because "this application resolves
from the second root" is a claim about this application: a copy of it under
`src/` would satisfy the import and fail here.

No database, no network, no subprocess. The app registry is populated at session
start, and the one filesystem touch is a comparison of a resolved `__file__`
against a path this repository owns.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Final

import pytest
from django.apps import apps
from django.conf import settings

from conda_package_supply_chain_monitor.identity.apps import IdentityConfig

#: `CPM-IDENTITY-S02`'s migration, imported by name because a module beginning
#: with a digit cannot be spelled in an `import` statement. The shape of a
#: migration is a contract -- `tests/unit/users/test_migrations.py` establishes
#: the pattern -- and this one carries a hand-written guard whose refusal no
#: database can reach once the constraint it protects exists.
_resolution_migration = importlib.import_module(
    "conda_package_supply_chain_monitor.identity.migrations.0002_resolution",
)

#: This repository's root, four levels up from `tests/unit/django_apps/`.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Where the application must resolve from. Not `src/`: an application that
#: resolved from the first root would mean the second one is doing nothing.
APPLICATION_ROOT: Final[Path] = REPO_ROOT / "src" / "django_apps"

#: The dotted name the application is installed and imported as. `django_apps` is
#: absent from it on purpose -- it is a path root, not a package.
APPLICATION_NAME: Final[str] = "conda_package_supply_chain_monitor.identity"

#: Derived by Django from the last segment of the name.
APPLICATION_LABEL: Final[str] = "identity"

#: The application adopted before this one. Order in `LOCAL_APPS` is load-bearing
#: (AD-8 appends contributions in it), so "after `core`" is asserted rather than
#: assumed.
PRECEDING_APPLICATION_NAME: Final[str] = "conda_package_supply_chain_monitor.core"

#: The stage-2 owner (AD-26). No adopted application may precede it.
STAGE_TWO_OWNER_NAME: Final[str] = "django_service.users"

#: Every module this application is allowed to declare today. `CPM-AD-19` gives a
#: domain application more than this -- `urls.py`, `tasks.py`, an `api/`
#: subpackage -- when it has views or work to schedule; this one has neither yet.
#:
#: `services.py` arrived with `CPM-IDENTITY-S06`, which needed the one door
#: `CPM-AD-25` names: the collector that ingests the inventory never writes the
#: package table, so a package it names for the first time is created by
#: `identity`'s resolution service. `CPM-IDENTITY-S02` added the second door
#: beside it -- `record_resolution`, which writes what a resolver concluded about
#: a package that already exists -- and `CPM-IDENTITY-S05` the third,
#: `override_identity`. All three live in that one module.
#:
#: `confidence.py` arrived with `CPM-IDENTITY-S05` and is not a fourth surface: it
#: holds `IdentityConfidence` and nothing else, re-exported from `models.py` so no
#: importer changed. It exists because `core/models.py` reads that vocabulary
#: while `identity/models.py` now reads `core.models.AppendOnlyModel` for the
#: audit row, and a leaf module is what keeps those two edges from being a cycle.
#: Its own docstring carries the reasoning.
EXPECTED_MODULES: Final[tuple[str, ...]] = (
    "__init__.py",
    "apps.py",
    "confidence.py",
    "models.py",
    "services.py",
)

#: The surfaces this story does not build, in both shapes each can take. A
#: `tasks.py` and a `tasks/` package are the same surface to Django and to the
#: audits that sweep for it, so an absence check that saw only the file would be
#: satisfied by the directory.
ABSENT_SURFACES: Final[tuple[str, ...]] = ("api", "admin", "serializers", "tasks", "urls", "views")

#: The one subpackage this application must have. `migrations/` is not optional:
#: `tests/unit/django_apps/test_migration_completeness.py` compares the declared
#: models against the migration graph, and an application whose migrations are
#: not a package contributes nothing to that graph while still declaring tables.
MIGRATIONS_PACKAGE: Final[str] = "migrations"


def test_the_application_is_installed() -> None:
    """A name naming no installed application would make every case below vacuous."""
    assert APPLICATION_NAME in settings.INSTALLED_APPS


def test_the_application_resolves_from_the_second_import_root() -> None:
    """The import that the second root exists to make work.

    Nothing is on `sys.path` for this. The editable install's redirecting finder
    maps `conda_package_supply_chain_monitor` straight onto
    `src/django_apps/conda_package_supply_chain_monitor/__init__.py`, and the
    application resolves as a subpackage through that.

    The assertion is on the resolved file's location, which is what makes this
    about the *second* root: a copy of the package under `src/` would satisfy the
    import and fail here.
    """
    module = importlib.import_module(APPLICATION_NAME)

    assert module.__file__ is not None
    assert Path(module.__file__).is_relative_to(
        APPLICATION_ROOT / "conda_package_supply_chain_monitor" / APPLICATION_LABEL
    )


def test_the_app_config_names_the_application_without_the_root() -> None:
    """`name` is the installed dotted path, and the label falls out of it."""
    assert IdentityConfig.name == APPLICATION_NAME
    assert apps.get_app_config(APPLICATION_LABEL).name == APPLICATION_NAME


def test_the_app_config_overrides_no_ready_hook() -> None:
    """AD-26: `django_service.users` is the sole stage-2 owner.

    Asserted against `AppConfig` itself rather than by reading the source: what
    matters is that this class contributes no boot-time work, however it came to
    have some.
    """
    assert "ready" not in vars(IdentityConfig)


def test_the_app_config_declares_no_default_auto_field() -> None:
    """`DEFAULT_AUTO_FIELD` is set once, project-wide, in `config/settings/base.py`.

    A per-app restatement would be a second declaration of one decision, and the
    failure it invites is the quiet kind: the two agree today, somebody changes
    the project setting, and one application's tables keep the old key width with
    nothing failing. `CPM-AD-3` fixes the surrogate integer for every table in
    this product, so there is one place to say so.
    """
    assert "default_auto_field" not in vars(IdentityConfig)


def test_the_app_config_declares_no_label_of_its_own() -> None:
    """The label is Django's derivation from `name`, not a second spelling.

    An explicit `label = "identity"` would be the same value written twice, and
    the day the two disagreed the tables, the migrations and the app registry
    would follow the explicit one while every reference to the dotted name
    followed the other.
    """
    assert "label" not in vars(IdentityConfig)
    assert apps.get_app_config(APPLICATION_LABEL).label == APPLICATION_LABEL


def test_the_application_is_ordered_after_the_stage_two_owner() -> None:
    """Read off the resolved registry, because `local.py` prepends to `INSTALLED_APPS`.

    `tests/unit/startup/test_installed_apps_ordering.py` holds the structural
    half of this and reconciles the whole adopted roster; this is the same
    invariant stated for the application this story adds.
    """
    names = [app_config.name for app_config in apps.get_app_configs()]

    assert names.index(STAGE_TWO_OWNER_NAME) < names.index(APPLICATION_NAME)


def test_the_application_is_declared_in_local_apps_after_core() -> None:
    """Both halves of the adoption, on the installing side.

    Appended rather than inserted, which is what puts it behind the stage-2 owner
    by construction, and behind `core` -- which it depends on -- by declaration.
    """
    local_apps = list(settings.LOCAL_APPS)

    assert APPLICATION_NAME in local_apps
    assert local_apps.index(STAGE_TWO_OWNER_NAME) < local_apps.index(APPLICATION_NAME)
    assert local_apps.index(PRECEDING_APPLICATION_NAME) < local_apps.index(APPLICATION_NAME)


def test_the_application_ships_a_migrations_package() -> None:
    """The half `test_migration_completeness.py` depends on, asserted directly.

    That audit compares this repository's declared models against the migration
    graph and fails on any difference. An application whose `migrations/` is a
    plain directory rather than a package contributes nothing to the graph --
    Django finds no migrations for it, treats it as unmigrated, and the audit's
    `ignore_no_migrations=True` loader is what keeps that from being an error. So
    the models would declare tables that no migration builds, and the failure
    would land at `migrate` on somebody else's machine.

    The `__init__.py` makes the directory importable, and it is the file most
    easily lost to a `.gitignore` rule or a directory copied without its
    dotfiles. The file list beside it is a second, weaker claim and is meant to
    be edited: it is what makes an *added* migration a deliberate act, so a file
    generated by `makemigrations` and left under its autogenerated name fails
    here rather than landing with a name nobody chose.
    """
    package = Path(apps.get_app_config(APPLICATION_LABEL).path)
    migrations = package / MIGRATIONS_PACKAGE

    assert migrations.is_dir(), migrations
    assert (migrations / "__init__.py").is_file()
    assert sorted(path.name for path in migrations.glob("0*.py")) == [
        "0001_package_identity.py",
        "0002_resolution.py",
        "0003_identity_override.py",
    ]


def test_the_resolution_migration_checks_for_duplicates_before_adding_the_constraint() -> None:
    """`AddConstraint` alone fails opaquely on a database that already violates it.

    `one_package_per_source_key` is what stops duplicate shells accruing, so a
    database written before this migration is exactly where they already are --
    and the backend's own refusal names an index nobody has heard of, after
    `package_mappings` has already been created. The `RunPython` in front of it
    turns that into a message naming the pairs.

    The order is the assertion: a check placed *after* the `AddConstraint` would
    never run on the database that needs it.
    """
    operations = _resolution_migration.Migration.operations
    names = [type(operation).__name__ for operation in operations]

    assert names.index("RunPython") < names.index("AddConstraint")
    assert operations[names.index("RunPython")].code is _resolution_migration.check_source_keys_are_unique


def test_the_duplicate_check_refuses_and_names_the_pairs_it_found() -> None:
    """The refusal itself, reachable without a database that cannot hold the rows.

    Once the constraint exists, no test can insert the duplicates this guard is
    about -- which is why the query and the refusal are two functions. This
    exercises the half that raises, and the message has to name the pair: "the
    constraint could not be added" sends an operator to the migration, and
    `'inventory'/'internal/numpy'` sends them to the two rows.
    """
    with pytest.raises(RuntimeError) as refused:
        _resolution_migration.refuse_duplicate_source_keys([("inventory", "internal/numpy")])

    assert "internal/numpy" in str(refused.value)
    assert "one_package_per_source_key" in str(refused.value)


def test_the_duplicate_check_passes_a_database_that_holds_none() -> None:
    """The other side, so the guard is not simply a migration that always fails."""
    assert _resolution_migration.refuse_duplicate_source_keys([]) is None


def test_the_application_declares_no_urls_serializers_or_tasks() -> None:
    """The surface this story does not build, asserted rather than merely omitted.

    `CPM-AD-19` gives a domain application `urls.py`, an `api/` subpackage and
    `tasks.py` when it has views or work to schedule. This one has neither:
    resolution is a service its callers invoke rather than a task it schedules,
    the override path is `CPM-IDENTITY-S05`'s and every read surface is
    `CPM-EP-APP`'s. An empty `urls.py` added "for
    later" would be routed by nothing and would still have to be reviewed, and a
    `tasks.py` would be swept by `tests/unit/django_apps/test_task_routing_audit.py`
    for a route it has no task to declare.

    **Both shapes of each surface.** A module comparison alone is satisfied by a
    `tasks/` package, which is the same surface with the same consequences and a
    different filesystem shape -- so each name is checked as a directory as well.
    `migrations/` is the one subpackage that must be there, and it has its own
    case above.
    """
    package = Path(apps.get_app_config(APPLICATION_LABEL).path)

    assert package.is_dir(), package
    assert sorted(path.name for path in package.glob("*.py")) == sorted(EXPECTED_MODULES)

    present = [name for name in ABSENT_SURFACES if (package / name).exists() or (package / f"{name}.py").exists()]
    assert present == [], f"this story builds none of these surfaces, but they are present: {present}"

    subpackages = sorted(path.name for path in package.iterdir() if path.is_dir() and not path.name.startswith("__"))
    assert subpackages == [MIGRATIONS_PACKAGE]
