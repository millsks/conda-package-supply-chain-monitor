"""Stage 1 of the refusal contract: the checks that evaluate at settings import.

Called as the last statement of every leaf settings module, with that module's
own namespace as its argument. The namespace is passed rather than read off
`django.conf.settings` because `django.conf.settings` is not yet populated while
a settings module is still executing -- the module object is the only place the
composed values exist at that moment. Conditions read candidate names off it
with `getattr(module, name, default)`.

Every condition is deployed-only, so the whole stage returns before any of them
runs when `is_deployed()` is false. That is what keeps the entire developer and
CI surface -- all of which run local (AD-13) -- from refusing the moment this
contract lands.

A condition raises `django.core.exceptions.ImproperlyConfigured` and nothing
else. Never `warnings.warn`, never a log-and-continue branch: CG-3 exists
because a refusal softened into a warning makes deployment smoother and puts
local credentials into production.

Eight conditions live here. Six are unconditional: FR-12's settings-module
escape route, and conditions 1 to 5 of the refusal table -- the sqlite backend
over *every* configured alias (AD-9), the four local credential paths, the
OpenTelemetry kill switch, the JWKS trust anchor, and the unconfigured claims
contract. Two are feature-scoped: conditions 8 and 9, an in-process cache
backend where the Redis feature is selected and eager task execution where
background task processing is selected. That is ten of the fifteen forbidden
states; conditions 6, 7 and 10 and the stage-2 half of 5 are `stage_two.py`.

The two feature-scoped conditions are the only code in this module that is not
present in every combination, and the *only* mechanism that removes them is
AD-24's paired line comments. There is no runtime "is the feature selected?"
branch and there must never be one: AD-3 makes materialization subtractive, so a
combination without the feature does not contain the condition at all, and a
flag would leave the condition in the file with a second thing to keep in step.

**Region declarations, until Epic 7 moves them (AD-24, AD-1).** `accelerator.toml`
is the single declarative catalogue and it does not exist yet -- Epic 7 authors
it and moves these declarations into it without changing what any one of them
means. Until then this is their declaration site, and it is read as one:
`tests/unit/startup/test_feature_scoped_refusals.py` parses the bullets below
and reconciles them against the markers actually present in each path it names,
in both directions. Only the opening of each bullet is parsed -- the word "path"
and the repository-relative path in backticks, then the word "feature" and the
feature name in backticks, in that order. Everything after that is prose
describing what the region holds, and rewriting it breaks nothing.

* path `src/config/startup/stage_one.py`, feature `redis`, delimited by
  `feature:redis` / `/feature:redis`. It contains condition 8,
  `_refuse_in_process_cache`, the tuple of backends it refuses, and the
  condition's entry in the `_STAGE_ONE` roster. That is **two** marker pairs in
  this file, not one: a definition and its call site are not adjacent, and a
  region is a contiguous run of lines.
* path `src/config/startup/stage_one.py`, feature `celery`, delimited by
  `feature:celery` / `/feature:celery`. It contains condition 9,
  `_refuse_eager_tasks`, and the condition's entry in the `_STAGE_ONE` roster --
  likewise two pairs, for the same reason.
* path `tests/unit/startup/test_stage_one_conditions.py`, feature `redis`. It
  contains `_refuse_in_process_cache`'s name in `EXPECTED_EVALUATION_ORDER`,
  which pins the roster by name and order: in a combination that did not select
  Redis the roster loses that entry, so an expectation naming it would fail on a
  tree that is correct.
* path `tests/unit/startup/test_stage_one_conditions.py`, feature `celery`. It
  contains `_refuse_eager_tasks`'s name in the same tuple, for the same reason.
* path `tests/unit/startup/test_feature_scoped_refusals.py`, feature `redis`. It
  contains the cache dotted paths and the `LocMemCache` subclass condition 8 is
  driven with, the `CACHES` builder, the `redis` entry in that module's
  feature-to-condition mapping, and the whole test class for condition 8. The
  spine's Test-location convention is what puts them here: a feature's tests
  carry that feature's disposition and are pruned with it.
* path `tests/unit/startup/test_feature_scoped_refusals.py`, feature `celery`.
  It contains the `celery` entry in the same mapping and the whole test class
  for condition 9.
* path `tests/unit/startup/forbidden_states.py`, feature `redis`. It contains
  the `ForbiddenState` record naming condition 8's state. That file is FR-16's
  index of forbidden states, and a combination without Redis has no such state
  to demand a test for.
* path `tests/unit/startup/forbidden_states.py`, feature `celery`. It contains
  the record naming condition 9's state, for the same reason.
* path `tests/unit/startup/test_refusal_coverage_audit.py`, feature `redis`. It
  contains the `redis` entries in that module's conditional-state and
  conditional-condition expectations, which are what fix the total at fifteen
  and the conditions at ten without either literal: both shrink with the
  declaration they audit.
* path `tests/unit/startup/test_refusal_coverage_audit.py`, feature `celery`.
  It contains the `celery` entries in the same two mappings, for the same
  reason.
* path `tests/unit/startup/test_no_softening.py`, feature `redis`. Two pairs in
  that file: the builder that constructs condition 8's forbidden state together
  with its entry in the CG-3 refusal mapping, and -- separately, near the top --
  the `stage_one.py` entry in `BROAD_EXCEPT_ALLOWANCE`. The allowance records
  the `except Exception` guarding `import_string` a few lines below, which is
  itself inside this file's `feature:redis` region; a combination without Redis
  loses the handler, so an allowance left behind would fail a tree that is
  correct.
* path `tests/unit/startup/test_no_softening.py`, feature `celery`. It contains
  condition 9's builder and its entry in the refusal mapping.

**Where the blank lines go is part of each region.** Every closing marker sits
directly beneath the blank lines that separate its region from whatever follows,
so removing the region takes that separation with it. The alternative -- markers
flush against the code with blank lines outside the pair on both sides -- leaves
six consecutive blank lines behind in a combination that dropped the region, and
`ruff format --check` then fails a materialized tree that is otherwise correct.
That was probed on a stripped copy rather than reasoned about.

The feature names are the ones the `[environments]` matrix will use (Epic 8):
`redis` and `celery`.

Nothing above says how many region-bearing paths this tree has, deliberately.
The set is open and the carrier declares it as an open array; an earlier
revision of AD-24 named three paths and was wrong, so a count written here would
be a claim about the whole tree maintained from inside one file of it.

One thing these declarations do **not** cover, recorded rather than hidden. The
three Django-core names condition 8 resolves its backends through -- `DummyCache`,
`LocMemCache` and `import_string` -- sit unmarked in the sorted import block
below. A marker pair inside that block does not survive `ruff`'s isort, which
reorders imports across it and carries the markers with whichever import they
attach to; that was probed rather than assumed. All three are Django's own, so
they resolve in every combination whether or not `redis` was selected, and what
removing the region leaves behind is an unused import rather than an
`ImportError`. Pruning it is the materializer's general orphan problem (Epic 8),
which AD-24's own worked example -- `CeleryInstrumentor` in a combination with no
instrumentor -- already puts on that epic.

**Nothing here re-declares what another module already owns (AD-1).** The
OpenTelemetry kill switch is read through `config.observability.telemetry`,
which is the module whose behaviour that variable changes; the JWKS derivation
rule and its explicit-or-conventional fallback are
`config.authorization.jwks`'s; the claims contract, its four variable names and
its `is_configured` predicate are `config.authorization.claims`'s. Each import
is unconditional and top-level, because AD-24 permits no `try`/`except
ImportError` and no conditional import inside this package.
"""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING
from typing import Final
from urllib.parse import urlsplit

