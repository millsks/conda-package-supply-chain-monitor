"""Every stage-2 condition, through a served request path -- not only `manage.py`.

FR-16's third acceptance condition. Stage 2 is owned by an `AppConfig.ready()`
because Django's own system-check framework does not run under a gunicorn or
uvicorn serving process, which is the only path that matters in deployment -- so
a suite that exercised the conditions only through management commands would
prove the contract on the one path it was not written for.

**One case per condition, and the probe runs once.** The probe boots the way a
server does -- `config/asgi.py` with no `DJANGO_SETTINGS_MODULE` set, so its own
`os.environ.setdefault` selects the module and `get_asgi_application()` runs
`django.setup()` -- drives one request through the callable that import produced,
and only then evaluates each stage-2 condition from inside that same process.
Story 4.3 wrote it as a single case at the end of
`test_stage_two_database_conditions.py`; it is here now, split per condition, so
that a state failing to refuse names itself. The boot is module-scoped: four
assertions about one process are four claims about one process, and booting four
times would not make them stronger.

**The paired management-command control.** Each condition is then driven through
`manage.py check` in a fresh interpreter, which is the other invocation point, so
"it fires under management commands as well" is proven rather than assumed. The
refusal arrives during `django.setup()` -- which is what `check`, `migrate` and
every other command performs before running -- so the command never executes, and
that is the correct behaviour rather than a quirk of `check`.

**AD-13's exemption is asserted, not treated as a gap.** The two stage-2
conditions that read a database gate on `is_serving_process()`, and process type
fails *open*: `COMPONENT_PROCESS` absent means not a serving process. That is
what keeps `manage.py migrate` -- the single action that clears the unapplied-
migrations state -- from being forbidden by the state it clears, which would
deadlock the FR-41 release stage (AD-22). Both halves are asserted here, and for
*both* database-backed conditions: each state refuses with `COMPONENT_PROCESS=web`
and is accepted without it, so the exemption is shown to be about process type
rather than about the command or about one condition. Reaching condition 5's
stage-2 half at all takes a migrated database, so its pair of cases run against
one a child of their own migrated first.

**CG-3 for the two database states.** `tests/unit/startup/test_no_softening.py`
asserts that a refusal raises rather than warning or logging, for the twelve
states reachable without a connection. The two that need one are asserted here,
by the same measurements, so the CG-3 claim covers all fourteen. The cases are
parametrized straight off `DELEGATED_TO_THE_INTEGRATION_SUITE`, which is what
makes that sentence true by measurement: a state delegated here with no case
fails here.

Nothing is left behind. The probes write into `tmp_path` and point the default
alias at a throwaway sqlite file there; the in-process cases delete a `Group`
inside `django_db`'s transaction, which the rollback restores.

`src/config/asgi.py` is in the coverage `omit` list, which is a closed
carrier-declared surface. These tests assert behaviour reached *through* that
module, so they neither require removing the entry nor add one.

`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

import json
import subprocess
import sys
import warnings
from typing import TYPE_CHECKING
from typing import Final

import pytest
import structlog
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from config.locality import LOCAL
from config.locality import PROCESS_ENV_VAR
from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup import run_stage_two
from tests.conftest import deployed_url_patterns
from tests.conftest import subprocess_env
from tests.conftest import temporary_root_urlconf
from tests.conftest import valid_deployed_settings_namespace
from tests.integration.startup.conftest import BOOT_PROBE_TIMEOUT_SECONDS
from tests.integration.startup.conftest import REPO_ROOT
from tests.unit.startup.forbidden_states import DELEGATED_TO_THE_INTEGRATION_SUITE

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping
    from pathlib import Path

#: A serving process type. Any member of `config.locality.SERVING_PROCESSES`
#: does; `web` is the one that serves HTTP and therefore the one the conditions
#: exist for.
SERVING_PROCESS: Final = "web"

#: The management-command probe's spelling of "declare no process type at all",
#: which is the state a release-stage `manage.py migrate` runs in.
NO_PROCESS_DECLARED: Final = ""

#: The probe's spelling of "configure no forbidden state", used for the control
#: run that has to complete cleanly.
NO_FAULT: Final = "none"

#: The designated groups the management-command probe's second child asks for.
#: Deliberately not the names `config/settings/local.py` defaults to, because the
#: first child migrates under those defaults and the data migration provisions
#: them -- so a contract naming these two is one whose groups are genuinely
#: absent from a database that is otherwise fully migrated. That is the only
#: shape in which condition 5's stage-2 half is reachable at all: condition 7
#: evaluates first and would refuse a never-migrated database before this one was
#: ever consulted.
ABSENT_STAFF_GROUP: Final = "probe-staff"
ABSENT_SUPERUSER_GROUP: Final = "probe-superuser"

#: The claims-contract environment the second child runs with. All four names,
#: because `_refuse_missing_designated_groups` reads the contract rather than
#: asking whether it is configured.
ABSENT_GROUP_CONTRACT: Final[dict[str, str]] = {
    "COMPONENT_IDENTITY_CLAIM": "sub",
    "COMPONENT_GROUP_CLAIM": "groups",
    "COMPONENT_STAFF_GROUP": ABSENT_STAFF_GROUP,
    "COMPONENT_SUPERUSER_GROUP": ABSENT_SUPERUSER_GROUP,
}

#: The exception type the whole contract promises, asserted by identity rather
#: than by `isinstance` -- Django ships `ImproperlyConfigured` subclasses, and a
#: condition raising one would say something narrower than the contract does.
REFUSAL_TYPE: Final = ImproperlyConfigured


# Boot this component the way a server does, serve one request through the
# callable that produced, and only then evaluate every stage-2 condition from
# inside that same process. Moved here unchanged from Story 4.3's
# `test_stage_two_database_conditions.py`, where it was one case over four
# conditions; FR-16 asks for one case per condition, and the report it writes is
# what the four cases below read.
#
# A string on purpose: nothing here executes in the test process, so the
# deferred imports and the `print`-free file handoff need no ruff exemptions.
_CONDITIONS_PROBE_SOURCE = '''
"""Serve one request through the ASGI callable, then exercise every stage-2 condition."""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import ModuleType

# The import that boots: `config/asgi.py` sets DJANGO_SETTINGS_MODULE by
# setdefault and calls `get_asgi_application()`, which runs `django.setup()` and
# with it every AppConfig.ready().
from config.asgi import application

PROBE_PATH = "/__stage-two-conditions-probe__/"
SERVE_TIMEOUT_SECONDS = 60.0

SCOPE = {
    "type": "http",
    "asgi": {"version": "3.0", "spec_version": "2.3"},
    "http_version": "1.1",
    "method": "GET",
    "scheme": "http",
    "path": PROBE_PATH,
    "raw_path": PROBE_PATH.encode("ascii"),
    "query_string": b"",
    "root_path": "",
    "headers": [(b"host", b"localhost")],
    "client": ("127.0.0.1", 54321),
    "server": ("localhost", 80),
}


async def _serve_one_request():
    """Drive one HTTP request through the ASGI callable and collect what it sent."""
    sent = []
    body_delivered = False
    never = asyncio.Event()

    async def receive():
        nonlocal body_delivered
        if not body_delivered:
            body_delivered = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await never.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await asyncio.wait_for(application(SCOPE, receive, send), SERVE_TIMEOUT_SECONDS)
    return sent


messages = asyncio.run(_serve_one_request())

# Everything from here runs in a process that has served a request. The locality
# declaration is dropped and a serving process declared, which is the state every
# stage-2 condition evaluates in.
os.environ.pop("COMPONENT_RUNTIME", None)
os.environ["COMPONENT_PROCESS"] = "web"

from contextlib import contextmanager

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connections
from django.test import override_settings
from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from config.authorization.claims import ClaimsContract
from config.local_dev import views as local_dev_views
from config.startup import run_stage_two
from django_service.users.provisioning import provision_designated_groups

SCRATCH = Path(sys.argv[2])

UNCONFIGURED_CONTRACT = ClaimsContract("", "", "", "")
CONFIGURED_CONTRACT = ClaimsContract(
    identity_key_claim="sub",
    group_claim="groups",
    staff_group="probe-staff",
    superuser_group="probe-superuser",
)


def install_urlconf(name, patterns):
    """Register a throwaway root URL configuration and return its dotted name."""
    module = ModuleType(name)
    module.urlpatterns = patterns
    sys.modules[name] = module
    return name


CLEAN = install_urlconf("probe_clean_urlconf", [path("admin/", admin.site.urls)])
TOKEN = install_urlconf(
    "probe_token_urlconf",
    [path("api/auth-token/", obtain_auth_token, name="obtain_auth_token")],
)
LOCAL = install_urlconf(
    "probe_local_sign_in_urlconf",
    [path("accounts/local-sign-in/", local_dev_views.persona_signin, name="local_persona_login")],
)


@contextmanager
def scratch_database():
    """Point the default alias at a throwaway sqlite file under the scratch directory.

    The probe boots on the local settings module, whose default database is a
    file in the repository root. Overriding it before anything connects is what
    keeps this test from creating one.
    """
    # The engine is named rather than inherited from the live configuration. A
    # spread of `settings.DATABASES["default"]` carries whatever engine the boot
    # selected, and pairing a postgres engine with this sqlite *filename* fails
    # on PostgreSQL's 63-character NAME limit instead of on anything this probe
    # is about.
    databases = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(SCRATCH / "probe.sqlite3"),
        },
    }
    with override_settings(DATABASES=databases):
        restored = connections.__dict__.get("settings")
        # Serving the request above materialized the default connection wrapper
        # from the settings that were live then, and replacing the handler's
        # mapping does not reconfigure a wrapper that already exists. Without
        # dropping it first, every query below would go to the local settings
        # module's own database file in the repository root -- which is the one
        # thing this probe must not touch.
        previous = connections["default"]
        previous.close()
        del connections["default"]
        connections.settings = connections.configure_settings(dict(databases))
        try:
            yield
        finally:
            connections["default"].close()
            del connections["default"]
            connections.__dict__.pop("settings", None)
            if restored is not None:
                connections.settings = restored
            connections["default"] = previous


def outcome(**overrides):
    """Run stage 2 under the given setting overrides and report what it did."""
    try:
        with override_settings(**overrides):
            run_stage_two()
    except ImproperlyConfigured as refusal:
        return str(refusal)
    return None


report = {
    "response_statuses": [m["status"] for m in messages if m["type"] == "http.response.start"],
    "credential_minting_route": outcome(ROOT_URLCONF=TOKEN),
    "local_sign_in_route": outcome(ROOT_URLCONF=LOCAL),
}

with scratch_database():
    report["database_in_use"] = connections["default"].settings_dict["NAME"]

    # Nothing has been migrated into the scratch database yet, so every
    # migration is pending on it.
    os.environ.pop("COMPONENT_PROCESS", None)
    report["migrations_pending_off_a_serving_process"] = outcome(ROOT_URLCONF=CLEAN)
    os.environ["COMPONENT_PROCESS"] = "web"
    report["unapplied_migrations"] = outcome(ROOT_URLCONF=CLEAN)

    # Migrated with an unconfigured contract, so the data migration provisions
    # nothing and the designated groups are genuinely absent afterwards.
    with override_settings(CLAIMS_CONTRACT=UNCONFIGURED_CONTRACT):
        call_command("migrate", verbosity=0)

    report["missing_designated_groups"] = outcome(
        ROOT_URLCONF=CLEAN,
        CLAIMS_CONTRACT=CONFIGURED_CONTRACT,
    )

    with override_settings(CLAIMS_CONTRACT=CONFIGURED_CONTRACT):
        provision_designated_groups()
        report["everything_satisfied"] = outcome(
            ROOT_URLCONF=CLEAN,
            CLAIMS_CONTRACT=CONFIGURED_CONTRACT,
        )

Path(sys.argv[1]).write_text(json.dumps(report), encoding="utf-8")
'''


# The management-command control, in a fresh interpreter.
#
# **The settings module is a real file, composed by Django's own loader.** The
# forbidden states stage 2 evaluates are settings -- `ROOT_URLCONF` and
# `DATABASES` -- and stage 2 reads them during `django.setup()`, before any code
# in the child could override them. A settings module synthesized in memory does
# not work here either: `config/__init__.py` imports `config.celery_app`, whose
# `os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")` runs
# on the *first* import of anything under `config` and configures
# `django.conf.settings` from the local module before a synthesized one could be
# registered. So the child is handed a directory holding two ordinary modules and
# imports them the way Django imports any settings module.
#
# The generated settings module composes `config.settings.local` under the
# declared local runtime -- stage 1's FR-12 escape route refuses that module
# outright on a deployed run, so it could not be composed at all otherwise -- and
# drops the declaration immediately afterwards. Everything from that line on,
# stage 2 included, evaluates deployed.
#
# **This child is a stage-2 probe and nothing else, and that is a limitation
# rather than a subtlety.** Stage 1 is called as the last statement of each leaf
# settings module; `local.py` calls it while the runtime is still declared local,
# so it returns before evaluating anything, and the generated module below makes
# no call of its own. So the namespace these cases run against never has a single
# stage-1 condition evaluated over it -- and it would not survive one, because the
# throwaway database it needs is sqlite and condition 1 refuses sqlite in a
# deployed component. `test_the_probe_never_has_stage_one_evaluated_over_it`
# measures exactly that rather than leaving it as prose: the child reports what
# stage 1 *would* have said, and the case asserts it is a refusal. Building the
# child on a genuinely deployed-shaped namespace instead would mean a real
# PostgreSQL for every run of this file, which `pixi run ci` does not have.
_PROBE_SETTINGS_TEMPLATE: Final = '''\
"""A deployed component's settings, carrying at most one stage-2 forbidden state.

