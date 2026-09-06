"""CG-3: a refusal raises. It never warns, never logs and continues, never softens.

> "Do not soften a refusal into a warning. A refusal that logs and continues
> makes deployment smoother and puts local credentials into production."

Every other module in this package asserts that a forbidden state *is* refused.
This one asserts the shape of the refusal, which is a different claim and the one
that decays quietly: a condition edited into `logger.warning(...)` and a `return`
still passes a test that only checks the component does not start cleanly, if
that test was written loosely enough. Four assertions, from four directions:

* **A** -- each forbidden state raises `ImproperlyConfigured` and emits no
  warning while doing it. A condition that warns *and* raises is still the wrong
  shape; a condition that warns and returns is the failure CG-3 names.
* **B** -- each forbidden state raises with nothing logged in place of the raise,
  captured through `structlog.testing.capture_logs()`. Logging alongside a raise
  is permitted by CG-3; logging instead of it is not.
* **C** -- the package's source contains no `warnings.warn`, no bare `except:`
  and no exception handler that swallows. Here the project standard and CG-3
  happen to forbid exactly the same three shapes.
* **D** -- every refusal raises `django.core.exceptions.ImproperlyConfigured`
  specifically, asserted both at runtime (the exact type, not a subclass of
  something broader) and over every `raise` statement in the package. The
  Consistency Conventions fix the type: "Every forbidden or missing configuration
  raises `ImproperlyConfigured` at one of the two refusal stages."

**Which states this module reaches.** Thirteen of the fifteen, plus FR-12's
escape route. The two it does not are the stage-2 database states -- unapplied
migrations and an absent designated group -- which need a live connection and are
therefore covered by the same measurements in
`tests/integration/startup/test_stage_two_served_path.py`, whose cases are
parametrized from `DELEGATED_TO_THE_INTEGRATION_SUITE` so that a state named there
and not covered fails on that side. Splitting them that way is what keeps this
module a unit test: it opens no database, no socket and no file beyond reading the
package's own source. That claim rests on the autouse fixture below deleting
`COMPONENT_PROCESS` as well as `COMPONENT_RUNTIME` -- two builders here run stage
2, whose database conditions gate on `is_serving_process()` reading that variable
off the environment, so a shell holding `COMPONENT_PROCESS=web` would otherwise
turn two of these cases into database-touching ones.

Each state is constructed here rather than imported from the module that asserts
its message, because what is under test is different: those modules ask *what* the
refusal said, and this one asks *how* it arrived. A shared builder would make one
module's convenience the other's coverage. Each builder still records **one**
distinguishing substring of the message its state refuses with, and every case
asserts it: stage 1 evaluates a roster in order, so a builder that stopped
constructing its state -- or a condition deleted outright -- would otherwise keep
these cases green under the label of the state no longer being checked.
"""

from __future__ import annotations

import ast
import os
import warnings
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from inspect import currentframe
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

import pytest
import structlog
from django.conf import settings
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import ImproperlyConfigured
from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from conda_package_supply_chain_monitor.collectors.sweep import COLLECTOR_KWARG
from conda_package_supply_chain_monitor.collectors.sweep import SWEEP_TASK_NAME
from conda_package_supply_chain_monitor.core import registry
from config.authorization.claims import ClaimsContract
from config.local_dev import views as local_dev_views
from config.locality import PROCESS_ENV_VAR
from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup import run_stage_two
from config.startup import stage_one
from config.startup.stage_one import LOCAL_SETTINGS_MODULE
from tests.collectors import FIXTURE_CADENCE
from tests.collectors import collector_class
from tests.collectors import fixture_evidence_model
from tests.collectors import selectable_collector_class
from tests.conftest import deployed_url_patterns
from tests.conftest import temporary_root_urlconf
from tests.conftest import valid_deployed_settings_namespace
from tests.unit.startup.forbidden_states import DELEGATED_TO_THE_INTEGRATION_SUITE
from tests.unit.startup.forbidden_states import ESCAPE_ROUTE_STATE
from tests.unit.startup.forbidden_states import FORBIDDEN_STATES

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
STARTUP_PACKAGE: Final[Path] = REPO_ROOT / "src" / "config" / "startup"

#: The package's path in the spelling a traceback carries, so that a filename
#: comparison is made against what the interpreter actually records rather than
#: against what the repository layout suggests. `warning_filter_is_live` below
#: proves the two agree, because an editable-install finder, a symlinked
#: site-packages or a case-differing mount would each break the equality
#: silently -- and every warning assertion in this module is an assertion that
#: nothing was recorded.
STARTUP_PACKAGE_POSIX: Final[str] = STARTUP_PACKAGE.as_posix()

