"""Nothing on the local start path reaches the network at boot (FR-23, AD-23).

Settings import, `configure_observability()` and `django.setup()` complete with
every socket refused, `KEY_STORE` holds no keys afterwards, and the two local
operations this module is about -- persona seeding and development keypair
generation -- reach nothing either. Seeding is asserted next to the rest of the
seeding suite, in `tests/integration/test_local_dev_seeding.py`, because it
needs a real database.

**What this module does not claim.** Environment installation downloads packages
by definition; the claim begins once the environment exists. And it is not
absolute even then: `OTEL_TRACES_EXPORTER=otlp` set by hand with no endpoint
configured attaches a batch processor to an exporter that defaults to
`http://localhost:4318`. The attachment is what `configure_observability()`
does; the outbound connection is made by the exporter's own background thread
shortly after boot. That is a deliberate opt-in, documented at
`docs/development.md` under "Running with no external services", and the one
supported way to make boot reach the network -- which is why the boot probe
excludes it from the child's environment rather than inheriting it.

**Why the boot assertion is a subprocess.** `tests/unit/conftest.py` says unit
tests touch no database, no network and no filesystem, and the boot probe is not
an evasion of that -- it is the only context in which the property is literally
true. pytest-django completes `django.setup()` at session start, so an
in-process call is a no-op; and `configure_observability()` is guarded by
`telemetry.py`'s `_configured` flag, which `src/config/__init__.py` ->
`src/config/celery_app.py` has already set at collection time, so an in-process
call executes nothing at all. The child pays that cost for real, though not
through its explicit call: importing `config.observability` imports the `config`
package, whose `__init__.py` reaches `celery_app` and configures telemetry
there, so the import chain is what performs the configuration and the explicit
call that follows is the same no-op it is here. The call stays because it is
what `manage.py` does. A negative assertion over code that never runs is the
failure mode this module is most exposed to, so the child reports positive
post-conditions -- the tracer provider is installed, the app registry is ready,
the configured issuer materialised -- and *also* reports that its own guard was
still armed on both sides of the boot it just performed.

The child re-declares the guard rather than importing `tests.conftest`: it runs
with `PYTHONSAFEPATH` set and `PYTHONPATH` cleared, so only the editable install
resolves, and `tests/` is not on its import path. `test_the_guard_refuses_a_
connection_rather_than_making_one` below is what keeps the in-process half
honest for the same reason.
"""

from __future__ import annotations

import importlib
import json
import os
import socket
import subprocess
import sys
from math import inf
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from allauth.socialaccount import providers
from django.conf import settings

from config.local_dev import keys
from config.local_dev.keys import JWKS_FILENAME
from config.local_dev.keys import PRIVATE_KEY_FILENAME
from config.local_dev.keys import ensure_keypair
from config.locality import RUNTIME_ENV_VAR
from tests.conftest import _ABSENT
from tests.conftest import _GUARDED_SOCKET_FUNCTIONS
from tests.conftest import _GUARDED_SOCKET_METHODS
from tests.conftest import NetworkAccessAttempted
from tests.conftest import _network_guard

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]

# The four settings modules, evicted together. `config.settings.base` goes with
# whichever module is under test because the `from .base import *` in each one
# would otherwise reuse the already-imported copy and re-read nothing.
BASE = "config.settings.base"
LOCAL = "config.settings.local"
PRODUCTION = "config.settings.production"
TEST = "config.settings.test"
SETTINGS_MODULES = (BASE, LOCAL, PRODUCTION, TEST)

# The key `SOCIALACCOUNT_PROVIDERS` is written under and the id allauth registers
# the provider class by. One string, two roles, named once.
OIDC_PROVIDER_KEY = "openid_connect"

# An issuer that looks like a real one and resolves nowhere: `.invalid` is
# reserved by RFC 2606. Settings read it, the provider block carries it, and
# nothing fetches it -- which is the whole of AD-31's contribution to FR-23. A
# value that appears nowhere in `src/` so nothing below can pass on a literal
# that happened to match.
PROBE_ISSUER = "https://no-network-probe.invalid/realms/component"

