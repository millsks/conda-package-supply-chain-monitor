"""The two forbidden route states, and the two evasions a string match would miss.

Refusal condition 6, both halves: a route whose view callable **is** DRF's
`obtain_auth_token`, and a route whose view callable belongs to the local
sign-in module. AD-26 states the rule these cases are measured against --
"predicates resolve objects, never strings" -- and the two evasion cases are what
make that rule assertable rather than aspirational:

* **Evasion A.** A route named `local_persona_login` mounted under `/accounts/`.
  AD-21 names this shape itself: it satisfies the AD by name and passes an
  allowlist that already permits `/accounts/` for allauth, because
  `config/urls.py` really does mount `allauth.urls` there. A predicate matching
  the URL name or the path prefix passes it; one resolving the view callable's
  defining module does not.
* **Evasion B.** `obtain_auth_token` re-exported under another module attribute
  and mounted under another route name at another prefix. A predicate comparing
  `__name__` or a dotted path passes it; one comparing object identity does not.

The negative case carries as much weight as either. Without a URL configuration
that both conditions *accept*, a predicate that refused everything would satisfy
every refusal assertion in this module and nothing here would notice.

Everything is driven through the public `run_stage_two()` rather than by calling
the conditions directly, so what these cases assert is the behaviour a booting
component actually gets -- the roster, the locality gate and the condition
together. The two database conditions in that roster gate on
`COMPONENT_PROCESS`, which no test process declares (AD-13), so they return
before they query and these stay unit tests: no database, no network, no
filesystem.

Throwaway URL configurations are real module objects registered in `sys.modules`
and installed with `override_settings(ROOT_URLCONF=...)`, built by
`tests.conftest.temporary_root_urlconf`. A list of patterns handed to a resolver
directly would skip the import Django performs and would not exercise
`include()` at all.
"""

from __future__ import annotations

import inspect
import sys
from functools import partial
from functools import wraps
from types import ModuleType
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import include
from django.urls import path
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import SimpleRouter
from rest_framework.viewsets import ViewSetMixin

from config.local_dev import views as local_dev_views
from config.local_dev.constants import LOCAL_SIGNIN_PATH_PREFIX
from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup import run_stage_two
from config.startup import stage_two
from tests.conftest import deployed_component_urlconf
from tests.conftest import deployed_url_patterns
from tests.conftest import temporary_root_urlconf
from tests.conftest import valid_deployed_settings_namespace

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    from django.urls import URLPattern
    from django.urls import URLResolver

# The roster, by function name and in the order the module declares it. Named
# here rather than read off the module so that a reordering has to be made in
# two places -- which is what makes it a decision rather than an edit.
EXPECTED_EVALUATION_ORDER = (
    "_refuse_credential_minting_route",
    "_refuse_local_sign_in_route",
    "_refuse_collector_without_freshness_target",
    "_refuse_unreconciled_cadence",
    "_refuse_unapplied_migrations",
    "_refuse_missing_designated_groups",
)

# The dotted path of the module the local sign-in views are defined in. Asserted
# *in the refusal message* rather than used as a predicate: the message has to
# tell an operator which module was routed, and that is the one place in this
# story where the name is legitimately a string.
LOCAL_SIGN_IN_VIEW_MODULE = "config.local_dev.views"

# The module name the `urlconf` parameter is driven against. A constant rather
# than a serial, because exactly one case installs it: `django.urls.get_resolver`
# is cached on the dotted name, so a name reused by a second case would be
# resolved from the first one's object graph.
EXPLICITLY_WALKED_URLCONF = "tests._explicitly_walked_urlconf"


class _LocallyMintedToken(ObtainAuthToken):
    """A static-token endpoint written here rather than imported from DRF.

    The subclass case, which neither an identity comparison nor a dotted-path
    match sees: it is a different object in a different module with a different
    name, and it mints the same credential. `issubclass` is what catches it.
    """


