"""Migration is a release-stage step, and nothing in the component performs it (AD-22).

The property this file keeps is the *absence* of a behaviour, which is why the
artefact is a test rather than a module. AD-22's rule is that **no entrypoint,
task or container command runs migrations**: the deployment repository applies
them once per database before new pods serve, exactly as `component.toml`
declares, and a serving process that finds an unrecognized schema refuses to
start rather than repairing it.

Absence is the hardest kind of rule to keep, because nothing fails on the day it
is broken. `depends-on = ["migrate"]` added to `web` is one line, it makes a
developer's `pixi run web` work against a fresh database, and it turns every
rolling deploy into N replicas racing to apply the same migration. So the check
here is **transitive**: a process task fails if its own command migrates, and it
fails equally if anything it depends on -- at any depth -- migrates.

**Three surfaces, because there are three ways in.**

* The pixi tasks, which are how the deployment repository starts a process
  (AD-14). Membership in the process group is structural, not nominal: it is
  exactly the set of tasks whose `env` declares `COMPONENT_PROCESS` (AD-26), and
  it is computed by `tests/pixi_manifest.py` so that this module and
  `tests/unit/test_process_model.py` cannot disagree about what the group is.
* The boot-time entrypoint modules -- the WSGI and ASGI applications gunicorn
  and uvicorn import, the gunicorn worker class the `web` task names, and the
  Celery application `worker` and `beat` name. A `call_command("migrate")` in
  any of them runs inside every replica at every boot.
* The `Dockerfile`, whose executing instructions are the container half of the
  same question. Story 5.6 landed it as `machinery` (AD-15), and the assertion
  written here for a file that did not exist yet armed itself on that day with
  no edit. Its `pytest.skip` branch stays where it is: what it accommodates is
  *absence*, and absence is the normal state of this file in a materialized
  component, so removing the branch would make this module unusable in the one
  place AD-15 says the Dockerfile will not be.

**The other direction: what must *not* be a serving process.** `migrate` and
`collectstatic` are a release-stage and a build-stage step. Neither may declare
`COMPONENT_PROCESS`, and the reason is the deadlock AD-13 names rather than
tidiness: process type fails *open* precisely so that `pixi run migrate` is not a
serving process, because the stage-2 unapplied-migrations refusal would otherwise
fire against the one command that clears the state it refuses on, and the release
stage would have no way forward at all.

**What this file does not own.** The refusal itself is Epic 4's, condition 7 of
the nine-condition table, and it lives in `src/config/startup/stage_two.py` with
one owner (AD-26). Nothing here reimplements, moves or relaxes it;
`tests/integration/test_release_stage.py` asserts its behaviour from the
deployment side, and FR-16's own condition test is
`tests/integration/startup/test_stage_two_database_conditions.py`.

Disposition `core`: these assertions run inside every combination's gate. They
are written against whatever `pixi.toml` and `component.toml` are at the
repository root, with no path assumption beyond that, and the process group is
derived rather than named -- so they hold unchanged in a combination where the
`celery` region has removed `worker` and `beat`.

These are unit tests: they read repository files and consult Django's own
command registry. No database, no network.
"""

from __future__ import annotations

import ast
import re
import shlex
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.core.management import get_commands

from config.component import load_component_declaration
from config.locality import PROCESS_ENV_VAR
from tests.dockerfile import DOCKERFILE
from tests.dockerfile import EXECUTING_INSTRUCTIONS
from tests.dockerfile import instruction_lines
from tests.pixi_manifest import REPO_ROOT
from tests.pixi_manifest import load_manifest
from tests.pixi_manifest import process_group
from tests.pixi_manifest import task_command
from tests.pixi_manifest import task_dependencies
from tests.pixi_manifest import task_env
from tests.pixi_manifest import tasks
from tests.pixi_manifest import tasks_named

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from config.component import ComponentDeclaration

# The two Django commands that write to the migration graph or to
# `django_migrations`. `migrate --check` is `migrate` with a flag, so naming the
# base command covers it; `makemigrations` is here because a component that
# authored migrations at start-up would be generating schema on a serving
# process, which is the same defect one step earlier.
#
# Matched as whole words rather than as substrings, and the character class in
# both look-arounds is what makes that true against real commands: `--no-migrate`
# is not a migrate invocation, and neither is a dotted module path that happens
# to end in one. A bare substring search would also match this module's own
# prose, which is the failure mode the spec names for the Dockerfile assertion
# and which applies just as much here.
MIGRATION_INVOCATION: Final[re.Pattern[str]] = re.compile(r"(?<![\w.-])(?:migrate|makemigrations)(?![\w.-])")