SQLITE_ENGINE: Final = "django.db.backends.sqlite3"
MODEL_BACKEND: Final = "django.contrib.auth.backends.ModelBackend"
AUTHTOKEN_APP: Final = "rest_framework.authtoken"
FOREIGN_JWKS_URL: Final = "https://keys.attacker.test/realms/component/certs"

#: The one exception type a condition is permitted to raise. Read as an identity
#: rather than as an `isinstance`, because `ImproperlyConfigured` has subclasses
#: in Django's own tree -- `InvalidCacheBackendError` among them -- and a
#: condition raising one of those would say something narrower than the contract
#: promises while satisfying every `pytest.raises` in the suite.
REFUSAL_TYPE: Final = ImproperlyConfigured

#: The broad `except Exception` handlers this package is permitted to contain,
#: counted per file rather than licensed per form.
#:
#: `stage_one.py` has exactly one: condition 8 resolves a `CACHES[...]["BACKEND"]`
#: dotted path through `import_string`, which executes third-party module code
#: that can raise anything at all. Its handler does not swallow -- it `continue`s
#: to the next alias, under a comment recording that a backend which will not
#: load is Django's defect and not a fifteenth forbidden state. That is a skip
#: with a stated reason, not the log-and-continue CG-3 forbids and not the
#: `except X: pass` the project standard forbids; the assertions below distinguish
#: the two rather than banning the word `Exception`.
#:
#: A *second* one appearing in this package fails here, which is the point of
#: counting: the licence is for one recorded decision, never for the file.
#:
#: **The entry is marker-delimited, because the handler it records is.** That
#: `except Exception` sits inside `stage_one.py`'s own `feature:redis` region --
#: it guards `import_string` on a `CACHES` backend, and condition 8 is Redis's.
#: A combination materialized without Redis loses the handler and would then fail
#: this assertion on an allowance nothing in the tree still needs. Keyed by the
#: file's path relative to the package, so a subpackage added later is
#: distinguishable from a same-named module beside it.
BROAD_EXCEPT_ALLOWANCE: Final[dict[str, int]] = {
    # A comment inside the braces holds the literal in its expanded form, so a
    # combination that dropped the entry below is left with a mapping
    # `ruff format` accepts rather than one it wants rewritten as `{}`.
    # feature:redis
    "stage_one.py": 1,
    # /feature:redis
}

#: The exception names a broad handler may catch. `BaseException` is deliberately
#: absent: `KeyboardInterrupt`, `SystemExit` and the suite's own network guard
#: have to pass through a settings import untouched.
#:
#: Compared against the *last* segment of the caught name, so that
#: `builtins.Exception` -- a legal and equivalent spelling -- is counted as the
#: broad handler it is rather than passing as an unrecognized dotted path.
BROAD_EXCEPTION_NAMES: Final = frozenset({"Exception"})