from django.core.cache.backends.dummy import DummyCache
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from config.authorization.claims import CLAIMS_ENVIRONMENT_VARIABLES
from config.authorization.claims import ClaimsContract
from config.authorization.jwks import jwks_url_derives_from_issuer
from config.authorization.jwks import resolve_jwks_url
from config.locality import LOCAL
from config.locality import RUNTIME_ENV_VAR
from config.locality import is_deployed
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.observability.telemetry import otel_sdk_is_disabled

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

__all__ = [
    "LOCAL_SETTINGS_MODULE",
    "PRODUCTION_SETTINGS_MODULE",
    "run_stage_one",
]

#: The settings module a deployed process must never load, and the one it should
#: load instead. Spelled once each, because both appear in the refusal message
#: and in the condition that raises it.
LOCAL_SETTINGS_MODULE: Final[str] = "config.settings.local"
PRODUCTION_SETTINGS_MODULE: Final[str] = "config.settings.production"

#: The variable Django reads the settings module from. Named here only to write
#: the resolution into the message; the condition below never reads it, because
#: a process can set it to one value and import another.
SETTINGS_MODULE_ENV_VAR: Final[str] = "DJANGO_SETTINGS_MODULE"


def _refuse_the_local_settings_module(settings_module: ModuleType) -> None:
    """Refuse a deployed process that loaded the local settings module (FR-12).

    The escape route this whole contract is built around: a deployed component
    whose `DJANGO_SETTINGS_MODULE` points at `config.settings.local` gets the
    development secret key, `DEBUG=True`, the console email backend and the
    locally minted signing keypair -- and nothing inside `local.py` could
    object, because `local.py` is the thing that would have to object.

    The module's own `__name__` is what is compared, taken from the object that
    is actually executing. `os.environ["DJANGO_SETTINGS_MODULE"]` is not read:
    a process can set that variable to one module and import another, and the
    module that ran is the one whose values are live.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When a deployed process loaded `local.py`. The
            message states both resolutions, because the right one depends on
            which half is wrong and the reader is the only one who knows.

    """
    if settings_module.__name__ != LOCAL_SETTINGS_MODULE:
        return

    message = (
        f"{LOCAL_SETTINGS_MODULE} was loaded by a deployed component. "
        f"Set {RUNTIME_ENV_VAR}={LOCAL} if this is local development, "
        f"or point {SETTINGS_MODULE_ENV_VAR} at {PRODUCTION_SETTINGS_MODULE} if it is a deployment."
    )
    raise ImproperlyConfigured(message)


#: The value a settings module carries when a name is not set on it at all.
#: A sentinel rather than None, so a refusal can say *absent* where the name was
#: never declared and say `None` where something declared it as None. The two
#: are different mistakes and send a reader to different lines.
_ABSENT: Final = object()

#: Every suffix a sqlite-backed `ENGINE` ends in. Compared as strings because
#: `DATABASES` holds settings scalars rather than routes or callables: AD-26's
#: "predicates resolve objects, never strings" governs the URLconf conditions of
#: Story 4.3, and a backend that is not installed in this environment has no
#: object to resolve.
#:
#: **`spatialite` is here because it is the same forbidden state, not because it
#: is thorough.** `django.contrib.gis.db.backends.spatialite` is sqlite with the
#: GIS extensions loaded -- it ends in `spatialite`, not in `sqlite3`, so a
#: single-suffix rule reads it as a real backend. What condition 1 refuses is a
#: deployment reading a table off a file on a container's ephemeral disk, and
#: that is exactly what spatialite is; the file just also holds geometry. AD-9's
#: point is that a second alias is where this hides, and a GIS alias beside a
#: PostGIS `default` is the likeliest shape it takes. Do not narrow this back to
#: one suffix.
_SQLITE_ENGINE_SUFFIXES: Final[tuple[str, ...]] = ("sqlite3", "spatialite")

#: The container types a settings name holding a roster of dotted paths is
#: allowed to be. Named types rather than `collections.abc.Iterable` for two
#: reasons, and both are failures a looser test would produce rather than catch.
#: A `str` is iterable, so `AUTHENTICATION_BACKENDS = "…ModelBackend"` -- a
#: plausible typo -- would be read one character at a time and match nothing. And
#: an arbitrary iterator can raise while it is being consumed, which would leave
#: a condition raising something that is not `ImproperlyConfigured`; the module
#: docstring and CG-3 both say that must not happen.
_ROSTER_TYPES: Final = (list, tuple, set, frozenset)