# The tasks this manifest is supposed to have that migrate, and the complete
# list of them. `migrate` is the release stage's own invocation and
# `makemigrations` authors migrations in development; a third name matching the
# detector is either an aggregate of the declared steps or an entrypoint in
# waiting.
MIGRATION_TASKS: Final[tuple[str, ...]] = ("makemigrations", "migrate")

# The release-stage and build-stage steps. Neither is a serving process, and the
# consequence of declaring either one to be is not cosmetic -- see the module
# docstring, and AD-13.
NON_SERVING_STEPS: Final[tuple[str, ...]] = ("migrate", "collectstatic")

# The feature that owns `celery_app.py`, and the four entrypoint modules a
# process loads at boot, each mapped to the feature that owns it -- `None` for
# the three that are `core` and exist in every combination.
#
# `config/asgi.py` is what gunicorn and uvicorn load and `config/wsgi.py` is the
# synchronous equivalent. `config/workers.py` is loaded just as early: the `web`
# task names `-k config.workers.DrainingUvicornWorker`, so gunicorn imports it in
# every worker process. `config/celery_app.py` is the `-A config.celery_app` the
# `worker` and `beat` tasks name. A management command invoked from any of them
# runs in every replica at every boot -- the same defect as an entrypoint
# migration, arriving through the queue rather than through the web tier.
CELERY_FEATURE: Final[str] = "celery"
ENTRYPOINT_MODULES: Final[dict[str, str | None]] = {
    "asgi.py": None,
    "wsgi.py": None,
    "workers.py": None,
    "celery_app.py": CELERY_FEATURE,
}

# The management package no entrypoint may reach for, and the one callable that
# would run a command from inside a process. Both are checked, because importing
# the package is how the call becomes available and the call is how it happens.
MANAGEMENT_PACKAGE: Final[str] = "django.core.management"
COMMAND_RUNNER: Final[str] = "call_command"

# Where the Dockerfile reader went, and why it is not here any more.
#
# `DOCKERFILE`, `EXECUTING_INSTRUCTIONS` and the parser this module wrote moved
# to `tests/dockerfile.py` when Story 5.6 landed the file and needed the same
# instruction reading for a second set of assertions -- the FR-38/FR-39 payload
# properties in `tests/unit/test_payload_properties.py`. It is imported from
# there rather than copied, for the reason `tests/pixi_manifest.py` records about
# the pixi manifest: two parsers that can disagree about what an instruction *is*
# would let a line escape one module's assertion while satisfying the other's.
# Nothing about the parse changed in the move, and its execution -- the synthetic
# cases below -- deliberately stayed here, because the second half of each case
# asserts the *migration* count, which is this module's question rather than the
# parser's.

# The page that carries the release-stage contract in prose, and the two headings
# this story wrote into it. Pinned by literal, as
# `tests/unit/test_component_declaration.py` pins its own: the R-3 price is
# recorded under its own subheading rather than mitigated, and a price nobody can
# find is not recorded. Renaming a heading is fine -- doing it without noticing
# that two module docstrings promise a reader they will find it is not.
DEPLOYMENT_DOC: Final[Path] = REPO_ROOT / "docs" / "deployment.md"
RELEASE_STAGE_HEADING: Final[str] = "## Migrations are a release-stage step"
ACCEPTED_RISK_HEADING: Final[str] = "### Accepted risk R-3: the refusal only fires for a declared process"

# What `component.toml`'s `[[databases]] migrate` steps are: arguments to
# `manage.py`, not shell commands. The deployment repository runs each one
# through pixi (`pixi run manage <step>`), so a step that spelled its own
# interpreter or its own manifest path would be declaring a second invocation
# mechanism beside the one AD-14 gives it.
STEP_MUST_NOT_START_WITH: Final[frozenset[str]] = frozenset(
    {"python", "python3", "pixi", "manage.py", "./manage.py", "django-admin", "django-admin.py"}
)

# The option a step names its target alias with. Long form only: Django's own
# `migrate` declares `--database` and no short alias, so a second spelling here
# would be inventing one.
DATABASE_OPTION: Final[str] = "--database"

# The option that makes a step runnable where nothing can answer a prompt. Both
# spellings, because Django's own `--noinput` argument declares `--no-input`
# alongside it and a step using the second is not making a different decision.
#
# Structural rather than stylistic: the release stage runs unattended, with no
# TTY, so a step that stops to ask hangs the rollout -- before any new pod has
# started, with the old generation still serving and the deploy neither applied
# nor rolled back.
NO_INPUT_OPTIONS: Final[frozenset[str]] = frozenset({"--noinput", "--no-input"})