Generated by tests/integration/startup/test_stage_two_served_path.py. Composed
from the local settings module because that is the only fully populated one a
test can reach: `config.settings.production` demands real deployment secrets and
a real database from the environment.

**Stage 1 is never evaluated over this namespace.** `local.py` runs it while the
runtime is still declared local, and nothing here calls it again -- so what the
child exercises is stage 2 in a deployed process, and nothing it reports says
anything about stage 1. The generating module records why, and asserts it.
"""

from config.settings.local import *  # noqa: F401, F403

import os

# Composed local; deployed from here on, which is the state stage 2 evaluates in.
os.environ.pop("COMPONENT_RUNTIME", None)

ROOT_URLCONF = "probe_urlconf"

# The development tooling `local.py` installs under DJANGO_DEBUG_APPS is dropped:
# a deployed component does not install it, and django-debug-toolbar in
# particular makes the migrations condition report a state `manage.py migrate`
# cannot clear. Its own AppConfig.ready() hides its migrations from the migrate
# command unless the database store is configured, while anything reading
# migration state from inside an *earlier* AppConfig.ready() -- which is where
# stage 2 runs -- still sees them. So a child that kept it would report
# debug_toolbar.0001_initial pending on a database that had just been fully
# migrated.
INSTALLED_APPS = [app for app in INSTALLED_APPS if app not in {{"debug_toolbar", "django_extensions"}}]  # noqa: F405
MIDDLEWARE = [entry for entry in MIDDLEWARE if not entry.startswith("debug_toolbar.")]  # noqa: F405

# A throwaway database. For the unapplied-migrations condition an unmigrated one
# is the fault itself; the designated-group case migrates it in a child of its
# own first, so that condition 7 passes and condition 5's stage-2 half is the one
# that fires.
DATABASES = {{
    "default": {{
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": {database!r},
    }},
}}
'''

#: The root URL configuration each case installs, keyed by the forbidden state it
#: constructs. Imported by Django at first resolution -- which is inside the
#: stage-2 walk, long after `django.setup()` populated the app registry -- so a
#: view whose module defines a model is importable here and would not have been
#: in a configuration built before setup.
_PROBE_URLCONFS: Final[dict[str, str]] = {
    NO_FAULT: '''\
"""The admin alone: a configuration neither URLconf condition objects to."""

from django.contrib import admin
from django.urls import path

urlpatterns = [path("admin/", admin.site.urls)]
''',
    "credential-minting-route": '''\
"""Condition 6, state a: DRF's token-minting endpoint, mounted."""

