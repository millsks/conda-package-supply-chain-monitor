"""The three runtimes resolve this project's imports identically (AD-7, AC #4).

A unit test can only assert that the six removed declaration sites are gone.
What AD-7 actually prevents is narrower and worse: a source root that works
under pytest and fails under gunicorn. Nothing short of starting the servers
catches that, so these tests start them -- real subprocesses, real binds, and a
real HTTP request whose status is asserted.

The request is what makes the server legs mean something. A bind proves only
that a listening socket exists: gunicorn's arbiter creates its sockets in
``Arbiter.start()`` *before* forking, so without ``--preload`` an unimportable
application still binds the port and a bind-only check passes green -- the exact
"works under pytest, fails under gunicorn" failure this file exists to catch. So
gunicorn is started with ``--preload`` (the master imports the application before
binding, and an ImportError exits it rather than a worker), and both server legs
then issue a GET and assert the status.

The path requested is deliberately one no URLconf routes. Django answers 404
only after importing ``config.urls``, which imports ``django_service.users.urls``
through ``include()`` -- so the 404 is proof that both packages resolved *in the
server process*, while an unresolvable one gives a 500 instead. A routed path
would answer 200 and prove the same thing, but every routed view runs inside the
transaction ``ATOMIC_REQUESTS`` opens, which would create ``db.sqlite3`` in the
repository root under the local settings these servers boot with. These tests
leave nothing behind, so they ask for the response that needs no database.

Every subprocess runs with ``PYTHONSAFEPATH`` set and ``PYTHONPATH`` cleared, so
neither the current working directory nor an inherited path entry can supply
``config`` or ``django_service``. The only thing left that can is the editable
install generated from ``[tool.hatch.build.targets.wheel] sources`` -- the one
retained declaration site. If that site were wrong, these tests would be the
ones to fail rather than the wheel build, which succeeds either way.
``DJANGO_SETTINGS_MODULE`` is dropped for the same reason: pytest-django has
already set it to ``config.settings.test`` in this process, and inheriting it
would make each entrypoint's ``os.environ.setdefault`` a no-op and leave that
line untested.

gunicorn is declared only for linux-64 and osx-arm64 (``pixi.toml``
``[target.*.dependencies]``): it is POSIX-only and has no conda-forge win-64
build, which is also why AD-18 keeps the six-combination harness Linux-only. On
a platform without it that leg skips at runtime rather than being marked
skipped, so it runs wherever it can run.
"""

from __future__ import annotations

import contextlib
import http.client
import importlib.util
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import zipfile
from collections import deque
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]

# Generous: a cold Django start pays for app loading and the OpenTelemetry
# instrumentors. Overshooting costs nothing when the server comes up quickly.
BIND_TIMEOUT_SECONDS = 60.0
POLL_INTERVAL_SECONDS = 0.2
SHUTDOWN_TIMEOUT_SECONDS = 15.0
HTTP_TIMEOUT_SECONDS = 30.0

# A one-line `python -c` import, not a server start: it has no app registry and
# no instrumentors to pay for, so it gets its own budget. Reusing the 60s bind
# timeout would make a genuinely hung probe take a minute to say so.
PROBE_TIMEOUT_SECONDS = 30.0

# Building a wheel is a real build; hatchling and hatch-vcs are already in the
# environment (`--no-isolation`), so this is generous rather than tight.
BUILD_TIMEOUT_SECONDS = 300.0

# Server output is drained continuously into this many lines. Bounded because a
# server that never binds could otherwise log until memory runs out, and the
# lines that explain a failed start are the first ones anyway.
CAPTURED_LINE_LIMIT = 400

# The import that has to mean the same thing in all three runtimes: a package
# under src/config/ and the top-level package beside it.
IMPORT_PROBE = "import config.asgi, django_service"

# Routed by nothing, on purpose -- see the module docstring.
UNROUTED_PATH = "/__import-probe__/"

# `config.asgi.__file__` and `django_service.__file__`, one per line.
PROBE_PATHS_PRINTED = 2


