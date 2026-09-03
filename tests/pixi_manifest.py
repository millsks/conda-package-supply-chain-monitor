"""How the suite reads `pixi.toml`, in one place.

Two modules assert over the pixi manifest's task tables and they assert
different things about them. `tests/unit/test_process_model.py` reconciles the
process group against `component.toml` in both directions (AD-14);
`tests/unit/test_release_stage.py` asserts that nothing in that group migrates
(AD-22). Both need the same three facts first -- where the task tables are, what
each task's `env` declares, and what each task runs -- and neither can answer its
own question without them.

A second reader would be the failure mode AD-26 names for the refusal contract,
arriving through the tests instead: two parsers that can disagree about what the
process group *is*, so a task that one of them walks past is a task the other's
assertion never saw. Membership is structural rather than nominal -- the group is
exactly the set of tasks whose `env` declares `COMPONENT_PROCESS` -- and a
structural definition is only worth having while one piece of code computes it.

This is a helper module, not a collected one. `[tool.pytest.ini_options]
python_files` matches `test_*.py` and `tests.py`, so nothing here is collected,
and it sits at `tests/` rather than under `tests/unit/` because
`tests/conftest.py` records why shared helpers go to the home both suites already
share: a collected test module is not a helper library, and importing one from
another ties two files' collection together.

`tests/unit/test_locality_declaration.py` reads the same tables through its own
copies of `_task_tables` and `_task_env`. Those are deliberately left where they
are: that module asserts the *other* half of AD-13's task-`env` contract -- which
tasks may declare `COMPONENT_RUNTIME` -- and its walk predates and is wider than
this one, taking in `[activation.env]` tables that have nothing to do with tasks.
Folding it in is a refactor of Story 5.2's and Story 4.4's work rather than of
this story's, and it is recorded here rather than done quietly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any
from typing import Final

from config.locality import PROCESS_ENV_VAR

#: The repository root. Two parents up: `pixi_manifest.py` -> `tests` -> root.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: The manifest every reader below opens. Whatever `pixi.toml` is at the
#: repository root, with no path assumption beyond that -- Epic 8 runs the same
#: assertions inside each materialized combination, where the file has been
#: stripped but is still here.
PIXI_MANIFEST: Final[Path] = REPO_ROOT / "pixi.toml"

#: pixi's implicit feature. The unscoped `[tasks]` table belongs to it, and the
#: walk below treats it as one feature scope among the rest so that a task
#: declared under `[feature.<name>.tasks]` is read exactly like an unscoped one.
DEFAULT_FEATURE: Final[str] = "default"


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """Return the parsed pixi manifest.

    Args:
        path: The manifest to read. Defaults to the repository root's.

    Returns:
        The manifest, parsed from TOML.
    """
    with (path or PIXI_MANIFEST).open("rb") as handle:
        parsed: dict[str, Any] = tomllib.load(handle)
    return parsed


def manifest_lines(path: Path | None = None) -> list[str]:
    """Return the manifest's lines, stripped, for the positional region assertions.

    A region is a span of lines. `tomllib` does not preserve one, and neither
    does it preserve comments, so the AD-24 marker assertions read text -- and
    only they do. Every assertion about a task's *content* goes through the
    parsed document.

    Args:
        path: The manifest to read. Defaults to the repository root's.

    Returns:
        Every line of the manifest, with surrounding whitespace removed.
    """
    return [line.strip() for line in (path or PIXI_MANIFEST).read_text(encoding="utf-8").splitlines()]


def feature_scopes(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return every feature scope in the manifest, including the implicit default one.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Feature name -> the table that scopes it. The unscoped root is returned
        under `default`, which is the feature it belongs to.

    Raises:
        ValueError: When the manifest declares a literal `[feature.default]`
            table. pixi's default feature is the implicit one the root tables
            belong to, so such a table would take the `default` key here and
            replace the root scope -- and every unscoped task would then vanish
            from every walk built on this function, silently. The failure mode is
            a scan that finds nothing rather than one that finds an offender, so
            it is raised rather than resolved.
    """
    scopes: dict[str, dict[str, Any]] = {DEFAULT_FEATURE: manifest}
    for name, feature in manifest.get("feature", {}).items():
        if not isinstance(feature, dict):
            continue
        if str(name) == DEFAULT_FEATURE:
            message = (
                f"pixi.toml declares a literal [feature.{DEFAULT_FEATURE}] table. That name belongs to pixi's "
                f"implicit feature, which the unscoped root tables are already read as, so honouring it here "
                f"would drop every unscoped task from every walk in the suite."
            )
            raise ValueError(message)
        scopes[str(name)] = feature
    return scopes