from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [path("api/auth-token/", obtain_auth_token, name="obtain_auth_token")]
''',
    "local-sign-in-route": '''\
"""Condition 6, state b: the local persona sign-in view, mounted."""

from django.urls import path

from config.local_dev import views

urlpatterns = [path("accounts/local-sign-in/", views.persona_signin, name="local_persona_login")]
''',
}

# Run one management command and report whether the refusal contract stopped it.
#
# The refusal arrives out of `django.setup()`, which `ManagementUtility.execute`
# performs before dispatching to any command -- so the command never runs, and
# that is a property of every management command rather than a quirk of `check`.
#
# A string on purpose: nothing here executes in the test process, so the
# `print`-free file handoff needs no ruff exemptions.
_MANAGEMENT_COMMAND_PROBE_SOURCE = '''
"""Run one management command in a deployed component and report what it met."""

import json
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management import execute_from_command_line

COMMAND = sys.argv[1]
REPORT = Path(sys.argv[2])

report = {"command": COMMAND, "refusal": None, "refusal_type": None}
try:
    execute_from_command_line(["manage.py", COMMAND] + sys.argv[3:])
except ImproperlyConfigured as refusal:
    report["refusal"] = str(refusal)
    report["refusal_type"] = type(refusal).__name__

# What stage 1 would have said about this namespace, had anything asked it. The
# generated settings module never calls it -- see the template's docstring -- so
# this is the measurement that keeps that limitation stated rather than implied:
# the caller asserts a refusal here, which is the proof that the run above
# exercised stage 2 alone.
from django.conf import settings as _settings  # noqa: E402