def _subprocess_env() -> dict[str, str]:
    """Return an environment in which only the editable install can resolve src/.

    ``PYTHONSAFEPATH`` keeps the interpreter from prepending the working
    directory (for ``-c`` and ``-m``) to ``sys.path``, and ``PYTHONPATH`` is
    dropped outright. What remains is site-packages, where the editable
    install's finder lives.

    ``DJANGO_SETTINGS_MODULE`` is dropped too. pytest-django sets it to
    ``config.settings.test`` in this process from the ``--ds`` in ``addopts``,
    and a server subprocess that inherited it would never exercise the
    ``os.environ.setdefault`` each entrypoint makes -- the statement the
    comment in ``asgi.py`` and ``wsgi.py`` is about.

    Returns:
        A copy of the current environment with those three adjustments.

    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONSAFEPATH"] = "1"
    return env


def _free_port() -> int:
    """Return a port the OS has just confirmed is free.

    Closed before it is handed over, so there is a window in which something
    else could take it. Nothing else in this suite binds a port, and the
    alternative -- parsing the port back out of a server's log -- differs
    between uvicorn and gunicorn.

    Returns:
        A TCP port on 127.0.0.1 that was free a moment ago.

    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


class _ServerProcess:
    """A server subprocess whose combined output is drained while it runs.

    Draining matters for correctness, not only for diagnostics: with
    ``stdout=PIPE`` and nothing reading, a server that writes more than one pipe
    buffer before binding blocks forever on the write. The symptom would be the
    bind timeout -- exactly the misdiagnosis ``_wait_for_bind`` exists to
    prevent. Reading on a daemon thread also means the early-exit branch never
    has to call a blocking ``read()`` on a pipe a forked worker may still hold.
    """

    def __init__(self, process: subprocess.Popen[str]) -> None:
        """Start draining ``process``.

        Args:
            process: A started subprocess with ``stdout`` piped and text mode on.

        """
        self.process = process
        self._lines: deque[str] = deque(maxlen=CAPTURED_LINE_LIMIT)
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self) -> None:
        """Copy the process's output into the bounded buffer until it closes."""
        stream = self.process.stdout
        if stream is None:
            return
        with contextlib.suppress(ValueError, OSError):
            for line in stream:
                self._lines.append(line)

    def output(self) -> str:
        """Return the server output captured so far.

        Returns:
            The last ``CAPTURED_LINE_LIMIT`` lines the server produced.

        """
        return "".join(self._lines)


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    """Kill a server and every process it forked.

    ``process.kill()`` reaches the gunicorn arbiter only; its workers survive,
    still holding the inherited listening socket, which is precisely the "no
    child or listening socket behind" promise being broken. The servers are
    started in their own session, so killing the process group reaches all of
    them.

    Args:
        process: The server process to kill.

    """
    killpg = getattr(os, "killpg", None)
    getpgid = getattr(os, "getpgid", None)
    if killpg is None or getpgid is None:  # pragma: no cover - Windows
        process.kill()
        return
    try:
        killpg(getpgid(process.pid), signal.SIGKILL)
    except OSError:
        process.kill()


def _terminate(server: _ServerProcess) -> None:
    """Stop a server process and leave no child or listening socket behind.

    Args:
        server: The server to stop.

    """
    process = server.process
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            # Suppressed rather than raised: this runs in a `finally`, and an
            # exception here would replace whatever the test actually found.
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    with contextlib.suppress(OSError):
        if process.stdout is not None:
            process.stdout.close()


@contextlib.contextmanager
def _server(command: list[str]) -> Iterator[_ServerProcess]:
    """Run ``command`` as a server subprocess and stop it on the way out.

    Args:
        command: The argv to run, from the repository root.

    Yields:
        The running server, with its output being drained.

    """
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=str(REPO_ROOT),
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # Its own process group, so the escalation path in `_terminate` can
        # reach forked workers without reaching pytest itself. POSIX-only.
        start_new_session=os.name == "posix",
    )
    server = _ServerProcess(process)
    try:
        yield server
    finally:
        _terminate(server)


