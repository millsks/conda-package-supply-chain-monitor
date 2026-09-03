"""The first domain application under the second import root.

`src/django_apps/` is a path root, not a package. That distinction is the whole
of what this module asserts, in the three forms it can take without building a
wheel: the application imports under the name it is installed as, the root
itself does not import at all, and the app registry carries it in the position
`INSTALLED_APPS` puts it in.

The wheel-layout row of the story's matrix is not here -- it needs a real build,
and `tests/integration/test_import_resolution.py` owns it, along with the same
import probes run in a subprocess with `PYTHONPATH` cleared. What runs here runs
in-process against the registry pytest-django already populated: no database, no
network, no subprocess and no build.

Two cases do touch the filesystem, and deliberately. `stat`-ing
`src/django_apps/` for an absent `__init__.py`, and comparing a resolved
`__file__` against a repository path, are how "the root is not a package" and
"the application resolves from the second root" are stated as facts about the
tree rather than as facts about whichever import happened to run first. They are
two `stat` calls against paths this repository owns -- no I/O that can be slow,
flake, or leave anything behind -- so this stays a unit test.

The assertions are shaped as this module's neighbours in `tests/unit/startup/`
are: an anti-vacuity guard first, then one assertion per invariant.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings

from conda_package_supply_chain_monitor.core.apps import CoreConfig

REPO_ROOT = Path(__file__).resolve().parents[3]

# The second root's directory name, and the module name that must never resolve.
ROOT_NAME = "django_apps"

# Where the application must resolve from. Not `src/`: an application that
# resolved from the first root would mean the second one is doing nothing.
APPLICATION_ROOT = REPO_ROOT / "src" / ROOT_NAME

# The dotted name the application is installed and imported as. `django_apps`
# is absent from it on purpose -- see the module docstring.
APPLICATION_NAME = "conda_package_supply_chain_monitor.core"

# Derived by Django from the last segment of the name.
APPLICATION_LABEL = "core"

# The stage-2 owner (AD-26). No adopted application may precede it.
STAGE_TWO_OWNER_NAME = "django_service.users"


def test_the_application_is_installed() -> None:
    """A name naming no installed application would make every case below vacuous."""
    assert APPLICATION_NAME in settings.INSTALLED_APPS


def test_the_application_resolves_from_the_second_import_root() -> None:
    """The import that the second root exists to make work.

    Nothing is on `sys.path` for this. `dev-mode-exact = true` makes the
    editable install a redirecting finder that maps
    `conda_package_supply_chain_monitor` straight onto
    `src/django_apps/conda_package_supply_chain_monitor/__init__.py`, and the
    application resolves as a subpackage through that. The finder is generated
    from `[tool.hatch.build.targets.wheel]` and nothing else in this repository
    may resolve the name -- `tests/unit/test_import_roots.py` asserts the
    absence of every alternative.

    The assertion is on the resolved file's location, which is what makes this
    about the *second* root: a copy of the package under `src/` would satisfy
    the import and fail here.
    """
    module = importlib.import_module(APPLICATION_NAME)

    assert module.__file__ is not None
    assert Path(module.__file__).is_relative_to(APPLICATION_ROOT / "conda_package_supply_chain_monitor" / "core")


def test_the_import_root_is_not_a_package() -> None:
    """`django_apps` never appears in an import statement.

    It carries no `__init__.py` and is mapped onto the wheel root, so there is
    no second, silently-working spelling of any application. If this import
    started succeeding, the root would have become importable and
    `django_apps.conda_package_supply_chain_monitor.core` would resolve too --
    which is what it did under hatchling's default editable mode, where
    `<repo>/src` goes on `sys.path` and makes `django_apps` an implicit
    namespace package.

    `sys.modules` is cleared of the name and the finder caches invalidated
    first. `import_module` returns a cached module without consulting any
    finder, so anything that had imported `django_apps` earlier in the session
    -- including a future test written to prove it *can* be imported -- would
    make this case pass while asserting nothing. This is the story's central
    requirement, so a silent pass is the worst available failure.
    """
    sys.modules.pop(ROOT_NAME, None)
    importlib.invalidate_caches()

    with pytest.raises(ModuleNotFoundError, match=ROOT_NAME):
        importlib.import_module(ROOT_NAME)


def test_the_import_root_carries_no_init_module() -> None:
    """The file whose absence the case above depends on, asserted directly.

    Kept separate because the import above can fail for reasons that have
    nothing to do with the file -- a stale entry in `sys.modules`, say -- and
    "the root is not a package" is a property of the tree.
    """
    assert APPLICATION_ROOT.is_dir(), APPLICATION_ROOT
    assert not (APPLICATION_ROOT / "__init__.py").exists()


def test_the_app_config_names_the_application_without_the_root() -> None:
    """`name` is the installed dotted path, and the label falls out of it."""
    assert CoreConfig.name == APPLICATION_NAME
    assert apps.get_app_config(APPLICATION_LABEL).name == APPLICATION_NAME


def test_the_app_config_overrides_no_ready_hook() -> None:
    """AD-26: `django_service.users` is the sole stage-2 owner.

    Asserted against `AppConfig` itself rather than by reading the source: what
    matters is that this class contributes no boot-time work, however it came to
    have some.
    """
    assert "ready" not in vars(CoreConfig)


def test_the_application_is_ordered_after_the_stage_two_owner() -> None:
    """Read off the resolved registry, because `local.py` prepends to `INSTALLED_APPS`.

    `tests/unit/startup/test_installed_apps_ordering.py` holds the structural
    half of this -- `LOCAL_APPS` is the trailing segment and the owner heads it.
    This is the same invariant stated for the application that made it load-bearing.
    """
    names = [app_config.name for app_config in apps.get_app_configs()]

    assert names.index(STAGE_TWO_OWNER_NAME) < names.index(APPLICATION_NAME)


def test_the_application_is_declared_in_local_apps() -> None:
    """First-party, appended -- which is what puts it behind the owner by construction."""
    local_apps = list(settings.LOCAL_APPS)

    assert APPLICATION_NAME in local_apps
    assert local_apps.index(STAGE_TWO_OWNER_NAME) < local_apps.index(APPLICATION_NAME)