#: The local credential paths condition 2 refuses, each spelled once.
#:
#: **Why these are compared as dotted paths and not resolved with
#: `import_string` + `issubclass`.** Two independent reasons, both load-bearing:
#:
#: 1. *It cannot be evaluated here.* Stage 1 runs while a settings module is
#:    still executing -- which is inside `apps.populate(settings.INSTALLED_APPS)`,
#:    before the app registry is ready. `django.contrib.auth.backends` imports
#:    `django.contrib.auth.models`, and defining a model class with an unready
#:    registry raises `AppRegistryNotReady`. The same is true of
#:    `allauth.account.auth_backends` and of this component's own
#:    `config.authorization.authentication`. A resolving condition would pass the
#:    unit suite -- pytest-django completes `django.setup()` during collection, so
#:    the registry *is* ready there -- and then abort a real deployed boot with
#:    `AppRegistryNotReady` instead of the `ImproperlyConfigured` CG-3 requires.
#: 2. *`issubclass` is the wrong predicate even where it works.*
#:    `allauth.account.auth_backends.AuthenticationBackend` -- the one backend a
#:    deployed component must keep, and the one every IdP sign-in goes through --
#:    **is** a `ModelBackend` subclass. A rule refusing subclasses refuses the
#:    correct configuration, so identity is the only rule that separates the two.
#:
#: Closing the "a subclass re-exported under another name" evasion is therefore
#: not this condition's to close. It is FR-17's allowlist, Story 4.6, which AD-26
#: already specifies as holding **objects, not dotted strings** -- and which for
#: that very reason has to run where objects can be resolved.
_MODEL_BACKEND: Final[str] = "django.contrib.auth.backends.ModelBackend"
_AUTHTOKEN_APP: Final[str] = "rest_framework.authtoken"
_TOKEN_AUTHENTICATION: Final[str] = "rest_framework.authentication.TokenAuthentication"  # noqa: S105 - a dotted class path, not a credential

#: The key inside `REST_FRAMEWORK` that carries the API credential surface.
_API_AUTHENTICATION_CLASSES: Final[str] = "DEFAULT_AUTHENTICATION_CLASSES"


def _refuse_sqlite(settings_module: ModuleType) -> None:
    """Refuse a deployed component that reaches the sqlite backend (AC #1).

    Every configured alias is iterated, not only `default` (AD-9). That is
    reachable only because stage 1 runs *after* the AD-8 composition step by
    construction: a contributed database (Epic 9) adds its alias to `DATABASES`
    in the leaf, and an alias nobody remembered to configure is filled with the
    FR-18 sqlite substitution by `base.py` itself. No alias is exempt, because a
    deployment reading one table off a file on a container's ephemeral disk is
    the same defect whichever alias it is spelled under.

    `config/settings/production.py` keeps its own copy of this refusal over the
    `default` alias, and deliberately: it has to fire before the line beneath it
    sets `CONN_MAX_AGE`, which assumes a real backend. The two are consistent by
    construction rather than by review -- both raise on the same predicate --
    and this one is the general form.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When any configured alias names a sqlite engine.
            The message carries the alias and the engine, which is what tells a
            reader whether they forgot `DATABASE_URL` or forgot to configure the
            second database they added.

    """
    databases: object = getattr(settings_module, "DATABASES", _ABSENT)
    if not isinstance(databases, dict):
        return

    for alias, configuration in databases.items():
        engine = str(configuration.get("ENGINE", "")) if isinstance(configuration, dict) else ""
        if engine.endswith(_SQLITE_ENGINE_SUFFIXES):
            message = (
                f"DATABASES[{alias!r}] reaches the sqlite backend ({engine}) in a deployed component. "
                "sqlite is the FR-18 local substitution and never a deployment backend -- the GIS "
                "variant included, which is the same file on the same ephemeral disk. "
                "Configure DATABASE_URL, or POSTGRES_DB and its companions, for every alias."
            )
            raise ImproperlyConfigured(message)


def _refuse_local_credential_paths(settings_module: ModuleType) -> None:
    """Refuse a deployed component with a local credential path live in settings (AC #2).

    Four distinct forbidden states, each with its own raise and its own message.
    They are not collapsed into one aggregated error because FR-16 requires each
    to be testable separately, and because the four are fixed in four different
    places -- an operator handed "a local credential path is configured" has been
    told nothing they can act on.

    The four:

    * `ModelBackend` in `AUTHENTICATION_BACKENDS` -- Django's own username and
      password check against the local user table, which is the credential FR-4
      moved to the IdP.
    * a non-empty `ACCOUNT_LOGIN_METHODS` -- allauth's local sign-in form,
      reachable whenever any login method is declared.
    * `DJANGO_ADMIN_FORCE_ALLAUTH` anything other than true -- `/admin/` serving
      Django's own credential form with the IdP never involved (FR-7).
    * the static-token surface -- `rest_framework.authtoken` installed, or
      `TokenAuthentication` among DRF's defaults. One state, two halves, because
      either half alone is a locally minted API credential.

    Every name is read off the module object rather than from
    `django.conf.settings`: settings are not populated while the module that
    holds them is still executing.

    **Absence is judged against the framework default, never assumed neutral.**
    A settings module that never declares a name does not thereby switch the
    behaviour off -- it inherits whatever Django or allauth defaults to, and for
    two of these four that default *is* the forbidden state. So
    `AUTHENTICATION_BACKENDS` and `ACCOUNT_LOGIN_METHODS` refuse when absent, as
    `DJANGO_ADMIN_FORCE_ALLAUTH` already did, while `INSTALLED_APPS` and DRF's
    class list read as empty when absent because their defaults name nothing
    forbidden. This matters now rather than hypothetically: deleting a line is a
    plausible way to remove `ModelBackend` from `base.py:203-206`, and it would
    reinstate the exact state it was meant to remove.

    The four states are four helpers below rather than four blocks here. Each
    raises its own `ImproperlyConfigured`, which is what FR-16 requires; this
    function is only the fixed order they are evaluated in.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When any of the four states is live. See
            `_MODEL_BACKEND` above for why the two class surfaces are compared as
            dotted paths rather than resolved -- the short version is that
            resolving them here raises `AppRegistryNotReady`, and that
            `issubclass` would refuse allauth's backend, which is a `ModelBackend`
            subclass and is the one backend that has to stay.

    """
    _refuse_the_model_backend(settings_module)
    _refuse_declared_login_methods(settings_module)
    _refuse_an_unforced_admin(settings_module)
    _refuse_the_static_token_surface(settings_module)