def _wait_for_bind(server: _ServerProcess, port: int) -> None:
    """Fail unless the server accepts a connection on ``port`` before the timeout.

    A server that dies on an ImportError exits rather than binding, so the
    early exit is checked on every poll and its output is reported -- an
    import failure should read as an import failure, not as a timeout. The
    timeout reports the captured output too, since a server that is still
    starting has usually said why.

    Args:
        server: The running server.
        port: The port it was told to bind.

    """
    process = server.process
    deadline = time.monotonic() + BIND_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"server exited with {process.returncode} before binding to {port}:\n{server.output()}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(POLL_INTERVAL_SECONDS)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(f"server did not bind to 127.0.0.1:{port} within {BIND_TIMEOUT_SECONDS}s:\n{server.output()}")


def _get_status(port: int, path: str) -> int:
    """Return the HTTP status the server answers ``path`` with.

    ``http.client`` rather than a client library: this file may not add a
    dependency to make an assertion about dependencies resolving.

    Args:
        port: The server's port on 127.0.0.1.
        path: The request path.

    Returns:
        The response's status code.

    """
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=HTTP_TIMEOUT_SECONDS)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def _assert_serves_the_application(server: _ServerProcess, port: int) -> None:
    """Fail unless the server answers a request from an application that imported.

    Args:
        server: The running server.
        port: The port it was told to bind.

    """
    _wait_for_bind(server, port)
    try:
        status = _get_status(port, UNROUTED_PATH)
    except OSError as exc:
        # A bind followed by a refused or dropped request is the shape of a
        # worker that died after the arbiter opened the socket. Report the
        # server's own account of it rather than a bare ConnectionRefusedError.
        pytest.fail(f"GET {UNROUTED_PATH} on port {port} failed with {exc!r}:\n{server.output()}")

    assert status == HTTPStatus.NOT_FOUND, (
        f"GET {UNROUTED_PATH} answered {status}, not {HTTPStatus.NOT_FOUND}; "
        f"a 5xx here means the URLconf -- and so `config` or `django_service` -- "
        f"did not import in the server process:\n{server.output()}"
    )


@pytest.mark.integration
def test_the_import_probe_resolves_under_the_test_runtime() -> None:
    """Under pytest, in-process: this is the leg the removed `pythonpath` covered."""
    import config.asgi  # noqa: PLC0415
    import django_service  # noqa: PLC0415

    assert Path(config.asgi.__file__).is_relative_to(REPO_ROOT / "src")
    assert django_service.__file__ is not None
    assert Path(django_service.__file__).is_relative_to(REPO_ROOT / "src")


@pytest.mark.integration
def test_the_wsgi_entrypoint_imports_and_exposes_an_application() -> None:
    """`config.wsgi` is imported here or by nothing in this suite at all.

    It is the third entrypoint AD-7 edited, `WSGI_APPLICATION =
    "config.wsgi.application"` is what `runserver` loads, and it is omitted from
    coverage measurement -- so nothing else in the repository would notice an
    import-time break in it. Only a text-absence assertion stood behind that
    edit before this test.

    In-process rather than as a fourth subprocess: Django is already set up
    here, so this costs an import, and the two server legs below are what prove
    the *runtime* claim.
    """
    import config.wsgi  # noqa: PLC0415

    assert Path(config.wsgi.__file__).is_relative_to(REPO_ROOT / "src")
    assert callable(config.wsgi.application)


@pytest.mark.integration
def test_the_import_probe_resolves_in_a_plain_interpreter() -> None:
    """A bare interpreter with no path help resolves the same two packages.

    This is the control for the two server legs below: if it fails, the
    retained declaration site is broken and the server failures that follow
    would be a symptom rather than the finding.
    """
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", f"{IMPORT_PROBE}; print(config.asgi.__file__); print(django_service.__file__)"],
        cwd=str(REPO_ROOT),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    # `splitlines`, not `split`: a repository path containing a space is routine
    # on macOS and this is a template meant to be cloned anywhere. The count is
    # asserted first because `all(...)` over an empty list is True, so a
    # subprocess that printed nothing would otherwise pass vacuously.
    resolved = result.stdout.splitlines()
    assert len(resolved) == PROBE_PATHS_PRINTED, result.stdout
    for path in resolved:
        assert Path(path).is_relative_to(REPO_ROOT / "src"), result.stdout


