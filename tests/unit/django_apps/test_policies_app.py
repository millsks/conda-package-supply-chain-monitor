"""The policy application is installed, labelled, placed, and adopts its passes.

Shaped after `tests/unit/django_apps/test_identity_app.py`, which is a template
rather than a sweep: it hardcodes its application because the properties it
asserts are properties of *that* application's adoption, and the same is true
here. A single parametrized module over four applications would look like an
economy and would lose the thing that makes any of them useful -- an adoption can
be forgotten in one of its two halves, and a sweep that iterated `INSTALLED_APPS`
would pass on whatever it happened to find.

What is deliberately *not* repeated from `tests/unit/django_apps/test_core_app.py`:
`src/django_apps/` carrying no `__init__.py`, and `django_apps` failing to
import. Those are facts about the import root rather than about an application,
`CPM-PLATFORM-S01` owns them, and asserting them four times would mean four
modules to edit the day the root changes. What *is* repeated is the resolution
probe, because "this application resolves from the second root" is a claim about
this application: a copy of it under `src/` would satisfy the import and fail
here.

**This application declares a `ready()`, which is why this module has cases the
other two do not.** `core` and `identity` declare none and their modules assert
that; `collectors` was the first that did. The hook here adopts `CurrencyPass`
into `core`'s registry, and what is asserted is that the adoption happened, that
it is idempotent, and that no refusal was invented to go with it.

No database, no network, no subprocess. The app registry is populated at session
start, and the one filesystem touch is a comparison of a resolved `__file__`
against a path this repository owns.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Final

from django.apps import apps
from django.conf import settings

from conda_package_supply_chain_monitor.core.policy import column_owners
from conda_package_supply_chain_monitor.core.policy import pass_registrations
from conda_package_supply_chain_monitor.core.rollup import contributable_columns
from conda_package_supply_chain_monitor.policies.apps import PoliciesConfig
from conda_package_supply_chain_monitor.policies.currency import POLICY_NAME
from conda_package_supply_chain_monitor.policies.currency import ROLLUP_COLUMN
from conda_package_supply_chain_monitor.policies.currency import CurrencyPass
from tests.passes import ADOPTED_PASS_NAMES

#: This repository's root, four levels up from `tests/unit/django_apps/`.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Where the application must resolve from. Not `src/`: an application that
#: resolved from the first root would mean the second one is doing nothing.
APPLICATION_ROOT: Final[Path] = REPO_ROOT / "src" / "django_apps"

#: The dotted name the application is installed and imported as. `django_apps` is
#: absent from it on purpose -- it is a path root, not a package.
APPLICATION_NAME: Final[str] = "conda_package_supply_chain_monitor.policies"

#: Derived by Django from the last segment of the name.
APPLICATION_LABEL: Final[str] = "policies"

#: The application adopted before this one. Order in `LOCAL_APPS` is load-bearing
#: (AD-8 appends contributions in it), so "after `collectors`" is asserted rather
#: than assumed -- and the pass registry keeps *declaration* order (`CPM-AD-21`),
#: so where this application sits is part of what is declared about which pass
#: may read which.
PRECEDING_APPLICATION_NAME: Final[str] = "conda_package_supply_chain_monitor.collectors"

#: The stage-2 owner (AD-26). No adopted application may precede it.
STAGE_TWO_OWNER_NAME: Final[str] = "django_service.users"

#: Every module this application declares today. `CPM-AD-19` gives a domain
#: application `urls.py`, `tasks.py` and an `api/` subpackage when it has views or
#: work to schedule; this one has neither. A pass runs inside a policy run, which
#: `core/tasks.py` already schedules, so there is no task here to declare and
#: nothing for `tests/unit/django_apps/test_task_routing_audit.py` to route.
#:
#: `outcomes.py` is a leaf module holding `CurrencyOutcome` and nothing else, on
#: exactly the terms `identity/confidence.py` holds `IdentityConfidence`:
#: `core/models.py` reads the vocabulary for the rollup column while
#: `policies/currency.py` reads `core.policy`, and those two edges together would
#: be an import cycle. Its own docstring carries the reasoning.
EXPECTED_MODULES: Final[tuple[str, ...]] = (
    "__init__.py",
    "apps.py",
    "currency.py",
    "models.py",
    "outcomes.py",
)

#: The surfaces this story does not build, in both shapes each can take. A
#: `tasks.py` and a `tasks/` package are the same surface to Django and to the
#: audits that sweep for it, so an absence check that saw only the file would be
#: satisfied by the directory.
ABSENT_SURFACES: Final[tuple[str, ...]] = ("api", "admin", "serializers", "tasks", "urls", "views")

#: The one subpackage this application must have.
#: `tests/unit/django_apps/test_migration_completeness.py` compares the declared
#: models against the migration graph, and an application whose `migrations/` is
#: not a package contributes nothing to that graph while still declaring tables.
MIGRATIONS_PACKAGE: Final[str] = "migrations"

#: The migrations this application ships, by name. A second, weaker claim beside
#: the package check above, and meant to be edited: it is what makes an *added*
#: migration a deliberate act, so a file generated by `makemigrations` and left
#: under its autogenerated name fails here rather than landing with a name nobody
#: chose.
EXPECTED_MIGRATIONS: Final[tuple[str, ...]] = ("0001_package_currency.py",)


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
        APPLICATION_ROOT / "conda_package_supply_chain_monitor" / APPLICATION_LABEL,
    )


def test_the_app_config_names_the_application_without_the_root() -> None:
    """`name` is the installed dotted path, and the label falls out of it."""
    assert PoliciesConfig.name == APPLICATION_NAME
    assert apps.get_app_config(APPLICATION_LABEL).name == APPLICATION_NAME


def test_the_app_config_declares_no_default_auto_field() -> None:
    """`DEFAULT_AUTO_FIELD` is set once, project-wide, in `config/settings/base.py`.

    A per-app restatement would be a second declaration of one decision, and the
    failure it invites is the quiet kind: the two agree today, somebody changes
    the project setting, and one application's tables keep the old key width with
    nothing failing. `CPM-AD-3` fixes the surrogate integer for every table in
    this product, so there is one place to say so.
    """
    assert "default_auto_field" not in vars(PoliciesConfig)


def test_the_app_config_declares_no_label_of_its_own() -> None:
    """The label is Django's derivation from `name`, not a second spelling.

    An explicit `label = "policies"` would be the same value written twice, and
    the day the two disagreed the tables, the migrations and the app registry
    would follow the explicit one while every reference to the dotted name
    followed the other.
    """
    assert "label" not in vars(PoliciesConfig)
    assert apps.get_app_config(APPLICATION_LABEL).label == APPLICATION_LABEL


def test_the_application_is_ordered_after_the_stage_two_owner() -> None:
    """Read off the resolved registry, because `local.py` prepends to `INSTALLED_APPS`.

    `tests/unit/startup/test_installed_apps_ordering.py` holds the structural
    half of this and reconciles the whole adopted roster; this is the same
    invariant stated for the application this story adds -- and it matters more
    here than for `core` and `identity`, because this application declares a
    `ready()` and would therefore actually run before stage two if it preceded
    the owner.
    """
    names = [app_config.name for app_config in apps.get_app_configs()]

    assert names.index(STAGE_TWO_OWNER_NAME) < names.index(APPLICATION_NAME)


def test_the_application_is_declared_in_local_apps_last() -> None:
    """Both halves of the adoption, on the installing side.

    Appended rather than inserted, which is what puts it behind the stage-2 owner
    by construction and behind every application it depends on -- `core` for the
    pass machinery, `identity` for the package and the authority order, and
    `collectors` for the four evidence tables it reads.

    Last, and that is asserted rather than merely true: `CPM-AD-21` keeps the
    pass registry in *declaration* order because a later pass may read an earlier
    pass's derived rows, so the position of the application that registers a pass
    is part of what has been declared about it.
    """
    local_apps = list(settings.LOCAL_APPS)

    assert local_apps.index(STAGE_TWO_OWNER_NAME) < local_apps.index(APPLICATION_NAME)
    assert local_apps.index(PRECEDING_APPLICATION_NAME) < local_apps.index(APPLICATION_NAME)
    assert local_apps[-1] == APPLICATION_NAME


def test_the_ready_hook_adopted_this_applications_passes() -> None:
    """The registration `policies/apps.py` performs, asserted against the live registry.

    This is the case that would fail if `ready()` were removed, if the
    application were dropped from `LOCAL_APPS`, or if the tuple in the hook were
    emptied -- each of which would silently return
    `tests/unit/django_apps/test_pass_ownership_audit.py` to sweeping nothing,
    which is the state that module spent an epic being honest about.

    Asserted by *identity*, not by name: two classes under one name are what
    `register_pass` refuses, and a name check would pass for whichever of them
    got there.
    """
    assert pass_registrations().get(POLICY_NAME) is CurrencyPass
    assert set(ADOPTED_PASS_NAMES) <= set(pass_registrations())


def test_the_adopted_pass_owns_the_rollup_column_it_declares() -> None:
    """The other half of adoption: the contribution the registry recorded.

    A pass can be registered and own nothing -- `contributes` is legitimately
    empty for a pass whose whole output is its own derived table -- so
    registration alone does not say the column arrived. This does, in both
    directions: the rollup offers the column, and this pass is who owns it.
    """
    assert ROLLUP_COLUMN in contributable_columns()
    assert column_owners().get(ROLLUP_COLUMN) == POLICY_NAME


def test_the_ready_hook_can_run_twice_without_aborting_boot() -> None:
    """`AppConfig.ready` is Django's to call, and a second `django.setup()` calls it again.

    `register_pass` refuses a duplicate name, correctly -- two different classes
    under one name share an entry in the rollup's version map and are
    indistinguishable in every report. What the guard in the hook stops is that
    refusal firing on an adoption that had *already succeeded*, which would be a
    component that will not start for no reason anybody chose.

    Driven rather than read: calling `ready()` again is the exact thing a second
    `django.setup()` does, and asserting the source contains an `if` would be
    asserting the shape of the fix rather than the property.
    """
    before = pass_registrations()

    apps.get_app_config(APPLICATION_LABEL).ready()

    assert pass_registrations() == before
    assert column_owners().get(ROLLUP_COLUMN) == POLICY_NAME


def test_the_application_ships_a_migrations_package() -> None:
    """The half `test_migration_completeness.py` depends on, asserted directly.

    That audit compares this repository's declared models against the migration
    graph and fails on any difference. An application whose `migrations/` is a
    plain directory rather than a package contributes nothing to the graph --
    Django finds no migrations for it, treats it as unmigrated, and the audit's
    `ignore_no_migrations=True` loader is what keeps that from being an error. So
    the models would declare tables that no migration builds, and the failure
    would land at `migrate` on somebody else's machine.
    """
    package = Path(apps.get_app_config(APPLICATION_LABEL).path)
    migrations = package / MIGRATIONS_PACKAGE

    assert migrations.is_dir(), migrations
    assert (migrations / "__init__.py").is_file()
    assert tuple(sorted(path.name for path in migrations.glob("0*.py"))) == EXPECTED_MIGRATIONS


def test_the_application_declares_no_urls_serializers_or_tasks() -> None:
    """The surface this story does not build, asserted rather than merely omitted.

    `CPM-AD-19` gives a domain application `urls.py`, an `api/` subpackage and
    `tasks.py` when it has views or work to schedule. This one has neither: a
    pass is executed by `core/policy_run.py` inside the run `core/tasks.py`
    schedules, and every read surface is `CPM-EP-APP`'s. An empty `urls.py` added
    "for later" would be routed by nothing and would still have to be reviewed,
    and a `tasks.py` would be swept by
    `tests/unit/django_apps/test_task_routing_audit.py` for a route it has no
    task to declare.

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