# The `depends-on` walk's positive control, and the only manifests in this file
# not read off disk.
#
# The transitive walk is the mechanism this module exists for, and no task in
# this repository's process group declares `depends-on` at all -- so every scan
# built on it runs over a dependency closure of exactly one task, and a walk that
# had stopped following `depends-on` entirely would look identical. These four
# synthetic manifests are what makes the walk observable: a process task reaching
# `migrate` at depth two, in both spellings pixi permits, plus the negative
# control that keeps the positive ones from passing on a scan that flags
# everything.
#
# The third is the case AD-22 names as the convenience to stop, arriving in the
# form that survives a name-only walk: `manage`'s own command is `python
# manage.py` and contains no migrate, and the migration is in the dependency
# entry's `args`.
SYNTHETIC_PROCESS_MANIFESTS: Final[tuple[tuple[str, dict[str, Any], str], ...]] = (
    (
        "a bare-string depends-on reaching migrate directly",
        {
            "tasks": {
                "web": {
                    "cmd": "gunicorn config.asgi:application",
                    "env": {PROCESS_ENV_VAR: "web"},
                    "depends-on": ["migrate"],
                },
                "migrate": {"cmd": "python manage.py migrate"},
            }
        },
        "migrate",
    ),
    (
        "a bare-string depends-on reaching migrate at depth two",
        {
            "tasks": {
                "web": {
                    "cmd": "gunicorn config.asgi:application",
                    "env": {PROCESS_ENV_VAR: "web"},
                    "depends-on": ["prepare"],
                },
                "prepare": {"cmd": "python manage.py check", "depends-on": ["migrate"]},
                "migrate": {"cmd": "python manage.py migrate"},
            }
        },
        "migrate",
    ),
    (
        "a table depends-on carrying the migration in its args, at depth two",
        {
            "tasks": {
                "web": {
                    "cmd": "gunicorn config.asgi:application",
                    "env": {PROCESS_ENV_VAR: "web"},
                    "depends-on": [{"task": "prepare"}],
                },
                "prepare": {
                    "cmd": "python manage.py check",
                    "depends-on": [{"task": "manage", "args": ["migrate", "--noinput"]}],
                },
                "manage": {"cmd": "python manage.py"},
            }
        },
        "manage",
    ),
    (
        "a depends-on chain of the same depth that reaches no migration",
        {
            "tasks": {
                "web": {
                    "cmd": "gunicorn config.asgi:application",
                    "env": {PROCESS_ENV_VAR: "web"},
                    "depends-on": ["prepare"],
                },
                "prepare": {"cmd": "python manage.py check", "depends-on": [{"task": "manage", "args": ["shell"]}]},
                "manage": {"cmd": "python manage.py"},
            }
        },
        "",
    ),
)


# The Dockerfile parser's own cases, and the reason they stay here.
#
# They were written when `Dockerfile` did not exist, because the case that scans
# it skipped and `instruction_lines` therefore had no execution at all -- a
# parser carrying four ways to miss an instruction, none of which anything would
# notice until the day the file landed and the assertion it feeds reported
# nothing. Story 5.6 has landed the file, and they are no less necessary for it:
# the real Dockerfile contains none of these forms, so it drives one path through
# the parser and would look identical against a reader that had stopped joining
# continuations or absorbing heredoc bodies.
#
# Each entry is one form an instruction can take, its expected parse, and how
# many of its instructions the migration scan must flag. The
# comment-inside-a-continuation case is the one that must flag *nothing*: prose
# about the prohibition is not a breach of it.
SYNTHETIC_DOCKERFILES: Final[tuple[tuple[str, str, tuple[tuple[int, str, str], ...], int], ...]] = (
    (
        "a continuation joined into the instruction that carries it",
        "RUN pixi run collectstatic \\\n    && pixi run migrate\n",
        ((1, "RUN", "pixi run collectstatic && pixi run migrate"),),
        1,
    ),
    (
        "an instruction whose last line is still continued",
        "RUN pixi run migrate \\\n",
        ((1, "RUN", "pixi run migrate"),),
        1,
    ),
    (
        "a comment between the lines of a continuation",
        "RUN pixi run collectstatic \\\n# migrate is a release-stage step, never a build step\n    && pixi run check\n",
        ((1, "RUN", "pixi run collectstatic && pixi run check"),),
        0,
    ),
    (
        "a heredoc body absorbed into the instruction that opened it",
        'RUN <<EOF\npixi run migrate\nEOF\nCMD ["pixi", "run", "web"]\n',
        ((1, "RUN", "<<EOF pixi run migrate"), (4, "CMD", '["pixi", "run", "web"]')),
        1,
    ),
    (
        "an ONBUILD prefix stripped from the instruction it wraps",
        "ONBUILD RUN pixi run migrate\n",
        ((1, "RUN", "pixi run migrate"),),
        1,
    ),
    (
        "a HEALTHCHECK, which executes on an interval for the life of the container",
        "HEALTHCHECK --interval=30s CMD pixi run migrate --check\n",
        ((1, "HEALTHCHECK", "--interval=30s CMD pixi run migrate --check"),),
        1,
    ),
    (
        "a file that describes an image and runs no migration",
        (
            "# migrate is a release-stage step; this image never runs one\n"
            'FROM ghcr.io/example/base:1\nCOPY . /app\nCMD ["pixi", "run", "web"]\n'
        ),
        ((2, "FROM", "ghcr.io/example/base:1"), (3, "COPY", ". /app"), (4, "CMD", '["pixi", "run", "web"]')),
        0,
    ),
)


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    """Return the parsed pixi manifest.

    Returns:
        The manifest, parsed from TOML.
    """
    return load_manifest()