@pytest.mark.integration
def test_uvicorn_serves_the_asgi_application() -> None:
    """uvicorn resolves `config.asgi:application` with no `--app-dir` (AC #5).

    Not the same command as `pixi run serve`, and the difference is more than
    the port: that task runs the `uvicorn` console script in the `default`
    environment against whatever settings the environment supplies, while this
    runs `python -m uvicorn` in the `dev` environment with
    `DJANGO_SETTINGS_MODULE` cleared so `config/asgi.py`'s own
    `setdefault(..., "config.settings.local")` is what chooses.

    What it does prove is the part AC #5 is about: uvicorn given nothing but the
    `config.asgi:application` string imports it, serves it, and answers.
    """
    port = _free_port()
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "config.asgi:application",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    with _server(command) as server:
        _assert_serves_the_application(server, port)


@pytest.mark.integration
def test_gunicorn_serves_the_asgi_application_through_the_uvicorn_worker() -> None:
    """The production pairing resolves the same import the other two runtimes do.

    `--preload` is load-bearing. Without it gunicorn imports the application in
    each forked worker, *after* the arbiter has already created the listening
    socket, so a broken import binds the port and dies quietly behind it. With
    it the master imports first and an ImportError exits the master before any
    bind, which `_wait_for_bind` reports as the import error it is.

    Skipped, at runtime, where the pairing is not installed: gunicorn and
    uvicorn-worker are declared for linux-64 and osx-arm64 only in ``pixi.toml``'s
    ``[target.*.dependencies]`` because gunicorn is POSIX-only and conda-forge
    has no win-64 build. Both are checked, so a missing worker class reads as a
    missing dependency rather than as a server that failed to start. A runtime
    skip rather than ``@pytest.mark.skip`` so the leg runs on every platform
    that can run it.
    """
    missing = [name for name in ("gunicorn", "uvicorn_worker") if importlib.util.find_spec(name) is None]
    if missing:
        pytest.skip(f"{', '.join(missing)} declared for linux-64 and osx-arm64 only -- see pixi.toml [target.*]")

    port = _free_port()
    command = [
        sys.executable,
        "-m",
        "gunicorn",
        "config.asgi:application",
        "-k",
        "uvicorn_worker.UvicornWorker",
        "--bind",
        f"127.0.0.1:{port}",
        # Import the application in the master, before the listening socket
        # exists. See the docstring: without this the leg cannot fail.
        "--preload",
        # Otherwise gunicorn 26 opens a control socket under $HOME, which is
        # state this suite has no business creating.
        "--no-control-socket",
    ]

    with _server(command) as server:
        _assert_serves_the_application(server, port)


@pytest.mark.integration
def test_the_built_wheel_ships_the_source_tree_at_its_root(tmp_path: Path) -> None:
    """The retained declaration is checked against the artifact it produces.

    `[tool.hatch.build.targets.wheel]` is the whole of AD-7's remaining site,
    and what it actually claims is a property of the wheel: everything under
    `src/` lands at the root, so `config` and `django_service` are top-level and
    an app added later needs no edit. Every other test in this repository reads
    the declaration; this one reads the result, which is what would catch
    `only-include` or `sources` being dropped -- neither of which makes the
    build fail.

    Built into `tmp_path` rather than `dist/`, so the repository's own build
    output is neither consumed nor clobbered.
    """
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(tmp_path)],
        cwd=str(REPO_ROOT),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=BUILD_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    wheels = sorted(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, wheels

    with zipfile.ZipFile(wheels[0]) as archive:
        top_level = {Path(name).parts[0] for name in archive.namelist()}

    packages = {entry for entry in top_level if not entry.endswith(".dist-info")}
    expected = {path.name for path in (REPO_ROOT / "src").iterdir() if path.is_dir() and not path.name.startswith("_")}

    assert packages == expected, sorted(top_level)