class _TokenViewSet(ViewSetMixin, ObtainAuthToken):
    """The same endpoint mounted the way this repository mounts its API.

    `config/api_router.py` registers viewsets on a DRF router, so a token
    endpoint re-added here would most naturally arrive as a viewset rather than
    as a bare `as_view()` product -- and a viewset is the one shape that records
    its class under a different attribute. `ViewSetMixin.as_view()` sets `cls`
    and never `view_class`, and its `__wrapped__` chain terminates at
    `APIView.dispatch`, so identity, `view_class` and the chain all miss it.

    `create` exists because `SimpleRouter` builds a route only for the actions it
    can map: a viewset whose only method is DRF's `post` is registered and routes
    nothing, which would make this case pass while asserting over an empty
    configuration.
    """

    def create(self, request: object, *args: object, **kwargs: object) -> object:
        """Mint a token through the inherited endpoint, under the name a router routes."""
        return self.post(request, *args, **kwargs)


def _undecorated_wrapper(view: Callable[..., object]) -> Callable[..., object]:
    """Wrap a view in a closure that sets no `__wrapped__` at all.

    The evasion `functools.wraps` conventions do not cover. `wraps` is what
    populates `__wrapped__`, and a decorator author who never calls it -- through
    haste, or deliberately -- leaves the walk nothing to follow: the URLconf
    holds the wrapper, `inspect.getmodule` answers *this* module, and both
    URLconf conditions would read the decorator's module rather than the view's.
    What is left to find the view by is the closure cell the wrapper holds it in.

    Args:
        view: The view to hide.

    Returns:
        A wrapper carrying no `functools.wraps` metadata whatsoever.

    """

    def wrapper(request: object, *args: object, **kwargs: object) -> object:
        return view(request, *args, **kwargs)

    return wrapper


@pytest.fixture(autouse=True)
def _deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declare the run deployed, which is the only state stage 2 evaluates in.

    `OTEL_SDK_DISABLED` is deleted alongside it because the AC #3 case below runs
    stage 1 as well, and condition 3 reads that variable off the environment
    rather than off the namespace.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)


def _refusal(*patterns: URLPattern | URLResolver) -> str:
    """Install a URL configuration, run stage 2 against it, and return the refusal.

    Args:
        *patterns: The `urlpatterns` of the configuration to install.

    Returns:
        The refusal message, for the caller to assert its distinguishing
        substring on. Substring assertions rather than `pytest.raises(match=...)`
        because the messages carry regex metacharacters that would have to be
        escaped at every call site.

    """
    with temporary_root_urlconf(*patterns), pytest.raises(ImproperlyConfigured) as refused:
        run_stage_two()
    return str(refused.value)


def _routed_under_another_name(view: Callable[..., object]) -> str:
    """Re-export one view under a different module and a different attribute name.

    Evasion B's setup, and it has to be a real module rather than a local alias:
    what a dotted-path predicate reads is where the object can be *found*, so the
    evasion is only constructed once the object is findable somewhere else.

    Args:
        view: The view to re-export.

    Returns:
        The dotted name of the module now carrying it as `mint_session`.

    """
    name = "tests._relocated_credential_route"
    module = ModuleType(name)
    module.mint_session = view
    sys.modules[name] = module
    return name


@pytest.fixture
def relocated_credential_route() -> Iterator[Any]:
    """Yield `obtain_auth_token` as it is reachable from a module of another name.

    Yields:
        The re-exported view object.

    """
    name = _routed_under_another_name(obtain_auth_token)
    try:
        yield sys.modules[name].mint_session
    finally:
        del sys.modules[name]