@pytest.fixture(scope="module")
def declaration() -> ComponentDeclaration:
    """Return the repository's own component declaration.

    Read through the loader rather than with a second parse, so this module
    asserts against the records every other consumer sees -- the loader's own
    refusals included.

    Returns:
        The parsed and validated declaration.
    """
    return load_component_declaration()


def _migrates(command: str) -> bool:
    """Report whether a command string invokes a migration command.

    Args:
        command: The command as the manifest or the Dockerfile spells it.

    Returns:
        True when `migrate` or `makemigrations` appears as a word.
    """
    return MIGRATION_INVOCATION.search(command) is not None


def _reachable(manifest: dict[str, Any], name: str) -> Iterator[tuple[str, str]]:
    """Yield every task reachable from one task through `depends-on`, transitively.

    The task itself is yielded first, so a caller checking "does anything this
    process runs migrate" needs no special case for the process's own command.

    A dependency's `args` are appended to the command of the task it names,
    because that is what the dependency actually runs: `depends-on = [{ task =
    "manage", args = ["migrate", "--noinput"] }]` reaches a migration through a
    task whose own command is `python manage.py` and contains no migrate at all.
    Scanning the name's command alone would walk straight past it.

    Cycles terminate: a (name, arguments) pair is walked once, and the set of
    pairs is finite because the arguments come from the edges. pixi would reject
    a cyclic `depends-on` itself, but a walk that assumed so would hang rather
    than fail on a manifest that somehow carried one.

    Args:
        manifest: The parsed pixi manifest.
        name: The task to start from.

    Yields:
        (task name, the command that task runs with the arguments it was reached
        with), for the task and everything it depends on. A dependency naming a
        task the manifest does not declare contributes nothing -- that is
        `tests/unit/test_process_model.py`'s two-way gate to report, not this
        module's.
    """
    seen: set[tuple[str, str]] = set()
    pending: list[tuple[str, str]] = [(name, "")]
    while pending:
        current, arguments = pending.pop()
        if (current, arguments) in seen:
            continue
        seen.add((current, arguments))
        for _table, _name, definition in tasks_named(manifest, current):
            yield current, " ".join(part for part in (task_command(definition), arguments) if part)
            pending.extend(task_dependencies(definition))


def _migrating_processes(manifest: dict[str, Any]) -> list[str]:
    """Return every serving process in a manifest that reaches a migration.

    Factored out of the case that asserts the list is empty so that the positive
    control can drive the same expression over a manifest where it must not be.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        One line per offending reachability, sorted, empty when nothing migrates.
    """
    return sorted(
        f"process {process_type!r} (task {name!r} in {table}) reaches {reached!r}: {command!r}"
        for table, name, process_type in process_group(manifest)
        for reached, command in _reachable(manifest, name)
        if _migrates(command)
    )


def _migrating_instructions(instructions: list[tuple[int, str, str]]) -> list[str]:
    """Return every parsed instruction that executes something and migrates.

    Args:
        instructions: The parsed instructions, as `instruction_lines` returns.

    Returns:
        One line per offending instruction, sorted, empty when none migrates.
    """
    return sorted(
        f"line {number}: {instruction} {arguments!r}"
        for number, instruction, arguments in instructions
        if instruction in EXECUTING_INSTRUCTIONS and _migrates(arguments)
    )