def _as_roster(value: object, label: str) -> tuple[str, ...]:
    """Read a settings value as a roster of dotted paths, or refuse it as unreadable.

    Args:
        value: Whatever the settings module put there.
        label: How to name it in a refusal -- the setting name, or the setting
            name and key for a value nested inside one.

    Returns:
        The entries as stripped strings.

    Raises:
        ImproperlyConfigured: The value is not one of the container types a
            roster is allowed to be. Refused rather than skipped: a name this
            condition cannot read is a broken settings module, and skipping it
            would make a typo present as a clean configuration -- which is the
            single failure mode a refusal contract must not have.

    """
    if isinstance(value, _ROSTER_TYPES):
        return tuple(str(entry).strip() for entry in value)
    message = (
        f"{label} is declared as a {type(value).__name__} in a deployed component, "
        "which is not a roster the refusal contract can inspect. It is refused rather than "
        "skipped, because a setting nobody can read is not a setting nobody has to check."
    )
    raise ImproperlyConfigured(message)


def _declared_roster(settings_module: ModuleType, name: str, *, when_absent: str | None) -> tuple[str, ...]:
    """Read a settings name that holds a roster of dotted paths.

    Args:
        settings_module: The settings module currently being composed.
        name: The settings name to read.
        when_absent: What to say when the name is not declared at all -- the
            framework default it falls back to, and why that default is the
            forbidden state. None where absence genuinely names nothing
            forbidden, in which case an absent name reads as an empty roster.

    Returns:
        The entries as stripped strings, empty when the name is absent and
        absence is neutral.

    Raises:
        ImproperlyConfigured: The name is absent and its framework default is
            itself forbidden, or it holds something that is not a roster.

    """
    value = getattr(settings_module, name, _ABSENT)
    if value is _ABSENT:
        if when_absent is None:
            return ()
        message = f"{name} is absent in a deployed component. {when_absent}"
        raise ImproperlyConfigured(message)
    return _as_roster(value, name)


def _refuse_the_model_backend(settings_module: ModuleType) -> None:
    """State 2a: Django's own username-and-password check against the local user table.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When `AUTHENTICATION_BACKENDS` names `ModelBackend`
            -- or is absent, because `django.conf.global_settings` sets it to
            exactly `['django.contrib.auth.backends.ModelBackend']` and an
            undeclared name is that value, not an empty one.

    """
    backends = _declared_roster(
        settings_module,
        "AUTHENTICATION_BACKENDS",
        when_absent=(
            "Absence is not neutral here: django.conf.global_settings declares it as "
            f"['{_MODEL_BACKEND}'], so a settings module that never names it runs on exactly the "
            "local credential path this condition refuses. Declare it, with allauth's "
            "AuthenticationBackend as the only entry."
        ),
    )
    if _MODEL_BACKEND in backends:
        message = (
            f"AUTHENTICATION_BACKENDS contains {_MODEL_BACKEND} in a deployed component. "
            "That is a local username-and-password credential path; authentication is the IdP's (FR-4). "
            "Leave allauth's AuthenticationBackend as the only entry."
        )
        raise ImproperlyConfigured(message)


def _refuse_declared_login_methods(settings_module: ModuleType) -> None:
    """State 2b: allauth's local sign-in form, reachable whenever any method is declared.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When `ACCOUNT_LOGIN_METHODS` is non-empty -- or is
            absent, because allauth then falls back to its own default and
            resolves `LOGIN_METHODS` to the username method, which leaves the
            form exactly as reachable as declaring it would have.

    """
    declared = _declared_roster(
        settings_module,
        "ACCOUNT_LOGIN_METHODS",
        when_absent=(
            "Absence is not neutral here: allauth falls back to its own default and resolves "
            "the username login method, so the local sign-in form stays reachable. Declare it "
            "as an empty collection, which is the only spelling that means no local method."
        ),
    )
    if declared:
        message = (
            f"ACCOUNT_LOGIN_METHODS declares {', '.join(sorted(declared))} in a deployed component. "
            "Any declared login method keeps allauth's local sign-in form reachable; "
            "set it to an empty collection so the IdP is the only way in."
        )
        raise ImproperlyConfigured(message)


def _refuse_an_unforced_admin(settings_module: ModuleType) -> None:
    """State 2c: `/admin/` serving Django's own credential form with the IdP never involved.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When `DJANGO_ADMIN_FORCE_ALLAUTH` is anything other
            than `True`. Absent counts as not true and always did -- the setting
            has no framework default at all, and nothing reads it as one.

    """
    forced = getattr(settings_module, "DJANGO_ADMIN_FORCE_ALLAUTH", _ABSENT)
    if forced is not True:
        stated = "absent" if forced is _ABSENT else repr(forced)
        message = (
            f"DJANGO_ADMIN_FORCE_ALLAUTH is {stated} in a deployed component. "
            "Anything other than True leaves /admin/ serving Django's own credential form "
            "with the IdP never involved (FR-7)."
        )
        raise ImproperlyConfigured(message)