from config.startup import run_stage_one as _run_stage_one  # noqa: E402

try:
    _run_stage_one(sys.modules[_settings.SETTINGS_MODULE])
except ImproperlyConfigured as refusal:
    report["stage_one_over_this_namespace"] = str(refusal)
else:
    report["stage_one_over_this_namespace"] = None

REPORT.write_text(json.dumps(report), encoding="utf-8")
'''


@pytest.fixture(scope="module")
def served_path_report(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, object]:
    """Boot through `config.asgi`, serve one request, and evaluate every stage-2 condition.

    Module-scoped: one boot, four claims about that one process.

    Args:
        tmp_path_factory: pytest's session-scoped temporary directory factory.
            Everything the probe touches lives under the directory it hands out.

    Returns:
        The probe's report, keyed by condition.

    """
    root = tmp_path_factory.mktemp("stage-two-served-path")
    report_path = root / "stage-two-conditions.json"
    scratch = root / "scratch"
    scratch.mkdir()

    # Boot has to happen *local*: `config/asgi.py` selects `config.settings.local`,
    # and stage 1's FR-12 escape route refuses that module the moment the run is
    # deployed -- so a deployed declaration would abort the child during
    # `django.setup()` and every assertion below would be about a component that
    # never started. The probe flips to deployed and serving itself, after it has
    # served, which is the state these conditions evaluate in.
    env = subprocess_env()
    env[RUNTIME_ENV_VAR] = LOCAL
    env.pop(PROCESS_ENV_VAR, None)

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _CONDITIONS_PROBE_SOURCE, str(report_path), str(scratch)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=BOOT_PROBE_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0, (
        f"the stage-two conditions probe exited {completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )

    report: dict[str, object] = json.loads(report_path.read_text(encoding="utf-8"))
    # Recorded by the fixture rather than by the probe, so that the case asserting
    # what the probe migrated compares against the directory this process handed
    # it -- the probe's own scratch directory, not the session temporary root that
    # every other test's files also live under.
    report["scratch_directory"] = str(scratch)
    return report


def _write_probe_modules(directory: Path, *, fault: str) -> None:
    """Generate the settings module and root URL configuration a probe child imports.

    Args:
        directory: The child's working directory, which is the import root for
            the two modules written into it.
        fault: The forbidden state the URL configuration constructs, or
            `NO_FAULT` for a configuration neither URLconf condition objects to.

    """
    (directory / "probe_settings.py").write_text(
        _PROBE_SETTINGS_TEMPLATE.format(database=str(directory / "probe.sqlite3")),
        encoding="utf-8",
    )
    (directory / "probe_urlconf.py").write_text(_PROBE_URLCONFS[fault], encoding="utf-8")


def _run_management_command(
    directory: Path,
    command: str,
    *,
    process: str,
    claims: Mapping[str, str] | None = None,
    arguments: tuple[str, ...] = (),
) -> Mapping[str, object]:
    """Run one management command in a deployed child and report what it met.

    The child is launched with `directory` as its working directory and
    `PYTHONSAFEPATH` cleared -- which is what puts that directory on the child's
    `sys.path` and nothing else. `config` and `django_service` still resolve
    through the editable install exactly as they do in a deployed process, and the
    repository root is not on the path at all, so this is narrower than the
    environment the other probes run in rather than wider. No Python file in this
    repository declares an import root either way (AD-7): the directory is a
    generated fixture the child imports its own settings from.

    Args:
        directory: The directory holding the generated modules, the report and
            the scratch database.
        command: The management command to run.
        process: The `COMPONENT_PROCESS` value to declare, or `NO_PROCESS_DECLARED`
            to leave it undeclared -- which is what AD-13 makes *not a serving
            process*.
        claims: The claims-contract variables to declare, if any. Absent, the
            child composes `config/settings/local.py`'s own defaults.
        arguments: Further arguments for the command itself.

    Returns:
        The child's report: the command it ran, the refusal it met if any, and
        what stage 1 would have said about the namespace it ran against.

    """
    report_path = directory / f"management-command-{command}-{process or 'no-process'}.json"

    env = subprocess_env()
    env[RUNTIME_ENV_VAR] = LOCAL
    env["DJANGO_SETTINGS_MODULE"] = "probe_settings"
    # The child's own working directory is the import root for its two generated
    # modules, so `PYTHONSAFEPATH` -- which is what keeps the interpreter from
    # prepending it -- has to go for this probe alone.
    env.pop("PYTHONSAFEPATH", None)
    env.update(claims or {})
    if process:
        env[PROCESS_ENV_VAR] = process
    else:
        env.pop(PROCESS_ENV_VAR, None)

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _MANAGEMENT_COMMAND_PROBE_SOURCE, command, str(report_path), *arguments],
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=BOOT_PROBE_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0, (
        f"the management-command probe running {command!r} exited {completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )

    report: dict[str, object] = json.loads(report_path.read_text(encoding="utf-8"))
    return report


def _management_command_outcome(tmp_path: Path, *, fault: str, process: str) -> Mapping[str, object]:
    """Run `manage.py check` in a deployed child carrying one fault, and report the result.

    Args:
        tmp_path: The directory the generated modules, the report and the scratch
            database live in.
        fault: The forbidden state to configure, or `NO_FAULT` for a clean run.
        process: The `COMPONENT_PROCESS` value to declare, or `NO_PROCESS_DECLARED`
            to leave it undeclared.

    Returns:
        The child's report.

    """
    _write_probe_modules(tmp_path, fault=fault)
    return _run_management_command(tmp_path, "check", process=process)


@pytest.fixture(scope="module")
def migrated_probe_directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A probe directory whose throwaway database is fully migrated and has no designated groups.

    Two children, because one cannot do it: `django.setup()` is idempotent, so a
    second `execute_from_command_line` in the same process never re-enters
    `AppConfig.ready()` and never re-evaluates stage 2. So the first child applies
    the migrations with no process type declared -- AD-13's exemption is what lets
    it, and is the reason `manage.py migrate` can clear the state it would
    otherwise be refused for -- and the cases run their own `check` children
    against the database it left behind.

    The groups the migration provisions are `config/settings/local.py`'s defaults.
    The cases then run under `ABSENT_GROUP_CONTRACT`, which designates two other
    names, so condition 5's stage-2 half meets a fully migrated database in which
    its own designated groups are genuinely absent. That is the only arrangement
    that reaches it: condition 7 runs first and refuses a never-migrated database
    before condition 5 is consulted at all.

    Args:
        tmp_path_factory: pytest's session-scoped temporary directory factory.

    Returns:
        The directory, ready for a `check` child to run in.

    """
    directory = tmp_path_factory.mktemp("management-command-designated-groups")
    _write_probe_modules(directory, fault=NO_FAULT)

    prepared = _run_management_command(
        directory,
        "migrate",
        process=NO_PROCESS_DECLARED,
        arguments=("--verbosity", "0"),
    )

    assert prepared["refusal"] is None, (
        f"the probe database could not be migrated, so nothing below is about a migrated one: {prepared['refusal']}"
    )
    return directory


class TestTheProbeReallyServed:
    """The two claims every case in the next class rests on."""

    def test_the_probe_served_a_request_before_evaluating_anything(
        self,
        served_path_report: Mapping[str, object],
    ) -> None:
        """Without this, "on a served path" is an assertion about nothing.

        The conditions would refuse just as readily in a process that imported
        `config.asgi` and stopped, and the whole point of AC #3 is the process
        that has served traffic.
        """
        assert served_path_report["response_statuses"], (
            "the probe never served a request, so nothing below is about serving"
        )

    def test_the_probe_left_the_tree_as_it_found_it(
        self,
        served_path_report: Mapping[str, object],
    ) -> None:
        """The probe migrates a database; it must be its own throwaway one.

        The local settings module's default database is a file in the repository
        root, and a probe that migrated *that* would leave an artifact behind on
        every developer's clone.

        Compared against the probe's **own scratch directory**, not against the
        session temporary root. The root is where every test's files live, so a
        probe that migrated some other test's database would satisfy the looser
        comparison while having done exactly the thing this case exists to catch.
        """
        scratch = str(served_path_report["scratch_directory"])

        assert str(served_path_report["database_in_use"]).startswith(scratch), (
            "the probe migrated something other than its own scratch database, "
            f"so it did not leave the tree as found: {served_path_report['database_in_use']}"
        )


class TestEveryStageTwoConditionFiresOnTheServedPath:
    """AC #3: one case per stage-2 condition, all four in a process that has served."""

    @pytest.mark.forbidden_state("credential-minting-route")
    def test_the_credential_minting_route_refuses(self, served_path_report: Mapping[str, object]) -> None:
        """Condition 6, state a, reached through the served path."""
        refusal = served_path_report["credential_minting_route"]

        assert refusal is not None, "the token-minting route was accepted in a process that had served"
        assert "rest_framework.authtoken" in str(refusal)

    @pytest.mark.forbidden_state("local-sign-in-route")
    def test_the_local_sign_in_route_refuses(self, served_path_report: Mapping[str, object]) -> None:
        """Condition 6, state b, reached through the served path."""
        refusal = served_path_report["local_sign_in_route"]

        assert refusal is not None, "the local sign-in route was accepted in a process that had served"
        assert "config.local_dev" in str(refusal)

    @pytest.mark.forbidden_state("unapplied-migrations")
    def test_unapplied_migrations_refuse(self, served_path_report: Mapping[str, object]) -> None:
        """Condition 7, against a database in the state a never-migrated one is in."""
        refusal = served_path_report["unapplied_migrations"]

        assert refusal is not None, "a serving process started against a schema with migrations pending"
        assert "unapplied migrations" in str(refusal)

    @pytest.mark.forbidden_state("designated-group-absent")
    def test_an_absent_designated_group_refuses(self, served_path_report: Mapping[str, object]) -> None:
        """Condition 5's stage-2 half (AD-27), after the probe migrated with an unconfigured contract."""
        refusal = served_path_report["missing_designated_groups"]

        assert refusal is not None, "a serving process started with a designated group absent"
        assert "probe-staff" in str(refusal)

    def test_a_fully_satisfied_component_is_accepted(self, served_path_report: Mapping[str, object]) -> None:
        """The positive control, and the load-bearing one.

        Without it a stage-2 implementation that refused unconditionally would
        satisfy every case above, and the component would be one that can never
        start.
        """
        assert served_path_report["everything_satisfied"] is None, (
            "a fully satisfied component was refused on the served path, so every refusal above proves nothing"
        )

    def test_the_migrations_condition_is_exempt_off_a_serving_process(
        self,
        served_path_report: Mapping[str, object],
    ) -> None:
        """AD-13's fail-open process type, on the served path's own report.

        The same database, with every migration still pending, evaluated with no
        `COMPONENT_PROCESS` declared. R-3 is the recorded price of the exemption
        and is carried rather than compensated for.
        """
        assert served_path_report["migrations_pending_off_a_serving_process"] is None, (
            "the migrations condition fired on a process that declared no serving type (AD-13)"
        )


class TestTheManagementCommandControl:
    """AC #3's second half: the same conditions fire under `manage.py`, and one does not."""

    @pytest.mark.parametrize(
        ("fault", "expected"),
        [
            pytest.param("credential-minting-route", "rest_framework.authtoken", id="credential-minting-route"),
            pytest.param("local-sign-in-route", "config.local_dev", id="local-sign-in-route"),
        ],
    )
    def test_a_forbidden_route_refuses_a_management_command_too(
        self,
        tmp_path: Path,
        fault: str,
        expected: str,
    ) -> None:
        """The URLconf conditions are not serving-process-gated, so `check` meets them.

        The refusal arrives out of `django.setup()`, before the command runs at
        all -- which is what makes it a property of every management command
        rather than of `check`.
        """
        report = _management_command_outcome(tmp_path, fault=fault, process=NO_PROCESS_DECLARED)

        assert report["refusal"] is not None, f"`manage.py check` started cleanly with {fault} configured"
        assert expected in str(report["refusal"])
        assert report["refusal_type"] == REFUSAL_TYPE.__name__

    def test_unapplied_migrations_do_not_refuse_a_management_command(self, tmp_path: Path) -> None:
        """AD-13's exemption, asserted explicitly rather than read as a coverage gap.

        `manage.py migrate` is the one action that clears the unapplied-migrations
        state. A refusal that fired on management commands would deadlock the
        FR-41 release stage against a state nothing could resolve (AD-22), so the
        condition gates on process type and process type fails open.

        The database this runs against has never been migrated, which the paired
        case below proves by refusing on the same one.
        """
        report = _management_command_outcome(tmp_path, fault=NO_FAULT, process=NO_PROCESS_DECLARED)

        assert report["refusal"] is None, (
            "a management command was refused for the unapplied migrations it exists to apply (AD-13): "
            f"{report['refusal']}"
        )

    def test_the_exemption_is_about_process_type_and_not_about_the_command(self, tmp_path: Path) -> None:
        """The paired half, without which the case above proves only that nothing fired.

        The same command against the same never-migrated database, with a serving
        process declared, is refused. So the exemption above is AD-13's fail-open
        process type doing its work rather than the migrations condition being
        absent -- and R-3's recorded price is stated exactly: a serving process
        started outside the declared process tasks does not fire this refusal.
        """
        report = _management_command_outcome(tmp_path, fault=NO_FAULT, process=SERVING_PROCESS)

        assert report["refusal"] is not None, (
            "a process declaring itself a serving process was not refused despite pending migrations"
        )
        assert "unapplied migrations" in str(report["refusal"])
        assert report["refusal_type"] == REFUSAL_TYPE.__name__

    def test_an_absent_designated_group_does_not_refuse_a_management_command(
        self,
        migrated_probe_directory: Path,
    ) -> None:
        """AD-13's exemption on condition 5's stage-2 half, which is wider than migrations alone.

        Both database-backed stage-2 conditions gate on `is_serving_process()`,
        so a management command that declares no process type is exempt from both
        -- and the exemption on this one has no `manage.py migrate` argument
        behind it. It is the same fail-open process type, asserted where it also
        applies rather than assumed from the case above.

        The database is fully migrated, so condition 7 has nothing to say and
        this is genuinely condition 5 being reached and passing over.
        """
        report = _run_management_command(
            migrated_probe_directory,
            "check",
            process=NO_PROCESS_DECLARED,
            claims=ABSENT_GROUP_CONTRACT,
        )

        assert report["refusal"] is None, (
            "a management command with no process type declared was refused for an absent designated "
            f"group (AD-13): {report['refusal']}"
        )

    def test_an_absent_designated_group_refuses_a_serving_management_command(
        self,
        migrated_probe_directory: Path,
    ) -> None:
        """The paired half, without which the case above proves only that nothing fired.

        The same command, against the same migrated database, with a serving
        process declared: refused, and refused for the group rather than for the
        schema. That is what shows the exemption above is about process type
        rather than about condition 5 being unreachable from a management command
        at all.
        """
        report = _run_management_command(
            migrated_probe_directory,
            "check",
            process=SERVING_PROCESS,
            claims=ABSENT_GROUP_CONTRACT,
        )

        assert report["refusal"] is not None, (
            "a serving process was accepted with both designated groups absent from a migrated database"
        )
        assert ABSENT_STAFF_GROUP in str(report["refusal"])
        assert "unapplied migrations" not in str(report["refusal"]), (
            "the refusal is condition 7's, so the probe database was never migrated and condition 5's "
            "stage-2 half was not reached"
        )
        assert report["refusal_type"] == REFUSAL_TYPE.__name__

    def test_the_probe_never_has_stage_one_evaluated_over_it(self, tmp_path: Path) -> None:
        """What this probe does *not* exercise, measured rather than asserted in prose.

        The generated settings module composes `config.settings.local` under a
        declared local runtime and then drops the declaration, so stage 1 ran
        while the run was still local and returned before evaluating anything.
        Every case in this class therefore reports on stage 2 alone, and none of
        them says anything about the namespace being one a deployed component
        could legitimately have -- it is not: the throwaway database these probes
        need is sqlite, which condition 1 refuses outright.

        The child reports what stage 1 *would* have said, and this asserts it is a
        refusal. That keeps the limitation a measured fact rather than a comment
        that could quietly stop being true, and it is the reason the clean control
        run above is not evidence of a stage-1-clean configuration.
        """
        report = _management_command_outcome(tmp_path, fault=NO_FAULT, process=NO_PROCESS_DECLARED)

        assert report["stage_one_over_this_namespace"] is not None, (
            "stage 1 accepts the probe's namespace, so the limitation this case records no longer holds "
            "and the probe could be built on a deployed-shaped settings module instead"
        )
        assert "sqlite" in str(report["stage_one_over_this_namespace"])


def _absent_designated_group() -> str:
    """Delete a designated `Group` row and return what the refusal has to say.

    Deleted inside `django_db`'s transaction, so the rollback restores the row
    `users.0003_provision_designated_groups` created.

    Returns:
        The distinguishing substring of condition 5's stage-2 refusal.

    """
    staff_group = settings.CLAIMS_CONTRACT.staff_group
    Group.objects.filter(name=staff_group).delete()
    return repr(staff_group)


def _pending_migration() -> str:
    """Make one applied migration pending again, and return what the refusal has to say.

    The mirror of the case above, on the other database-backed condition: a row
    is deleted from `django_migrations` inside `django_db`'s transaction, so the
    alias is one with a migration outstanding for the duration of the case and is
    fully migrated again the moment it rolls back. The leaf is found rather than
    named, so a migration added later moves this with it.

    Returns:
        The `app.name` of the migration the refusal has to name.

    """
    connection = connections[DEFAULT_DB_ALIAS]
    loader = MigrationExecutor(connection).loader
    leaf = next(node for node in sorted(loader.graph.leaf_nodes()) if node in loader.applied_migrations)
    MigrationRecorder(connection).migration_qs.filter(app=leaf[0], name=leaf[1]).delete()
    return f"{leaf[0]}.{leaf[1]}"


#: One builder per state `tests/unit/startup/test_no_softening.py` delegates here,
#: keyed by the same `state_id`. The class below parametrizes straight off
#: `DELEGATED_TO_THE_INTEGRATION_SUITE`, so a state delegated with no builder here
#: fails on this side rather than being delegated into a gap -- which is what
#: happened while the delegation was a one-way list compared against another list.
_DELEGATED_STATES: Final[dict[str, Callable[[], str]]] = {
    "designated-group-absent": _absent_designated_group,
    "unapplied-migrations": _pending_migration,
}


class TestTheTwoDatabaseStatesAreNotSoftened:
    """CG-3 for the two states `tests/unit/startup/test_no_softening.py` cannot reach.

    Both of them, and both by the same three measurements the unit module makes
    over the other twelve: the refusal raises, warns about nothing, logs nothing
    in place of the raise, and is exactly `ImproperlyConfigured`. The migrations
    half was missing until Story 4.5's review -- three docstrings claimed the CG-3
    assertions covered all fourteen states while thirteen were measured.
    """

    @pytest.fixture(autouse=True)
    def _deployed_serving_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Declare a deployed serving process, which both conditions require."""
        monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
        monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)
        monkeypatch.setenv(PROCESS_ENV_VAR, SERVING_PROCESS)

    @pytest.fixture(autouse=True)
    def _structlog_capture_is_live(self) -> None:
        """Prove `capture_logs()` can still see an event before any case relies on its silence.

        `capture_logs()` swaps the configured processor chain, and a module that
        reconfigured structlog earlier in the session -- or a logger cached under
        `cache_logger_on_first_use` before the swap -- makes the capture go quiet
        without failing. Every "nothing was logged" assertion in this class would
        then pass while proving nothing at all.

        An **autouse fixture** rather than a case of its own, which is the whole
        of the difference. As a case it ran after the assertion it protects by
        nothing stronger than definition order, so `-x`, `-k`, `-p no:randomly` or
        any reordering left the silence assertion passing vacuously with its
        control never having run. As a fixture it runs at setup, before every
        case in the class, which is what the unit module's own control already
        does.
        """
        with structlog.testing.capture_logs() as captured:
            structlog.get_logger("tests.integration.startup.test_stage_two_served_path").info("capture-control")

        assert [event["event"] for event in captured] == ["capture-control"], (
            "structlog.testing.capture_logs() captured nothing at all, so every "
            "'nothing was logged' assertion in this class would pass vacuously"
        )

    @pytest.mark.django_db
    @pytest.mark.parametrize("state_id", sorted(DELEGATED_TO_THE_INTEGRATION_SUITE), ids=str)
    def test_the_delegated_refusal_neither_warns_nor_logs_instead(self, state_id: str) -> None:
        """The state raises, warns about nothing, logs nothing in its place, and says which it is.

        The message is asserted as well as the type, for the reason the unit
        module states: the stage-2 roster evaluates in order and every condition
        raises the same class, so a case that checked only the type would pass on
        whichever condition happened to refuse -- including the one *before* the
        state it is named after.

        Only warnings raised from the refusal contract's own source are counted:
        a `DeprecationWarning` out of Django or a third-party import is not this
        contract softening anything.
        """
        says = _DELEGATED_STATES[state_id]()
        contract_source = (REPO_ROOT / "src" / "config" / "startup").as_posix()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with structlog.testing.capture_logs() as captured:
                with (
                    temporary_root_urlconf(*deployed_url_patterns()),
                    pytest.raises(REFUSAL_TYPE) as refused,
                ):
                    run_stage_two()
                emitted = [event.get("event") for event in captured]

        assert says in str(refused.value), (
            f"the refusal for {state_id!r} does not say {says!r}, so this case is measuring a "
            f"different condition: {refused.value}"
        )
        assert type(refused.value) is REFUSAL_TYPE
        assert [str(entry.message) for entry in caught if contract_source in entry.filename] == []
        assert emitted == []

    def test_every_delegated_state_has_a_case_here(self) -> None:
        """The second direction of the delegation, which is the one that was missing.

        `test_no_softening.py` proves each declared state is either built there or
        recorded as delegated. That is bookkeeping between two lists: it says
        nothing about whether the module the state was delegated *to* covers it,
        and as first written this one covered a single delegated state while
        three docstrings claimed both. The equality here is what closes it, and
        the parametrization above is driven off the same set, so a builder added
        without a case is impossible.
        """
        assert set(_DELEGATED_STATES) == set(DELEGATED_TO_THE_INTEGRATION_SUITE)


@pytest.mark.django_db
def test_both_stages_accept_a_fully_valid_component_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 7's end-to-end positive: a valid namespace and a clean URLconf pass both stages.

    Every other positive control in the suite covers one condition. This one
    covers the pair, in the order a deployed component meets them: stage 1
    against a fully valid settings namespace, then stage 2 against a URL
    configuration a deployed component would serve, on a migrated database whose
    designated groups the data migration provisioned.

    Without it, a contract in which some condition refused every input would
    still satisfy every per-condition negative case in the epic -- and would
    describe a component that can never start.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)
    monkeypatch.setenv(PROCESS_ENV_VAR, SERVING_PROCESS)

    run_stage_one(valid_deployed_settings_namespace())

    with temporary_root_urlconf(*deployed_url_patterns()):
        run_stage_two()