def test_the_detector_recognizes_the_manifests_own_migration_tasks(manifest: dict[str, Any]) -> None:
    """The scans below mean nothing if the thing they look for cannot be seen.

    `migrate` and `makemigrations` are declared in this manifest and both must be
    matched. A predicate that had stopped matching -- a tightened look-around, a
    renamed command -- would make every case in this file pass by finding
    nothing, which is the shape of green this guard exists to prevent.
    """
    undetected = sorted(
        f"{name} = {task_command(definition)!r}"
        for name in ("migrate", "makemigrations")
        for _table, _name, definition in tasks_named(manifest, name)
        if not _migrates(task_command(definition))
    )
    assert not undetected, f"the migration detector no longer recognizes these declared tasks: {undetected}"
    assert not _migrates("gunicorn config.asgi:application --bind 0.0.0.0:8000"), (
        "the migration detector matches a command that does not migrate, so every case below is noise"
    )


def test_the_process_group_is_not_empty(manifest: dict[str, Any]) -> None:
    """No task declares a process type would make the transitive scan below vacuous."""
    assert process_group(manifest), (
        f"no task declares {PROCESS_ENV_VAR}, so the assertion that no serving process migrates holds "
        f"over nothing at all"
    )


def test_no_serving_process_migrates_directly_or_through_a_dependency(manifest: dict[str, Any]) -> None:
    """AC #1: no entrypoint or task runs migrations, at any depth (AD-22).

    The transitive half is the half this case exists for. `web` running gunicorn
    is obviously not a migration, and nobody would write one into that command;
    `depends-on = ["migrate"]` on the same task is one line, reads as a
    convenience, and produces N replicas applying the same migration
    concurrently on every rolling deploy -- the race AD-22 names in as many
    words.
    """
    offenders = _migrating_processes(manifest)
    assert not offenders, (
        f"these serving processes migrate: {offenders}. AD-22: no entrypoint, task or container command "
        f"runs migrations -- migration is a release-stage step the deployment repository performs once per "
        f"database before new pods serve, and a task that migrates races across replicas."
    )


@pytest.mark.parametrize(
    ("synthetic", "expected"),
    [(synthetic, expected) for _label, synthetic, expected in SYNTHETIC_PROCESS_MANIFESTS],
    ids=[label for label, _synthetic, _expected in SYNTHETIC_PROCESS_MANIFESTS],
)
def test_the_transitive_walk_finds_a_migration_reached_through_a_dependency(
    synthetic: dict[str, Any], expected: str
) -> None:
    """The positive control for the mechanism the case above is built on.

    No task in this repository's process group declares `depends-on`, so the
    assertion above runs over a dependency closure of exactly one task per
    process and would pass unchanged against a walk that had stopped following
    `depends-on` at all -- the vacuous green its two sibling guards exist to
    prevent for the *detector*, arriving instead through the *walk*.

    So the walk is driven here over manifests written for it: `migrate` reached
    directly, reached at depth two, and reached at depth two through a
    `{task, args}` entry whose named task does not migrate and whose `args` do.
    The last is the shape that survives a name-only walk, and it is the exact
    convenience AD-22 exists to stop. The fourth case reaches nothing and must
    report nothing, so a scan that flagged everything could not pass this set.
    """
    offenders = _migrating_processes(synthetic)
    if not expected:
        assert offenders == [], f"the walk reports a migration this manifest does not contain: {offenders}"
        return
    assert offenders, (
        f"the transitive depends-on walk reached no migration in {synthetic!r}. Every assertion in this "
        f"module that a serving process does not migrate is only as good as this walk."
    )
    assert any(f"reaches {expected!r}" in offender for offender in offenders), (
        f"the walk found a migration but not through {expected!r}: {offenders}"
    )


@pytest.mark.parametrize("step", NON_SERVING_STEPS)
def test_the_release_and_build_stage_steps_declare_no_process_type(manifest: dict[str, Any], step: str) -> None:
    """`migrate` and `collectstatic` are steps, not serving processes (AD-13).

    Declaring `COMPONENT_PROCESS` on `migrate` would make the stage-2
    unapplied-migrations refusal fire against the very command that clears the
    state it refuses on, and the release stage would deadlock against a refusal
    nothing could resolve. That is the deadlock AD-13 names as its reason for
    making process type fail *open*, and it arrives through this one line.

    `collectstatic` is a build-stage step and is held to the same rule for the
    same mechanical reason: it too is a management command, and a
    `COMPONENT_PROCESS` on it would put it inside the process group that
    `component.toml` has to reconcile.
    """
    declarations = tasks_named(manifest, step)
    assert declarations, f"pixi.toml declares no {step!r} task; it is core and exists in every combination"

    offenders = sorted(
        f"{name} in {table} declares {PROCESS_ENV_VAR} = {task_env(definition).get(PROCESS_ENV_VAR)!r}"
        for table, name, definition in declarations
        if PROCESS_ENV_VAR in task_env(definition)
    )
    assert not offenders, (
        f"these release-stage or build-stage steps declare themselves serving processes: {offenders}. "
        f"{step!r} is not a serving process (AD-13), and a {PROCESS_ENV_VAR} on `migrate` in particular "
        f"deadlocks the release stage against the refusal only `migrate` can clear."
    )