class TestTheRosterAndThePositiveCase:
    """The two claims every case below rests on."""

    def test_the_roster_records_the_evaluation_order(self) -> None:
        """AD-26: one location, one owner, and a *fixed* order.

        Order is contract rather than convenience. A component with two forbidden
        states live meets exactly one refusal, and which one it meets is what an
        operator reads -- so a reordering changes the diagnostic every deployment
        in that state receives.
        """
        roster = stage_two._STAGE_TWO  # noqa: SLF001 - the declared order is the thing under test

        assert tuple(condition.__name__ for condition in roster) == EXPECTED_EVALUATION_ORDER

    def test_an_allauth_and_admin_url_configuration_is_accepted(self) -> None:
        """The negative case, and the load-bearing one.

        Without it a predicate that refused every route would satisfy every
        refusal assertion in this module. It is also the assertion that a
        correctly configured deployment can actually serve: the identity
        provider's own sign-in flow is mounted at `accounts/`, which is exactly
        the prefix evasion A hides under, and it is not a forbidden state.
        """
        with temporary_root_urlconf(*deployed_url_patterns()):
            run_stage_two()

    def test_the_local_sign_in_module_is_shipped_but_not_mounted(self) -> None:
        """AD-21's distinction, asserted rather than assumed: shipping is not mounting.

        Two halves, and the case is only about their conjunction. *Shipped:* the
        package is importable in this very process and its views are live
        callables defined in it -- that is what `core` in all six combinations
        means. *Not mounted:* the URL configuration a deployed component serves
        routes none of them, which is asserted over the walk itself rather than
        inferred from the absence of a refusal, so a condition that had stopped
        looking entirely could not satisfy it.

        Only then is the acceptance meaningful: the module is present, no route
        reaches it, and stage 2 passes. A reading of the condition under which
        the mere presence of `config.local_dev` refused would make every deployed
        component refuse to start.
        """
        assert callable(local_dev_views.persona_signin)
        assert callable(local_dev_views.persona_index)
        assert inspect.getmodule(local_dev_views.persona_signin) is local_dev_views

        with temporary_root_urlconf(*deployed_url_patterns()):
            walked = [view for _route, view in stage_two._iter_view_callables()]  # noqa: SLF001 - the walk is the evidence
            defining = {module.__name__ for view in walked if (module := inspect.getmodule(view)) is not None}

            assert not [name for name in defining if name.startswith("config.local_dev")]

            run_stage_two()

    def test_the_url_configuration_this_component_actually_ships_is_accepted(self) -> None:
        """The negative case over `config/urls.py` itself, not a two-route stand-in.

        Every other case in this suite runs against `deployed_url_patterns()` or
        a throwaway module built for the case. None of them touches the tree that
        actually ships: `config.api_router`'s DRF router, drf-spectacular's
        schema and Swagger views, `django_service.users.urls`, allauth and the
        admin. A forbidden route added under `api/` would therefore be refused by
        the contract at boot and caught by nothing in the suite until then --
        which is the wrong order for a refusal that stops a deployment.

        **A unit-level walk rather than a subprocess boot, and the reason is
        honesty about what is being asserted.** The faithful subprocess shape
        would boot with `COMPONENT_RUNTIME` unset -- but `config/asgi.py` selects
        `config.settings.local`, which stage 1's FR-12 escape route refuses
        outright on a deployed run, so such a probe would have to supply a whole
        deployed settings environment before it could reach stage 2 at all, and
        would then be asserting over a URLconf built from that environment rather
        than from this component's. Executing `config/urls.py` under a popped
        `COMPONENT_RUNTIME` reaches the same object graph with nothing invented:
        the conditions walk the real resolver over the real includes, and
        `tests/integration/startup/test_stage_two_fires.py` remains the case that
        proves stage 2 fires on a served path at all.
        """
        with deployed_component_urlconf():
            walked = list(stage_two._iter_view_callables())  # noqa: SLF001 - the breadth of the walk is part of the claim

            assert len(walked) > len(deployed_url_patterns()), (
                "the shipped configuration walked no more candidates than the two-route stand-in, "
                "so it was not the shipped configuration"
            )

            run_stage_two()