# TCP discard. Nothing listens there, so a guard that failed to install would
# produce a connection *refusal* rather than the exception -- a different error,
# not a green test.
DISCARD_ADDRESS = ("127.0.0.1", 9)

# A hostname reserved by RFC 2606, for the resolver chokepoints. A lookup is a
# network round trip that reaches no `socket.socket`, so it is guarded and probed
# separately from the connect chokepoints above.
RESOLVER_PROBE_HOST = "guard-probe.invalid"

# A cold Django start pays for app loading and the four OpenTelemetry
# instrumentors, and the child is one process doing all of it. Generous rather
# than tight: overshooting costs nothing when boot completes quickly, while a
# tight budget turns a slow CI runner into a failure that reads like a finding.
BOOT_PROBE_TIMEOUT_SECONDS = 180.0

# Telemetry variables the child never inherits, so its verdict is a property of
# this component rather than of the shell the suite was started from.
_SCRUBBED_TELEMETRY_VARS = (
    "OTEL_SDK_DISABLED",
    "OTEL_TRACES_EXPORTER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
)

# `KEY_STORE._fetched_at` before anything has fetched. Compared as `repr` because
# the child hands its report over as JSON, and `-inf` is not a JSON number.
NEVER_FETCHED = repr(-inf)

# What `manage.py` does, in a fresh interpreter, with the socket layer refusing
# every outbound connection -- and the report it writes so the parent can assert
# on the state boot left behind.
#
# It is a string on purpose. Nothing here executes in the test process, which is
# why the `print`-free file-handoff, the private `KEY_STORE` reads and the
# deferred imports below need no ruff exemptions: ruff sees a string literal.
# The report goes to a file named on the command line rather than to stdout,
# because Django's logging configuration also writes there and a report the
# parent has to find among log lines is a report that breaks when logging
# changes.
_BOOT_PROBE_SOURCE = '''
"""Boot this component once, in a fresh interpreter, with every socket blocked."""

import json
import socket
import sys
import threading
from pathlib import Path


class NetworkAccessAttempted(BaseException):
    """The guard `tests/conftest.py` installs, re-declared for this interpreter.

    `BaseException` for the reason it carries there: boot code that wraps a call
    in `except Exception` would otherwise swallow the refusal and this probe
    would report a clean boot that had reached the network.
    """


def _refuse(address):
    message = "a network connection to " + repr(address) + " was attempted during boot"
    raise NetworkAccessAttempted(message)


def _refuse_socket_method(self, address, *args, **kwargs):
    _refuse(address)


def _refuse_socket_function(address, *args, **kwargs):
    _refuse(address)


socket.socket.connect = _refuse_socket_method
socket.socket.connect_ex = _refuse_socket_method
socket.create_connection = _refuse_socket_function
socket.getaddrinfo = _refuse_socket_function
socket.gethostbyname = _refuse_socket_function

DISCARD_ADDRESS = ("127.0.0.1", 9)
RESOLVER_PROBE_HOST = "guard-probe.invalid"
GUARD_PROBE_TIMEOUT_SECONDS = 1.0

# A refusal raised on a worker thread never reaches this process's exit code, so
# without this the child's only failure signal would miss every exporter,
# instrumentor and connection pool that does its work off the main thread.
thread_refusals = []
_default_thread_excepthook = threading.excepthook


def _record_thread_refusal(args):
    """Record a refusal raised on a worker thread, then let the default hook report it."""
    if args.exc_type is not None and issubclass(args.exc_type, NetworkAccessAttempted):
        thread_refusals.append(str(args.exc_value))
    _default_thread_excepthook(args)


threading.excepthook = _record_thread_refusal


def _guard_is_armed():
    """Report whether every chokepoint still refuses, so a green report cannot mean an absent guard.

    An `OSError` from any probe means the guard was not in the way and the
    operating system answered instead -- a refused connection or a failed
    lookup is "the guard was absent", never "the guard worked". Every probe
    carries an explicit timeout, so a host that filters port 9 rather than
    refusing it fails this in a second instead of blocking for the OS connect
    timeout.
    """
    try:
        socket.getaddrinfo(RESOLVER_PROBE_HOST, 443)
    except NetworkAccessAttempted:
        pass
    except OSError:
        return False
    else:
        return False

    try:
        opened = socket.create_connection(DISCARD_ADDRESS, GUARD_PROBE_TIMEOUT_SECONDS)
    except NetworkAccessAttempted:
        pass
    except OSError:
        return False
    else:
        opened.close()
        return False

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(GUARD_PROBE_TIMEOUT_SECONDS)
    try:
        probe.connect(DISCARD_ADDRESS)
    except NetworkAccessAttempted:
        armed = True
    except OSError:
        armed = False
    else:
        armed = False
    finally:
        probe.close()
    return armed


armed_before_boot = _guard_is_armed()

import os

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.local"

# This import is what configures telemetry: it imports the `config` package,
# whose `__init__.py` reaches `celery_app`, which calls `configure_observability()`
# at import. The explicit call below is therefore a no-op, and is kept because it
# is what `manage.py` does.
from config.observability import configure_observability

configure_observability()

import django

django.setup()

from django.apps import apps
from django.conf import settings
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from config.authorization.jwks import KEY_STORE
from config.authorization.jwks import fetch_jwks_document

provider_app = settings.SOCIALACCOUNT_PROVIDERS["openid_connect"]["APPS"][0]

report = {
    "armed_before_boot": armed_before_boot,
    "armed_after_boot": _guard_is_armed(),
    "thread_refusals": thread_refusals,
    "settings_module": settings.SETTINGS_MODULE,
    "apps_ready": apps.ready,
    "oidc_provider_app_installed": "allauth.socialaccount.providers.openid_connect" in settings.INSTALLED_APPS,
    "tracer_provider_installed": isinstance(trace.get_tracer_provider(), TracerProvider),
    "oidc_issuer": settings.OIDC_ISSUER,
    "oidc_provider_server_url": provider_app["settings"]["server_url"],
    "jwks_cached_kids": sorted(KEY_STORE._keys),
    "jwks_fetched_at": repr(KEY_STORE._fetched_at),
    "jwks_fetch_is_the_module_default": KEY_STORE._fetch is fetch_jwks_document,
}

Path(sys.argv[1]).write_text(json.dumps(report), encoding="utf-8")
'''