def test_the_only_tasks_that_migrate_are_the_two_the_manifest_is_supposed_to_have(
    manifest: dict[str, Any],
) -> None:
    """An exact set, asserted in both directions, and both of them matter.

    *Nothing was added.* A component-side `migrate-all` that ran every declared
    step in sequence is the obvious convenience and it is refused here, because
    it would be a single name any process task could then `depends-on` -- and the
    transitive case above would be the only thing between that one line and a
    rolling deploy where every replica migrates at once. The deployment
    repository runs the steps `component.toml` declares; the component states
    them and stops there.

    *Nothing was removed.* The release stage runs the steps `component.toml`
    declares, each one through `pixi run manage <step>` -- which is the form
    those steps are shaped for (arguments to `manage.py`, never a shell command)
    and the form `docs/deployment.md` documents. The `migrate` task is not that
    invocation and is not made redundant by it: it is how a developer applies
    migrations locally, and it is the task AD-13's deadlock argument is written
    about, since `pixi run migrate` is the management command that would refuse
    on the state it exists to clear if process type failed closed. AD-22 takes
    migration out of every entrypoint, not out of the manifest -- and deleting
    either task would make every scan in this file pass by having nothing left to
    find.
    """
    migrating = sorted({name for _table, name, definition in tasks(manifest) if _migrates(task_command(definition))})
    assert migrating == sorted(MIGRATION_TASKS), (
        f"the tasks that migrate are {migrating}, not {sorted(MIGRATION_TASKS)}. `migrate` is the release "
        f"stage's own invocation and `makemigrations` authors migrations in development; a third is either "
        f"an aggregate of the steps component.toml declares or an entrypoint in waiting."
    )


@pytest.mark.parametrize("module", sorted(ENTRYPOINT_MODULES))
def test_no_entrypoint_module_runs_a_management_command(module: str, declaration: ComponentDeclaration) -> None:
    """AC #1: no boot-time entrypoint imports the management package or calls into it.

    Four modules, because there are four things a process loads before it serves:
    the ASGI and WSGI applications gunicorn and uvicorn import, the gunicorn
    worker class the `web` task names with `-k`, and the Celery application
    `worker` and `beat` name with `-A`. A `call_command(...)` in any of them is a
    migration that runs in every replica at every boot -- including `--preload`
    boots, where it runs before the fork, and rolling deploys, where every
    replica runs it at once. A migration reaching the database from `celery_app`
    is the same defect as one reaching it from `asgi`, arriving through the
    queue.

    `celery_app.py` is `feature:celery` and is absent from the four combinations
    that do not select it, so its presence is required *from the declaration*
    rather than unconditionally -- the same derivation
    `tests/unit/test_process_model.py` uses for `worker` and `beat`. The three
    `core` modules are required outright.

    Parsed rather than grepped. A docstring in any of these files may discuss
    migration -- several discuss the settings-module fallback at length -- and
    prose about a prohibition is not a breach of it.
    """
    path = REPO_ROOT / "src" / "config" / module
    owner = ENTRYPOINT_MODULES[module]
    deselected = owner is not None and owner not in declaration.selected_features
    if not path.is_file():
        assert deselected, (
            f"{path} is the entrypoint this assertion pins and it is not there. Only a module owned by a "
            f"feature this combination did not select may be absent; this one is owned by {owner!r}."
        )
        return

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                f"line {node.lineno}: imports {alias.name}"
                for alias in node.names
                if alias.name == MANAGEMENT_PACKAGE or alias.name.startswith(f"{MANAGEMENT_PACKAGE}.")
            )
        elif isinstance(node, ast.ImportFrom):
            imported = node.module or ""
            if imported == MANAGEMENT_PACKAGE or imported.startswith(f"{MANAGEMENT_PACKAGE}."):
                offenders.append(f"line {node.lineno}: imports from {imported}")
            elif imported == "django.core" and any(alias.name == "management" for alias in node.names):
                offenders.append(f"line {node.lineno}: imports management from django.core")
        elif isinstance(node, ast.Call):
            called = node.func
            name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
            if name == COMMAND_RUNNER:
                offenders.append(f"line {node.lineno}: calls {COMMAND_RUNNER}")

    assert not offenders, (
        f"src/config/{module} reaches for Django's management commands: {offenders}. No entrypoint runs "
        f"migrations (AD-22); the release stage does, once, before the new version serves."
    )