def _names_the_authtoken_app(entry: str) -> bool:
    """Report whether one `INSTALLED_APPS` entry installs the static-token app.

    Args:
        entry: One entry of `INSTALLED_APPS`.

    Returns:
        True for the bare module path and for any dotted path beneath it. Django
        accepts an `AppConfig` path as well as a module path, so
        `rest_framework.authtoken.apps.AuthTokenConfig` installs the very same
        app -- an equality test against the module path alone is escapable by
        spelling, and by the spelling Django's own documentation shows. The
        separator in the prefix is what stops a hypothetical
        `rest_framework.authtoken2` matching.

    """
    return entry == _AUTHTOKEN_APP or entry.startswith(f"{_AUTHTOKEN_APP}.")


def _refuse_the_static_token_surface(settings_module: ModuleType) -> None:
    """State 2d: a locally minted API credential, in either of the two halves it has.

    One state, two halves, because either alone is a credential the IdP does not
    own and cannot revoke: the app without the class stores tokens nothing reads,
    and the class without the app reads a table that had to exist for the
    deployment to get this far.

    Both are read as *absent is neutral*. Django's default `INSTALLED_APPS` is
    empty and DRF's default authentication classes are session and basic --
    neither names the token surface, so an undeclared name is not the forbidden
    state the way `AUTHENTICATION_BACKENDS` is.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When the app is installed under any of its spellings,
            or when `TokenAuthentication` is among DRF's default classes, or when
            either name holds something that is not a roster.

    """
    for entry in _declared_roster(settings_module, "INSTALLED_APPS", when_absent=None):
        if _names_the_authtoken_app(entry):
            message = (
                f"INSTALLED_APPS contains {entry} in a deployed component. "
                "The static-token credential surface is retired (FR-6): a token minted locally "
                "is a credential the IdP does not own and cannot revoke."
            )
            raise ImproperlyConfigured(message)

    rest_framework = getattr(settings_module, "REST_FRAMEWORK", _ABSENT)
    if rest_framework is _ABSENT:
        return
    if not isinstance(rest_framework, dict):
        message = (
            f"REST_FRAMEWORK is declared as a {type(rest_framework).__name__} in a deployed component, "
            "which is not a mapping the refusal contract can inspect. It is refused rather than "
            "skipped, because a setting nobody can read is not a setting nobody has to check."
        )
        raise ImproperlyConfigured(message)

    label = f"REST_FRAMEWORK[{_API_AUTHENTICATION_CLASSES!r}]"
    if _TOKEN_AUTHENTICATION in _as_roster(rest_framework.get(_API_AUTHENTICATION_CLASSES, ()), label):
        message = (
            f"{label} contains {_TOKEN_AUTHENTICATION} in a deployed component. "
            "The static-token credential surface is retired (FR-6); "
            "the Bearer class and the session are the whole of what a component accepts."
        )
        raise ImproperlyConfigured(message)


def _refuse_otel_disabled(_settings_module: ModuleType) -> None:
    """Refuse a deployed component that has switched the OpenTelemetry SDK off (AC #3).

    The one condition that reads the environment rather than the namespace:
    `OTEL_SDK_DISABLED` is an OpenTelemetry SDK variable, not a Django setting,
    and nothing mirrors it into settings. The parameter is therefore unused, and
    named with a leading underscore to say so -- the roster's calling convention
    is uniform, so every condition takes the module whether or not it reads it.

    **The read itself is `config.observability.telemetry`'s, not this module's.**
    Nothing in `src/config/startup/` imports `os`; `tests/unit/startup/test_module_shape.py`
    asserts that mechanically, because a second reader of a variable is a second
    spelling of it that can drift. `otel_sdk_is_disabled()` is the function whose
    answer actually decides whether tracing is installed, so it is the function
    this refusal has to agree with.

    That reuse widens the condition past the specification's literal `"true"`,
    deliberately. The SDK's reader here also recognizes `1` and `yes`, so a
    refusal matching only `"true"` would let `OTEL_SDK_DISABLED=1` disable
    tracing in a deployed component with nothing refusing it -- a hole exactly
    the size of the guarantee. `0` and `false` still do not refuse, which is what
    the narrower rule was protecting.

    Args:
        _settings_module: The settings module being composed. Unread: this
            condition's input is an environment variable.

    Raises:
        ImproperlyConfigured: When the SDK has been switched off. Distributed
            tracing is an immovable guarantee (FR-13) -- a component that turns
            it off has opted out of it silently, and silently is the part that
            makes this a refusal rather than a preference.

    """
    if not otel_sdk_is_disabled():
        return

    message = (
        f"{OTEL_SDK_DISABLED_ENV_VAR} is set in a deployed component. "
        "Distributed tracing is an immovable guarantee, not a per-deployment preference: "
        f"unset {OTEL_SDK_DISABLED_ENV_VAR}, and configure OTEL_TRACES_EXPORTER if the intent "
        "was to stop exporting rather than to stop tracing."
    )
    raise ImproperlyConfigured(message)


def _redacted(location: str) -> str:
    """Render a configured URL with everything that could be a secret removed (NFR-7).

    A refusal message is written to stderr at boot and from there into whatever
    collects a crashed container's logs. Scheme, host, port and path are what a
    reader needs to see why a location does not derive from the issuer; userinfo,
    query and fragment are not, and each of the three is somewhere a credential
    plausibly lives -- `https://user:pw@idp.example/...`, a `?access_token=`, an
    implicit-flow fragment. NFR-7 says secrets never appear in a refusal message,
    and the cheapest way to hold that is to interpolate nothing that could be one.

    This is message rendering and not a second derivation rule. The predicate
    stays `config.authorization.jwks.jwks_url_derives_from_issuer`, which is
    handed the location as configured; only what a human is shown is trimmed.

    Args:
        location: The configured issuer or JWKS location, as read.

    Returns:
        The location's scheme, host, port and path. A placeholder when the
        authority cannot be parsed at all -- `urlsplit` and `SplitResult.port`
        both raise `ValueError` on a malformed one, and a refusal that raises out
        of its own message is worse than a refusal that says the location was
        unreadable.

    """
    try:
        parts = urlsplit(location)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        # Handled and reported through the return value: the caller is already
        # raising, and what it needs here is a string, not a second exception
        # type escaping a condition that promises `ImproperlyConfigured`.
        return "<unreadable location>"
    authority = f"{host}:{port}" if port is not None else host
    scheme = f"{parts.scheme}://" if parts.scheme else ""
    return f"{scheme}{authority}{parts.path}" or "<empty>"


