"""The payload properties, verified by building the image and running it (FR-38, FR-39).

`tests/unit/test_payload_properties.py` asserts what the `Dockerfile` *declares*
and what the settings *resolve to*. Both are necessary and neither is the claim.
The claim AD-15 makes is behavioural -- the component starts from environment
variables alone, under a UID the image has never seen, on a read-only root
filesystem, and writes nothing outside a temporary directory -- and the only
thing that establishes it is a container that has actually done so.

**Two runs, because one cannot prove both things.** `docker diff` on a
`--read-only` container is trivially empty and proves nothing: the runtime
refused every write, so an image that wanted to write all over `/app` would look
identical to one that wanted nothing. So the no-writes claim is asserted against
a **writable** run -- every changed path must be under the temporary directory --
and the start-up claim is asserted against a **`--read-only --tmpfs /tmp`** run.
Both use `--user 12345:0`, a UID that appears nowhere in the image and has no
`/etc/passwd` entry; group 0 is how an arbitrary-UID platform grants access, and
`chgrp -R 0 /app && chmod -R g=u /app` in the image is what makes it work.

**pixi's task cache is redirected by the image, not by this harness.**
`pixi run <task>` writes `/app/.pixi/task-cache-v0/<env>-<task>-<hash>.json` when
the task completes, and the write is **not** optional: it happens after the task's
own exit status is known, and when it fails pixi exits non-zero with the task's
output already printed. Under `--read-only` that is `Read-only file system (os
error 30)`; under the image's `g=rX` tree it is `Permission denied (os error 13)`,
which is how a `manage migrate` that applied every migration and reported success
still failed the release stage.

An earlier revision of this module mounted a tmpfs over that directory and
described the write as an optimisation pixi carries on without. That was wrong on
both counts, and it put the workaround in the wrong place besides: a deployment
platform mounts `/tmp` and knows nothing about pixi's internals, so a payload that
needs a second mount to run read-only does not have the property this module
claims to verify. The image now symlinks that directory to `/tmp`, and the runs
below use a plain `--read-only --tmpfs /tmp`, which is what a platform actually
provides.

**The release stage runs first, and that is Story 5.5's contract demonstrated
rather than violated.** `_refuse_unapplied_migrations` fires for serving
processes, so `web` will not boot against a database nobody has migrated. The
harness therefore performs the release stage itself, as a separate non-serving
invocation of the same image, running exactly the steps `component.toml`
declares through `pixi run manage <step>` -- which is what
`docs/deployment.md` tells a deployment repository to do. The *image* still
declares no migrating instruction, which is what AD-22 forbids and what
`tests/unit/test_release_stage.py` holds.

**Two variables the harness sets that no deployment would.**
`DJANGO_ALLOWED_HOSTS`, because `production.py` defaults it to a public hostname
and the probes arrive at a published port on localhost; and
`DJANGO_SECURE_SSL_REDIRECT=False`, because it defaults to true and
`SecurityMiddleware` would 301 a plain-HTTP probe -- there is no
`SECURE_REDIRECT_EXEMPT` in this repository. Sending `X-Forwarded-Proto: https`
would work equally; the variable is the clearer statement in a test.

**Docker is a capability guard, not a dodged gate.** The module skips where
`docker` is not on `PATH`, which is a developer-machine accommodation: the gate
runs on Linux with Docker available, so these assertions execute there. The
exemption is recorded in `tests/unit/test_suite_policy.py`'s table like any
other, and it is a `skipif` on a capability rather than a `skip` on a failure --
there is no state here to be permissive about, only a tool that may be absent.

**Disposition `machinery`, with `tests/unit/test_payload_properties.py` and with
the `Dockerfile` itself.** These assertions do not run inside a materialized
combination's gate, because a materialized component ships no Dockerfile to
build (AD-15). Epic 7 lists all three explicitly in `accelerator.toml`; AD-2's
input reconciliation fails a path claimed by no disposition, and defaulting to
`machinery` is not the same as declaring it.

**State is left as it was found.** Every fixture removes what it created --
containers, the network, and the image -- in teardown, whatever the assertions
did.

These are integration tests: they build an image, start containers and open
sockets. `tests/integration/conftest.py` marks the directory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from typing import TYPE_CHECKING
from typing import Final

import pytest

from config.component import load_component_declaration
from tests.pixi_manifest import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The tool this module needs, resolved to an absolute path once. Absent, the
#: whole module skips; present, every invocation below runs the same binary
#: rather than whatever `PATH` resolves at the moment of the call.
DOCKER: Final[str | None] = shutil.which("docker")

#: What `docker version --format {{.Server.Os}}` reports where this module can work.
LINUX_CONTAINERS: Final[str] = "linux"

#: Bound on the capability probe. It is a local daemon query, so a slow answer is
#: an unhealthy daemon rather than a slow one, and waiting longer would not help.
DOCKER_VERSION_TIMEOUT_SECONDS: Final[int] = 30


def _builds_linux_images() -> bool:
    """Answer whether the local Docker can build the `linux/amd64` image this module needs.

    **The binary being on PATH is not the capability, and assuming it was is what
    this function exists to correct.** `windows-latest` in the compatibility
    matrix ships `docker.EXE` and runs it in *Windows containers* mode, where
    pulling the `linux/amd64` base fails with `no matching manifest for
    linux/amd64 in the manifest list entries` -- a red gate on a runner doing
    nothing wrong, reported as five errors that look like the image is broken.

    The daemon's own OS is the thing to ask. `docker version` reports it directly,
    and a daemon that is not running answers non-zero, so the unreachable case
    falls out of the same call rather than needing a second one.

    Returns:
        True when a Docker daemon is reachable and serving Linux containers.

    """
    if DOCKER is None:
        return False
    try:
        probed = subprocess.run(  # noqa: S603 - DOCKER is resolved by shutil.which, not from input
            [DOCKER, "version", "--format", "{{.Server.Os}}"],
            capture_output=True,
            text=True,
            timeout=DOCKER_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        # A docker binary that cannot be executed at all is the same capability
        # answer as one that is absent. Named rather than caught broadly.
        return False
    return probed.returncode == 0 and probed.stdout.strip() == LINUX_CONTAINERS


pytestmark = pytest.mark.skipif(
    not _builds_linux_images(),
    reason=(
        "no Docker daemon serving Linux containers. This module builds and runs the machinery image to "
        "verify the FR-38/FR-39 payload properties, and the image is linux/amd64 because pixi.lock declares "
        "linux-64 and no linux-aarch64. The gate runs on Linux with Docker available, so this is a "
        "capability guard for developer machines and for the Windows compatibility runner -- which has "
        "docker.EXE but serves Windows containers -- rather than a suppressed failure."
    ),
)

#: A per-session suffix, so a run cannot collide with a leftover container, a
#: developer's own image of the same name, or a second session on the same
#: machine. Teardown removes everything it names, and a name nothing else could
#: have created is what makes that removal safe to perform unconditionally.
SESSION: Final[str] = uuid.uuid4().hex[:8]

IMAGE_TAG: Final[str] = f"conda-package-supply-chain-monitor-payload:{SESSION}"
NETWORK_NAME: Final[str] = f"payload-{SESSION}-net"
DATABASE_CONTAINER: Final[str] = f"payload-{SESSION}-db"
WRITABLE_CONTAINER: Final[str] = f"payload-{SESSION}-writable"
READ_ONLY_CONTAINER: Final[str] = f"payload-{SESSION}-readonly"

#: The database the release stage migrates and the component connects to. The
#: same major version the gate's own service uses (`.github/workflows/ci.yml`)
#: and the one `libpq` is pinned against in `pixi.toml`.
POSTGRES_IMAGE: Final[str] = "postgres:17"
POSTGRES_CREDENTIAL: Final[str] = "payload"

#: The UID the containers run as: arbitrary, five digits, and present nowhere in
#: the image. Group 0, because that is how a platform that assigns UIDs grants
#: access to a tree it could not chown in advance.
ARBITRARY_UID: Final[str] = "12345:0"

#: The only writable path the component is permitted, and the one directory
#: inside the application root that `pixi run` caches into. The second is mounted
#: as a tmpfs in the writable run rather than left writable -- see the module
#: docstring.
TEMPORARY_DIRECTORY: Final[str] = "/tmp"  # noqa: S108
APPLICATION_ROOT: Final[str] = "/app"


#: The port the `web` task binds inside the container. The host port is chosen by
#: the runtime and read back with `docker port`, so two sessions cannot collide
#: and no test has to guess what is free.
CONTAINER_PORT: Final[str] = "8000"

#: The probes, and what each one is for (`src/config/health/urls.py`). Root
#: level, no trailing slash, behind no authentication.
LIVENESS_PATH: Final[str] = "livez"
READINESS_PATH: Final[str] = "readyz"
OK: Final[int] = 200

#: How long to wait for each stage. Generous, and deliberately so: the image is
#: `linux/amd64` because `pixi.lock` declares no `linux-aarch64`, so on an arm64
#: developer machine every one of these runs under emulation.
BUILD_TIMEOUT_SECONDS: Final[float] = 3600.0
COMMAND_TIMEOUT_SECONDS: Final[float] = 900.0
READY_TIMEOUT_SECONDS: Final[float] = 300.0
POLL_INTERVAL_SECONDS: Final[float] = 1.0
STOP_TIMEOUT_SECONDS: Final[str] = "30"


def _component_environment(database_url: str) -> dict[str, str]:
    """Build the environment a deployed component is started with.

    All of it is environment (FR-38). No file is mounted, nothing is baked into
    the image, and the image carries no `.env` at any level -- which is asserted
    below rather than assumed.

    Every value here is a variable a deployment platform sets. That is the whole
    of AC #1's "starts from environment variables alone": there is no
    configuration file, no mount, and no default baked into the image that would
    let the component start without them.

    Args:
        database_url: The URL of the database this run connects to.

    Returns:
        Variable name -> value, ready to be turned into `-e` arguments.
    """
    return {
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "DJANGO_SECRET_KEY": "harness-secret-not-a-deployment-key",
        "DJANGO_ADMIN_URL": "harness-admin/",
        "DATABASE_URL": database_url,
        "COMPONENT_OIDC_ISSUER": "https://idp.example.invalid/realms/component",
        "COMPONENT_IDENTITY_CLAIM": "sub",
        "COMPONENT_GROUP_CLAIM": "groups",
        "COMPONENT_STAFF_GROUP": "platform-staff",
        "COMPONENT_SUPERUSER_GROUP": "platform-superuser",
        # The two the harness needs and a deployment does not -- see the module
        # docstring.
        "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
        "DJANGO_SECURE_SSL_REDIRECT": "False",
    }


def _environment_arguments(environment: dict[str, str]) -> list[str]:
    """Return one `-e NAME=value` pair per variable.

    Args:
        environment: The variables to pass.

    Returns:
        The flattened argument list.
    """
    return [argument for name, value in environment.items() for argument in ("-e", f"{name}={value}")]


def _docker(*arguments: str, timeout: float = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    """Run one docker command and return its result, without raising on failure.

    `check=False`, deliberately. Every caller that needs success asserts it with
    a message naming what was being done, and a `CalledProcessError` raised out
    of a fixture reports a return code where the caller needs the daemon's own
    explanation.

    Args:
        *arguments: The arguments after `docker`.
        timeout: How long to wait before giving up.

    Returns:
        The completed process, with stdout and stderr captured as text.
    """
    return subprocess.run(  # noqa: S603
        [str(DOCKER), *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        cwd=REPO_ROOT,
    )


def _remove_container(name: str) -> None:
    """Remove one container, whether or not it is running or exists.

    Teardown runs after a failure as often as after a pass, so it cannot assume
    the container was ever created. A leftover container holds a name and a port
    and makes the next session fail for a reason that has nothing to do with the
    code under test.

    Args:
        name: The container to remove.
    """
    _docker("rm", "--force", "--volumes", name)


def _probe(base_url: str, path: str) -> int:
    """Return the status code one probe answers with.

    From the host over a published port rather than from inside the container:
    the pixi base image carries no `curl`, and a probe issued from inside would
    in any case not exercise the published port a platform actually uses.

    Args:
        base_url: The container's published base URL.
        path: The probe path, with no leading slash.

    Returns:
        The HTTP status code, or 0 when the connection could not be made at all
        -- which is what a container that has not finished starting looks like.
    """
    try:
        with urllib.request.urlopen(f"{base_url}/{path}", timeout=POLL_INTERVAL_SECONDS) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as answered:
        return int(answered.code)
    except OSError:
        # `URLError`, `TimeoutError` and every connection error derive from it.
        # A container that has not finished starting refuses the connection, and
        # that is a state to poll rather than a failure to report.
        return 0


def _wait_until_ready(base_url: str, container: str) -> None:
    """Block until readiness answers 200, or fail with the container's own logs.

    Args:
        base_url: The container's published base URL.
        container: The container name, so a failure can report what it logged.

    Raises:
        AssertionError: When readiness never answers within the window. The
            container's log is in the message, because "it did not start" is not
            a finding anybody can act on and the refusal contract's messages are
            written to be read.
    """
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _probe(base_url, READINESS_PATH) == OK:
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    logs = _docker("logs", container)
    message = (
        f"{container} never answered {READINESS_PATH} with {OK} within {READY_TIMEOUT_SECONDS}s.\n"
        f"--- container log ---\n{logs.stdout}\n{logs.stderr}"
    )
    raise AssertionError(message)


def _published_base_url(container: str) -> str:
    """Return the base URL the runtime published the container's port at.

    The host port is assigned by the runtime rather than chosen here, so two
    sessions on one machine cannot collide and no test has to guess what is free.

    Args:
        container: The container name.

    Returns:
        The `http://host:port` base URL.
    """
    published = _docker("port", container, CONTAINER_PORT)
    assert published.returncode == 0, f"could not read the published port of {container}: {published.stderr}"
    # `docker port` answers one line per binding, `0.0.0.0:49154` or
    # `[::]:49154`; the first is the IPv4 one this harness asked for.
    binding = published.stdout.strip().splitlines()[0]
    port = binding.rpartition(":")[2]
    return f"http://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    """Build the machinery image, and remove it again.

    Built from the repository root with no `--platform` of its own: the
    `Dockerfile`'s `FROM` pins `linux/amd64` because `pixi.lock` declares
    `linux-64` and no `linux-aarch64`, so `pixi install --locked` cannot resolve
    on any other base. Passing the platform here as well would be a second
    declaration of the same fact.

    Yields:
        The tag the image was built under.
    """
    built = _docker("build", "--tag", IMAGE_TAG, ".", timeout=BUILD_TIMEOUT_SECONDS)
    try:
        assert built.returncode == 0, f"the machinery image did not build:\n{built.stdout}\n{built.stderr}"
        yield IMAGE_TAG
    finally:
        _docker("image", "rm", "--force", IMAGE_TAG)


@pytest.fixture(scope="module")
def network() -> Iterator[str]:
    """Create a network of this session's own, and remove it again.

    Its own network rather than the default bridge, so the component reaches the
    database by container name and neither container is discoverable by anything
    else on the machine.

    Yields:
        The network name.
    """
    created = _docker("network", "create", NETWORK_NAME)
    try:
        assert created.returncode == 0, f"could not create the probe network: {created.stderr}"
        yield NETWORK_NAME
    finally:
        _docker("network", "rm", NETWORK_NAME)


@pytest.fixture(scope="module")
def database(network: str) -> Iterator[str]:
    """Start PostgreSQL on the session network, and remove it again.

    Yields:
        The `DATABASE_URL` the component connects with.
    """
    started = _docker(
        "run",
        "--detach",
        "--name",
        DATABASE_CONTAINER,
        "--network",
        network,
        "-e",
        f"POSTGRES_USER={POSTGRES_CREDENTIAL}",
        "-e",
        f"POSTGRES_PASSWORD={POSTGRES_CREDENTIAL}",
        "-e",
        f"POSTGRES_DB={POSTGRES_CREDENTIAL}",
        POSTGRES_IMAGE,
    )
    try:
        assert started.returncode == 0, f"could not start {POSTGRES_IMAGE}: {started.stderr}"
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            probe = _docker("exec", DATABASE_CONTAINER, "pg_isready", "-U", POSTGRES_CREDENTIAL)
            if probe.returncode == 0:
                break
            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            logs = _docker("logs", DATABASE_CONTAINER)
            message = f"{POSTGRES_IMAGE} never became ready:\n{logs.stdout}\n{logs.stderr}"
            raise AssertionError(message)
        yield (
            f"postgres://{POSTGRES_CREDENTIAL}:{POSTGRES_CREDENTIAL}@{DATABASE_CONTAINER}:5432/{POSTGRES_CREDENTIAL}"
        )
    finally:
        _remove_container(DATABASE_CONTAINER)


@pytest.fixture(scope="module")
def released(image: str, network: str, database: str) -> str:
    """Run the release stage against the database, exactly as `component.toml` declares it.

    One invocation per declared step, each through `pixi run manage <step>` --
    the form `docs/deployment.md` gives a deployment repository, and the form
    those steps are shaped for (arguments to `manage.py`, never a shell command).
    A serving process refuses to start against a schema nobody has recognized
    (`_refuse_unapplied_migrations`), so without this the `web` runs below would
    be asserting the refusal rather than the payload.

    Nothing about this contradicts AD-22. The step is performed *by the harness*,
    once, as a non-serving invocation of the same image, before anything serves.
    The image itself still declares no instruction that runs one, which is the
    property `tests/unit/test_release_stage.py` holds.

    Args:
        image: The built image tag.
        network: The session network.
        database: The `DATABASE_URL` to release against.

    Returns:
        The same `DATABASE_URL`, so a caller depends on the released database
        rather than on the raw one.
    """
    declaration = load_component_declaration()
    assert declaration.databases, "component.toml declares no database, so there is no release stage to run"
    for entry in declaration.databases:
        for step in entry.migrate:
            applied = _docker(
                "run",
                "--rm",
                "--network",
                network,
                "--user",
                ARBITRARY_UID,
                *_environment_arguments(_component_environment(database)),
                image,
                "pixi",
                "run",
                "manage",
                *step.split(),
            )
            assert applied.returncode == 0, (
                f"the release-stage step {step!r} for alias {entry.alias!r} failed:\n{applied.stdout}\n{applied.stderr}"
            )
    return database


@pytest.fixture(scope="module")
def read_only_container(image: str, network: str, released: str) -> Iterator[str]:
    """Start the component read-only under an arbitrary UID, and remove it again.

    `--read-only --tmpfs /tmp --user 12345:0` is the whole of AC #2 expressed as
    runtime flags: a root filesystem nothing can write to, one temporary
    directory that is not part of the image, and a UID the image has never seen.

    Yields:
        The published base URL, once readiness has answered.
    """
    started = _docker(
        "run",
        "--detach",
        "--name",
        READ_ONLY_CONTAINER,
        "--network",
        network,
        "--user",
        ARBITRARY_UID,
        "--read-only",
        "--tmpfs",
        TEMPORARY_DIRECTORY,
        "--publish",
        f"127.0.0.1::{CONTAINER_PORT}",
        *_environment_arguments(_component_environment(released)),
        image,
    )
    try:
        assert started.returncode == 0, f"the component did not start read-only: {started.stderr}"
        base_url = _published_base_url(READ_ONLY_CONTAINER)
        _wait_until_ready(base_url, READ_ONLY_CONTAINER)
        yield base_url
    finally:
        _remove_container(READ_ONLY_CONTAINER)


@pytest.fixture(scope="module")
def writable_container(image: str, network: str, released: str) -> Iterator[str]:
    """Start the component with a writable root, serve one request, stop it, and keep it.

    Kept rather than removed on the way out of the `with`, because `docker diff`
    reads a *stopped* container's layer and there is nothing to read once it has
    been deleted. Teardown removes it.

    Writable is the point: a `--read-only` container's diff is empty whatever the
    image wanted to do, so the no-writes claim can only be asserted where writing
    was possible. Nothing is mounted over any path in `/app` -- the image keeps
    pixi's task cache out of the application root itself, so what `docker diff`
    reports here is the whole of what the container wrote.

    Yields:
        The container name, stopped, ready to be diffed.
    """
    started = _docker(
        "run",
        "--detach",
        "--name",
        WRITABLE_CONTAINER,
        "--network",
        network,
        "--user",
        ARBITRARY_UID,
        "--publish",
        f"127.0.0.1::{CONTAINER_PORT}",
        *_environment_arguments(_component_environment(released)),
        image,
    )
    try:
        assert started.returncode == 0, f"the component did not start writable: {started.stderr}"
        base_url = _published_base_url(WRITABLE_CONTAINER)
        _wait_until_ready(base_url, WRITABLE_CONTAINER)
        # Served, not merely started: a process that had booted and never handled
        # a request would not have exercised the request path, which is where a
        # write to the source tree, to a log file or to media would arise.
        assert _probe(base_url, LIVENESS_PATH) == OK
        stopped = _docker("stop", "--time", STOP_TIMEOUT_SECONDS, WRITABLE_CONTAINER)
        assert stopped.returncode == 0, f"could not stop {WRITABLE_CONTAINER}: {stopped.stderr}"
        yield WRITABLE_CONTAINER
    finally:
        _remove_container(WRITABLE_CONTAINER)


def test_the_component_starts_read_only_under_an_arbitrary_uid(read_only_container: str) -> None:
    """AC #2: an arbitrary non-root UID and a read-only root filesystem, and startup succeeds.

    The fixture has already waited for readiness, so reaching this case at all is
    most of the assertion. What is added here is that the container is still
    serving after the wait rather than having answered once on the way past --
    a process that boots, answers and then dies of a write it could not perform
    would satisfy a one-shot probe.

    Nothing about this run is configured by a file. The container is given
    environment variables and an image, and no mount, no `.env` and no settings
    file participate.
    """
    assert _probe(read_only_container, READINESS_PATH) == OK, (
        "readiness stopped answering on a read-only root filesystem after having answered once, which is a "
        "component that starts and then fails on a write rather than one that needs no writes."
    )


def test_liveness_answers_immediately_and_readiness_answers_once_the_database_does(
    read_only_container: str,
) -> None:
    """AC #2, and the distinction between the two probes the platform relies on.

    Liveness is unconditional and touches nothing: it answers 200 for as long as
    the process is alive, because a liveness probe that consults a dependency
    turns a database blip into a restart loop. Readiness answers 200 only once
    every required alias has answered `SELECT 1`, which is what the release stage
    above made possible.

    Both, in one case, because the pair is the assertion: two probes that both
    answered unconditionally would pass a liveness-only check, and
    `docs/deployment.md` records at length what swapping them costs.
    """
    assert _probe(read_only_container, LIVENESS_PATH) == OK, (
        "liveness did not answer 200. It is unconditional and consults nothing; a non-200 here is the "
        "process being unable to serve at all."
    )
    assert _probe(read_only_container, READINESS_PATH) == OK, (
        "readiness did not answer 200 against a released database. Readiness answers once every required "
        "alias has answered SELECT 1."
    )


def test_the_component_writes_nothing_outside_the_temporary_directory(writable_container: str) -> None:
    """AC #2 and AC #3: the zero-writable-path claim, asserted rather than assumed.

    Against a container that *could* have written anywhere, which is the only
    kind of run in which the claim means anything.

    Three assertions, and the first exists because the other two are assertions
    of *absence*. An empty diff satisfies both of them perfectly, and an empty
    diff is also what a diff read from the wrong container, or from one that
    never started, looks like -- so the case first requires that the container
    wrote *something*. It always does: gunicorn creates its own temporary
    directory under `/tmp` before it binds.

    The second is the one AC #2 names. Nothing under `/app` may change: not
    `staticfiles/`, which was collected at build; not `src/`, which is why the
    image sets `PYTHONDONTWRITEBYTECODE` -- CPython would otherwise write
    `__pycache__` beside the source the editable install resolves, on the first
    request of every container. The third is wider and is the property itself:
    every path that changed at all is inside the temporary directory.
    """
    diffed = _docker("diff", writable_container)
    assert diffed.returncode == 0, f"could not diff {writable_container}: {diffed.stderr}"

    changed = [line.split(" ", 1)[1] for line in diffed.stdout.splitlines() if " " in line]
    assert changed, (
        f"{writable_container} served a request and changed no path at all, not even under "
        f"{TEMPORARY_DIRECTORY}. gunicorn creates a temporary directory before it binds, so an empty diff "
        f"is a diff being read from the wrong place rather than a component that writes nothing -- and it "
        f"would satisfy both assertions below without asserting anything."
    )

    inside_application = sorted(
        path for path in changed if path == APPLICATION_ROOT or path.startswith(f"{APPLICATION_ROOT}/")
    )
    assert not inside_application, (
        f"the container wrote inside {APPLICATION_ROOT}: {inside_application}. AC #2: the component "
        f"declares no writable path beyond a temporary directory, so a payload that modifies its own "
        f"application root cannot run on a read-only root filesystem."
    )

    outside_temporary = sorted(
        path for path in changed if not (path == TEMPORARY_DIRECTORY or path.startswith(f"{TEMPORARY_DIRECTORY}/"))
    )
    assert not outside_temporary, (
        f"the container wrote outside {TEMPORARY_DIRECTORY}: {outside_temporary}. Static files are "
        f"collected at build and served by the application, user media is a non-goal (FR-25), logs go to "
        f"the event stream and sessions are database-backed -- so there is nothing left that needs to "
        f"write anywhere else."
    )


def test_no_configuration_file_is_present_in_the_image(image: str) -> None:
    """AC #1: no configuration file is present, searched for rather than reasoned about.

    `tests/unit/test_payload_properties.py` asserts that no `COPY` instruction
    brings one in, which is the same claim made at the point of entry. This is
    the claim made against the finished artefact, and the two fail differently:
    a `.env` could arrive in a base image, be written by a build step, or land
    through a path the COPY scan reads as innocuous.

    The whole filesystem, at every level, excluding only the pseudo-filesystems
    the runtime mounts -- `-xdev` keeps the search on the image's own layers
    rather than descending into `/proc` and `/sys`.
    """
    found = _docker(
        "run",
        "--rm",
        "--entrypoint",
        "/bin/sh",
        image,
        "-c",
        'find / -xdev \\( -name ".env" -o -name ".envs" \\) 2>/dev/null; exit 0',
    )
    assert found.returncode == 0, f"could not search the image for configuration files: {found.stderr}"
    present = sorted(line for line in found.stdout.splitlines() if line.strip())
    assert not present, (
        f"the image carries configuration files: {present}. FR-38: a component's configuration is "
        f"exclusively environmental, and an image carrying one starts correctly while being configured by "
        f"something no deployment manifest names."
    )


def test_static_files_are_baked_into_the_image(image: str) -> None:
    """AC #3's static leg: collected at build, so nothing collects at run time.

    The manifest is what makes this more than a file count.
    `whitenoise.storage.CompressedManifestStaticFilesStorage` resolves every
    `{% static %}` reference through `staticfiles.json`, and a component whose
    manifest was missing would raise on the first template render rather than
    serve an unhashed file -- so the manifest's presence in the *image* is what
    says the collection happened at build and not at boot.
    """
    listed = _docker(
        "run",
        "--rm",
        "--user",
        ARBITRARY_UID,
        "--read-only",
        "--tmpfs",
        TEMPORARY_DIRECTORY,
        "--entrypoint",
        "/bin/sh",
        image,
        "-c",
        f"find {APPLICATION_ROOT}/staticfiles -type f | wc -l && cat {APPLICATION_ROOT}/staticfiles/staticfiles.json",
    )
    assert listed.returncode == 0, f"the image carries no collected static files: {listed.stderr}"
    count, _, manifest = listed.stdout.partition("\n")
    assert int(count.strip()) > 0, "the image's staticfiles directory is empty"
    assert json.loads(manifest)["paths"], (
        "the image carries a staticfiles manifest with no paths in it. WhiteNoise resolves every static "
        "reference through it, so an empty manifest is a component that raises on its first render."
    )