class TestACredentialMintingRouteIsReachable:
    """Condition 6, state a: a route whose view callable is DRF's token endpoint."""

    @pytest.mark.forbidden_state("credential-minting-route")
    def test_the_token_route_as_config_urls_once_mounted_it_refuses(self) -> None:
        """The exact route Story 2.8 deleted, reinstated: `api/auth-token/`."""
        message = _refusal(path("api/auth-token/", obtain_auth_token, name="obtain_auth_token"))

        assert "rest_framework.authtoken" in message
        assert "api/auth-token/" in message

    def test_the_route_refuses_under_another_name_at_another_prefix(
        self,
        relocated_credential_route: Any,
    ) -> None:
        """Evasion B: the same object, re-exported and remounted, still refuses.

        Neither the module attribute it is reached through nor the route name nor
        the prefix is what the predicate reads, so changing all three changes
        nothing. A predicate comparing `callable.__name__ == "obtain_auth_token"`
        or `callable.__module__` against a literal passes this case.
        """
        assert relocated_credential_route is obtain_auth_token

        message = _refusal(path("internal/v2/session/", relocated_credential_route, name="session-create"))

        assert "internal/v2/session/" in message

    def test_a_decorator_over_the_route_does_not_hide_it(self) -> None:
        """A `functools.wraps` chain is walked link by link, not collapsed.

        DRF built `obtain_auth_token` by wrapping an `as_view()` product in
        `csrf_exempt`, so the object the URLconf holds is already the outermost
        link of a chain -- which is why the walk yields every link rather than
        only what `inspect.unwrap` terminates at. A decorator added on top is one
        more link and is seen the same way.
        """

        @wraps(obtain_auth_token)
        def audited(request: object, *args: object, **kwargs: object) -> object:
            return obtain_auth_token(request, *args, **kwargs)

        message = _refusal(path("api/token/", audited, name="token"))

        assert "api/token/" in message

    def test_a_freshly_built_view_of_the_same_class_refuses(self) -> None:
        """`as_view()` returns a new object every call, so identity cannot see it.

        The class recorded on the product is what does, which is why the
        condition asks `issubclass` as well as `is`.
        """
        message = _refusal(path("auth/", ObtainAuthToken.as_view(), name="auth"))

        assert "auth/" in message

    def test_a_locally_written_subclass_refuses(self) -> None:
        """A subclass in another module under another name mints the same credential."""
        message = _refusal(path("sessions/", _LocallyMintedToken.as_view(), name="sessions"))

        assert "sessions/" in message

    def test_a_viewset_mounted_through_a_router_refuses(self) -> None:
        """The live shape: a token endpoint re-added the way this repository mounts an API.

        `config/api_router.py` registers viewsets on a DRF router, and
        `ViewSetMixin.as_view()` records its class as `cls` rather than as
        `view_class` while its `__wrapped__` chain terminates at
        `APIView.dispatch`. So identity, `view_class` and the chain all answer
        no, and reading `cls` is the whole of what catches it. The route comes
        from a real `SimpleRouter` rather than a hand-written `path()`, because
        what the router builds is the object the condition has to recognize.
        """
        router = SimpleRouter()
        router.register("tokens", _TokenViewSet, basename="tokens")

        assert router.urls, "the router registered no routes, so nothing below is about a mounted viewset"

        message = _refusal(*router.urls)

        assert "rest_framework.authtoken" in message

    def test_a_decorator_that_never_called_wraps_does_not_hide_it(self) -> None:
        """The `__wrapped__` chain is a convention, and a closure cell is not.

        `functools.wraps` is what sets `__wrapped__`; a decorator that never
        calls it leaves the walk a single layer -- the wrapper -- and an identity
        comparison against it answers no. The view is still reachable, because
        the wrapper closes over it, and the closure sweep is what finds it there.
        """
        message = _refusal(path("api/token/", _undecorated_wrapper(obtain_auth_token), name="token"))

        assert "rest_framework.authtoken" in message
        assert "api/token/" in message

    def test_a_partial_over_the_route_does_not_hide_it(self) -> None:
        """`functools.partial` sets no `__wrapped__` either, and holds its target in `func`."""
        message = _refusal(path("api/mint/", partial(obtain_auth_token), name="mint"))

        assert "rest_framework.authtoken" in message
        assert "api/mint/" in message

    def test_settings_can_be_entirely_correct_and_the_route_still_refuses(self) -> None:
        """AC #3: settings correct, URL configuration wrong -- and that is the gap this closes.

        Stage 1 refuses `rest_framework.authtoken` in `INSTALLED_APPS` and
        `TokenAuthentication` among DRF's defaults, and the namespace here has
        neither. The view imports and works with the app uninstalled, so a
        component can pass every settings-side condition and still mint tokens;
        only the resolved URL configuration says so.
        """
        namespace = valid_deployed_settings_namespace()

        run_stage_one(namespace)

        message = _refusal(path("api/auth-token/", obtain_auth_token, name="obtain_auth_token"))

        assert "FR-6" in message


