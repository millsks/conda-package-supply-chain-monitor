"""`CPM-PLATFORM-S03`: the local stack, and the two ways it fails without saying so.

`pixi run local-stack` brings up Redis and PostgreSQL in containers and runs the web
process, a worker, beat and flower from the pixi environment. The web process is the
**deployed** command -- gunicorn with the draining uvicorn worker -- because a stack
whose purpose is to run the product the way it actually runs should serve it the way
production does. Both of its defects
during development were **quiet** — the stack started, printed banners, and did
nothing — which is why they are cases here rather than notes.

**A bare `pixi run worker` reads deployed settings.** `COMPONENT_RUNTIME=local` comes
from `[feature.dev.activation.env]` and from nowhere else;
`tests/unit/test_locality_declaration.py` fails the gate on any task that declares it.
So a `Procfile` line without `-e dev` resolves in `default`, finds no broker URL, and
falls back to Celery's built-in `amqp://guest@localhost:5672`. The worker then starts,
drains the right queue *names*, and consumes nothing, because it is connected to a
RabbitMQ that is not running.

**The containers publish on 6380 and 5433, not 6379 and 5432.** A developer machine
very often already has a Redis on the default port, and this product calls
`cache.clear()`, which flushes an entire Redis database. A stack that talked to
"whatever was already there" would be one bad afternoon away from flushing somebody
else's project.

**None of the stack's tasks is a deployment process, and that is asserted rather than
assumed.** `component.toml` declares the process group and
`tests/unit/test_process_model.py` reconciles it in both directions. These tasks are
development conveniences: `local-stack` is not a process type this component deploys,
and flower is a monitor rather than one of `[[admin_processes]]` — that table requires
a Django management command, which flower is not. Without the cases below, the next
person to read the process-model test would "fix" the omission by declaring them.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any
from typing import Final

import pytest
import yaml

#: The repository root, from this file rather than from a layout assumption.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PIXI: Final[Path] = REPO_ROOT / "pixi.toml"
PROCFILE: Final[Path] = REPO_ROOT / "Procfile"
COMPOSE: Final[Path] = REPO_ROOT / "compose.yaml"
STACK_DOWN: Final[Path] = REPO_ROOT / "scripts" / "local-stack-down.sh"

#: The tasks that make up the local stack and must stay outside the process group.
OUTSIDE_THE_PROCESS_GROUP: Final[tuple[str, ...]] = (
    "local-stack",
    "local-stack-down",
    "stack-migrate",
    "stack-personas",
    "stack-seed",
    "flower",
    "docker-up",
    "docker-down",
    "docker-down-v",
    "docker-logs",
    "docker-ps",
    "docker-psql",
    "docker-redis",
)

#: The variable that makes a task a member of the deployment's process group.
THE_MEMBERSHIP_MARKER: Final[str] = "COMPONENT_PROCESS"

#: Every task that runs *against* the local stack's containers.
#:
#: They are a set rather than one task because `CPM-PLATFORM-S06`: `migrate`,
#: `seed-personas` and `seed-demo` run against whatever the default environment
#: resolves -- SQLite -- while `local-stack` runs against the compose PostgreSQL. Two
#: databases, and nothing said so, so the documented first-run sequence seeded one and
#: started the other: a hundred packages in a file nothing was reading, and no personas
#: in the database serving the screens, which left no way to sign in and find out.
#:
#: The fix was three tasks carrying the stack's own environment, and the risk the fix
#: creates is four copies of one database URL. That is the shape the defect had, so
#: `test_every_stack_task_names_the_same_database` reconciles them.
AGAINST_THE_STACK: Final[tuple[str, ...]] = (
    "local-stack",
    "stack-migrate",
    "stack-personas",
    "stack-seed",
)

#: Host ports the compose services must **not** publish on.
#:
#: The defaults. See the module docstring: a stack that reached whatever was already
#: listening would eventually flush a Redis database belonging to something else.
PORTS_TOO_LIKELY_TO_BE_TAKEN: Final[frozenset[str]] = frozenset({"6379", "5432"})


def manifest() -> dict[str, Any]:
    """Return the parsed pixi manifest.

    Returns:
        The whole manifest.

    """
    return tomllib.loads(PIXI.read_text(encoding="utf-8"))


def tasks() -> dict[str, Any]:
    """Return every declared task, across the root table and every feature.

    Returns:
        Task name to its definition.

    """
    parsed = manifest()
    found: dict[str, Any] = dict(parsed.get("tasks", {}))
    for feature in parsed.get("feature", {}).values():
        found.update(feature.get("tasks", {}))
    return found


def procfile_lines() -> dict[str, str]:
    """Return the `Procfile`'s processes.

    Returns:
        Process name to the command honcho runs for it.

    """
    found: dict[str, str] = {}
    for line in PROCFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        name, _, command = stripped.partition(":")
        found[name.strip()] = command.strip()
    return found


# ---------------------------------------------------------------------------
# The quiet failure: a process that starts and does nothing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("process", sorted(procfile_lines()))
def test_every_stack_process_runs_in_the_dev_environment(process: str) -> None:
    """`-e dev`, or the process reads deployed settings and connects to nothing.

    This is the defect that shipped in the first draft. A worker without it starts,
    prints a banner listing the right queue names, and consumes nothing — because
    `COMPONENT_RUNTIME` came from `default`, the settings had no broker URL, and
    Celery fell back to `amqp://guest@localhost:5672`.

    Nothing errors. The stack looks like it is running.

    Args:
        process: The `Procfile` process name.

    """
    command = procfile_lines()[process]

    assert command.startswith("pixi run -e dev "), (
        f"{process!r} runs {command!r}. Without `-e dev` it resolves in the `default` environment, reads "
        f"deployed settings, and finds no broker -- and says so nowhere."
    )


@pytest.mark.parametrize("process", sorted(procfile_lines()))
def test_every_stack_process_delegates_to_a_declared_task(process: str) -> None:
    """The `Procfile` names tasks; it does not spell commands.

    `pixi.toml` is where a process's command is declared and `component.toml`
    reconciles the deployed ones against it. A command written out here would be a
    second spelling, and the two would disagree the first time somebody changed a
    queue name or a scheduler.

    Args:
        process: The `Procfile` process name.

    """
    task = procfile_lines()[process].removeprefix("pixi run -e dev ").strip()

    assert task in tasks(), f"{process!r} runs {task!r}, which `pixi.toml` does not declare."


# ---------------------------------------------------------------------------
# The deployment contract: these are conveniences, not process types.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task", OUTSIDE_THE_PROCESS_GROUP)
def test_no_local_stack_task_joins_the_deployment_process_group(task: str) -> None:
    """Declared exclusion, so nobody later "fixes" it by adding a declaration.

    `component.toml` declares the process group and `test_process_model.py`
    reconciles it in both directions -- no declared process may name a task that does
    not exist, and no task in the group may go undeclared. A `COMPONENT_PROCESS` on
    any of these would put a local convenience into the deployment contract.

    Flower is the one worth spelling out: it is a monitor, and the obvious home would
    be `[[admin_processes]]` -- except that table requires a Django management
    command, which flower is not.

    Args:
        task: The task that must stay outside the group.

    """
    declared = tasks()
    assert task in declared, f"{task!r} is listed here and `pixi.toml` does not declare it."

    assert THE_MEMBERSHIP_MARKER not in declared[task].get("env", {}), (
        f"{task!r} declares {THE_MEMBERSHIP_MARKER}, which makes it a member of the deployment's process group. "
        f"It is a local development convenience; the group is what this component *deploys*."
    )


def test_the_stack_runs_the_application_outside_the_containers() -> None:
    """Compose brings up infrastructure; pixi runs the application.

    A `web` service here would mean a rebuild on every edit and a second, slower way
    to run what pixi already runs -- and the pixi environment is the one runtime. It
    is also what keeps the compose file honest about being local-only: `Dockerfile`
    is what builds the deployable image.
    """
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]

    assert set(services) == {"redis", "postgres"}, sorted(services)


# ---------------------------------------------------------------------------
# The port choice, which is a safety property rather than a preference.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("service", ["redis", "postgres"])
def test_no_service_publishes_on_a_port_something_else_probably_holds(service: str) -> None:
    """6379 and 5432 are taken on a developer machine more often than not.

    Publishing onto one either fails to bind or -- worse -- the stack talks to
    whatever was already there. This product calls `cache.clear()`, which flushes an
    entire Redis database, so "whatever was already there" is not a risk worth the
    convenience of a default port.

    Args:
        service: The compose service.

    """
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    published = {entry.split(":")[0] for entry in compose["services"][service]["ports"]}

    assert not published & PORTS_TOO_LIKELY_TO_BE_TAKEN, (
        f"{service} publishes on {sorted(published & PORTS_TOO_LIKELY_TO_BE_TAKEN)}, which a developer machine "
        f"very often already has something on."
    )


def test_the_stack_points_at_the_containers_it_started() -> None:
    """Explicitly, rather than by hoping the defaults match.

    `REDIS_URL` defaults to `localhost:6379` and the database defaults to SQLite. A
    stack that left both alone would talk to neither of the containers it just
    brought up.
    """
    stack = tasks()["local-stack"]
    env = stack.get("env", {})

    assert "6380" in env.get("REDIS_URL", ""), env
    assert "5433" in env.get("DATABASE_URL", ""), env
    assert env.get("CELERY_TASK_ALWAYS_EAGER") == "0", (
        "local settings run tasks inline by default, which would leave the worker, beat and flower idle while "
        "the web process quietly did their work."
    )
    assert "docker-up" in stack.get("depends-on", []), stack


@pytest.mark.parametrize("task", AGAINST_THE_STACK)
def test_every_stack_task_names_the_same_database(task: str) -> None:
    """Four copies of one URL, which is the shape the defect this prevents had.

    `migrate` and the two seeders run against the *default* environment -- SQLite --
    and `local-stack` runs against the compose PostgreSQL. Following the documented
    first-run sequence and then starting the stack produced a product with no packages
    and no personas: nothing to look at, and no way to sign in and discover that.

    A fifth task added later that seeded the wrong database would reproduce it exactly,
    and nothing else in this suite would notice -- the seeding would succeed, the stack
    would start, and the screens would simply be empty.

    Args:
        task: The task under test.

    """
    env = tasks()[task].get("env", {})

    assert "5433" in env.get("DATABASE_URL", ""), f"{task} does not run against the stack's PostgreSQL: {env}"
    assert "6380" in env.get("REDIS_URL", ""), f"{task} does not point at the stack's Redis: {env}"


def test_the_stack_migrates_before_it_serves() -> None:
    """So a fresh clone's first `local-stack` finds a schema rather than no tables.

    The containers come up empty. Without this, the first command somebody runs after
    cloning starts four processes against a database with none of this product's
    fifty-two tables, and every one of them fails in a different way.
    """
    assert "stack-migrate" in tasks()["local-stack"].get("depends-on", [])


def test_seeding_is_not_something_the_stack_does_on_every_start() -> None:
    """Evidence is append-only, so seeding twice appends rather than replacing.

    A stack that seeded on start-up would add a second observation of every seeded fact
    on every restart -- which is realistic behaviour for the seeder and absurd
    behaviour for a start-up task.
    """
    assert "stack-seed" not in tasks()["local-stack"].get("depends-on", [])


# ---------------------------------------------------------------------------
# The way down when honcho did not take its children with it.
# ---------------------------------------------------------------------------


def test_the_way_down_is_the_script_and_the_script_is_scoped_to_this_checkout() -> None:
    """`local-stack-down` finds stragglers by this checkout's environment, not by name.

    Closing the terminal, or `kill -9` on honcho, reparents gunicorn, flower, beat
    and the worker to PID 1, where they hold 8000 and 5555 until somebody finds them
    by hand. The script is what finds them -- and it must match on the interpreter
    path under *this* repository's `.pixi/envs/dev`, because the sibling repository's
    stack runs a worker with the same `-A config.celery_app`, and a match on the
    command name alone would kill that one too.
    """
    task = tasks()["local-stack-down"]
    assert task["cmd"] == f"bash {STACK_DOWN.relative_to(REPO_ROOT)}", task

    script = STACK_DOWN.read_text(encoding="utf-8")
    assert ".pixi/envs/dev/bin/(gunicorn|celery)" in script, "the match is on this checkout's environment path"
    assert "pkill -TERM" in script, "a warm shutdown first: an idle worker exits cleanly on TERM"
    assert "pkill -KILL" in script, "a worker's warm shutdown waits for in-flight tasks, and a stuck one waits forever"
    assert "pixi run docker-down" in script, "the containers come down last, so the worker is not left reconnecting"


def test_the_way_down_does_not_discard_the_data() -> None:
    """`docker-down`, not `docker-down-v`: stopping the stack is not resetting it.

    The seeded inventory is append-only evidence that took a command to produce.
    A stop that discarded it would make `stack-seed` a prerequisite of every
    restart, which is the trap `local-stack` itself deliberately avoids.
    """
    commands = [
        line.strip()
        for line in STACK_DOWN.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert "pixi run docker-down" in commands, commands
    assert not any("docker-down-v" in command for command in commands), commands


@pytest.mark.parametrize("path", [PIXI, PROCFILE, COMPOSE, STACK_DOWN], ids=lambda path: path.name)
def test_the_files_this_module_reads_are_where_it_thinks(path: Path) -> None:
    """So every case above cannot pass by parsing nothing.

    Args:
        path: The file that must exist.

    """
    assert path.is_file(), path