def _refuse_untrusted_jwks_anchor(settings_module: ModuleType) -> None:
    """Refuse a JWKS location not derived from the configured IdP issuer (AC #4).

    AD-23: the trust anchor is derived from `COMPONENT_OIDC_ISSUER`, and **this
    check is syntactic and can be nothing else**. The predicate is
    `config.authorization.jwks.jwks_url_derives_from_issuer`, which Story 2.7
    delivered for precisely this consumer and which never raises; the
    explicit-or-conventional fallback is that module's `resolve_jwks_url`. Both
    are imported rather than re-derived, so the location this refuses is
    character-for-character the location the fetch would later use.

    Three things it deliberately does not do. It makes **no network call** --
    reading `jwks_uri` out of the issuer's discovery document is the boot-time
    fetch FR-23 forbids, and "derived from" is not "confirmed against" (L-4: an
    issuer whose real `jwks_uri` does not match surfaces on the first Bearer
    request). It touches **no filesystem** -- this is the condition that catches
    a component anchored to a keypair generated onto a developer's laptop *with
    no key file present at all*, so an existence check would make the worst case
    pass. And it resolves **no second issuer**: a component with two answers to
    "who signs these tokens" has none.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When the issuer is unset, when it derives no
            location at all, or when the location does not derive from it. The
            three are separate messages because they are three different fixes,
            and each names the variable that is actually at fault. Both values are
            passed through `_redacted` before they are interpolated: an issuer and
            a JWKS location are public endpoints, but a URL carrying userinfo or a
            query-string token is not, and a refusal message ends up in
            deployment logs (NFR-7).

    """
    issuer = str(getattr(settings_module, "OIDC_ISSUER", "") or "").strip()
    explicit = str(getattr(settings_module, "OIDC_JWKS_URL", "") or "").strip()
    jwks_url = resolve_jwks_url(explicit, issuer)

    if not issuer:
        message = (
            "OIDC_ISSUER is unset in a deployed component. It is the single trust anchor (AD-23): "
            "with no issuer there is nothing for the JWKS location to derive from, and no `iss` to verify "
            "a token against. Set COMPONENT_OIDC_ISSUER."
        )
        raise ImproperlyConfigured(message)

    if not jwks_url:
        # Reachable only with no explicit location *and* an issuer that derives
        # none -- one made of nothing but separators, which reads as declared
        # because it is a non-empty string and then strips to nothing. The
        # variable at fault is therefore the issuer, and the message says so:
        # telling an operator to leave COMPONENT_OIDC_JWKS_URL unset would be
        # telling them to keep doing the thing they already did.
        message = (
            f"OIDC_ISSUER ({_redacted(issuer)}) derives no JWKS location in a deployed component, "
            "and COMPONENT_OIDC_JWKS_URL supplied none either. The issuer carries no host and no path "
            "to derive from: set COMPONENT_OIDC_ISSUER to the IdP's own issuer URL."
        )
        raise ImproperlyConfigured(message)

    if not jwks_url_derives_from_issuer(issuer, jwks_url):
        message = (
            f"OIDC_JWKS_URL ({_redacted(jwks_url)}) is not derived from "
            f"OIDC_ISSUER ({_redacted(issuer)}) in a deployed component. "
            "The trust anchor is the issuer and nothing else (AD-23): the location must be https, "
            "on the issuer's own host and port, at or beneath the issuer's path."
        )
        raise ImproperlyConfigured(message)


def _refuse_unconfigured_claims_contract(settings_module: ModuleType) -> None:
    """Refuse a deployed component whose claims contract is unconfigured (AC #5).

    The stage-1 half of refusal condition 5. Its stage-2 half -- a designated
    group absent from the database (AD-27) -- is Story 4.3's, and cannot be here:
    stage 1 issues no query at all (NFR-1).

    `config.authorization.claims` owns both halves of what this reads. The
    contract object is `ClaimsContract`, `is_configured` is its own predicate for
    "all four names were supplied", and `CLAIMS_ENVIRONMENT_VARIABLES` is the
    tuple of variable names **in field order**. The message pairs the two by
    position rather than spelling the four variable names a second time.

    That pairing is checked before it is made. `isinstance` admits a subclass, and
    a subclass carrying a fifth dataclass field would make a `strict` zip raise
    `ValueError` -- out of a condition whose whole contract is that it raises
    `ImproperlyConfigured` and nothing else (CG-3). So the count is compared
    first and refused as a misconfiguration in its own right: a contract with a
    field no environment variable names cannot be configured by an operator, and
    reporting that is more use than reporting the four fields that *are* named.
    `strict=True` stays on the zip underneath as the belt.

    Story 2.2's rule is what makes this reachable at all -- no conventional claim
    name is ever defaulted in place of a missing one, so an unset variable
    arrives as an empty field rather than as a plausible-looking `sub` or
    `groups` that resolves nothing.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When `CLAIMS_CONTRACT` is absent, is not a
            `ClaimsContract`, carries fields no environment variable names, or
            leaves any of its four names empty. The message names the variables
            that are unset -- never the values of the ones that are set, which
            are claim and group *names* but are still configuration a refusal has
            no reason to echo.

    """
    contract = getattr(settings_module, "CLAIMS_CONTRACT", _ABSENT)
    if not isinstance(contract, ClaimsContract):
        stated = "absent" if contract is _ABSENT else type(contract).__name__
        message = (
            f"CLAIMS_CONTRACT is {stated} in a deployed component. "
            "It is the mapping from the IdP's claim taxonomy onto Django (FR-10), built by "
            f"config.authorization.claims.load_claims_contract from {', '.join(CLAIMS_ENVIRONMENT_VARIABLES)}."
        )
        raise ImproperlyConfigured(message)

    contract_fields = fields(contract)
    if len(contract_fields) != len(CLAIMS_ENVIRONMENT_VARIABLES):
        message = (
            f"CLAIMS_CONTRACT carries {len(contract_fields)} fields in a deployed component, but "
            f"{len(CLAIMS_ENVIRONMENT_VARIABLES)} environment variables name them "
            f"({', '.join(CLAIMS_ENVIRONMENT_VARIABLES)}). A field no variable names cannot be "
            "configured by an operator, so the contract is unusable however it was populated."
        )
        raise ImproperlyConfigured(message)

    if contract.is_configured:
        return

    unset = [
        variable
        for variable, value in zip(
            CLAIMS_ENVIRONMENT_VARIABLES,
            (getattr(contract, field.name) for field in contract_fields),
            strict=True,
        )
        if not value
    ]
    message = (
        f"The claims contract is unconfigured in a deployed component: {', '.join(unset)} "
        f"{'is' if len(unset) == 1 else 'are'} unset. No conventional claim name is defaulted in its place, "
        "because a contract mapping against a name nobody declared resolves nothing and presents as a 401."
    )
    raise ImproperlyConfigured(message)