class TestTheLocalSignInRouteIsReachable:
    """Condition 6, state b: a route whose view callable belongs to the local sign-in module."""

    @pytest.mark.forbidden_state("local-sign-in-route")
    def test_the_package_url_configuration_mounted_at_its_own_prefix_refuses(self) -> None:
        """The mount `config/urls.py` builds when the run is local, on a deployed run."""
        message = _refusal(path(LOCAL_SIGNIN_PATH_PREFIX, include("config.local_dev.urls")))

        assert LOCAL_SIGN_IN_VIEW_MODULE in message

    def test_a_route_named_local_persona_login_under_accounts_refuses(self) -> None:
        """Evasion A, in AD-21's own words, and the case the whole predicate exists for.

        The name is one an allowlist would read as legitimate and the prefix is
        one that is already permitted for allauth. Both are wrong signals; the
        view callable's defining module is the right one.
        """
        message = _refusal(
            *deployed_url_patterns(),
            path("accounts/local-sign-in/", local_dev_views.persona_signin, name="local_persona_login"),
        )

        assert LOCAL_SIGN_IN_VIEW_MODULE in message
        assert "accounts/local-sign-in/" in message

    def test_the_index_view_refuses_as_well_as_the_sign_in_view(self) -> None:
        """Both views in the package, not only the one that establishes a session.

        The index lists what can be signed in as, which is a disclosure of the
        credential path in its own right -- and the predicate is the module, so
        a view added to the package later is covered without an edit.
        """
        message = _refusal(path("dev/", local_dev_views.persona_index, name="anything"))

        assert LOCAL_SIGN_IN_VIEW_MODULE in message

    def test_the_wrapped_link_alone_is_enough_to_refuse(self) -> None:
        """The case that pins the `__wrapped__` walk, with every other route to the view cut.

        `functools.wraps` copies `__module__`, so a plainly decorated view
        refuses on the *wrapper* and the chain beneath it is never consulted --
        which means a decorated case that stops there asserts nothing about the
        walk. The wrapper's `__module__` is reset to this test module afterwards,
        leaving `__wrapped__` as the only link that can reach
        `config.local_dev.views`. If the walk collapsed to `inspect.unwrap`'s
        terminal, or stopped at the outermost layer, this case fails and the
        others do not.
        """

        @wraps(local_dev_views.persona_signin)
        def rate_limited(request: object, *args: object, **kwargs: object) -> object:
            return local_dev_views.persona_signin(request, *args, **kwargs)  # type: ignore[arg-type]

        rate_limited.__module__ = __name__

        assert inspect.getmodule(rate_limited) is sys.modules[__name__]
        assert rate_limited.__wrapped__ is local_dev_views.persona_signin

        message = _refusal(path("accounts/signin/", rate_limited, name="login"))

        assert LOCAL_SIGN_IN_VIEW_MODULE in message

    def test_a_decorator_that_never_called_wraps_does_not_hide_the_view(self) -> None:
        """The other half of P2's evasion: no `__wrapped__`, no copied `__module__`.

        A bare closure decorator carries none of `functools.wraps`'s metadata, so
        the wrapper's defining module is this test file and the chain is one
        layer long -- the shape under which the module predicate would read
        `tests.unit.startup.test_stage_two_urlconf` and pass. The view is in the
        wrapper's closure, which is where the sweep finds it.
        """
        message = _refusal(
            path("accounts/signin/", _undecorated_wrapper(local_dev_views.persona_signin), name="login"),
        )

        assert LOCAL_SIGN_IN_VIEW_MODULE in message


