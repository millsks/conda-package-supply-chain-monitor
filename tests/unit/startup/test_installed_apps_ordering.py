"""No adopted application precedes the stage-2 owner in `INSTALLED_APPS` (AC #4).

AD-26 makes the stage-2 invocation the property of one *named* immovable-core
application, and the naming is only half of it: an application whose `ready()`
runs before the owner's runs before the refusal contract has been evaluated at
all. That ordering is `INSTALLED_APPS` order, which Django's app registry
preserves, so it is assertable rather than reviewable.

**The strong form of this gate needs Epic 5.** The adopted-app list arrives with
`component.toml` (Story 5.1); until it exists there is no roster of adopted
applications to compare indices against. What is assertable now is the invariant
that *makes* the strong form hold by construction: the owner is declared in
`LOCAL_APPS`, `LOCAL_APPS` is the last segment of the `INSTALLED_APPS`
composition, and every application at or after the owner comes from `LOCAL_APPS`.
An adopted application is appended to `LOCAL_APPS`, so it lands after the owner
by construction rather than by review. When `component.toml` lands, this module
gains the index comparison against its adopted-app list and keeps these as the
structural backstop.

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

from config.startup.stage_two import STAGE_TWO_OWNER_APP_LABEL


def _app_names_in_installed_order() -> list[str]:
    """Return every installed application's dotted name, in `INSTALLED_APPS` order."""
    return [app_config.name for app_config in apps.get_app_configs()]


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
