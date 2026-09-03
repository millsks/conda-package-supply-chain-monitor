"""No adopted application precedes the stage-2 owner in `INSTALLED_APPS` (AC #4).

AD-26 makes the stage-2 invocation the property of one *named* immovable-core
application, and the naming is only half of it: an application whose `ready()`
runs before the owner's runs before the refusal contract has been evaluated at
all. That ordering is `INSTALLED_APPS` order, which Django's app registry
preserves, so it is assertable rather than reviewable.

**The strong form is now live.** The adopted-app list arrived with
`component.toml` (Story 5.1) and is non-empty as of the first domain
application, so this module compares indices against that roster directly:
every adopted application is installed, and every one of them is ordered after
the owner.

The structural cases are kept as the backstop, and they are not redundant. They
say the owner is declared in `LOCAL_APPS`, that `LOCAL_APPS` is the last segment
of the `INSTALLED_APPS` composition, and that every application at or after the
owner comes from `LOCAL_APPS` -- which is what makes an appended adopted
application land behind the owner *by construction*. But they inspect
`names[owner_index:]` only, so an adopted application that arrived some other
way -- installed into `THIRD_PARTY_APPS`, or prepended by `local.py` -- would
sit ahead of the owner in a stretch of the list they never look at. The roster
comparison is what closes that, because it starts from the declared adoption
rather than from the owner's position.

Read off the live app registry rather than off a parsed `base.py`: what matters
is the order Django resolved, and `local.py` already prepends to
`INSTALLED_APPS` -- so a source-level assertion would be asserting about a list
that no running process ever sees.

This is a unit test: the app registry is populated at session start and no
database, network or filesystem access is involved.
"""

from __future__ import annotations

from django.apps import apps
from django.conf import settings

from config.component import load_component_declaration
from config.startup.stage_two import STAGE_TWO_OWNER_APP_LABEL


def _app_names_in_installed_order() -> list[str]:
    """Return every installed application's dotted name, in `INSTALLED_APPS` order."""
    return [app_config.name for app_config in apps.get_app_configs()]


def _adopted_apps() -> tuple[str, ...]:
    """Return the applications `component.toml` declares this component has adopted."""
    return load_component_declaration().adopted_apps


def test_the_stage_two_owner_is_installed() -> None:
    """A label naming no installed application would make every case below vacuous."""
    labels = [app_config.label for app_config in apps.get_app_configs()]

    assert STAGE_TWO_OWNER_APP_LABEL in labels


def test_the_stage_two_owner_lives_in_django_service() -> None:
    """AD-29: `django_service` is `core` in its entirety.

    That is what makes the owner travel in all six combinations by construction
    -- no `feature:*` disposition may apply to any path inside it, so no
    materialization can remove the application that owns the invocation point.
    """
    owner = apps.get_app_config(STAGE_TWO_OWNER_APP_LABEL)

    assert owner.name.startswith("django_service.")


def test_the_stage_two_owner_is_declared_in_local_apps() -> None:
    """The owner is a first-party application, not a third-party one adopted here."""
    owner = apps.get_app_config(STAGE_TWO_OWNER_APP_LABEL)

    assert owner.name in settings.LOCAL_APPS


def test_local_apps_is_the_last_segment_of_the_installed_apps_composition() -> None:
    """`INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS`, asserted as resolved.

    This is the half that makes the weaker invariant equivalent to the strong
    one: an adopted application is appended to `LOCAL_APPS`, so as long as
    `LOCAL_APPS` is last and the owner is its first entry, no adopted
    application can precede the owner.
    """
    installed = list(settings.INSTALLED_APPS)
    local_apps = list(settings.LOCAL_APPS)

    assert local_apps, "LOCAL_APPS is empty, so this case asserts nothing"
    assert installed[-len(local_apps) :] == local_apps


def test_no_application_after_the_stage_two_owner_comes_from_outside_local_apps() -> None:
    """AC #4, in the form that is assertable before `component.toml` exists.

    Epic 5's adopted-app list is the eventual source of the roster this compares
    against; until then the assertion is that everything at or after the owner
    is a `LOCAL_APPS` entry, which is where an adopted application will be
    declared.
    """
    names = _app_names_in_installed_order()
    owner_name = apps.get_app_config(STAGE_TWO_OWNER_APP_LABEL).name
    owner_index = names.index(owner_name)

    trailing = names[owner_index:]
    outsiders = [name for name in trailing if name not in settings.LOCAL_APPS]

    assert outsiders == [], f"these applications are ordered at or after the stage-2 owner: {outsiders}"


def test_the_stage_two_owner_is_the_first_local_app() -> None:
    """The owner heads `LOCAL_APPS`, so an application appended to it lands behind."""
    owner_name = apps.get_app_config(STAGE_TWO_OWNER_APP_LABEL).name

    assert next(iter(settings.LOCAL_APPS)) == owner_name


def test_this_component_has_adopted_something() -> None:
    """An empty roster would make the two cases below assert nothing at all.

    Empty is an ordinary state for a component in general -- `component.toml`'s
    loader treats it as one and `tests/unit/test_component_declaration.py`
    covers it -- but it is not this repository's state, and the strong form of
    AC #4 is only a gate while something is declared. This is the guard that
    says so out loud rather than letting the roster comparison pass vacuously.
    """
    assert _adopted_apps(), "component.toml declares no adopted application; the cases below are vacuous"


def test_every_adopted_application_is_installed() -> None:
    """A declared adoption that is not installed makes its ordering unassertable.

    `adopted_apps` is a declaration and `INSTALLED_APPS` is what installs; until
    Epic 9 composes the first into the second they are written separately, so
    they can disagree. This is the case that notices.
    """
    installed = list(settings.INSTALLED_APPS)

    missing = [name for name in _adopted_apps() if name not in installed]

    assert missing == [], f"these applications are adopted in component.toml but not installed: {missing}"


def test_no_adopted_application_precedes_the_stage_two_owner() -> None:
    """AC #4 in its strong form: the roster compared against the resolved registry.

    Indices off the live registry, and the whole list rather than the stretch
    after the owner. The structural cases above look only at `names[owner_index:]`
    and so cannot see an adopted application that reached `INSTALLED_APPS` by
    some route other than being appended to `LOCAL_APPS` -- an entry added to
    `THIRD_PARTY_APPS`, or one `local.py` prepends. Both land *before* the
    owner, which is exactly the failure AD-26 forbids and exactly the region
    those cases do not inspect.
    """
    names = _app_names_in_installed_order()
    owner_index = names.index(apps.get_app_config(STAGE_TWO_OWNER_APP_LABEL).name)

    offenders = [name for name in _adopted_apps() if name in names and names.index(name) < owner_index]

    assert offenders == [], f"these adopted applications are ordered before the stage-2 owner: {offenders}"