class TestTheWalkItself:
    """The properties of `_iter_view_callables` no condition case can assert alone."""

    def test_a_self_including_configuration_terminates(self) -> None:
        """A URL configuration that includes itself is a mistake, not an impossibility.

        Without the `id(resolver)` guard the walk would recurse until the
        interpreter stopped it, and a refusal contract that crashes on a
        malformed configuration reports nothing about the configuration.
        """
        with temporary_root_urlconf() as name:
            sys.modules[name].urlpatterns = [
                path("loop/", include(name)),
                path("home/", local_dev_views.persona_index, name="home"),
            ]

            walked = list(stage_two._iter_view_callables())  # noqa: SLF001 - the walk is the thing under test

        assert any(view is local_dev_views.persona_index for _route, view in walked)

    def test_the_walk_descends_into_included_configurations(self) -> None:
        """`include()` is where a route hides from a scan of `config/urls.py` as text."""
        with temporary_root_urlconf(path("nested/", include("config.local_dev.urls"))):
            routes = {route for route, _view in stage_two._iter_view_callables()}  # noqa: SLF001 - the walk is the thing under test

        assert any(route.startswith("nested/") for route in routes)

    def test_a_view_whose_defining_module_cannot_be_resolved_is_passed_over(self) -> None:
        """A callable naming a module that is not imported resolves to no module at all.

        `inspect.getmodule` answers None there rather than raising, and the
        module condition has to carry on: a URL configuration Django accepted is
        one this contract has to finish walking, and a refusal that raised
        `AttributeError` out of a predicate would replace the refusal contract's
        one exception type with whatever the malformed route produced (CG-3).
        """

        def orphan(request: object) -> object:
            return request

        orphan.__module__ = "a.module.nothing.imported"

        with temporary_root_urlconf(path("orphan/", orphan, name="orphan")):
            run_stage_two()

    def test_a_configuration_can_be_walked_by_name_without_installing_it(self) -> None:
        """The `urlconf` parameter is the seam its docstring advertises, and it is driven here.

        Task 1 specifies the signature, and `_iter_view_callables()` is called
        everywhere with no argument -- so the parameter's claim to let a caller
        "walk a throwaway configuration without touching global state" was sold
        and never exercised. Both halves are asserted: the named configuration is
        walked, and `ROOT_URLCONF` -- which this case never overrides -- is
        unaffected, which is what "without touching global state" has to mean.
        """
        module = ModuleType(EXPLICITLY_WALKED_URLCONF)
        module.urlpatterns = [path("only-by-name/", local_dev_views.persona_index, name="only-by-name")]
        sys.modules[EXPLICITLY_WALKED_URLCONF] = module
        try:
            by_name = {route for route, _view in stage_two._iter_view_callables(EXPLICITLY_WALKED_URLCONF)}  # noqa: SLF001 - the seam is the thing under test
            installed = {route for route, _view in stage_two._iter_view_callables()}  # noqa: SLF001 - the seam is the thing under test
        finally:
            sys.modules.pop(EXPLICITLY_WALKED_URLCONF, None)

        assert "only-by-name/" in by_name
        assert "only-by-name/" not in installed

    def test_every_yielded_candidate_is_callable(self) -> None:
        """The contract of the iterator: objects a route could be recognized by.

        A `None` callback or a stray attribute leaking into the stream would make
        every predicate below it silently unreliable, because `is` and
        `issubclass` against a non-object answer False rather than raising.
        """
        with temporary_root_urlconf(*deployed_url_patterns()):
            walked = list(stage_two._iter_view_callables())  # noqa: SLF001 - the walk is the thing under test

        assert walked
        assert all(callable(view) for _route, view in walked)