def _refuse_sqlite_backend(_monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure condition 1's forbidden state and run the stage that refuses it."""
    namespace = valid_deployed_settings_namespace()
    namespace.DATABASES["default"]["ENGINE"] = SQLITE_ENGINE
    run_stage_one(namespace)


def _refuse_model_backend(_monkeypatch: pytest.MonkeyPatch) -> None:
    """State 2a: Django's own username-and-password backend is installed."""
    namespace = valid_deployed_settings_namespace()
    namespace.AUTHENTICATION_BACKENDS = [MODEL_BACKEND]
    run_stage_one(namespace)


def _refuse_declared_login_methods(_monkeypatch: pytest.MonkeyPatch) -> None:
    """State 2b: a declared login method keeps allauth's local sign-in form reachable."""
    namespace = valid_deployed_settings_namespace()
    namespace.ACCOUNT_LOGIN_METHODS = {"username"}
    run_stage_one(namespace)


def _refuse_unforced_admin(_monkeypatch: pytest.MonkeyPatch) -> None:
    """State 2c: the admin keeps its own login form."""
    namespace = valid_deployed_settings_namespace()
    namespace.DJANGO_ADMIN_FORCE_ALLAUTH = False
    run_stage_one(namespace)


def _refuse_static_token_surface(_monkeypatch: pytest.MonkeyPatch) -> None:
    """State 2d: the app that mints and stores local API tokens is installed."""
    namespace = valid_deployed_settings_namespace()
    namespace.INSTALLED_APPS = [*namespace.INSTALLED_APPS, AUTHTOKEN_APP]
    run_stage_one(namespace)


def _refuse_disabled_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 3, the one input read from the environment rather than the namespace."""
    monkeypatch.setenv(OTEL_SDK_DISABLED_ENV_VAR, "true")
    run_stage_one(valid_deployed_settings_namespace())


def _refuse_untrusted_jwks_anchor(_monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 4: the trust anchor sits on a host the issuer does not control."""
    namespace = valid_deployed_settings_namespace()
    namespace.OIDC_JWKS_URL = FOREIGN_JWKS_URL
    run_stage_one(namespace)


def _refuse_unconfigured_claims(_monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 5, stage 1: the contract carries none of its four names."""
    namespace = valid_deployed_settings_namespace()
    namespace.CLAIMS_CONTRACT = ClaimsContract("", "", "", "")
    run_stage_one(namespace)


def _refuse_credential_minting_route(_monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 6, state a: DRF's token endpoint is reachable in the resolved URLconf."""
    with temporary_root_urlconf(path("api/auth-token/", obtain_auth_token, name="obtain_auth_token")):
        run_stage_two()


def _refuse_local_sign_in_route(_monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 6, state b: the local persona sign-in view is reachable."""
    with temporary_root_urlconf(
        path("accounts/local-sign-in/", local_dev_views.persona_signin, name="local_persona_login"),
    ):
        run_stage_two()


def _refuse_a_collector_without_a_freshness_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 10: a registered collector whose evidence would never go stale.

    The registry is replaced wholesale rather than written to, which is what
    keeps this a unit case with no cleanup of its own: `monkeypatch.setattr` puts
    the module's mapping back however the condition exits, and a registration
    that leaked out of a case asserting a *refusal* would refuse every case that
    ran after it.

    A stand-in URL configuration goes on for the reason the two URLconf builders
    above install theirs: `run_stage_two` evaluates its roster in order, and this
    process built the *local* configuration, which mounts the persona sign-in
    route condition 6 exists to refuse. Without the substitution this case would
    be measuring that condition instead, which the `says` assertion would catch
    but only after sending its reader to the wrong file.
    """
    built = collector_class(
        declared_model=fixture_evidence_model(),
        declared_freshness_target=None,
    )
    monkeypatch.setattr(registry, "_REGISTERED", {built.name: built})
    with temporary_root_urlconf(*deployed_url_patterns()):
        run_stage_two()


def _refuse_a_cadence_the_schedule_disagrees_with(monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 11: a collector swept on an interval its own declaration denies.

    The registry and the schedule are both replaced wholesale, for the reason the
    builder above replaces the registry: `monkeypatch` puts both back however the
    condition exits, and a registration or a schedule entry that leaked out of a
    case asserting a *refusal* would refuse every case that ran after it.

    Replacing the registry is also what keeps this case about condition 11 alone.
    The four real collectors are registered in this process and the shipped
    schedule reconciles with them, so leaving either in place would leave this
    builder constructing its state on top of a state that is already correct --
    which is harmless here and would stop being so the moment the shipped pair
    disagreed for a reason of its own.

    A stand-in URL configuration goes on for the reason the two URLconf builders
    above install theirs.
    """
    built = selectable_collector_class(
        declared_model=fixture_evidence_model(),
        declared_name="cpm-fixture-unreconciled",
        declared_cadence=FIXTURE_CADENCE,
    )
    monkeypatch.setattr(registry, "_REGISTERED", {built.name: built})
    monkeypatch.setattr(
        settings,
        "CELERY_BEAT_SCHEDULE",
        {
            "cpm-sweep-fixture": {
                "task": SWEEP_TASK_NAME,
                "schedule": FIXTURE_CADENCE * 7,
                "kwargs": {COLLECTOR_KWARG: built.name},
            },
        },
    )
    with temporary_root_urlconf(*deployed_url_patterns()):
        run_stage_two()


def _refuse_the_local_settings_module(_monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-12's escape route, driven through the roster rather than through an import.

    The import form is `tests/unit/startup/test_stage_one_escape_route.py`'s, and
    that is where it belongs: it is the case that proves the *module load path*
    refuses. What is under test here is the shape of the refusal, so the namespace
    form is the one that isolates it -- a real import would also execute
    `base.py`, whose own imports may legitimately warn about anything at all.
    """
    run_stage_one(valid_deployed_settings_namespace(LOCAL_SETTINGS_MODULE))


# feature:redis
def _refuse_in_process_cache(_monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 8: an in-process cache backend where the Redis feature is selected."""
    namespace = valid_deployed_settings_namespace()
    namespace.CACHES = {"default": {"BACKEND": f"{LocMemCache.__module__}.{LocMemCache.__qualname__}"}}
    run_stage_one(namespace)


# /feature:redis
# feature:celery
def _refuse_eager_tasks(_monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 9: eager task execution where background task processing is selected."""
    namespace = valid_deployed_settings_namespace()
    namespace.CELERY_TASK_ALWAYS_EAGER = True
    run_stage_one(namespace)


# /feature:celery
@dataclass(frozen=True, slots=True)
class _Refusal:
    """One forbidden state this module can construct, and what its refusal says.

    Attributes:
        configure: Builds the state and runs the stage that refuses it.
        says: One distinguishing substring of the message that state refuses
            with. Not the whole message -- these carry regex metacharacters,
            interpolated paths and counts -- but enough that a case cannot pass
            on a *different* condition's refusal.

    """

    configure: Callable[[pytest.MonkeyPatch], None]
    says: str


#: One builder per forbidden state this module can construct without a database
#: connection, keyed by the `state_id` `tests/unit/startup/forbidden_states.py`
#: declares. Keyed by identifier rather than listed positionally so that
#: `test_every_declared_state_is_either_built_here_or_delegated` can reconcile
#: the two in both directions -- a state added to the declaration and forgotten
#: here would otherwise be silently untested for its *shape*, which is precisely
#: the decay CG-3 is about.
#:
#: **Each entry carries what its refusal says, and that is not decoration.**
#: Stage 1 evaluates its roster in order and every condition raises the same
#: type, so `pytest.raises(ImproperlyConfigured)` alone is satisfied by *any*
#: condition refusing -- including a condition that refused because the builder
#: stopped constructing its state, or because the state under test was deleted
#: and something earlier in the roster objected instead. Asserting the message is
#: what ties each case to the condition it is named after, and is what every
#: other module in this package already does.
#:
#: The last two entries are marker-delimited: they name the feature-scoped
#: conditions, which a combination without Redis or without background task
#: processing does not contain at all.
REFUSALS: Final[dict[str, _Refusal]] = {
    ESCAPE_ROUTE_STATE.state_id: _Refusal(_refuse_the_local_settings_module, "was loaded by a deployed component"),
    "sqlite-backend": _Refusal(_refuse_sqlite_backend, "reaches the sqlite backend"),
    "model-backend-installed": _Refusal(_refuse_model_backend, f"AUTHENTICATION_BACKENDS contains {MODEL_BACKEND}"),
    "account-login-methods-declared": _Refusal(_refuse_declared_login_methods, "ACCOUNT_LOGIN_METHODS declares"),
    "admin-not-forced-through-allauth": _Refusal(_refuse_unforced_admin, "DJANGO_ADMIN_FORCE_ALLAUTH is"),
    "static-token-surface": _Refusal(_refuse_static_token_surface, f"INSTALLED_APPS contains {AUTHTOKEN_APP}"),
    "otel-sdk-disabled": _Refusal(_refuse_disabled_telemetry, OTEL_SDK_DISABLED_ENV_VAR),
    "untrusted-jwks-anchor": _Refusal(_refuse_untrusted_jwks_anchor, "is not derived from"),
    "unconfigured-claims-contract": _Refusal(_refuse_unconfigured_claims, "The claims contract is unconfigured"),
    "credential-minting-route": _Refusal(_refuse_credential_minting_route, "rest_framework.authtoken"),
    "local-sign-in-route": _Refusal(_refuse_local_sign_in_route, "config.local_dev"),
    "collector-without-freshness-target": _Refusal(
        _refuse_a_collector_without_a_freshness_target,
        "freshness_target=None",
    ),
    "collector-cadence-not-reconciled": _Refusal(
        _refuse_a_cadence_the_schedule_disagrees_with,
        "cadence disagreement",
    ),
    # feature:redis
    "in-process-cache-backend": _Refusal(_refuse_in_process_cache, "CACHES['default']"),
    # /feature:redis
    # feature:celery
    "eager-task-execution": _Refusal(_refuse_eager_tasks, "CELERY_TASK_ALWAYS_EAGER"),
    # /feature:celery
}


@pytest.fixture(autouse=True)
def _deployed_and_traced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put every case in a deployed component with tracing on, and off a serving process.

    Deployed by deleting `COMPONENT_RUNTIME` rather than by setting it, because
    locality fails closed (AD-13). `OTEL_SDK_DISABLED` goes with it: condition 3
    reads it off the environment, so a developer's shell holding it would refuse
    every case here through the wrong condition.

    `COMPONENT_PROCESS` goes for a different reason, and it is what keeps this a
    unit module. Two builders here run stage 2, whose two database conditions
    gate on `config.locality.is_serving_process()` -- which reads that variable
    off the environment. A shell or a CI runner holding `COMPONENT_PROCESS=web`
    would turn those two cases into cases that open a connection, and the module
    docstring's claim to open no database would be false without anything
    failing.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)
    monkeypatch.delenv(PROCESS_ENV_VAR, raising=False)


@pytest.fixture
def structlog_capture_is_live() -> None:
    """Prove `capture_logs()` can still see an event before a case relies on its silence.

    `structlog.testing.capture_logs` swaps the configured processor chain, and a
    module that has reconfigured structlog -- or a logger cached under
    `cache_logger_on_first_use` before the swap -- makes the capture go quiet
    without failing. Every assertion in Test B below is an assertion that nothing
    was captured, so a blinded capture would make all of them pass while proving
    nothing at all. This emits one event through a freshly bound logger and
    insists it arrives.

    Returns:
        None. The check is the effect, and it happens at setup -- before the case
        that depends on it observes anything.

    """
    with structlog.testing.capture_logs() as captured:
        structlog.get_logger("tests.unit.startup.test_no_softening").info("capture-control")
    assert [event["event"] for event in captured] == ["capture-control"], (
        "structlog.testing.capture_logs() captured nothing at all, so every "
        "'nothing was logged' assertion in this module would pass vacuously"
    )


def _a_contract_frame_is_on_the_stack() -> bool:
    """Report whether any frame currently executing belongs to the refusal package.

    Returns:
        True when a live frame's code object was compiled from a file inside
        `src/config/startup/`.

    """
    frame = currentframe()
    while frame is not None:
        if STARTUP_PACKAGE_POSIX in Path(frame.f_code.co_filename).as_posix():
            return True
        frame = frame.f_back
    return False


@contextmanager
def _warnings_the_contract_raised() -> Iterator[list[str]]:
    """Record every warning the refusal package issues inside the block.

    Two mechanisms, because one of them is evadable. The filename a
    `WarningMessage` carries is the one `stacklevel` attributes the warning to,
    and `warnings.warn(..., stacklevel=2)` -- ruff's own preferred spelling --
    attributes it to the *caller*, which for the builders above is this test
    module. A filename filter alone would therefore miss the most likely
    spelling of the failure CG-3 names. So the live frame stack is consulted as
    well: whatever `stacklevel` claims, a warning issued from inside a condition
    has that condition's frame on the stack when `warn` is called.

    A warning from Django or from a third-party import is still not counted. It
    is not this contract softening anything, and counting it would fail the case
    on somebody else's release note.

    Yields:
        The list the messages accumulate in, populated as the block runs.

    """
    raised: list[str] = []

    def _record(message: Warning | str, _category: type[Warning], filename: str, *_rest: object) -> None:
        if _a_contract_frame_is_on_the_stack() or STARTUP_PACKAGE_POSIX in Path(filename).as_posix():
            raised.append(str(message))

    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.showwarning = _record
        yield raised


@pytest.fixture
def warning_filter_is_live() -> None:
    """Prove a warning attributed to the refusal package is caught before a case relies on silence.

    The mirror of `structlog_capture_is_live`, guarding the mirror-image failure.
    Every assertion in Test A below is an assertion that nothing was recorded, so
    a filter that stopped matching -- an editable-install finder redirecting
    `__file__`, a symlinked site-packages, a case-differing mount -- would make
    all of them pass while measuring nothing at all.

    `warn_explicit` is used rather than `warn` because it takes the attributed
    filename as an argument, and the argument handed to it is the package's own
    `__file__` as the interpreter reports it. That is exactly the string a real
    warning out of a condition would carry, so this asserts the comparison holds
    against what Python records rather than against what the tree looks like.

    Returns:
        None. The check is the effect, and it happens at setup -- before the case
        that depends on it observes anything.

    """
    with _warnings_the_contract_raised() as raised:
        warnings.warn_explicit(
            "warning-filter-control",
            UserWarning,
            str(stage_one.__file__),
            1,
        )

    assert raised == ["warning-filter-control"], (
        "a warning attributed to the refusal package's own source file was not recorded, so every "
        "'the refusal warned about nothing' assertion in this module would pass vacuously"
    )


def _package_source_files() -> list[Path]:
    """Return every Python file under `src/config/startup/`, however deeply nested.

    Recursive rather than a single directory listing: a subpackage added under
    the refusal contract would be invisible to every static scan below if this
    were `glob`, and the scans are what cover the branches no test reaches.

    Returns:
        Every `.py` file beneath the package, sorted by path.

    """
    return sorted(STARTUP_PACKAGE.rglob("*.py"))


def _parsed_package_modules() -> list[tuple[Path, ast.Module]]:
    """Return every module in `src/config/startup/`, parsed.

    Returns:
        One `(path, tree)` pair per source file, sorted by path.

    """
    return [(source, ast.parse(source.read_text(encoding="utf-8"))) for source in _package_source_files()]


def _within_the_package(source: Path) -> str:
    """Name a scanned file the way a failure needs to point at it.

    Args:
        source: The scanned file.

    Returns:
        Its path relative to the package -- `stage_one.py` today, and
        `subpackage/module.py` for a file a plain name could not distinguish.

    """
    return source.relative_to(STARTUP_PACKAGE).as_posix()


def _dotted_name(node: ast.expr) -> str:
    """Return the dotted source spelling of an attribute or name expression.

    Args:
        node: The expression to spell.

    Returns:
        The dotted name, or the empty string for an expression that is neither.

    """
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _caught_names(handler: ast.ExceptHandler) -> list[str]:
    """Return every exception name one handler catches, in its source spelling.

    Both evasions of a naive `_dotted_name(handler.type)` are handled here rather
    than at the call site. `except (Exception, OSError):` is an `ast.Tuple`, for
    which a dotted-name reader returns the empty string and the handler counts as
    catching nothing at all; and `except builtins.Exception:` spells the same
    class through a qualified path, which no comparison against the bare name
    would recognize.

    Args:
        handler: The handler to inspect.

    Returns:
        One dotted name per caught class. Empty for a bare `except:`, which
        `test_no_handler_in_the_package_is_bare` owns.

    """
    caught = handler.type
    if caught is None:
        return []
    elements = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return [name for name in (_dotted_name(element) for element in elements) if name]


def _catches_broadly(handler: ast.ExceptHandler) -> bool:
    """Report whether a handler catches one of the broad exception classes.

    Args:
        handler: The handler to inspect.

    Returns:
        True when any caught name's last segment is in `BROAD_EXCEPTION_NAMES`,
        so that `Exception`, `builtins.Exception` and
        `(builtins.Exception, OSError)` are all counted alike.

    """
    return any(name.rsplit(".", 1)[-1] in BROAD_EXCEPTION_NAMES for name in _caught_names(handler))


def _swallows(handler: ast.ExceptHandler) -> bool:
    """Report whether an exception handler does nothing at all with what it caught.

    `except X: pass` and `except X: ...` are the two spellings. A handler that
    logs, re-raises, returns or continues under a stated reason is not this: it
    took a decision, and CG-3 is about decisions that are never taken.

    Args:
        handler: The handler to inspect.

    Returns:
        True when the body is exactly one no-op statement.

    """
    if len(handler.body) != 1:
        return False
    only = handler.body[0]
    return isinstance(only, ast.Pass) or (
        isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is Ellipsis
    )


class TestTheStatesThisModuleCovers:
    """The reconciliation that keeps the three assertion sets below exhaustive."""

    def test_every_declared_state_is_either_built_here_or_delegated(self) -> None:
        """An equality in both directions, so neither list can drift from the declaration.

        A new forbidden state has to arrive in one of the two places, and a state
        removed from the declaration has to leave both.
        """
        declared = {state.state_id for state in FORBIDDEN_STATES} | {ESCAPE_ROUTE_STATE.state_id}

        assert set(REFUSALS) | DELEGATED_TO_THE_INTEGRATION_SUITE == declared

    def test_no_state_is_both_built_here_and_delegated(self) -> None:
        """Overlap would mean a state counted twice and a state counted not at all."""
        assert set(REFUSALS) & DELEGATED_TO_THE_INTEGRATION_SUITE == set()


class TestARefusalIsNeverAWarning:
    """Test A: it raises, and it emits no warning on the way (CG-3)."""

    @pytest.mark.parametrize("state_id", sorted(REFUSALS), ids=str)
    def test_the_forbidden_state_raises_and_warns_about_nothing(
        self,
        state_id: str,
        monkeypatch: pytest.MonkeyPatch,
        warning_filter_is_live: None,
    ) -> None:
        """Every filter set to `always`, and the recording proven live first.

        `pytest.warns(None)` is not the spelling: modern pytest raises on it
        outright rather than meaning "expect no warning".

        Only warnings raised *by the refusal package* are counted -- see
        `_warnings_the_contract_raised` for the two mechanisms that decide what
        that means, and why a filename filter alone is not one of them.
        """
        refusal = REFUSALS[state_id]

        with _warnings_the_contract_raised() as raised, pytest.raises(REFUSAL_TYPE) as refused:
            refusal.configure(monkeypatch)

        assert refusal.says in str(refused.value), (
            f"the refusal for {state_id!r} does not say {refusal.says!r}, so this case is measuring "
            f"a different condition: {refused.value}"
        )
        assert raised == [], (
            f"the refusal for {state_id!r} warned as well as raising: {raised}. "
            "A refusal is a refusal; a warning beside it is the first half of softening it."
        )


class TestARefusalIsNeverALogLine:
    """Test B: nothing is logged in place of the raise (CG-3)."""

    @pytest.mark.parametrize("state_id", sorted(REFUSALS), ids=str)
    def test_the_forbidden_state_raises_and_logs_nothing_instead(
        self,
        state_id: str,
        monkeypatch: pytest.MonkeyPatch,
        structlog_capture_is_live: None,
    ) -> None:
        """Captured through structlog, with the capture itself proven live first.

        CG-3 permits logging *alongside* a raise and forbids logging *instead* of
        one. The refusal contract logs nothing today -- it imports no logger at
        all -- so the assertion is emptiness, and that is deliberately the
        stricter reading: the day a condition legitimately wants to log beside its
        raise, this line is where the decision gets recorded rather than made in
        passing.
        """
        refusal = REFUSALS[state_id]

        with structlog.testing.capture_logs() as captured:
            with pytest.raises(REFUSAL_TYPE) as refused:
                refusal.configure(monkeypatch)
            emitted = [event.get("event") for event in captured]

        assert refusal.says in str(refused.value), (
            f"the refusal for {state_id!r} does not say {refusal.says!r}, so this case is measuring "
            f"a different condition: {refused.value}"
        )
        assert emitted == [], f"the refusal for {state_id!r} emitted log events: {emitted}"


class TestTheSourceCarriesNoneOfTheThreeShapes:
    """Test C: `warnings.warn`, a bare `except:`, and a handler that swallows."""

    def test_there_are_modules_to_scan(self) -> None:
        """A scan whose glob resolves to nothing passes without asserting anything."""
        assert {_within_the_package(path) for path, _ in _parsed_package_modules()} >= {
            "__init__.py",
            "allowlist.py",
            "stage_one.py",
            "stage_two.py",
        }

    def test_the_scan_reaches_every_file_in_the_package(self) -> None:
        """Nothing under the package escapes the scans, however deeply it is nested.

        The superset assertion above names four files and therefore cannot detect
        a *narrowing*: a walk that stopped descending -- a plain `glob` where an
        `rglob` was meant -- would keep finding all four while silently skipping
        every module of a subpackage added later, and Test C and the static half
        of Test D are the only things covering the branches no test reaches.

        Walked independently here, with `os.walk`, so that the assertion is a
        comparison between two mechanisms rather than a restatement of one.
        """
        walked = {
            _within_the_package(Path(directory) / name)
            for directory, _subdirectories, names in os.walk(STARTUP_PACKAGE)
            for name in names
            if name.endswith(".py")
        }

        assert {_within_the_package(path) for path, _ in _parsed_package_modules()} == walked

    def test_the_package_never_imports_the_warnings_module(self) -> None:
        """The strongest form: it cannot call what it never imported.

        Stronger than scanning for `warnings.warn(` because it also catches
        `from warnings import warn` and any alias of it, and it reads as the rule
        rather than as one spelling of the rule.
        """
        importers = [
            _within_the_package(source)
            for source, tree in _parsed_package_modules()
            for node in ast.walk(tree)
            if (isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "warnings" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "warnings")
        ]

        assert importers == [], f"these modules in the refusal contract import `warnings`: {importers}"

    def test_no_call_in_the_package_issues_a_warning(self) -> None:
        """The call-site half, for a warning reached through something other than an import.

        `django.utils.deprecation`, a re-export, or a warning issued through an
        object attribute would all pass the import scan above.
        """
        warned = [
            f"{_within_the_package(source)}:{node.lineno}"
            for source, tree in _parsed_package_modules()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _dotted_name(node.func).split(".")[-1] in {"warn", "warn_explicit"}
        ]

        assert warned == [], f"a refusal is being softened into a warning at: {warned}"

    def test_no_handler_in_the_package_is_bare(self) -> None:
        """`except:` catches `KeyboardInterrupt` and `SystemExit` too, and is banned outright."""
        bare = [
            f"{_within_the_package(source)}:{node.lineno}"
            for source, tree in _parsed_package_modules()
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and node.type is None
        ]

        assert bare == [], f"bare `except:` in the refusal contract at: {bare}"

    def test_no_handler_in_the_package_swallows_what_it_caught(self) -> None:
        """`except X: pass` -- the exact shape CG-3 forbids, expressed as error handling.

        Deliberately narrower than "no broad handler". Condition 8's
        `except Exception` around `import_string` does not swallow: it continues
        to the next cache alias under a comment recording that a backend which
        will not load is Django's defect rather than a fifteenth forbidden state.
        Banning the word `Exception` would have failed that guard while catching
        nothing CG-3 is actually about; banning the *no-op body* catches the
        failure without touching the decision.
        """
        swallowed = [
            f"{_within_the_package(source)}:{node.lineno}"
            for source, tree in _parsed_package_modules()
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and _swallows(node)
        ]

        assert swallowed == [], f"an exception is swallowed rather than acted on at: {swallowed}"

    def test_the_broad_handlers_are_the_recorded_ones_and_no_more(self) -> None:
        """One recorded `except Exception`, counted, not licensed by form.

        The count is what makes it a record rather than a permission: a second
        broad handler in the same file fails here exactly as it would in a file
        with no allowance at all, and the removal of the recorded one fails from
        the other side.
        """
        broad: Counter[str] = Counter(
            _within_the_package(source)
            for source, tree in _parsed_package_modules()
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and _catches_broadly(node)
        )

        assert dict(broad) == BROAD_EXCEPT_ALLOWANCE, (
            f"broad `except Exception` handlers in the refusal contract are {dict(broad)}, "
            f"and the recorded allowance is {BROAD_EXCEPT_ALLOWANCE}"
        )


#: The one `raise` in the package that is deliberately not `ImproperlyConfigured`,
#: by module, frozen so a second one fails while the recorded one does not.
#:
#: `allowlist.py`'s `AuthenticationRouteScope.__post_init__` refuses a scope record
#: that declares both a literal prefix and a settings key, or neither. Two reasons
#: it is a `ValueError` and cannot be the refusal type:
#:
#: * **It cannot import Django.** AD-8's composition step imports the allowlist
#:   during settings composition, so the module imports nothing from `django` at
#:   all -- `tests/unit/startup/test_module_shape.py` asserts that directly. There
#:   is no `ImproperlyConfigured` in scope to raise.
#: * **It is not a configuration state.** Every other raise in this package is a
#:   deployed component's settings or routes being wrong, which is what an
#:   operator's runbook is written against. This one is the *declaration* being
#:   malformed -- a programming error in a frozen dataclass literal, reachable only
#:   by editing this repository, and never by any environment.
OTHER_RAISE_ALLOWANCE: Final[dict[str, str]] = {"allowlist.py": "ValueError"}


class TestTheExceptionTypeIsFixed:
    """Test D: `ImproperlyConfigured`, never something broader."""

    @pytest.mark.parametrize("state_id", sorted(REFUSALS), ids=str)
    def test_the_refusal_is_exactly_improperly_configured(
        self,
        state_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Type identity, not `isinstance`.

        `pytest.raises(ImproperlyConfigured)` is satisfied by any subclass, and
        Django ships several -- `InvalidCacheBackendError` among them. The
        Consistency Conventions fix the type exactly, because it is what an
        operator's runbook and every caller's `except` clause are written
        against.
        """
        refusal = REFUSALS[state_id]

        with pytest.raises(REFUSAL_TYPE) as refused:
            refusal.configure(monkeypatch)

        assert refusal.says in str(refused.value), (
            f"the refusal for {state_id!r} does not say {refusal.says!r}, so this case is measuring "
            f"a different condition: {refused.value}"
        )
        assert type(refused.value) is REFUSAL_TYPE, (
            f"the refusal for {state_id!r} raised {type(refused.value).__name__}, not {REFUSAL_TYPE.__name__}"
        )

    def test_every_raise_in_the_package_raises_improperly_configured(self) -> None:
        """The static half, which also covers the branches no test reaches.

        A `ValueError` on an unreachable-looking path is still an escape hatch out
        of the one promise this package makes, and it is the kind of thing that
        arrives in a helper rather than in a condition.

        One recorded exception, frozen the way the broad-handler allowance above
        is: see `OTHER_RAISE_ALLOWANCE`.
        """
        wrong = {
            f"{_within_the_package(source)}:{node.lineno}": _dotted_name(
                node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            )
            for source, tree in _parsed_package_modules()
            for node in ast.walk(tree)
            if isinstance(node, ast.Raise)
            and node.exc is not None
            and _dotted_name(node.exc.func if isinstance(node.exc, ast.Call) else node.exc) != REFUSAL_TYPE.__name__
        }
        by_module = {location.split(":")[0]: raised for location, raised in wrong.items()}

        assert by_module == OTHER_RAISE_ALLOWANCE, (
            f"the refusal contract raises something other than {REFUSAL_TYPE.__name__} at {wrong}, "
            f"and the recorded allowance is {OTHER_RAISE_ALLOWANCE}"
        )

    def test_the_name_improperly_configured_is_djangos_in_every_module_that_raises_it(self) -> None:
        """The scan above compares a *name*, so the name has to be the one it means.

        `raise ImproperlyConfigured(...)` passes that comparison whatever
        `ImproperlyConfigured` happens to be bound to, and a class of that name
        defined or aliased inside the package would satisfy every static
        assertion here while raising something no caller's `except` clause
        catches. So: no module in the package may bind the name to anything of
        its own, and every module that mentions it must import it, unaliased,
        from `django.core.exceptions`.
        """
        name = REFUSAL_TYPE.__name__
        rebound: list[str] = []
        unsourced: list[str] = []

        for source, tree in _parsed_package_modules():
            where = _within_the_package(source)
            mentions = any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(tree))
            imported_from_django = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "django.core.exceptions"
                and any(alias.name == name and alias.asname is None for alias in node.names)
                for node in ast.walk(tree)
            )
            rebound += [
                f"{where}:{node.lineno}"
                for node in ast.walk(tree)
                if (isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name)
                or (isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store))
                or (isinstance(node, ast.alias) and node.asname == name and node.name != name)
            ]
            if mentions and not imported_from_django:
                unsourced.append(where)

        assert rebound == [], f"{name} is bound to something of the package's own at: {rebound}"
        assert unsourced == [], (
            f"these modules use {name} without importing it from django.core.exceptions: {unsourced}"
        )
