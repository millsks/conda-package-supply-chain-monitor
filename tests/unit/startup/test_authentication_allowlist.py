"""FR-17: the component's authentication surface matches the approved list exactly.

The nine refusal conditions are a denylist and cannot catch a credential path
invented next year. This is the inverse check: what the component installs and
what it routes under its own authentication prefixes must be *exactly* what
`config.startup.allowlist` approves, so a path added later fails the gate until
somebody edits the declaration -- which is the moment a human decides whether it
belongs.

**Exact equality, in both directions.** An entry present but not listed fails,
and an entry listed but absent fails too. The second half is what makes the
allowlist a statement about the surface rather than a floor: an approved class
that quietly stopped being installed is a change to the credential surface, and
FR-17 is a response to credential-surface changes nobody noticed.

**The surface asserted is the deployed one.** `base.py` declares what a deployed
component inherits, and `production.py` overrides neither roster -- which is
asserted here rather than assumed. `local.py` and `test.py` add the local
username-and-password path on top, and the composed settings this suite runs
under therefore carry `ModelBackend`; that is a locality-scoped affordance stage 1
refuses in a deployed component, and `TestTheLocalAdditionsAreClosedByAConditio`
holds it to that rather than letting `local.py` become the hole the allowlist
cannot see.

**Prefix scoping is not the predicate.** The scopes say which routes are judged;
the permitted view packages say what may be routed there. AD-21 names the failure
that separation exists for, and both evasion cases below construct it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from allauth.account import views as allauth_account_views
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import include
from django.urls import path
from django.utils.module_loading import import_string
from rest_framework.authtoken.views import obtain_auth_token

from config.local_dev import views as local_dev_views
from config.settings import base as base_settings
from config.startup import run_stage_one
from config.startup import run_stage_two
from config.startup.allowlist import ALLOWED_API_AUTHENTICATION_CLASSES
from config.startup.allowlist import ALLOWED_AUTHENTICATION_BACKENDS
from config.startup.allowlist import ALLOWED_AUTHENTICATION_ROUTE_SCOPES
from config.startup.allowlist import FRAMEWORK_VIEW_MACHINERY
from config.startup.stage_two import _iter_view_callables
from tests.conftest import deployed_component_urlconf
from tests.conftest import deployed_url_patterns
from tests.conftest import temporary_root_urlconf
from tests.conftest import valid_deployed_settings_namespace

if TYPE_CHECKING:
    from types import ModuleType

    from django.urls import URLPattern
    from django.urls import URLResolver

#: The remedy AC #3 requires a failure to state, in the words it has to state it
#: in. Carried in the failure message of every case below rather than left to a
#: reader of this file: the person who sees the failure is the person adding the
#: credential path, and the message is the only thing they are guaranteed to read.
SRC_ROOT = Path(__file__).resolve().parents[3] / "src"

#: The two settings names the FR-17 rosters are the approved contents of. A
#: deployed component inherits both from `base.py` unchanged, which is what makes
#: asserting `base.py` an assertion about deployment.
GOVERNED_SETTINGS_NAMES = frozenset({"AUTHENTICATION_BACKENDS", "REST_FRAMEWORK"})

REMEDY = (
    "Adding a credential path requires editing src/config/startup/allowlist.py in the same change, "
    "and that edit is the moment a human decides whether the path belongs."
)

#: The local username-and-password path `local.py` and `test.py` add on top of the
#: approved surface, with the stage-1 state that closes each in a deployed
#: component. Keyed by settings name so the reconciliation below can drive both.
LOCAL_ADDITIONS = {
    "AUTHENTICATION_BACKENDS": "django.contrib.auth.backends.ModelBackend",
}


def _unapproved(installed: object, approved: frozenset[str], setting_name: str) -> str:
    """Return a failure message when a roster does not match its allowlist exactly.

    Args:
        installed: The value the settings module carries, any iterable of dotted
            paths.
        approved: The allowlist the value has to match.
        setting_name: The settings key, for the message.

    Returns:
        The empty string when the two match exactly, otherwise a message naming
        the unexpected and missing entries and stating AC #3's remedy.

    """
    present = set(installed)  # type: ignore[call-overload]
    unexpected = sorted(present - approved)
    missing = sorted(approved - present)
    if not unexpected and not missing:
        return ""
    return (
        f"{setting_name} does not match the FR-17 allowlist. "
        f"Present but not approved: {unexpected or 'none'}. "
        f"Approved but not present: {missing or 'none'}. "
        f"{REMEDY}"
    )


def _scope_for(route: str, admin_url: str) -> str | None:
    """Return the key of the scope a route falls under, or None when it is out of scope.

    Args:
        route: The concatenated route pattern `_iter_view_callables` yields.
        admin_url: The value of `settings.ADMIN_URL`, supplied rather than read
            so this mirrors how the declaration is meant to be consumed.

    Returns:
        The scope key, or None for a business route the allowlist has no
        authority over (AC #2).

    """
    for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES:
        if route.startswith(scope.resolve_prefix({"ADMIN_URL": admin_url})):
            return scope.key
    return None


def _permitted_packages(scope_key: str) -> frozenset[str]:
    """Return the view packages permitted under one scope, framework machinery included.

    Args:
        scope_key: The scope's stable key.

    Returns:
        The declared packages plus `FRAMEWORK_VIEW_MACHINERY`.

    """
    scope = next(scope for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES if scope.key == scope_key)
    return scope.permitted_view_packages | FRAMEWORK_VIEW_MACHINERY


def _defines_permitted(module: ModuleType | None, permitted: frozenset[str]) -> bool:
    """Answer whether a view's defining module falls under a permitted package.

    Matched exactly or as a dotted prefix, which is the predicate `stage_two.py`
    resolves views by -- and never against the route's name or path, which is
    what AD-21's evasion defeats.

    Args:
        module: The view's defining module, or None when `inspect.getmodule`
            could not resolve one.
        permitted: The packages permitted under the route's scope.

    Returns:
        True when the module is defined under one of the permitted packages.

    """
    if module is None:
        return False
    return any(module.__name__ == package or module.__name__.startswith(f"{package}.") for package in permitted)


def _unapproved_routes(urlconf: str, admin_url: str) -> list[tuple[str, str, str]]:
    """Walk a URL configuration and return every in-scope route the allowlist refuses.

    Args:
        urlconf: The dotted name of the configuration to walk.
        admin_url: The admin mount's prefix.

    Returns:
        One `(route, defining module, scope key)` triple per unapproved view
        candidate, in walk order.

    """
    offenders: list[tuple[str, str, str]] = []
    for route, view in _iter_view_callables(urlconf):
        scope_key = _scope_for(route, admin_url)
        if scope_key is None:
            continue
        module = inspect.getmodule(view)
        if not _defines_permitted(module, _permitted_packages(scope_key)):
            offenders.append((route, module.__name__ if module else "<unresolved>", scope_key))
    return offenders


def _refuse(*extra: URLPattern | URLResolver) -> list[tuple[str, str, str]]:
    """Install a deployed-shaped configuration plus some extra routes and check the allowlist.

    Args:
        *extra: The routes the case is constructing a forbidden surface out of.

    Returns:
        Whatever `_unapproved_routes` found.

    """
    with temporary_root_urlconf(*deployed_url_patterns(), *extra) as urlconf:
        return _unapproved_routes(urlconf, settings.ADMIN_URL)


class TestTheSettingsSideSurface:
    """AC #1: the two rosters match the allowlist exactly."""

    def test_the_authentication_backends_match_the_allowlist_exactly(self) -> None:
        """`base.py` is the surface a deployed component inherits, so it is the one asserted."""
        failure = _unapproved(
            base_settings.AUTHENTICATION_BACKENDS,
            ALLOWED_AUTHENTICATION_BACKENDS,
            "AUTHENTICATION_BACKENDS",
        )

        assert not failure, failure

    def test_the_api_authentication_classes_match_the_allowlist_exactly(self) -> None:
        """The same, for DRF's defaults. Membership, not order -- order is Story 2.7's assertion."""
        failure = _unapproved(
            base_settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],
            ALLOWED_API_AUTHENTICATION_CLASSES,
            "DEFAULT_AUTHENTICATION_CLASSES",
        )

        assert not failure, failure

    @pytest.mark.parametrize(
        "dotted_path",
        sorted(ALLOWED_AUTHENTICATION_BACKENDS | ALLOWED_API_AUTHENTICATION_CLASSES),
    )
    def test_every_approved_path_resolves(self, dotted_path: str) -> None:
        """The declaration holds strings; this is where they become objects.

        A dotted path that no longer resolves would pass every set comparison in
        this module -- the settings module names it, the allowlist names it, the
        two agree -- while the component failed to load the class at runtime. The
        skeleton this allowlist replaced held resolved objects for exactly this
        reason; resolving them here rather than in the declaration keeps that
        guarantee without making the module unimportable during the settings
        composition Epic 9 will import it from.
        """
        assert import_string(dotted_path) is not None

    def test_production_overrides_neither_roster(self) -> None:
        """What makes `base.py` the deployed surface rather than merely a default.

        If `production.py` reassigned either name, asserting `base.py` would say
        nothing about what a deployed component installs.

        Read from the source rather than by importing the module: `production.py`
        demands real deployment secrets and refuses without them, so an import
        here would either need the whole deployed environment or would be skipped
        -- and a skipped case is the one shape
        `tests/unit/startup/test_refusal_coverage_audit.py` refuses to count as a
        claim. Both a rebinding and an in-place mutation of the inherited dict are
        looked for; the second would not be an assignment to the name at all.
        """
        source = (SRC_ROOT / "config" / "settings" / "production.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        rebound: set[str] = set()
        mutated: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        rebound.add(target.id)
                    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                        mutated.add(target.value.id)

        assert not (rebound & GOVERNED_SETTINGS_NAMES), (
            f"production.py rebinds {sorted(rebound & GOVERNED_SETTINGS_NAMES)}, "
            "so base.py is no longer the surface a deployed component inherits"
        )
        assert not (mutated & GOVERNED_SETTINGS_NAMES), (
            f"production.py mutates {sorted(mutated & GOVERNED_SETTINGS_NAMES)} in place, "
            "which changes the inherited surface without rebinding the name"
        )


class TestAnUnlistedEntryFails:
    """AC #1 and AC #3: the mechanism, not the claim."""

    def test_an_extra_backend_fails_the_allowlist(self) -> None:
        """Without this, "an entry present but not listed fails" is untested.

        The check is driven through the same helper the real assertion uses, so
        the case proves the mechanism rather than a copy of it.
        """
        failure = _unapproved(
            [*base_settings.AUTHENTICATION_BACKENDS, "myapp.backends.LegacyPasswordBackend"],
            ALLOWED_AUTHENTICATION_BACKENDS,
            "AUTHENTICATION_BACKENDS",
        )

        assert "LegacyPasswordBackend" in failure

    def test_an_extra_api_class_fails_the_allowlist(self) -> None:
        """The credential surface FR-6 retired, re-added: the shape this most has to catch."""
        failure = _unapproved(
            [
                *base_settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],
                "rest_framework.authentication.TokenAuthentication",
            ],
            ALLOWED_API_AUTHENTICATION_CLASSES,
            "DEFAULT_AUTHENTICATION_CLASSES",
        )

        assert "TokenAuthentication" in failure

    def test_a_missing_approved_entry_fails_too(self) -> None:
        """The other direction, and the reason this is equality rather than containment.

        An approved class that stopped being installed is a change to the
        credential surface. A subset test would call it fine.
        """
        failure = _unapproved([], ALLOWED_AUTHENTICATION_BACKENDS, "AUTHENTICATION_BACKENDS")

        assert "Approved but not present" in failure

    def test_the_failure_states_the_remedy(self) -> None:
        """AC #3 in the message. The person who sees this is the person adding the path."""
        failure = _unapproved(["something.Else"], ALLOWED_AUTHENTICATION_BACKENDS, "AUTHENTICATION_BACKENDS")

        assert "src/config/startup/allowlist.py" in failure
        assert "in the same change" in failure