def test_no_dockerfile_instruction_migrates() -> None:
    """AC #1's container half, over instruction lines rather than the whole file.

    Story 5.6 landed `Dockerfile` as `machinery` (AD-15 -- this repository ships
    one so the harness can verify the FR-38/FR-39 payload properties;
    materialized components ship none), and this case armed itself on that day
    with no edit here.

    The `pytest.skip` branch stays, and it is not a leftover. What it
    accommodates is the file's *absence*, which is the normal state of a
    materialized component and of any tree this module is copied into -- so the
    branch is what keeps this module usable there rather than erroring on a file
    AD-15 says will not exist. It remains recorded in
    `tests/unit/test_suite_policy.py`'s exemption table, and the two go together:
    removing the branch without the entry fails from one side, removing the entry
    without the branch fails from the other.

    `RUN`, `ENTRYPOINT`, `CMD` and `HEALTHCHECK` are the instructions that
    execute something; the rest describe the image. The parser is what makes
    that classification hold against how the file is written -- continuations
    joined, heredoc bodies absorbed, comments dropped, `ONBUILD` unwrapped -- and
    it is exercised directly by
    `test_the_dockerfile_parser_reads_each_form_an_instruction_can_take` below,
    over forms the real file does not contain.
    """
    if not DOCKERFILE.is_file():
        pytest.skip(
            f"{DOCKERFILE.name} is absent, which is what a materialized component looks like -- AD-15 "
            f"ships one only in this repository, as `machinery`, so the harness can verify the payload "
            f"properties. This branch is an accommodation for the file's absence and not a licence for "
            f"its contents: wherever the file exists, the assertion below runs."
        )

    instructions = instruction_lines(DOCKERFILE.read_text(encoding="utf-8"))
    assert instructions, f"{DOCKERFILE.name} exists but parses to no instruction at all"

    offenders = _migrating_instructions(instructions)
    assert not offenders, (
        f"these {DOCKERFILE.name} instructions migrate: {offenders}. AD-22: no container command runs "
        f"migrations. The image's CMD is `pixi run web`; the release stage runs the steps component.toml "
        f"declares, before the new pods serve."
    )


@pytest.mark.parametrize(
    ("text", "expected", "offences"),
    [(text, expected, offences) for _label, text, expected, offences in SYNTHETIC_DOCKERFILES],
    ids=[label for label, _text, _expected, _offences in SYNTHETIC_DOCKERFILES],
)
def test_the_dockerfile_parser_reads_each_form_an_instruction_can_take(
    text: str, expected: tuple[tuple[int, str, str], ...], offences: int
) -> None:
    """The parser is `tests/dockerfile.py`'s, and nothing else drives it this hard.

    The real `Dockerfile` contains none of these forms -- it is written plainly,
    which is the right way to write it -- so the case that scans it exercises one
    path and would look identical against a reader that had stopped joining
    continuations, absorbing heredoc bodies, dropping comments or unwrapping
    `ONBUILD`. Every one of those is a way an instruction becomes invisible to a
    scan for absence, and an invisible instruction reads as a pass.

    These cases are that execution: a continuation, a continuation still open at
    end of file, a comment between continuation lines, a BuildKit heredoc, an
    `ONBUILD` prefix and a `HEALTHCHECK`.

    Both halves are asserted, because the parse and the classification fail
    differently: an instruction read wrongly is a migration nobody scans, and an
    instruction classified wrongly is either a migration nobody scans or a
    comment reported as one.
    """
    assert tuple(instruction_lines(text)) == expected
    assert len(_migrating_instructions(instruction_lines(text))) == offences