# feature:redis
#: The cache backends condition 8 refuses, as **objects rather than dotted
#: paths**. AD-26's rule -- predicates resolve objects, never strings -- applies
#: here and does not apply to condition 2, and the difference is worth stating
#: because the two conditions sit in the same file doing visibly different things.
#:
#: Condition 2 compares dotted paths because it cannot resolve them: importing an
#: authentication backend during stage 1 raises `AppRegistryNotReady`, and
#: `issubclass` would refuse allauth's backend, which is the one that has to stay.
#: Neither obstacle exists here. A cache backend class imports no model -- Django's
#: own `django.core.cache.backends.*` are `BaseCache` subclasses over a dict and a
#: no-op -- and no correct in-process subclass exists that a deployment needs to
#: keep, so ancestry is exactly the right predicate.
#:
#: `DummyCache` is here alongside `LocMemCache` for the same reason `spatialite`
#: is beside `sqlite3` above: it is the same forbidden state in the spelling that
#: does not look like it. A component that selected Redis and then configured the
#: cache away entirely has a cache that stores nothing, which is worse than a
#: per-worker one and reads as deliberate.
_IN_PROCESS_CACHE_BACKENDS: Final[tuple[type[object], ...]] = (LocMemCache, DummyCache)


def _refuse_in_process_cache(settings_module: ModuleType) -> None:
    """Refuse an in-process cache backend where the Redis feature is selected (AC #1).

    Condition 8, and one of the two conditions in the whole contract that is not
    unconditional. It is scoped because `config/settings/production.py` hardcodes
    `django_redis.cache.RedisCache` with no feature branch: a component that did
    *not* select Redis legitimately falls back to Django's in-process cache in a
    deployment, so an unconditional refusal here would reject two of the six valid
    combinations for having exactly the cache they were built with.

    Every configured alias is iterated rather than only `default`, on AD-9's
    reasoning applied to a second mapping: a second alias is where this hides, and
    a `sessions` alias left on the in-process backend beside a Redis `default` is
    the likeliest shape it takes.

    **Resolution is by object, not by string.** `import_string` resolves the
    dotted `BACKEND` and `issubclass` tests the result, so a subclass re-exported
    under another name -- `myapp.cache.FastCache(LocMemCache)` -- is refused too.
    That is the evasion this closes, and a string comparison would not close it.

    Five inputs are skipped rather than refused, and each is skipped for the same
    reason: it is not the state this condition's message describes. `CACHES` that
    is not a mapping at all; an alias whose configuration is not a mapping; a
    `BACKEND` that is not a string; a `BACKEND` that cannot be loaded; and one
    that loads to something which is not a class. Django owns all five and refuses
    each of them itself, at the first cache access, with the message that names
    what is actually wrong.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When any configured alias resolves to `LocMemCache`,
            to `DummyCache`, or to a subclass of either. The message names the
            alias, the configured path and the Redis feature, because which half
            of the pair is wrong -- the cache or the selection -- is something
            only the reader knows.

    """
    caches: object = getattr(settings_module, "CACHES", _ABSENT)
    if not isinstance(caches, dict):
        return

    for alias, configuration in caches.items():
        if not isinstance(configuration, dict):
            continue
        dotted_path = configuration.get("BACKEND")
        if not isinstance(dotted_path, str):
            continue

        try:
            resolved = import_string(dotted_path)
        except Exception:  # noqa: BLE001, S112 - see below: any failure to *load* a backend is Django's defect
            # Skipped, and deliberately not converted into a refusal. This
            # condition's message describes *an in-process backend in a component
            # that selected Redis*, which is not what a backend that will not load
            # is; refusing here would add another forbidden state to a settled
            # count, under a message that would send the reader to the wrong
            # line. Django already owns the defect
            # and raises `InvalidCacheBackendError` -- itself an
            # `ImproperlyConfigured` -- at the first cache access.
            #
            # **Why the guard is `Exception` and not `ImportError`.**
            # `import_string` executes third-party module code: it imports the
            # module named by the dotted path, and that module's top level can
            # raise anything at all. `AppRegistryNotReady` is the one a Django
            # package plausibly raises here, because stage 1 runs while
            # `apps.populate` is still going; a module whose import-time work
            # fails raises whatever it raises. Both were reproduced escaping a
            # narrow `except ImportError`. An escaping exception breaks the one
            # promise this module makes (CG-3, and the `Raises:` section above):
            # `ImproperlyConfigured` and nothing else comes out of a condition.
            # `BaseException` is deliberately *not* caught -- `KeyboardInterrupt`,
            # `SystemExit` and the test suite's own network guard have to pass
            # through a settings import untouched.
            #
            # **This is error handling, not feature detection.** AD-24 forbids
            # `try`/`except ImportError` as a *removal mechanism* -- a way of
            # asking whether a feature is present. Nothing is asked here: the
            # dotted path came from the settings module rather than from this
            # file, the resolution is attempted unconditionally, and the condition
            # either side of the guard is the same in every combination that
            # contains this region at all. Widening the guard does not change
            # that: it is still one already-resolved settings value being loaded,
            # and no branch anywhere behaves differently for a feature's presence.
            continue

        # `issubclass` raises `TypeError` when handed something that is not a
        # class, and a `BACKEND` naming a function or a constant is a plausible
        # typo. A condition that raised `TypeError` out of a settings import
        # would break the one promise CG-3 makes about this module.
        if not isinstance(resolved, type):
            continue

        forbidden = next((backend for backend in _IN_PROCESS_CACHE_BACKENDS if issubclass(resolved, backend)), None)
        if forbidden is None:
            continue

        message = (
            f"CACHES[{alias!r}] configures {dotted_path} in a deployed component, which resolves to a "
            f"{forbidden.__name__} -- Django's in-process cache. This component selected the Redis "
            "cache feature, so a shared cache is the one it was built to have: an in-process cache is "
            "per-worker and per-container, so a value written by one gunicorn worker is invisible to "
            "the next request and gone at the next restart. "
            "Point BACKEND at django_redis.cache.RedisCache."
        )
        raise ImproperlyConfigured(message)