def task_tables(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return every task table in the manifest, keyed by where it lives.

    `[tasks]`, each `[feature.<name>.tasks]`, and the platform-scoped variants of
    both. Four unscoped-or-feature tables exist today and the platform-scoped
    ones hold nothing; they are read anyway, because a `worker` declared under
    `[target.linux-64.tasks]` is as real as any other and would otherwise escape
    every assertion built on this walk.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Table location -> {task name: task definition}.
    """
    tables: dict[str, dict[str, Any]] = {}
    for feature, scope in feature_scopes(manifest).items():
        prefix = "" if feature == DEFAULT_FEATURE else f"feature.{feature}."
        tasks_table = scope.get("tasks")
        if isinstance(tasks_table, dict):
            tables[f"[{prefix}tasks]"] = tasks_table
        for platform, target in scope.get("target", {}).items():
            platform_tasks = target.get("tasks")
            if isinstance(platform_tasks, dict):
                tables[f"[{prefix}target.{platform}.tasks]"] = platform_tasks
    return tables


def tasks(manifest: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Return every task in the manifest as (table location, name, definition).

    A list rather than a name-keyed mapping: keying by name lets a task declared
    in two tables overwrite its twin, and a shadowed `worker` declaring a
    different `COMPONENT_PROCESS` would then pass every assertion while the
    manifest contained a task none of them had seen.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        One entry per declaration, in manifest order.
    """
    return [
        (table, str(name), definition)
        for table, table_tasks in task_tables(manifest).items()
        for name, definition in table_tasks.items()
    ]


def tasks_named(manifest: dict[str, Any], name: str) -> list[tuple[str, str, Any]]:
    """Return every declaration of one task name, across every table.

    Args:
        manifest: The parsed pixi manifest.
        name: The task name to look for.

    Returns:
        The matching declarations, empty when the manifest declares no such task.
    """
    return [entry for entry in tasks(manifest) if entry[1] == name]


def task_env(definition: Any) -> dict[str, Any]:
    """Return the `env` table a task definition declares, or an empty one.

    A task written as a bare command string declares no `env` at all, which is
    the right answer here: absent process type means *not a serving process*
    (process type fails open), and absent locality means *deployed* (locality
    fails closed). The pair of directions is deliberate -- failing process type
    closed would make every management command a serving process and deadlock
    the release stage on the migrations refusal (AD-13).

    Args:
        definition: One task's definition, in either legal form.

    Returns:
        The declared environment, or `{}` when the task declares none.
    """
    if not isinstance(definition, dict):
        return {}
    env = definition.get("env")
    return env if isinstance(env, dict) else {}


def task_command(definition: Any) -> str:
    """Return the command a task runs, in every form the manifest permits.

    `cmd` takes a string *or* an argument list, and both are read. Returning an
    empty string for the list form would put a `cmd = ["python", "manage.py",
    "migrate"]` beyond every scan built on this function while it ran exactly as
    the string form does -- a task that escapes an assertion by how it is
    spelled, which is the shape of hole the shared reader exists to close.

    Args:
        definition: One task's definition.

    Returns:
        The command string -- the argument list joined with spaces where the
        manifest spells it that way -- or an empty string for a task that
        declares only `depends-on`.
    """
    if isinstance(definition, str):
        return definition
    if isinstance(definition, dict):
        command = definition.get("cmd")
        if isinstance(command, str):
            return command
        if isinstance(command, list):
            return " ".join(str(part) for part in command)
    return ""


def task_dependencies(definition: Any) -> tuple[tuple[str, str], ...]:
    """Return one definition's `depends-on` entries as (task name, extra arguments).

    pixi permits two spellings in that list -- a bare task name, and a table
    carrying `task` alongside `args`. Both are read, because a dependency
    written in the second form is as real as one written in the first and would
    otherwise be invisible to a transitive walk.

    The `args` come back with the name rather than being discarded, because they
    are part of what the dependency actually runs: `depends-on = [{ task =
    "manage", args = ["migrate", "--noinput"] }]` invokes a migration through a
    task whose own command is `python manage.py` and contains no migrate at all.
    A caller handed only the name would scan the wrong string and find nothing.

    Args:
        definition: One task's definition.

    Returns:
        (dependency name, the arguments that entry passes, joined with spaces
        and empty when it passes none), in declaration order.
    """
    if not isinstance(definition, dict):
        return ()
    declared = definition.get("depends-on")
    if not isinstance(declared, list):
        return ()
    dependencies: list[tuple[str, str]] = []
    for entry in declared:
        if isinstance(entry, str):
            dependencies.append((entry, ""))
        elif isinstance(entry, dict) and isinstance(entry.get("task"), str):
            arguments = entry.get("args")
            joined = " ".join(str(part) for part in arguments) if isinstance(arguments, list) else ""
            dependencies.append((entry["task"], joined))
    return tuple(dependencies)


def process_group(manifest: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return the process group as (table location, task name, declared process type).

    The group is defined by what a task *declares*, not by what it is called
    (AD-26). A task is in it when its own `env` carries `COMPONENT_PROCESS`, and
    out of it otherwise, whatever its name suggests.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        One entry per task declaring a process type, in manifest order.
    """
    return [
        (table, name, str(env[PROCESS_ENV_VAR]))
        for table, name, definition in tasks(manifest)
        for env in [task_env(definition)]
        if PROCESS_ENV_VAR in env
    ]