class TestTheRouteSideSurface:
    """AC #1 and AC #2, over the URL configuration a deployed component actually builds."""

    def test_the_deployed_configuration_passes(self) -> None:
        """The negative case, and the reason every refusal below means anything.

        `config/urls.py`'s own deployed branch, not a stand-in: several hundred
        view candidates across allauth, the admin, the DRF router, drf-spectacular
        and the users app. Without it, an allowlist that refused everything would
        satisfy every other case in this class.
        """
        with deployed_component_urlconf() as urlconf:
            offenders = _unapproved_routes(urlconf, settings.ADMIN_URL)

        assert offenders == [], (
            f"the component's own deployed URL configuration is refused by its own allowlist: {offenders}"
        )

    def test_a_business_route_outside_every_prefix_is_not_judged(self) -> None:
        """AC #2's second clause. An allowlist over every route dies in a week.

        The view deliberately belongs to the local sign-in module -- the most
        forbidden object in the tree -- so what the case demonstrates is the
        *scoping* and nothing else. Stage 2 refuses this same route by defining
        module at every prefix, which is the next case.
        """
        offenders = _refuse(path("reports/monthly/", local_dev_views.persona_index, name="monthly-report"))

        assert offenders == []

    def test_the_business_route_the_allowlist_ignores_is_still_refused_by_stage_two(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The division of labour, asserted rather than assumed.

        AC #2 puts business routes outside the allowlist's scope, which is only
        safe because the denylist has no scope at all: condition 6 resolves every
        routed view's defining module wherever it is mounted. Two independent
        mechanisms over one declaration -- neither calls the other, and this case
        is what proves the gap between them is covered rather than merely
        asserted to be.
        """
        monkeypatch.delenv("COMPONENT_RUNTIME", raising=False)
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

        with (
            temporary_root_urlconf(
                *deployed_url_patterns(),
                path("reports/monthly/", local_dev_views.persona_index, name="monthly-report"),
            ),
            pytest.raises(ImproperlyConfigured, match=r"config\.local_dev"),
        ):
            run_stage_two()

    def test_a_permitted_prefix_does_not_permit_everything_under_it(self) -> None:
        """AD-21's worked evasion, verbatim: `local_persona_login` mounted under `/accounts/`.

        The route name satisfies AD-21 by sounding local, and the prefix is one
        the allowlist genuinely permits -- `config/urls.py` really does mount
        `allauth.urls` at `accounts/`. An implementation that allowlists the
        prefix and stops looking passes it.
        """
        offenders = _refuse(
            path("accounts/local-sign-in/", local_dev_views.persona_signin, name="local_persona_login"),
        )

        assert [module for _route, module, _key in offenders] == ["config.local_dev.views"]
        assert offenders[0][2] == "allauth"

    def test_an_innocuous_name_at_the_reserved_token_prefix_fails(self) -> None:
        """The mirror evasion: nothing about the route says token, and the view mints them.

        `api/auth-token/` is the address the reference application minted static
        tokens at before Story 2.8 deleted the surface. The prefix stays in scope
        with nothing permitted, so re-mounting it fails here as well as at stage 2.
        """
        offenders = _refuse(path("api/auth-token/", obtain_auth_token, name="account-helper"))

        assert offenders
        assert {key for _route, _module, key in offenders} == {"token-issuance"}

    def test_the_local_sign_in_prefix_is_reserved_in_a_deployed_component(self) -> None:
        """The mount `config/urls.py` makes only where locality is local, made anyway.

        `_local/` is in scope with nothing permitted, so the allowlist refuses the
        route the moment it appears in a configuration a deployed component
        serves. This is the reservation doing its job rather than a hypothetical:
        the suite's own `config.urls` has this route mounted, because the whole
        suite runs local.
        """
        offenders = _refuse(path("_local/", include("config.local_dev.urls")))

        assert offenders
        assert {key for _route, _module, key in offenders} == {"local-sign-in"}

    def test_an_allauth_view_moved_onto_the_admin_login_route_fails(self) -> None:
        """Scopes are not interchangeable: approved *somewhere* is not approved *here*.

        Without this, a single flattened set of permitted packages would pass
        every other case in this class while letting the identity provider's
        sign-in flow be served from the address the admin's own credential form
        occupies -- which is where a redirect loop or an open redirect would be
        least visible.

        One allauth *view* rather than a second `include("allauth.urls")`: the
        walk carries a `seen` set keyed on resolver identity, and allauth's own
        nested `include()` objects are module-level, so a second mount of the same
        URLconf would be skipped after the first and the case would pass
        vacuously.
        """
        offenders = _refuse(path(f"{settings.ADMIN_URL}login/", allauth_account_views.login, name="login"))

        assert offenders
        assert {key for _route, _module, key in offenders} == {"admin-login"}

    def test_the_admin_mount_itself_is_out_of_scope(self) -> None:
        """The deliberate narrowing, from the behavioural side.

        Every installed app's `ModelAdmin` is routed under `ADMIN_URL`, and the
        allowlist judges none of them. `test_the_deployed_configuration_passes`
        above is the case that would fail if this were ever widened -- it walks
        the real mount with `django_celery_beat`, `django.contrib.auth` and the
        contenttypes shortcut all registered.
        """
        offenders = _refuse(path(f"{settings.ADMIN_URL}reports/", local_dev_views.persona_index, name="admin-report"))

        assert offenders == []


class TestTheLocalAdditionsAreClosedByACondition:
    """`local.py` and `test.py` add to the approved surface; each addition is refused deployed.

    This is what stops the local leaves from being the hole the allowlist cannot
    see. The allowlist states the deployed surface, and a locality-scoped
    affordance is legitimate only while some stage-1 condition refuses it in a
    deployed component -- so the two are reconciled here, by constructing the
    forbidden state and asserting the refusal rather than by trusting the
    arrangement.
    """

    def test_the_suite_is_running_with_the_local_additions_installed(self) -> None:
        """The control. Without it the reconciliation below could pass over an empty set."""
        for setting_name, entry in LOCAL_ADDITIONS.items():
            assert entry in getattr(settings, setting_name), setting_name

    def test_every_local_addition_is_absent_from_the_allowlist(self) -> None:
        """An addition that were approved would need no condition, and would ship."""
        assert LOCAL_ADDITIONS["AUTHENTICATION_BACKENDS"] not in ALLOWED_AUTHENTICATION_BACKENDS

    def test_the_added_backend_is_refused_in_a_deployed_component(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stage 1's condition 2, state a, driven with exactly the entry `test.py` adds.

        The entry is read from `LOCAL_ADDITIONS` rather than spelled again, so a
        local leaf that changed which backend it added would fail here rather
        than leave this case refusing a backend nobody installs any more.
        """
        monkeypatch.delenv("COMPONENT_RUNTIME", raising=False)
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        namespace = valid_deployed_settings_namespace()
        namespace.AUTHENTICATION_BACKENDS = [
            *namespace.AUTHENTICATION_BACKENDS,
            LOCAL_ADDITIONS["AUTHENTICATION_BACKENDS"],
        ]

        with pytest.raises(ImproperlyConfigured, match="AUTHENTICATION_BACKENDS"):
            run_stage_one(namespace)