@pytest.fixture(autouse=True)
def _evict_settings_modules() -> Iterator[None]:
    """Drop freshly imported settings modules before and after each case.

    The same idiom `tests/unit/test_settings.py` uses, and it is autouse for the
    same reason: a module left behind would be re-used by the next importer
    under whatever environment *that* test set up. Django's active settings are
    unaffected -- they were materialised at startup and hold no reference to
    these fresh module objects.
    """
    for name in SETTINGS_MODULES:
        sys.modules.pop(name, None)
    yield
    for name in SETTINGS_MODULES:
        sys.modules.pop(name, None)


def _boot_probe_env() -> dict[str, str]:
    """Return an environment in which only the editable install can resolve `src/`.

    `PYTHONSAFEPATH` keeps the interpreter from prepending the working directory
    to `sys.path` for `-c`, and `PYTHONPATH` is dropped outright, so the child
    resolves `config` exactly the way a deployed process does.
    `DJANGO_SETTINGS_MODULE` goes too: pytest-django has set it to
    `config.settings.test` in this process, and the child is booting
    `config.settings.local` -- the module `manage.py` defaults to.

    `COMPONENT_OIDC_ISSUER` is declared rather than inherited, so what boots is a
    component with an issuer *configured*: `config/settings/local.py` fills an
    empty issuer with a fallback of its own, and a probe that left it unset would
    be asserting that nothing fetched a value nothing had.

    The telemetry variables in `_SCRUBBED_TELEMETRY_VARS` are dropped so the
    ambient state under test is the documented one -- no endpoint configured --
    rather than whatever the developer's shell happens to export. Two of them
    would otherwise decide the verdict: `OTEL_SDK_DISABLED` installs no provider
    and would fail the tracer-provider assertion with a diagnosis about
    `configure_observability()` that is simply wrong, and `OTEL_TRACES_EXPORTER`
    set to `otlp` takes the opt-in this module documents as the one supported way
    to make boot reach the network -- the documented exception, not a regression
    for the child to discover. Everything else is inherited, `COMPONENT_RUNTIME`
    included, so what boots is what a developer's `pixi run manage` boots.

    Returns:
        A copy of the current environment with those adjustments.

    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("DJANGO_SETTINGS_MODULE", None)
    for name in _SCRUBBED_TELEMETRY_VARS:
        env.pop(name, None)
    env["PYTHONSAFEPATH"] = "1"
    env["COMPONENT_OIDC_ISSUER"] = PROBE_ISSUER
    return env


def test_the_guard_refuses_a_connection_rather_than_making_one(no_network: None) -> None:
    """The fixture every other case here depends on, asserted rather than assumed.

    Every other assertion in this module is negative -- "no exception was
    raised" -- and a guard that silently failed to install would make all of
    them pass without proving anything. So the guard is exercised directly, at
    every chokepoint it installs -- the two connect methods, `create_connection`
    and both resolver entry points -- and the refusal is required to name the
    address it refused.
    """
    with pytest.raises(NetworkAccessAttempted) as refused:
        socket.create_connection(DISCARD_ADDRESS)
    assert repr(DISCARD_ADDRESS) in str(refused.value), "the refusal does not say where the caller was headed"

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkAccessAttempted):
            probe.connect(DISCARD_ADDRESS)
        with pytest.raises(NetworkAccessAttempted):
            probe.connect_ex(DISCARD_ADDRESS)
    finally:
        probe.close()

    with pytest.raises(NetworkAccessAttempted):
        socket.getaddrinfo(RESOLVER_PROBE_HOST, 443)
    with pytest.raises(NetworkAccessAttempted):
        socket.gethostbyname(RESOLVER_PROBE_HOST)


def test_the_guard_restores_the_socket_layer_exactly() -> None:
    """The guard is process-wide, so leaving anything behind would poison the rest of the run.

    Restoration is asserted in both directions, because the interesting one is
    the absence: `connect` and `connect_ex` are *inherited* by `socket.socket`
    rather than defined on it, so a teardown that wrote the saved value back
    would bind them as own attributes of the subclass and leave the class in a
    state it was never in. `monkeypatch.setattr` is exactly that teardown, which
    is why `tests/conftest.py` does the bookkeeping by hand and why this case
    checks `socket.socket.__dict__` membership rather than `getattr`.
    """
    owned_before = {name: socket.socket.__dict__.get(name, _ABSENT) for name in _GUARDED_SOCKET_METHODS}
    functions_before = {name: getattr(socket, name) for name in _GUARDED_SOCKET_FUNCTIONS}
    assert any(original is _ABSENT for original in owned_before.values()), (
        "no guarded method is inherited any more, so this case no longer checks what it was written for"
    )

    with _network_guard():
        assert all(socket.socket.__dict__[name] is not owned_before[name] for name in _GUARDED_SOCKET_METHODS)
        assert all(getattr(socket, name) is not functions_before[name] for name in _GUARDED_SOCKET_FUNCTIONS)

    owned_after = {name: socket.socket.__dict__.get(name, _ABSENT) for name in _GUARDED_SOCKET_METHODS}
    assert owned_after == owned_before, "the socket class did not come back as it was"
    for name, original in functions_before.items():
        assert getattr(socket, name) is original, f"socket.{name} was not restored to the function it replaced"


def test_settings_import_performs_no_network_call(
    no_network: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #1, first half: reading the settings is environment reads and computation.

    The issuer is set to a real-looking URL for this case, so the assertion is
    about a *configured* component rather than about an empty string that could
    never have been fetched. AD-31 is what makes it hold: the provider is
    configured from `SOCIALACCOUNT_PROVIDERS`, populated from the environment,
    and its discovery document is fetched by allauth's request-time
    `openid_config` property -- so the issuer arrives here as a string and stays
    one.
    """
    monkeypatch.delenv("COMPONENT_OIDC_JWKS_URL", raising=False)
    monkeypatch.setenv("COMPONENT_OIDC_ISSUER", PROBE_ISSUER)

    base = importlib.import_module(BASE)
    local = importlib.import_module(LOCAL)

    assert base.OIDC_ISSUER == PROBE_ISSUER
    provider_app = base.SOCIALACCOUNT_PROVIDERS[OIDC_PROVIDER_KEY]["APPS"][0]
    assert provider_app["settings"]["server_url"] == PROBE_ISSUER, "the provider is configured from something else"
    assert local.OIDC_ISSUER == PROBE_ISSUER, "the local module did not inherit the configured issuer"

    # The fresh-clone case, re-imported under the same guard. With no issuer
    # declared, `config/settings/local.py` derives the development JWKS location
    # from `DEV_KEY_DIR` -- a computation near the end of the module, so reading
    # the derived value back is what says the import ran to its end rather than
    # merely started. The derivation is skipped above precisely because an issuer
    # was configured there, which is why it takes a second import to reach.
    for name in SETTINGS_MODULES:
        sys.modules.pop(name, None)
    monkeypatch.delenv("COMPONENT_OIDC_ISSUER")
    fresh = importlib.import_module(LOCAL)

    assert (keys.DEV_KEY_DIR / JWKS_FILENAME).as_uri() == fresh.OIDC_JWKS_URL, (
        "the local settings did not derive the development JWKS location"
    )