def test_every_declared_migration_step_is_a_management_invocation_naming_its_own_alias(
    declaration: ComponentDeclaration,
) -> None:
    """AC #3: the declared steps are runnable, and each one targets the alias that declares it.

    `tests/unit/test_component_declaration.py` already asserts that every
    `[[databases]]` entry carries a non-empty `migrate` list; this is the step's
    *content*, which that file does not read. Two things have to hold for a step
    to be an instruction a deployment repository can follow.

    It has to be a management command Django actually has -- checked against
    `get_commands()`, the registry `manage.py` itself dispatches through, so a
    typo or a command from an app this combination did not select fails here
    rather than at three in the morning in the release stage.

    It has to be a *migration* command. "A command Django has" is satisfied by
    `shell`, and `migrate = ["shell --database default"]` would leave the
    release-stage contract's central declaration filled with something that never
    touches the migration graph while every case in this file stayed green. The
    detector this module already uses is what decides, so there is one definition
    of "migrates" here rather than two that can drift.

    It has to carry `--noinput`. The release stage has no TTY, so a step that
    stops to ask a question hangs the rollout before a single new pod has
    started -- the old generation still serving, the deploy neither applied nor
    rolled back. `docs/deployment.md`'s own example carries the flag for exactly
    this reason.

    And it has to name its own alias explicitly, exactly once. AD-9 turns
    release-stage migration into one step per database, which only means anything
    if each step says which database it is for: a step that omits `--database`
    migrates `default` whatever entry it was declared under, so a contributed
    database (AD-9, Epic 9) could be added with a step that silently re-migrates
    the wrong alias. *Exactly* once, because Django honours the last occurrence
    of a repeated option -- a step naming two aliases would satisfy a check that
    read the first and migrate the other one.
    """
    assert declaration.databases, "component.toml declares no database, so this case holds over nothing"
    known = get_commands()
    offenders: list[str] = []
    for database in declaration.databases:
        for step in database.migrate:
            try:
                tokens = shlex.split(step)
            except ValueError as error:
                offenders.append(f"{database.alias}: {step!r} cannot be split into arguments ({error})")
                continue
            if not tokens:
                offenders.append(f"{database.alias}: {step!r} is empty")
                continue
            command, *arguments = tokens
            if command in STEP_MUST_NOT_START_WITH or "/" in command:
                offenders.append(f"{database.alias}: {step!r} spells its own interpreter or path")
            elif command not in known:
                offenders.append(f"{database.alias}: {step!r} names {command!r}, which is not a management command")
            elif not _migrates(command):
                offenders.append(f"{database.alias}: {step!r} names {command!r}, which is not a migration command")
            if not NO_INPUT_OPTIONS.intersection(arguments):
                offenders.append(f"{database.alias}: {step!r} names no {sorted(NO_INPUT_OPTIONS)} and can prompt")
            targeted = _targeted_aliases(arguments)
            if targeted != [database.alias]:
                offenders.append(
                    f"{database.alias}: {step!r} names {DATABASE_OPTION} as {targeted} rather than exactly "
                    f"[{database.alias!r}]"
                )

    assert not offenders, (
        f"these [[databases]] migrate steps are not instructions a deployment repository can follow: "
        f"{offenders}. AD-9 makes release-stage migration one step per database; each step is a migration "
        f"command, names the database it is for exactly once with {DATABASE_OPTION}, and cannot prompt."
    )


def test_the_deployment_page_still_carries_the_release_stage_contract_and_the_accepted_risk() -> None:
    """AC #3 and #4: the contract and its price are where two docstrings say they are.

    `docs/deployment.md` is the only place the ordering the deployment repository
    must implement is written down, and R-3 is accepted rather than mitigated --
    which makes the paragraph recording it the whole of the mitigation. This
    module's docstring and `tests/integration/test_release_stage.py`'s both send a
    reader to that subheading by name; without this case, renaming or deleting
    either heading fails nothing and the promise goes quietly stale.

    Pinned by literal, in the same way and for the same reason as
    `tests/unit/test_component_declaration.py` pins its own heading.
    """
    prose = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    missing = [heading for heading in (RELEASE_STAGE_HEADING, ACCEPTED_RISK_HEADING) if heading not in prose]
    assert not missing, (
        f"{DEPLOYMENT_DOC.name} no longer carries these headings: {missing}. The release-stage contract is "
        f"documentation or it is nothing, and R-3 is accepted on the strength of being recorded under its "
        f"own subheading."
    )


def _targeted_aliases(arguments: list[str]) -> list[str]:
    """Return every alias a step's arguments name, in either spelling.

    Every one, not the first. Django's own parser honours the *last* occurrence
    of a repeated option, so a step naming `--database` twice migrates the second
    alias -- and a reader that stopped at the first would report the step as
    targeting the alias that declares it while the release stage migrated
    another. The caller requires the list to be exactly one long.

    Args:
        arguments: The step's tokens after the command name.

    Returns:
        The values of every `--database`, in the order the step names them, and
        empty when it names none.
    """
    named: list[str] = []
    for index, argument in enumerate(arguments):
        if argument == DATABASE_OPTION and index + 1 < len(arguments):
            named.append(arguments[index + 1])
        elif argument.startswith(f"{DATABASE_OPTION}="):
            named.append(argument.removeprefix(f"{DATABASE_OPTION}="))
    return named
