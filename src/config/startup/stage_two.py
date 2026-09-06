"""Stage 2 of the refusal contract: the checks that evaluate at process startup.

Invoked from the `AppConfig.ready()` of one named immovable-core app inside
`django_service` (AD-26). `ready()` runs inside `django.setup()`, so this fires
under gunicorn and uvicorn exactly as it does under a management command --
there is no serving-process-only hook to miss, and no `sys.argv` sniffing
anywhere (AD-13 forbids it outright).

`django_service` is `core` in its entirety (AD-29), so the owner travels in all
six combinations by construction and no adopted application can displace it. No
adopted application may precede it in `INSTALLED_APPS` either;
`tests/unit/startup/test_installed_apps_ordering.py` is the gate on that.

Whatever runs here runs at boot, so FR-23 and NFR-1 bind it: no network call,
and no query beyond migration state -- plus the single designated-group
existence read AD-27 requires. `tests/unit/test_no_network_at_boot.py` enforces
the network half by booting this component with every socket refused.

**The sentinel is set first, before the locality check.** What AC #3 asserts is
that the invocation point fires at all under a serving process. Every developer
and CI path runs local (AD-13), so a record written after the `is_deployed()`
early return would never be observed and the test that reads it would assert
nothing.

**Predicates resolve objects, never strings (AD-26).** The two URLconf
conditions walk the resolved configuration and compare *view callables* -- by
identity, by class, and by the module object that defines them. Nothing here
reads a route name, a path prefix or a dotted path, because a rename or a
remount would defeat every one of those and leave the route as reachable as it
was. The one string this module carries out of the walk is the route's location,
interpolated into a refusal message so an operator knows which line to open; no
predicate reads it.

**Imports are deferred into the function that needs them for two different
reasons, and neither is AD-24's conditional import.** AD-24 forbids
`try`/`except ImportError` and imports made conditional on a feature being
present -- a removal mechanism. Every import below is unconditional and always
executes; they are merely placed past a lifecycle boundary.

*The registry-bound ones.* `config.startup.stage_two` is imported while a
settings module is still executing (through `config.startup.run_stage_one`) and
again during app loading, and at both of those moments the application registry
is not populated: `rest_framework.authtoken.views` and
`django.contrib.auth.models` each define or import a model class, so a
module-scope import of either raises
`django.core.exceptions.AppRegistryNotReady` and takes the whole boot down with
something that is not `ImproperlyConfigured`. The collector registry sweep is the
third, and it is worth saying why rather than leaving it to look like caution:
`conda_package_supply_chain_monitor.core.registry` holds no model itself, but it
imports the collector base, which imports `core.models`, which *defines*
`CollectionRun` and `PolicyRun`. It therefore fails in exactly the same way, and
a reader who checked only the imported module for a model class would move the
import back. Inside the condition bodies the registry is ready, because stage 2
runs from `AppConfig.ready()`.

*`django.conf.settings`, which is deferred for something else entirely.* It is
**not** a registry problem: `from django.conf import settings` binds a lazy
proxy, reads nothing and touches no registry, and is perfectly safe at module
scope. It is deferred because `config/startup/__init__.py` states the package
convention -- "nothing in this package may import `django.conf.settings` at
module scope" -- and that convention exists because stage 1 runs while a
settings module is still executing, at which point the settings object is not
yet populated and a module-scope binding is a standing invitation to read off it
there. The distinction is written out because a reader who collapses the two
reasons into one will eventually relocate the wrong import.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING
from typing import Final

from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.urls import URLResolver
from django.urls import get_resolver

from config import local_dev
from config.locality import is_deployed
from config.locality import is_serving_process

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

__all__ = [
    "STAGE_TWO_OWNER_APP_LABEL",
    "run_stage_two",
    "stage_two_has_run",
]

#: The app label of the immovable-core application that owns the stage-2
#: invocation. One declaration site (AD-1); Epic 7 adds a mirror of it in
#: `accelerator.toml` with a gate test asserting the two are equal, and
#: `src/config/startup/` stays the authoritative copy (AD-26).
STAGE_TWO_OWNER_APP_LABEL: Final[str] = "users"

#: Whether `run_stage_two()` has been entered in this interpreter.
#:
#: A mutable record rather than a rebound module global, because ruff `PLW0603`
#: forbids the `global` statement -- and read through `stage_two_has_run()`
#: rather than directly, because `SLF001` forbids the cross-module private read
#: and a direct `from ... import` would bind a copy of the boolean at import
#: time and never observe the later write.
_STAGE_TWO_RAN: Final[dict[str, bool]] = {"entered": False}

#: The module object the local sign-in condition resolves against, imported as a
#: package rather than named as a string (AD-26). `config.local_dev.__init__` is
#: a docstring and nothing else -- it imports no model, reads no setting and
#: touches no registry -- so unlike the two deferred imports above it is safe at
#: module scope, where a settings module is still executing.
#:
#: The *package* and not `config.local_dev.views`, deliberately. AD-21 makes the
#: package the single home for local-development code precisely so one module
#: object identifies all of it; a second view added in a sibling module of the
#: same package is caught by the prefix test below without an edit here.
_LOCAL_SIGN_IN_MODULE: Final = local_dev


def stage_two_has_run() -> bool:
    """Report whether `run_stage_two()` has been entered in this interpreter.

    The public reader for the boot sentinel. It says the invocation point fired,
    not that any condition evaluated: the record is written before the locality
    check, which is the only point at which a local process can observe it.

    Returns:
        True once `run_stage_two()` has been entered.

    """
    return _STAGE_TWO_RAN["entered"]


def _defining_object(candidate: object) -> Callable[..., object] | None:
    """Admit a candidate only if it is a kind of object a view can be *defined* by.

    The narrow gate on everything `_attached_objects` produces, and the reason
    the closure sweep below is safe to perform at boot. A wrapper closes over
    whatever its author happened to reference -- a settings dict, a string, a
    logger, a model instance -- and every one of those objects has a
    `__module__`. Handing them to the defining-module predicate would let an
    arbitrary closed-over value from `config.local_dev` refuse a deployed boot
    that routes nothing forbidden, which is a false refusal at startup and
    therefore the worst failure this contract can have.

    Functions, bound methods and classes are the only three kinds of object a
    routed view is ever *made of*, so restricting to them keeps the sweep
    precise without narrowing what it can find.

    Args:
        candidate: Any object reached from a wrapper layer.

    Returns:
        The candidate itself when it is a function, a bound method or a class,
        otherwise None.

    """
    if inspect.isfunction(candidate):
        return candidate
    if inspect.ismethod(candidate):
        return candidate
    if inspect.isclass(candidate):
        return candidate
    return None


def _attached_objects(layer: object) -> Iterator[object]:
    """Yield everything one wrapper layer holds a reference to.

    Args:
        layer: One link of a route's wrapper chain.

    Yields:
        `view_class`, `cls`, a `functools.partial`'s target, and the contents of
        every closure cell -- unfiltered. `_defining_object` is what decides
        which of them may be compared against.

    """
    yield getattr(layer, "view_class", None)
    yield getattr(layer, "cls", None)
    yield getattr(layer, "func", None)
    for cell in getattr(layer, "__closure__", None) or ():
        try:
            contents = cell.cell_contents
        except ValueError:
            # A cell bound to no value yet -- a closure over a name the
            # enclosing frame has not assigned. Reported by skipping this one
            # cell rather than by propagating: a `ValueError` escaping here
            # would replace the refusal contract's single exception type with
            # whatever a malformed closure produced (CG-3), and an empty cell
            # holds nothing a view could be recognized by in any case.
            continue
        yield contents


def _view_candidates(callback: Callable[..., object]) -> Iterator[Callable[..., object]]:
    """Yield every object one route's view can legitimately be recognized by.

    Several sources, and all of them are yielded rather than only the innermost,
    because each closes a different evasion and none of them subsumes the others.

    * **The callback as routed.** `obtain_auth_token` *is* an
      `ObtainAuthToken.as_view()` product that DRF built once at import time, so
      the identity comparison condition 6 is specified in terms of is only
      available against the object the URLconf actually holds.
    * **The `functools.wraps` chain beneath it.** A decorator applied to a
      forbidden view would otherwise hide it behind a wrapper of its own. The
      chain is walked link by link rather than collapsed with `inspect.unwrap`
      to its terminal, and that difference is load-bearing here: DRF wraps every
      `as_view()` product in `csrf_exempt`, so `inspect.unwrap(obtain_auth_token)`
      returns the inner `View.as_view.<locals>.view` closure and *not*
      `obtain_auth_token`. Yielding only the terminal would silently break the
      identity comparison on the one route this condition exists for.
    * **The `view_class` each layer carries.** `View.as_view()` records the class
      it was built from, which is what recognizes a *fresh* `as_view()` product
      -- a different object every time it is called, and therefore invisible to
      any identity test -- and what gives the defining-module predicate a class
      whose `__module__` is the view's own rather than
      `django.views.generic.base`.
    * **The `cls` a DRF ViewSet carries instead.** `rest_framework.viewsets.ViewSetMixin.as_view()`
      does **not** set `view_class`; it sets `cls`, and its `__wrapped__` chain
      terminates at `APIView.dispatch`. So a `ViewSetMixin` subclass of
      `ObtainAuthToken` registered on `config/api_router.py`'s DRF router --
      which is the shape a token endpoint would most naturally be re-added under
      in this repository -- is matched by none of the three sources above. Both
      attributes are read, because Django's own class-based views and DRF's
      viewsets record the same fact under different names.
    * **A `functools.partial`'s target, and every object in a layer's closure
      cells.** Both exist because the `__wrapped__` chain is a *convention*, not
      a mechanism: a decorator that does not call `functools.wraps` sets nothing
      at all, so the walk would yield only the wrapper and both URLconf
      conditions would read the decorator's own module. A plain closure
      decorator holds its wrapped view in a cell, and a `partial` holds it in
      `func`; reading both is what makes the two conditions survive a wrapper
      that was never written with them in mind. Everything reached this way
      passes `_defining_object` first -- see there for why an unrestricted sweep
      would be dangerous rather than merely noisy.

    **What is still invisible, named rather than implied.** A wrapper that uses
    no `functools.wraps`, is not a `partial`, and does not close over the view --
    one that reaches it through a module global, a registry lookup or an
    instance attribute -- is not found by any of these sources. That residual is
    accepted: the alternative is calling the route to see what it does, which a
    boot-time refusal must not do.

    Args:
        callback: The view callable a `URLPattern` holds.

    Yields:
        Each distinct candidate object, outermost first. Deduplicated by
        identity, which also terminates a `__wrapped__` chain that loops back on
        itself and keeps a closure that references its own wrapper from looping.

    """
    seen: set[int] = set()
    layers: list[Callable[..., object]] = []

    current: object = callback
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        layers.append(current)
        current = getattr(current, "__wrapped__", None)

    for layer in layers:
        yield layer
        for attached in _attached_objects(layer):
            recognized = _defining_object(attached)
            if recognized is None or id(recognized) in seen:
                continue
            seen.add(id(recognized))
            yield recognized


def _iter_view_callables(urlconf: str | None = None) -> Iterator[tuple[str, Callable[..., object]]]:
    """Walk a resolved URL configuration and yield the view callables it routes.

    The shared machinery of both URLconf conditions, and the reason neither of
    them can be evaded by a rename: what comes out of here is objects. The
    accompanying string is the route's location -- the concatenated patterns
    that lead to it -- and it exists so a refusal can tell an operator where to
    look. No predicate reads it, and none may: AD-26 is explicit that a
    string-matching predicate is the failure this condition contract is built
    against.

    Args:
        urlconf: The dotted path of a URL configuration, or None for
            `settings.ROOT_URLCONF`. Django's own `get_resolver` argument,
            passed through unchanged so a test can walk a throwaway
            configuration without touching global state.

    Yields:
        One `(route, candidate)` pair per candidate object of every routed view,
        depth first in declaration order. See `_view_candidates` for why a single
        route yields more than one object.

    """
    yield from _walk(get_resolver(urlconf), "", set())


def _walk(
    resolver: URLResolver,
    prefix: str,
    seen: set[int],
) -> Iterator[tuple[str, Callable[..., object]]]:
    """Recurse through one resolver's entries, descending into every `include()`.

    Args:
        resolver: The resolver whose `url_patterns` to walk.
        prefix: The route accumulated by the resolvers above this one.
        seen: The `id()` of every resolver already walked. A URL configuration
            that includes itself -- directly, or through a cycle of includes --
            is a configuration mistake rather than an impossibility, and without
            this the walk would recurse until the interpreter stopped it. Keyed
            on identity because a `URLResolver` is not hashable by value and two
            distinct includes of the same module are two objects that both have
            to be walked.

    Yields:
        One `(route, candidate)` pair per candidate object of every routed view
        beneath this resolver.

    """
    if id(resolver) in seen:
        return
    seen.add(id(resolver))

    for entry in resolver.url_patterns:
        route = f"{prefix}{entry.pattern}"
        if isinstance(entry, URLResolver):
            yield from _walk(entry, route, seen)
        else:
            for candidate in _view_candidates(entry.callback):
                yield route, candidate


def _refuse_credential_minting_route() -> None:
    """Refuse a deployed component routing DRF's token-minting view (AC #1, #2, #3).

    Condition 6, state a. Epic 2 Story 2.8 deleted the route and the app; this
    is what makes the deletion permanent. Settings-side, stage 1 already refuses
    `rest_framework.authtoken` in `INSTALLED_APPS` and `TokenAuthentication`
    among DRF's defaults -- but a component can satisfy every one of those and
    still route the view, because the view imports and works with the app
    uninstalled. That gap is exactly this condition's, and AC #3 is the test that
    constructs it: settings correct, URL configuration wrong.

    Two comparisons, neither of them on a name. `obtain_auth_token` is compared
    by identity, which catches the module attribute however it was re-exported
    and whatever the route was named. `ObtainAuthToken` is compared with
    `issubclass` against any routed class, which catches a fresh `as_view()`
    product, a locally written subclass and a DRF viewset built from one --
    none of which is `obtain_auth_token` and all of which mint the same static
    token. Comparing `__name__` or `__module__` would be the string match AD-26
    forbids, and a one-line re-export is all it would take to pass it.

    There is deliberately no third `isinstance(view, ObtainAuthToken)` disjunct.
    It reads as one more layer of defence and is none: `_view_candidates` yields
    only objects that passed `callable()` or `_defining_object`, and an
    `ObtainAuthToken` *instance* is not callable -- `APIView` defines no
    `__call__`, only `as_view()`. A branch that can never be true is worse than
    no branch, because a reader counts it as coverage.

    The import is inside the body because the application registry is not ready
    at either point where this module is imported; the module docstring sets out
    why that is not AD-24's conditional import.

    Raises:
        ImproperlyConfigured: When any routed view resolves to DRF's token
            endpoint. The message carries the route so the mount can be found,
            and says why the surface is forbidden rather than merely that it is.

    """
    from rest_framework.authtoken.views import ObtainAuthToken  # noqa: PLC0415 - see the module docstring
    from rest_framework.authtoken.views import obtain_auth_token  # noqa: PLC0415 - see the module docstring

    for route, view in _iter_view_callables():
        is_the_view = view is obtain_auth_token
        is_the_class = isinstance(view, type) and issubclass(view, ObtainAuthToken)
        if is_the_view or is_the_class:
            message = (
                f"The URL configuration routes rest_framework.authtoken's token endpoint at {route!r} "
                "in a deployed component. The static-token credential surface is retired (FR-6): a token "
                "minted locally is a credential the IdP does not own and cannot revoke, and the route is "
                "reachable whether or not the app is installed. Remove the route."
            )
            raise ImproperlyConfigured(message)


def _refuse_local_sign_in_route() -> None:
    """Refuse a deployed component that mounts the local persona sign-in route (AC #1, #2).

    Condition 6, state b. The predicate is the *defining module* of the view
    callable, resolved with `inspect.getmodule` and compared against the imported
    `config.local_dev` module object -- the package's own `__name__`, read off
    the object rather than written here as a literal, and matched exactly or as
    a dotted prefix so any submodule of it counts.

    **The evasion this closes, stated because AD-21 states it.** A route named
    `local_persona_login` mounted under `/accounts/` satisfies AD-21 by name and
    passes an allowlist that already permits `/accounts/` for allauth --
    `config/urls.py` really does mount `allauth.urls` there, so this is a live
    shape and not a hypothetical one. Any implementation matching the route name
    or the path prefix is wrong, and the two constants
    `config.local_dev.constants` declares are deliberately not consulted here:
    they exist for the route's own construction and for the FR-17 allowlist.

    **Shipping is not mounting (AD-21).** The local sign-in module is `core` and
    travels in every component; Story 3.4 mounts its route only where
    `config.locality.is_local()` answered true. So a correctly configured
    deployed component gives this condition nothing to find. It is the backstop
    for a route reachable anyway -- through a URLconf edit, a misconfiguration,
    or a locality that failed open -- and never evidence that the route is
    mounted everywhere. Mounting it unconditionally would make every deployed
    component refuse to start.

    Raises:
        ImproperlyConfigured: When any routed view is defined in
            `config.local_dev` or beneath it.

    """
    package = _LOCAL_SIGN_IN_MODULE.__name__

    for route, view in _iter_view_callables():
        defining = inspect.getmodule(view)
        if defining is None:
            continue
        if defining.__name__ == package or defining.__name__.startswith(f"{package}."):
            message = (
                f"The URL configuration routes {defining.__name__} at {route!r} in a deployed component. "
                "Local persona sign-in is a credential path the identity provider neither owns nor can "
                "revoke (FR-19, AD-21): the module ships everywhere, but the route is mounted only where "
                f"the component runtime declares itself local. Mount it from {package}.urls behind that "
                "check rather than unconditionally."
            )
            raise ImproperlyConfigured(message)


def _refuse_unapplied_migrations() -> None:
    """Refuse a serving process starting against an unrecognized schema (AC #4, #6).

    Condition 7, and the only condition in the whole contract that is
    serving-process-only. Management commands are exempt because `manage.py
    migrate` is the single action that clears this state: forbidding it would
    deadlock the FR-41 release stage against a refusal that nothing could resolve
    (AD-22). AD-13's fail-open process type is what makes the exemption the
    default, and R-3 is its recorded price -- a serving process started outside
    the Epic 5 `web`, `worker` and `beat` tasks does not fire this refusal. That
    price is carried, not compensated for.

    **Every configured alias, and `default` is not special (AD-9).** A
    contributed database (Epic 9) adds its own alias in the leaf settings module,
    and a schema nobody migrated is the same defect whichever alias it is spelled
    under. Iterating every alias is reachable only because stage 1 runs after the
    AD-8 composition step, which is the same property AC #6 asserts across both
    stages.

    This is the one permitted query in the contract -- NFR-1: "no query beyond
    migration state". There is no connectivity retry, no timeout wrapper and no
    readiness poll here, and none may be added: a refusal that waits is a
    readiness probe, which is the platform's job and not the component's.

    **Every connection this opens is closed again, and only the ones it
    opened.** `MigrationExecutor` connects, and this runs inside
    `AppConfig.ready()` -- so a connection left open here is a socket held
    across `django.setup()`, which `gunicorn --preload` then forks into every
    worker, and a forked-and-shared PostgreSQL socket corrupts both sides of the
    protocol. Whether the alias was already connected is recorded *before* the
    executor is built and the close is skipped when it was: closing a connection
    the caller already had open would abort an enclosing transaction, which is
    exactly what pytest-django's rollback fixtures hold when a test drives this
    condition.

    Raises:
        ImproperlyConfigured: When any configured alias has a non-empty migration
            plan. The message names the alias and the pending migrations, because
            "migrations are pending" tells an operator nothing they can act on
            while "users.0003 on the reporting alias" tells them which database
            was never migrated.

    """
    if not is_serving_process():
        return

    from django.conf import settings  # noqa: PLC0415 - see the module docstring

    for alias in settings.DATABASES:
        was_open = connections[alias].connection is not None
        try:
            executor = MigrationExecutor(connections[alias])
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        finally:
            if not was_open:
                connections[alias].close()
        if not plan:
            continue
        pending = ", ".join(f"{migration.app_label}.{migration.name}" for migration, _backwards in plan)
        message = (
            f"DATABASES[{alias!r}] has unapplied migrations in a serving process: {pending}. "
            "A serving process never starts against an unrecognized schema (AD-22): migration is a "
            "release-stage step, run once before the new version serves, and no entrypoint or container "
            "command performs it. Run the release stage's migrate step against this alias."
        )
        raise ImproperlyConfigured(message)


def _refuse_missing_designated_groups() -> None:
    """Refuse a serving process whose designated groups are absent (AC #5).

    The stage-2 half of condition 5. Its stage-1 half -- the claims contract
    unconfigured -- is `stage_one.py`'s and cannot be here, because stage 1
    issues no query at all; this half cannot be there for the same reason in
    reverse. Gated on `is_serving_process()` alongside condition 7, since it too
    needs a live database.

    **Why an absent group is a refusal and not a warning (AD-27).** AD-12 makes a
    claim naming a nonexistent `Group` ignored and logged, never created. That
    rule is defensible only because the designated groups are guaranteed to
    exist; without the guarantee, a deployed component whose staff group was
    never provisioned grants nobody any authorization, nobody can reach the admin
    to repair it, and every local smoke check passes because a developer's
    database was seeded by hand. The misconfiguration must surface as a
    configuration error rather than as a mysterious permissions problem.

    One query, and it creates nothing. `django_service.users.provisioning` is the
    only mechanism in this repository that creates a `Group` row, driven by the
    data migration Story 2.3 delivered; a refusal never repairs, because a
    refusal that repaired would hide the state it exists to report.

    **One alias here, every alias next door, and the asymmetry is correct.**
    `_refuse_unapplied_migrations` iterates every entry in `settings.DATABASES`
    because AD-9 says a schema nobody migrated is the same defect under any
    alias. This condition instead issues one `Group` query, which the default
    router resolves to a single alias. The two are not inconsistent, because
    they are asking different questions: a *schema* exists once per database,
    while the designated groups are `auth` rows and live wherever the router
    sends `auth` -- one place, by definition, since a second copy under another
    alias is not a second requirement but the same rows read through a different
    connection. Iterating aliases here would refuse a component whose contributed
    reporting database (Epic 9) legitimately carries no `auth_group` table at
    all. The alias the query actually resolved to is read off the queryset and
    named in nothing but the connection bookkeeping below, never in a predicate.

    The connection is closed again when this condition is what opened it, for
    the reason `_refuse_unapplied_migrations` states: a socket left open across
    `django.setup()` is a `gunicorn --preload` fork hazard. It is *not* closed
    when the alias was already connected, because that connection may be inside
    a transaction the caller owns.

    Raises:
        ImproperlyConfigured: When either designated group has no matching row.
            The message names exactly which of the two is missing -- both, when
            both are -- and the variable that configured the name.

    """
    if not is_serving_process():
        return

    from django.conf import settings  # noqa: PLC0415 - see the module docstring
    from django.contrib.auth.models import Group  # noqa: PLC0415 - see the module docstring

    contract = settings.CLAIMS_CONTRACT
    designated = (contract.staff_group, contract.superuser_group)
    rows = Group.objects.filter(name__in=designated).values_list("name", flat=True)
    alias = rows.db
    was_open = connections[alias].connection is not None
    try:
        present = set(rows)
    finally:
        if not was_open:
            connections[alias].close()
    # `dict.fromkeys` rather than `set`, for two properties a set loses: the
    # declaration order of the two names is preserved, so a message naming both
    # names staff first; and a contract that designates the *same* group for
    # both reports it once instead of twice.
    missing = [name for name in dict.fromkeys(designated) if name not in present]
    if not missing:
        return

    message = (
        f"The claims contract designates {', '.join(repr(name) for name in missing)} in a deployed "
        f"component, and no such Group {'rows exist' if len(missing) > 1 else 'row exists'}. The "
        "designated groups are provisioned from the contract by a data migration inside django_service "
        "(AD-27), so a missing one means the migration never ran against this database or the contract "
        "was renamed after it did. Without them a claim naming a group is ignored (AD-12) and the "
        "component grants nobody anything -- which presents as a permissions bug rather than as the "
        "misconfiguration it is."
    )
    raise ImproperlyConfigured(message)


def _refuse_collector_without_freshness_target() -> None:
    """Refuse a deployed component whose registered collector declares no target.

    `CPM-AD-28`, and the whole of it: "every registered collector declares a
    freshness target. Startup raises `ImproperlyConfigured` when one does not."
    The failure it prevents is quiet rather than loud -- an unset target behaves
    as *fresh forever*, so six-month-old evidence reads as current, which is the
    `CPM-SM-C1` failure this product is built to avoid. Nothing at run time would
    report it: the collector collects, the rows are written, and every surface
    shows a clean result derived from an observation nobody made this year.

    **One rule, three moments, and this is the third.**
    `core/collection.py` refuses the declaration where the collector is *built*,
    which is the earliest moment the answer exists but is a moment inside a Celery
    task with a run-ledger row already `running`. `collectors/apps.py` refuses it
    in the `ready()` that registers the collectors, which is the moment a deployed
    process can actually meet it. And this condition refuses it here, where the
    refusal contract enumerates it as condition 10 and where the suite drives it
    against fixture collectors through the real dispatch. All three call
    `core/collection.py`'s `freshness_target_fault`; none of them restates it.

    **In a deployed process this condition sweeps an empty registry, and that is
    a property of the invocation point rather than of the rule.** Stage two runs
    from `django_service.users`' `ready()`, and
    `tests/unit/startup/test_installed_apps_ordering.py` requires every adopted
    application to be installed *after* that owner -- so no collector is
    registered yet when this runs. `collectors/apps.py` is what closes that, and
    it is why this condition is not the deployment's enforcement point even
    though it reads like one.

    **An empty registry is not a failure.** A component that has adopted no
    collector has forgotten nothing, and a condition that demanded at least one
    registration would make every component in this repository refuse to start.

    **Classes, never instances.** Constructing a collector to ask what it
    declares would build a `RequestsTransport` and its connection pool inside
    `django.setup()`, which `gunicorn --preload` then forks into every worker --
    the same hazard `_refuse_unapplied_migrations` closes by hand for its
    database connection. The declaration is a class attribute, so reading it
    costs nothing and opens nothing.

    Raises:
        ImproperlyConfigured: When any registered collector's declared target is
            absent, mistyped, zero or negative. The message names the class, the
            collector's declared name and what the declaration actually says,
            because "a collector has no freshness target" tells an operator
            nothing they can act on while naming the class tells them which file
            to open.

    """
    # Deferred for the reason the module docstring gives: this module is
    # imported while a settings module is still executing and again during app
    # loading, and `core.collection` reaches `core.models`, which defines model
    # classes. A module-scope import would raise `AppRegistryNotReady` and take
    # the boot down with something that is not `ImproperlyConfigured`.
    from conda_package_supply_chain_monitor.core.collection import freshness_target_fault  # noqa: PLC0415
    from conda_package_supply_chain_monitor.core.registry import registered_collectors  # noqa: PLC0415

    fault = freshness_target_fault(registered_collectors())
    if fault:
        raise ImproperlyConfigured(fault)


def _refuse_unreconciled_cadence() -> None:
    """Refuse a deployed component whose beat schedule and collectors disagree.

    Condition 11, `CPM-AD-20`, and it is the reconciliation `CPM-CURRENCY-S01`
    recorded as belonging here: "a weekly schedule against a daily-derived
    two-day target would make the whole inventory read stale five days out of
    seven, with every gate green." Cadence is *data* -- it lives in
    `django_celery_beat`'s tables, seeded from `CELERY_BEAT_SCHEDULE`, precisely
    so an operator can change it without editing code -- and a collector's
    freshness target and observation window are derived from a cadence the
    collector declares. Two independent statements of one number is the right
    shape and it is also a standing invitation to edit one of them, so this is
    what makes them agree.

    **Its own condition rather than a second rule inside condition 10.**
    `tests/unit/startup/forbidden_states.py` argues that filing an unrelated rule
    under an existing condition makes `FR-16`'s "each condition has at least one
    test that configures the forbidden state" a sentence about a condition
    covering two things. `CPM-AD-28` is about a target that was never declared;
    this is about `CPM-AD-20`'s schedule, which is a different architecture
    decision, a different artefact and a different fix.

    **The rule is `collectors/sweep.py`'s and this condition only asks it**, on
    exactly the terms condition 10 asks `freshness_target_fault`. It sweeps in
    both directions -- every registered collector that declares a cadence against
    the entry that fires it, and every entry against the registry -- and it also
    refuses a collector that declares a cadence without a selection or a selection
    without a cadence.

    **In a deployed process this condition, like condition 10, sweeps an empty
    registry**: stage two runs before the collectors application's own `ready()`.
    That hook calls the same rule immediately after registering, which is where a
    deployment actually meets this refusal; here it is enumerated by the contract
    and driven by the suite. An empty roster reconciles with anything, which is
    what keeps a deployed boot from refusing over four schedule entries naming
    collectors the registry does not yet hold.

    **Classes, never instances**, and no query, on exactly the terms condition 10
    states: the declarations are class attributes and the schedule is a settings
    value, so this reads two in-memory structures and opens nothing.

    Raises:
        ImproperlyConfigured: When any collector's declared cadence, freshness
            target, selection or schedule entry disagrees with the others, or
            when a schedule entry names a collector nothing registered. Every
            offender is reported in one message, for the reason condition 10
            reports all of its.

    """
    from django.conf import settings  # noqa: PLC0415 - see the module docstring

    from conda_package_supply_chain_monitor.collectors.sweep import (  # noqa: PLC0415 - see the module docstring
        cadence_reconciliation_fault,
    )
    from conda_package_supply_chain_monitor.core.registry import registered_collectors  # noqa: PLC0415

    fault = cadence_reconciliation_fault(
        registered_collectors(),
        getattr(settings, "CELERY_BEAT_SCHEDULE", {}),
    )
    if fault:
        raise ImproperlyConfigured(fault)


#: The stage-2 conditions, in evaluation order, and the order is part of the
#: contract rather than an accident of how they were written: AD-26 requires "one
#: location, one owner, and a fixed order", and
#: `tests/unit/startup/test_stage_two_urlconf.py` asserts this tuple.
#:
#: The four in-memory conditions run for **any** deployed process and come
#: first, because they read object graphs that are already loaded: a component
#: that routes a credential path, that has adopted a collector which would
#: read six-month-old evidence as current, or whose beat schedule and collectors
#: disagree about a cadence, should be told so whether or not it
#: can reach a database, and telling it costs nothing. The two database
#: conditions follow and gate on `config.locality.is_serving_process()` inside
#: their own bodies rather than through a branch here, so that the dispatch has
#: one shape and each condition owns the whole of its own applicability (AD-1).
#: Condition 7 is the one R-3 is about.
#:
#: **Condition 11 comes after condition 10 and that ordering is deliberate.** A
#: collector that declares no freshness target at all is condition 10's, and
#: condition 11 compares a target against a cadence -- so a component missing
#: both meets the more basic refusal first and is told to declare the target
#: rather than being told its target is not greater than something.
#:
#: **Condition 10 is this product's own, and it is why the settled count moved.**
#: The inherited platform contract is nine conditions across fourteen forbidden
#: states, all of them about credential surfaces, telemetry, schema and
#: authorization. `CPM-EVIDENCE-S06` adds a tenth for `CPM-AD-28` -- a registered
#: collector declaring no freshness target -- which belongs to none of the nine
#: because it is a refusal about *this* product's evidence rules rather than
#: about the platform's configuration. It is numbered rather than folded into an
#: existing condition so that FR-16's "each condition has at least one test that
#: configures the forbidden state" stays a partition rather than becoming a
#: count, and `tests/unit/startup/forbidden_states.py` records the arithmetic.
#:
#: **Condition 11 is this product's second, on the same terms.**
#: `CPM-CURRENCY-S05` adds `CPM-AD-20`'s reconciliation -- a registered
#: collector's declared cadence against the `CELERY_BEAT_SCHEDULE` entry that
#: fires it, in both directions. It is not folded into condition 10 for the
#: reason condition 10 is not folded into one of the inherited nine: a target
#: nobody declared and a schedule that disagrees with one are different rules
#: about different artefacts, and one condition covering both would make FR-16's
#: sentence a count rather than a partition. The settled arithmetic for this
#: repository is therefore **eleven conditions across sixteen states**.
#:
#: Epic 9 appends AD-8's navigation-registry check to this tuple when the
#: composition step exists. That is a contributed-setting validation rather than
#: a forbidden state of the component's own configuration, so it does not change
#: that count either.
_STAGE_TWO: Final[tuple[Callable[[], None], ...]] = (
    _refuse_credential_minting_route,
    _refuse_local_sign_in_route,
    _refuse_collector_without_freshness_target,
    _refuse_unreconciled_cadence,
    _refuse_unapplied_migrations,
    _refuse_missing_designated_groups,
)


def run_stage_two() -> None:
    """Evaluate every stage-2 condition at serving-process startup.

    Raises:
        ImproperlyConfigured: When any condition finds a forbidden state. Never a
            warning and never a log-and-continue (CG-3): a refusal softened into
            a warning makes deployment smoother and puts a local credential path
            into production.

    """
    _STAGE_TWO_RAN["entered"] = True

    if not is_deployed():
        return

    for condition in _STAGE_TWO:
        condition()