def test_boot_performs_no_network_call(tmp_path: Path) -> None:
    """AC #1 and AC #2: the whole start path completes with every socket refused.

    The assertion this story exists for. A fresh interpreter installs the guard,
    then does what `manage.py` does -- `configure_observability()`, then
    `django.setup()` under `config.settings.local` -- and writes back what boot
    left behind. Anything reaching the network raises `NetworkAccessAttempted`
    out of the child, which arrives here as a non-zero return code with the
    traceback naming the address.

    `KEY_STORE` is asserted here rather than in process on purpose: it is a
    module-level singleton (`jwks.py`) that the integration suite fills and
    resets, so "it holds no keys" is a statement about test ordering anywhere
    else and a statement about boot only here.

    AC #2's second clause -- that retrieval happens on the first Bearer request
    that needs it -- is Story 2.7's, asserted at
    `tests/integration/authorization/test_bearer_authentication.py`
    (`test_the_first_bearer_request_is_what_fetches_the_jwks`). It is traced to,
    not re-implemented.
    """
    report_path = tmp_path / "boot-report.json"

    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", _BOOT_PROBE_SOURCE, str(report_path)],
            cwd=str(REPO_ROOT),
            env=_boot_probe_env(),
            capture_output=True,
            text=True,
            timeout=BOOT_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as hung:
        pytest.fail(
            f"boot did not finish within {BOOT_PROBE_TIMEOUT_SECONDS} seconds, so nothing below was asserted"
            f"\nstdout: {hung.stdout!r}\nstderr: {hung.stderr!r}"
        )

    assert result.returncode == 0, result.stderr
    assert report_path.is_file(), f"the child exited cleanly but wrote no report:\n{result.stdout}\n{result.stderr}"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # The guard was live on both sides of the boot it was asked to watch, and no
    # worker thread swallowed a refusal the exit code could never have carried.
    assert report["armed_before_boot"] is True, "the child booted without the socket guard installed"
    assert report["armed_after_boot"] is True, "something restored the socket layer during boot"
    assert report["thread_refusals"] == [], "a background thread reached the network during boot"

    # Boot completed, rather than the assertions above holding because nothing ran.
    assert report["settings_module"] == LOCAL
    assert report["apps_ready"] is True, "django.setup() did not finish loading the app registry"
    assert report["oidc_provider_app_installed"] is True, "the OIDC provider app is not installed"
    assert report["tracer_provider_installed"] is True, "importing config installed no tracer provider"

    # A component with an issuer *configured* performed no discovery: the value
    # reached settings and the provider block, and stayed a string in both.
    assert report["oidc_issuer"] == PROBE_ISSUER, "the settings did not materialise the configured issuer"
    assert report["oidc_provider_server_url"] == PROBE_ISSUER, "the provider was configured from something else"

    # AC #2, first half: boot triggered no JWKS retrieval and moved no seam.
    assert report["jwks_cached_kids"] == [], "boot left keys in the store, so something fetched a JWK Set"
    assert report["jwks_fetched_at"] == NEVER_FETCHED, "boot recorded a fetch"
    assert report["jwks_fetch_is_the_module_default"] is True, "the fetch seam was replaced, so the store was primed"


