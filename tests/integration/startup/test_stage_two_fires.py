"""Stage 2 fires through a served request path, not only through `manage.py` (AC #3).

**Why this is a subprocess.** pytest-django completes `django.setup()` -- and
therefore `UsersConfig.ready()` -- during collection, before any test body runs.
An in-process read of the stage-2 sentinel is already true no matter what the
invocation point does, and would stay true if the `run_stage_two()` call were
deleted from `ready()` altogether. `tests/unit/test_no_network_at_boot.py`
records this exact problem for boot assertions and solves it the same way: a
`-c` boot probe in a fresh interpreter, writing a JSON report to a file named on
its command line rather than to stdout, because Django's logging configuration
also writes to stdout and a report the parent has to find among log lines is a
report that breaks when logging changes.

**What the probe proves.** It leaves `DJANGO_SETTINGS_MODULE` unset, so
`config/asgi.py`'s own `os.environ.setdefault` is what selects the module --
the statement a server process actually executes. It then imports `config.asgi`,
whose `get_asgi_application()` is what triggers `django.setup()` and the
`ready()` hook, reads the sentinel *at that point*, and only then drives one
request through the resulting `application` callable. The parent asserts the
hook fired **and** that the request produced a response, so a probe that never
served cannot report success.

`gunicorn` and `uvicorn` both import this same module and call the same
`get_asgi_application()`; `tests/integration/test_import_resolution.py` is what
proves those two runtimes resolve it identically, so this file drives the ASGI
callable directly rather than starting a third and fourth server.

The requested path is deliberately routed by nothing. Django answers 404 only
after importing `config.urls`, so the response proves the URL configuration
resolved -- while a routed view would run inside the transaction
`ATOMIC_REQUESTS` opens and create `db.sqlite3` in the repository root under the
local settings the probe boots with. This test leaves nothing behind.

`src/config/asgi.py` is in the coverage `omit` list, which is a closed
carrier-declared surface. This test asserts behaviour reached *through* that
module, so it neither requires removing the entry nor adds one. And what a
subprocess does is not measured by the parent's coverage run: the probe proves
the wiring, and the unit tests under `tests/unit/startup/` cover the code.

`tests/integration/conftest.py` marks everything under `tests/integration/` as
an integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.apps import apps
from django.core.management import call_command

from config.startup.stage_two import STAGE_TWO_OWNER_APP_LABEL
from config.startup.stage_two import stage_two_has_run
from tests.conftest import subprocess_env
from tests.integration.startup.conftest import BOOT_PROBE_TIMEOUT_SECONDS
from tests.integration.startup.conftest import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

# The module `config/asgi.py` defaults to when nothing names one. Asserted in the
# report rather than assumed, because the probe deliberately does not set it and
# a report about a differently configured component would prove nothing here.
EXPECTED_SETTINGS_MODULE = "config.settings.local"

# Boot this component the way a server does -- through `config.asgi` with no
# `DJANGO_SETTINGS_MODULE` set -- then serve one request through the callable
# that import produced, and report both halves.
#
# A string on purpose: nothing here executes in the test process, so the
# `print`-free file handoff and the deferred imports below need no ruff
# exemptions. ruff sees a string literal.
_STAGE_TWO_PROBE_SOURCE = '''
"""Boot through the ASGI entrypoint, serve one request, report what fired."""

import asyncio
import json
import sys
from pathlib import Path

# This import is the whole point: `config/asgi.py` sets DJANGO_SETTINGS_MODULE
# by `setdefault` and then calls `get_asgi_application()`, which runs
# `django.setup()` and with it every AppConfig.ready().
from config.asgi import application
from config.startup.stage_two import STAGE_TWO_OWNER_APP_LABEL
from config.startup.stage_two import stage_two_has_run

fired_during_setup = stage_two_has_run()

from django.apps import apps
from django.conf import settings

# Routed by nothing: the 404 proves `config.urls` resolved, and no view runs, so
# nothing opens the ATOMIC_REQUESTS transaction that would create a database.
PROBE_PATH = "/__stage-two-probe__/"

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


SERVE_TIMEOUT_SECONDS = 60.0


async def _serve_one_request():
    """Drive one HTTP request through the ASGI callable and collect what it sent.

    `receive` hands over the request body once and then blocks forever. That is
    what a real server's receive channel does between messages, and Django's
    handler depends on it: it races the response against a task awaiting
    `http.disconnect`, so a `receive` that returned again immediately would look
    like a client that had already gone away.
    """
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

report = {
    "settings_module": settings.SETTINGS_MODULE,
    "apps_ready": apps.ready,
    "owner_app_label": STAGE_TWO_OWNER_APP_LABEL,
    "owner_app_is_installed": apps.is_installed("django_service.users"),
    "stage_two_fired_during_setup": fired_during_setup,
    "stage_two_fired": stage_two_has_run(),
    "response_statuses": [m["status"] for m in messages if m["type"] == "http.response.start"],
    "response_body_messages": len([m for m in messages if m["type"] == "http.response.body"]),
}

Path(sys.argv[1]).write_text(json.dumps(report), encoding="utf-8")
'''


def test_stage_two_fires_when_a_request_is_served_through_the_asgi_entrypoint(tmp_path: Path) -> None:
    """AC #3: the hook fires on the served path, and the request really was served.

    Both halves are required of the same report. The sentinel alone would be
    satisfied by a probe that imported `config.asgi` and stopped; the response
    alone would be satisfied by a `ready()` that did nothing.
    """
    report_path = tmp_path / "stage-two-report.json"

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _STAGE_TWO_PROBE_SOURCE, str(report_path)],
        cwd=REPO_ROOT,
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=BOOT_PROBE_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0, (
        f"the stage-two boot probe exited {completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )
    assert report_path.exists(), "the boot probe exited cleanly without writing a report"

    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["settings_module"] == EXPECTED_SETTINGS_MODULE, (
        "config/asgi.py's own setdefault did not select the settings module"
    )
    assert report["apps_ready"] is True
    assert report["owner_app_is_installed"] is True
    assert report["owner_app_label"] == STAGE_TWO_OWNER_APP_LABEL
    assert report["stage_two_fired_during_setup"] is True, (
        "the stage-2 hook did not fire while get_asgi_application() ran django.setup()"
    )
    assert report["stage_two_fired"] is True
    assert report["response_statuses"] == [HTTPStatus.NOT_FOUND], (
        "the probe did not actually serve a request, so the hook assertion above proves nothing about serving"
    )
    assert report["response_body_messages"] >= 1


def test_stage_two_is_in_place_on_the_management_command_path() -> None:
    """AC #3's second half, and the weaker of the two assertions by design.

    `ready()` runs inside `django.setup()`, which every management command
    performs, so the invocation point is not serving-process-only. In this
    process the sentinel was already written at collection, so what this case
    asserts is that a management command completes with the hook in place --
    the subprocess above is what asserts that the hook is reached at all.

    `check` is the command with nothing else to do: it runs Django's system
    checks, touches no database and mutates nothing.
    """
    output = io.StringIO()

    call_command("check", stdout=output, stderr=output)

    assert stage_two_has_run() is True
    assert apps.get_app_config(STAGE_TWO_OWNER_APP_LABEL).name == "django_service.users"