# /feature:redis
# feature:celery
def _refuse_eager_tasks(settings_module: ModuleType) -> None:
    """Refuse eager task execution where background task processing is selected (AC #2).

    Condition 9, the second and last of the feature-scoped pair. Scoped for the
    mirror of condition 8's reason: eager execution is meaningless in a component
    with no background task processing, so an unconditional refusal would refuse
    combinations for a setting that does nothing in them.

    `config/settings/local.py:103` sets `CELERY_TASK_ALWAYS_EAGER = True`, which
    is correct there and is exactly the value that must not survive into a
    deployment: eager execution runs the task inline, on the web request's own
    thread and inside its transaction, so every queued job becomes latency the
    caller pays and the worker processes have nothing to do.

    **`CELERY_TASK_EAGER_PROPAGATES` is deliberately not refused.** `local.py:110`
    sets it beside the flag above, and it is inert without it -- it decides only
    whether an eagerly executed task re-raises. Refusing on it would create a
    second forbidden state where the architecture settled on one, and would refuse
    a deployed component whose tasks are queued normally.

    Absence is neutral and is the ordinary case: `config/settings/base.py`
    declares neither flag, so a deployed component that never mentions eager
    execution is a component that does not use it.

    Args:
        settings_module: The settings module currently being composed.

    Raises:
        ImproperlyConfigured: When `CELERY_TASK_ALWAYS_EAGER` is truthy. Truthy
            rather than `is True`, because this one is read as a switch by Celery
            itself -- unlike `DJANGO_ADMIN_FORCE_ALLAUTH`, where anything other
            than `True` is the forbidden state and identity is therefore the test.
            The value that makes the difference concrete is the string `"false"`,
            which is what an environment-driven settings module produces from a
            variable nobody parsed: Celery reads it as on, and an `is True` rule
            would read it as off and let it through.
            `tests/unit/startup/test_feature_scoped_refusals.py` drives that exact
            value, so the choice cannot be reverted by an edit that still passes.

    """
    if not getattr(settings_module, "CELERY_TASK_ALWAYS_EAGER", False):
        return

    message = (
        "CELERY_TASK_ALWAYS_EAGER is enabled in a deployed component. This component selected "
        "background task processing, so a task is queued for a worker rather than run inline: "
        "eager execution runs it in the web request that called it, on that request's thread and "
        "inside its transaction, which turns every queued job into latency the caller pays and "
        "every worker into a process with nothing to do. "
        "Unset and False are both correct here; config/settings/local.py is the only module that enables it."
    )
    raise ImproperlyConfigured(message)


# /feature:celery
#: The stage-1 conditions, in evaluation order, and the order is part of the
#: contract rather than an accident of how they were written: AD-26 requires "one
#: location, one owner, and a fixed order", and
#: `tests/unit/startup/test_stage_one_conditions.py` asserts this tuple.
#:
#: FR-12's escape route is first because it is the one condition that says the
#: *wrong module loaded* -- every condition after it is reading values from a
#: module that had no business executing, so its message is the one that helps.
#: The five that follow are conditions 1 to 5 of the refusal table, in the
#: table's own order.
#:
#: The two feature-scoped conditions are appended here rather than reached by a
#: second call inside `run_stage_one`, so that the dispatch has one shape and the
#: roster has one declaration site (AD-1). They are last because they are the
#: conditional ones: a component meets every refusal it shares with every other
#: combination before it meets one that depends on what it selected.
#:
#: Each entry carries its own marker pair, and that is not tidiness. The
#: materializer removes a region's lines, so a call site left outside the pair
#: would survive into a combination whose definition had gone -- a `NameError`
#: at settings import, which is the failure AD-24's worked example is about.
_STAGE_ONE: Final[tuple[Callable[[ModuleType], None], ...]] = (
    _refuse_the_local_settings_module,
    _refuse_sqlite,
    _refuse_local_credential_paths,
    _refuse_otel_disabled,
    _refuse_untrusted_jwks_anchor,
    _refuse_unconfigured_claims_contract,
    # feature:redis
    _refuse_in_process_cache,
    # /feature:redis
    # feature:celery
    _refuse_eager_tasks,
    # /feature:celery
)


def run_stage_one(settings_module: ModuleType, /) -> None:
    """Evaluate every stage-1 condition against a settings module being composed.

    Called as `run_stage_one(sys.modules[__name__])`, as the last statement of
    every leaf settings module. The parameter is required and positional-only
    on purpose: every call site passes it, so a default would only ever mask a
    call site that forgot, and a keyword catch-all would silently absorb a
    future condition's misrouted argument instead of failing on it.

    Args:
        settings_module: The module whose namespace the conditions inspect.

    Raises:
        ImproperlyConfigured: When any condition finds a forbidden state.

    """
    if not is_deployed():
        return

    for condition in _STAGE_ONE:
        condition(settings_module)