def test_django_setup_performs_no_oidc_discovery(no_network: None) -> None:
    """AC #1, second half: the one piece of boot-time allauth work, re-run under the guard.

    `SocialAccountConfig.ready()` is Django checks plus `providers.registry.load()`,
    and `load()` is guarded by `registry.loaded`, which is already `True` by the
    time any test runs. Clearing the flag and calling `load()` again is what makes
    boot-time provider configuration observable; re-loading is safe because the
    registry's provider map is only ever added to.

    The second assertion is AD-31 restated as a value: the provider's
    `server_url` is the issuer the environment supplied, one read and no fetch.
    Discovery is allauth's request-time `openid_config` property and is reached
    by a sign-in, never by configuration.
    """
    registry = providers.registry
    assert registry.loaded is True, "the provider registry was not loaded by Django setup"

    registry.loaded = False
    try:
        registry.load()
    finally:
        registry.loaded = True

    assert registry.get_class(OIDC_PROVIDER_KEY) is not None, "the OIDC provider is not registered"
    provider_app = settings.SOCIALACCOUNT_PROVIDERS[OIDC_PROVIDER_KEY]["APPS"][0]
    assert provider_app["settings"]["server_url"] == settings.OIDC_ISSUER


def test_keypair_generation_performs_no_network_call(
    no_network: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #3, first half: generating the development keypair is computation.

    `DEV_KEY_DIR` is relocated into `tmp_path` the way
    `tests/unit/test_local_dev_keys.py` relocates it, so the case owns the
    directory it asserts about. `COMPONENT_RUNTIME` is set explicitly even
    though the `dev` pixi environment already exports it: the refusal in
    `ensure_keypair` must be satisfied by this test's declaration rather than by
    an ambient one.

    Called twice, because the function has two branches and only the first
    generates: the second loads the PEM already on disk, and a reuse that
    reached the network would go unobserved if the guard only ever saw the
    generation.

    If this ever fails, something is fetching entropy or a key over a socket,
    and the fix is in that code -- never a narrower guard.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "local")
    key_dir = tmp_path / ".local-dev-keys"
    monkeypatch.setattr(keys, "DEV_KEY_DIR", key_dir)

    keypair = ensure_keypair()
    reused = ensure_keypair()

    assert keypair.private_key_path == key_dir / PRIVATE_KEY_FILENAME
    assert keypair.private_key_path.is_file(), "no private key was written"

    jwks_path = key_dir / JWKS_FILENAME
    assert jwks_path.is_file(), "no JWK Set document was written"
    document = json.loads(jwks_path.read_text(encoding="utf-8"))
    assert [key["kid"] for key in document["keys"]] == [keypair.kid], (
        "the JWK Set on disk does not describe the key that was generated"
    )
    assert reused.kid == keypair.kid, "the second call generated a new key rather than loading the one on disk"
