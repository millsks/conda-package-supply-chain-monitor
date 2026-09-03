"""The shape of the local sign-in route, asserted against the resolved URLconf.

AD-21 makes local persona sign-in "a URL route and by no other mechanism", with
"its URL name and path prefix fixed constants declared in exactly one place".
Those are structural claims, so they are asserted structurally: `reverse` and
`resolve` read the configuration Django actually loaded, the mount decision is
called as a function rather than inferred from a module that has already been
imported, and the single-declaration rule is checked by reading the source tree.

Three of these deserve their reasons stated.

**The view's owning module is asserted by object identity, not by name.** Epic
4's stage-2 predicate refuses any route whose view callable belongs to
`config.local_dev` (AD-26: predicates resolve objects, never strings). A refactor
that moved the view -- or a decorator that relocated its `__module__` -- would
leave every other assertion here green and silently make that predicate blind.
Asserting it now catches the move in the story that owns the module rather than
in the epic that consumes it.

**The mount decision is called, never reloaded.** The whole suite runs in the
`dev` pixi environment, which declares `COMPONENT_RUNTIME=local`, so
`config.urls` was imported with locality already true and the route already
mounted. A module-level `if` would therefore be assertable only by reloading the
URLconf, which mutates an object every later test resolves through.
`local_signin_urlpatterns()` is directly callable under a monkeypatched
environment, with nothing reloaded and nothing to restore. The other half -- that
the decision actually reaches the resolver -- is the reload test in
`tests/integration/test_local_dev_signin.py`.

**The prefix is asserted not to be under `accounts/`.** That is not decoration
either: AD-21 uses that exact case as its worked failure, because a local sign-in
route mounted there "would pass an allowlist that already permits `/accounts/`
for allauth".

Unit assertions throughout: the URLconf and the settings are read in-process and
the source tree is read as text, with no database, socket or template render.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.urls import URLResolver
from django.urls import resolve
from django.urls import reverse

from config import urls as project_urls
from config.local_dev import urls as local_dev_urls
from config.local_dev import views
from config.local_dev.constants import LOCAL_SIGNIN_PATH_PREFIX
from config.local_dev.constants import LOCAL_SIGNIN_URL_NAME
from config.local_dev.personas import persona_keys
from config.locality import RUNTIME_ENV_VAR
from config.urls import local_signin_urlpatterns

# The module Epic 4's predicate resolves against. Spelled here because it is the
# thing being asserted, not a way of naming something that could be imported.
VIEW_MODULE = "config.local_dev.views"

# The URLconf the mount includes, by dotted string so it is imported as the
# mount is built rather than whenever the project URLconf is.
INCLUDED_URLCONF = "config.local_dev.urls"

# The credential surface FR-17's allowlist is evaluated over, as this settings
# module composes it. Asserted as an exact, ordered list: the order decides which
# backend answers first, and the exactness is what fails when a local-development
# backend is added.
#
# `ModelBackend` is second and comes from `test.py`, not from `base.py`. Story 4.6
# moved it there with allauth's local login method, because a base carrying either
# is stage 1's condition 2 and made every deployed component refuse to start. What
# this list asserts is therefore the *composed* surface of a local run; the
# deployed surface is allauth's backend alone, and
# `tests/unit/startup/test_authentication_allowlist.py` asserts that one against
# `config.startup.allowlist`.
EXPECTED_BACKENDS = [
    "allauth.account.auth_backends.AuthenticationBackend",
    "django.contrib.auth.backends.ModelBackend",
]

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"

# The one module permitted to spell either constant, until Epic 7 relocates the
# declaration into `accelerator.toml`.
DECLARATION_SITE = SRC_ROOT / "config" / "local_dev" / "constants.py"

# Source-bearing files. `.html` is included because a template that spelled the
# route name in a `{% url %}` tag would be a second declaration site exactly as a
# Python literal would.
SOURCE_SUFFIXES = frozenset({".py", ".html"})


def _signin_path(persona_key: str) -> str:
    """Return the sign-in path for a persona key, through the resolver."""
    return reverse(LOCAL_SIGNIN_URL_NAME, kwargs={"persona_key": persona_key})


@pytest.mark.parametrize("persona_key", persona_keys())
def test_the_signin_route_reverses_under_the_declared_prefix(persona_key: str) -> None:
    """AC #2: the route is reachable by its declared name, at its declared prefix."""
    path = _signin_path(persona_key)

    assert path.startswith("/" + LOCAL_SIGNIN_PATH_PREFIX)
    assert path.endswith("/" + persona_key + "/")


def test_the_index_route_reverses_at_the_prefix_itself() -> None:
    """The list page is the prefix; the act is the prefix plus a persona key."""
    assert reverse(f"{LOCAL_SIGNIN_URL_NAME}_index") == "/" + LOCAL_SIGNIN_PATH_PREFIX


def test_the_persona_is_a_path_segment_rather_than_a_query_parameter() -> None:
    """AD-21 names "a query-parameter shim" as a forbidden shape.

    The captured keyword is what proves the persona is part of the path: a shim
    reading `?persona=` would resolve the same path with no arguments at all.
    """
    match = resolve(_signin_path("staff"))

    assert match.kwargs == {"persona_key": "staff"}


@pytest.mark.parametrize("url_name", [LOCAL_SIGNIN_URL_NAME, f"{LOCAL_SIGNIN_URL_NAME}_index"])
def test_the_resolved_view_belongs_to_the_local_sign_in_module(url_name: str) -> None:
    """AD-26: the property Epic 4's refusal predicate resolves, asserted here first.

    Neither view is decorated, so `__module__` is the one the `def` gave it. That
    is not a reason to stop asserting it: a refactor that moved a view, or a
    decorator added later that did not preserve `__module__`, would take the view
    out of the predicate's sight while every path and name assertion above stayed
    green.
    """
    path = reverse(url_name) if url_name.endswith("_index") else _signin_path("staff")

    assert resolve(path).func.__module__ == VIEW_MODULE


def test_the_prefix_is_not_mounted_under_the_allauth_prefix() -> None:
    """AD-21's worked failure: a route under `/accounts/` passes an allowlist that already permits it."""
    assert not LOCAL_SIGNIN_PATH_PREFIX.startswith("accounts/")
    assert not _signin_path("staff").startswith("/accounts/")


def test_the_authentication_backends_are_unchanged() -> None:
    """FR-17: this story adds one route prefix and no backend.

    `django.contrib.auth.login(request, user, backend=...)` names a backend that
    is already declared. Adding one would widen the allowlist surface, which is
    the one thing a route mounted only where locality is local cannot make safe:
    a backend is consulted in every environment.
    """
    assert list(settings.AUTHENTICATION_BACKENDS) == EXPECTED_BACKENDS
    assert not [entry for entry in settings.AUTHENTICATION_BACKENDS if entry.startswith("config.local_dev")]


def test_the_session_backend_is_one_of_the_declared_backends() -> None:
    """The name the view hands to `login()` has to be in the setting, or the session evaporates.

    `django.contrib.auth.login` does not check that the backend it is given is
    declared; `get_user` does, on the *next* request, and answers `AnonymousUser`
    when it is not. So a drifted spelling produces a sign-in that returns 302 and
    a session that is gone by the redirect -- a failure that reads as a session
    bug rather than a naming one. Asserted directly rather than relied on as a
    side effect of the admin tests.
    """
    assert views.SESSION_BACKEND in settings.AUTHENTICATION_BACKENDS


def test_the_mount_is_absent_when_the_run_is_not_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-21: "the module ships in every component; the route is mounted only where locality is local"."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")

    assert local_signin_urlpatterns() == []


def test_the_mount_is_present_when_the_run_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other branch, and that it mounts the declared prefix at the declared URLconf.

    The include is by dotted string, which Django resolves to the module as the
    mount is built -- so a deployed component, where this function returns
    nothing, never imports the local sign-in URLconf at all. The assertion is
    therefore on the resolved module's name rather than on the string that named
    it.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "local")

    mounted = local_signin_urlpatterns()

    assert len(mounted) == 1
    mount = mounted[0]
    assert isinstance(mount, URLResolver)
    assert str(mount.pattern) == LOCAL_SIGNIN_PATH_PREFIX
    assert mount.urlconf_name.__name__ == INCLUDED_URLCONF


def test_the_mount_is_gated_on_locality_and_not_on_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-13: `DEBUG` is not the locality signal, and must not be able to mount a credential path.

    The failure this forbids is concrete: a deployed component with `DEBUG`
    mistakenly true would otherwise serve a live persona sign-in route. Django's
    own `settings.DEBUG` is set directly here rather than through the `settings`
    fixture's restore machinery being relied on for anything else.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")
    monkeypatch.setattr(settings, "DEBUG", True)

    assert local_signin_urlpatterns() == []


@pytest.mark.parametrize("literal", [LOCAL_SIGNIN_URL_NAME, LOCAL_SIGNIN_PATH_PREFIX])
def test_each_constant_is_spelled_in_exactly_one_module(literal: str) -> None:
    """AC #2: "fixed constants held in exactly one place".

    A source-text scan rather than an import graph walk, because the failure it
    catches is a second *literal* -- a template that hardcodes the prefix, a URL
    name retyped into a view. Each imports nothing, would satisfy every other
    assertion in this file, and is a declaration Epic 7's move into
    `accelerator.toml` would leave behind.

    Its reach is exactly what it scans and no more, which is worth saying because
    the guarantee sounds wider than it is: `src/`, `.py` and `.html` only, by
    substring. A second spelling in `tests/`, in `docs/development.md` (which has
    one, in prose), or in a `.toml` -- `accelerator.toml` among them, the very
    file Epic 7 relocates these into -- is invisible to it, and a longer name
    containing one of these reads as the same declaration. What it does cover is
    the shipped source, which is where a second declaration would do harm.
    """
    spelled = sorted(
        candidate
        for candidate in SRC_ROOT.rglob("*")
        if candidate.is_file()
        and candidate.suffix in SOURCE_SUFFIXES
        and literal in candidate.read_text(encoding="utf-8")
    )

    assert spelled == [DECLARATION_SITE]


def test_both_urlconfs_reference_the_imported_constants() -> None:
    """The positive half: the one declaration is what the two URLconfs actually use.

    Object identity rather than equality, so a module that re-derived an equal
    string -- from a settings read, from a literal that happened to match -- fails
    here even though the scan above would find no second spelling.
    """
    assert project_urls.LOCAL_SIGNIN_PATH_PREFIX is LOCAL_SIGNIN_PATH_PREFIX
    assert local_dev_urls.LOCAL_SIGNIN_URL_NAME is LOCAL_SIGNIN_URL_NAME
