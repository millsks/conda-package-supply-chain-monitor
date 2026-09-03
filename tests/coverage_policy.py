"""The declared coverage surface, read from the places that declare it.

AD-20 makes the coverage `omit`/`exclude` list a closed, *carrier-declared*
surface subject to two-way reconciliation. The carrier -- `accelerator.toml` --
does not exist yet (Epic 7, Story 7.1), so the reading this project runs under
today is that "held in exactly one place" is satisfied by `pyproject.toml`
`[tool.coverage.run]`. That is the interim declaration site, not a second
declaration.

It is not, however, the only coverage-exclusion surface in the tree.
`sonar-project.properties` carries `sonar.coverage.exclusions`, read by the
merge-blocking SonarCloud quality gate (`.github/workflows/sonarqube.yml`). It
governs the *published* coverage view rather than the pytest-cov floor AD-20
sets, so it is a different consumer of the same idea rather than a second floor
-- but it is an exclusion surface all the same, it does not agree entry-for-entry
with the list above, and an unread surface is how a divergence becomes a drift.
`sonar_coverage_exclusions()` below reads it and
`tests/unit/test_coverage_policy.py` freezes what it says, so that surface is
closed too.

Every assertion in `tests/unit/test_coverage_policy.py` and
`tests/integration/test_coverage_measurement.py` reads a declared value through
a named accessor below rather than indexing a parsed manifest itself.
`pyproject()` and `pixi_manifest()` are exported for accessors here to build on,
not for tests to reach through.

Epic 7 moves the declaration into `accelerator.toml`. What moves is this module:
`PYPROJECT`, `DECLARATION_SITE`, `FLOOR_SITE` and the accessors' reads. What
does not move is the frozen expectation -- `CLOSED_OMIT`, `CLOSED_INCLUDE`,
`CLOSED_EXCLUDE`, `CLOSED_SONAR_EXCLUSIONS`, `COVERAGE_SOURCE` and
`COVERAGE_FLOOR` all live in `tests/unit/test_coverage_policy.py` and are
repointed there. And two assertions cannot be repointed at all:
`test_no_line_exclusion_surface_is_declared` and
`test_no_per_directory_narrowing_is_declared` assert that a *pyproject.toml*
table does not exist, so Epic 7 has to rewrite them against whatever shape the
carrier gives those two surfaces. The reader is a module rather than a
`tomllib` call inlined into each test so that the first list is a one-file
change, not so that the whole story is.

This is a helper module, not a test module: pytest collects nothing from it.
`tests/factories.py` is the existing precedent for a shared helper living here.
"""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path
from typing import Any

import pytest
from coverage import Coverage

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PIXI_MANIFEST = REPO_ROOT / "pixi.toml"
SONAR_PROPERTIES = REPO_ROOT / "sonar-project.properties"
SRC_ROOT = REPO_ROOT / "src"

# Named in failure messages so a report says where the declaration is, not just
# that two lists differ. Epic 7 changes this string with the reads below it.
DECLARATION_SITE = "pyproject.toml [tool.coverage.run]"

# The floor's own declaration site. It is a different file from the surface
# above because it is a different kind of thing -- a task argument, not a
# configuration table -- but it is read through this module for the same reason.
FLOOR_SITE = "pixi.toml [feature.dev.tasks] test-cov"

# The second exclusion surface, and the gate that consumes it.
SONAR_DECLARATION_SITE = "sonar-project.properties sonar.coverage.exclusions"
SONAR_COVERAGE_EXCLUSIONS_KEY = "sonar.coverage.exclusions"

# The flag that carries the floor, and the one task allowed to carry it. They
# live here rather than in a test module because both the unit assertions and
# the integration assertion on the floor *in force* need them, and a constant
# duplicated across two test modules is a third declaration of the floor.
FLOOR_FLAG = "--cov-fail-under"
FLOOR_TASK = "test-cov"


def _parse(path: Path) -> dict[str, Any]:
    """Return a parsed TOML manifest.

    Args:
        path: The manifest to read.

    Returns:
        The parsed document.

    """
    with path.open("rb") as handle:
        parsed: dict[str, Any] = tomllib.load(handle)
    return parsed


def pyproject() -> dict[str, Any]:
    """Return the parsed pyproject.toml."""
    return _parse(PYPROJECT)


def pixi_manifest() -> dict[str, Any]:
    """Return the parsed pixi manifest."""
    return _parse(PIXI_MANIFEST)


def coverage_run_table() -> dict[str, Any]:
    """Return the `[tool.coverage.run]` table, empty if it is absent."""
    table: dict[str, Any] = pyproject()["tool"].get("coverage", {}).get("run", {})
    return table


def coverage_report_table() -> dict[str, Any] | None:
    """Return the `[tool.coverage.report]` table, or None when it is not declared.

    None and `{}` are different answers here. The absence of the table is
    itself part of the declared surface -- an empty exclude surface is still a
    declared surface -- so the caller must be able to tell "not declared" from
    "declared and empty".

    Returns:
        The parsed table, or None if `pyproject.toml` declares no such table.

    """
    table: dict[str, Any] | None = pyproject()["tool"].get("coverage", {}).get("report")
    return table


def coverage_paths_table() -> dict[str, Any] | None:
    """Return the `[tool.coverage.paths]` table, or None when it is not declared."""
    table: dict[str, Any] | None = pyproject()["tool"].get("coverage", {}).get("paths")
    return table


def declared_omit() -> list[str]:
    """Return the declared omit list."""
    omit: list[str] = list(coverage_run_table().get("omit", []))
    return omit


def declared_include() -> list[str]:
    """Return the declared include list -- the measurement bound."""
    include: list[str] = list(coverage_run_table().get("include", []))
    return include


def declared_exclude() -> list[str]:
    """Return the declared line-exclusion list.

    Empty today, because `[tool.coverage.report]` is not declared at all. That
    emptiness is asserted rather than assumed: see `coverage_report_table`.

    Returns:
        Every pattern declared under `exclude_lines` and `exclude_also`.

    """
    report = coverage_report_table() or {}
    return [*report.get("exclude_lines", []), *report.get("exclude_also", [])]


def declared_fail_under() -> float | None:
    """Return the `[tool.coverage.report] fail_under`, or None when absent.

    A value here would be a second floor beside the one in `pixi.toml`, which
    is exactly what AD-20's "single global constant" forbids.
    """
    value: float | None = (coverage_report_table() or {}).get("fail_under")
    return value


def pytest_addopts() -> list[str]:
    """Return `[tool.pytest.ini_options] addopts`, tokenized.

    Declared as a list in this project and as a string in plenty of others;
    both spellings are accepted so the assertion that reads it does not become
    vacuous if the table is rewritten in the other form.

    Returns:
        One entry per command-line token.

    """
    addopts = pyproject()["tool"]["pytest"]["ini_options"].get("addopts", [])
    return shlex.split(addopts) if isinstance(addopts, str) else [str(token) for token in addopts]


def activation_env() -> dict[str, str]:
    """Return `[activation.env]` -- the variables every pixi environment carries."""
    env: dict[str, str] = pixi_manifest().get("activation", {}).get("env", {})
    return env


def _task_tokens(definition: object) -> list[str]:
    """Return one pixi task definition's command as command-line tokens.

    pixi accepts three shapes and the difference matters: a bare string
    (`fmt = "ruff format ."`), a table with a string `cmd`, and a table with
    `cmd` as a list of already-split tokens. A reader that handles only the
    middle shape raises on the first and shreds the third into tokens that
    match nothing -- either of which hides a second `--cov-fail-under` from
    every scan built on this function.

    Args:
        definition: The value pixi holds against a task name.

    Returns:
        The command's tokens, empty for a task that declares no `cmd` at all
        (`ci`, which is `depends-on` only).

    """
    if isinstance(definition, str):
        return shlex.split(definition)
    if isinstance(definition, dict):
        command = definition.get("cmd", "")
        if isinstance(command, list):
            return [str(token) for token in command]
        return shlex.split(str(command))
    return []


def tasks_in_manifest(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """Return every task in a parsed pixi manifest, whatever table it sits in.

    The manifest is walked recursively for any `tasks` table at any depth,
    rather than read at the two paths this project happens to use today.
    `[tasks]` and `[feature.<name>.tasks]` are not the whole set: pixi also
    honours `[target.<platform>.tasks]` and
    `[feature.<name>.target.<platform>.tasks]`, and this manifest already uses
    `[target.<platform>.dependencies]`, so a platform-scoped table is an
    established idiom here rather than a hypothetical one. A fixed-path reader
    cannot see a floor declared in one.
    `tests/unit/test_asgi_surface.py::_server_task_commands` walks the same
    file for the same reason.

    Args:
        manifest: A parsed pixi manifest.

    Raises:
        ValueError: If one task name is declared in more than one table. A
            later table silently winning is how a platform-scoped override
            would carry its own floor while the scan still read the original.

    Returns:
        The tokenized command of every task, keyed by task name.

    """
    tasks: dict[str, list[str]] = {}
    collisions: list[str] = []

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key == "tasks" and isinstance(value, dict):
                for name, definition in value.items():
                    if name in tasks:
                        collisions.append(str(name))
                    tasks[str(name)] = _task_tokens(definition)
            else:
                walk(value)

    walk(manifest)

    if collisions:
        message = (
            f"these pixi task names are declared in more than one table: {sorted(set(collisions))}. "
            "One definition would overwrite the other, so a scan of the tasks cannot say "
            "which command actually runs -- give them distinct names."
        )
        raise ValueError(message)

    return tasks


def pixi_tasks() -> dict[str, list[str]]:
    """Return every pixi task in this project's manifest, tokenized by name."""
    return tasks_in_manifest(pixi_manifest())


def declared_floor() -> float:
    """Return the coverage floor declared on the floor-carrying pixi task.

    Read rather than restated so the value asserted to be *in force* during a
    measured run is the same one the manifest declares, and not a third copy of
    the number.

    Raises:
        ValueError: If the floor task carries no floor at all.

    Returns:
        The declared percentage.

    """
    tokens = pixi_tasks().get(FLOOR_TASK, [])
    values = [token.split("=", 1)[1] for token in tokens if token.startswith(f"{FLOOR_FLAG}=")]
    if not values:
        message = f"{FLOOR_SITE} declares no {FLOOR_FLAG}; there is no floor to enforce"
        raise ValueError(message)
    return float(values[-1])


def reconcile(declared: list[str], effective: list[str]) -> tuple[list[str], list[str]]:
    """Reconcile a declared list against an effective one, in both directions.

    AD-20 asks for two-way reconciliation, and a set comparison alone reports
    only that the two differ. This returns each direction separately so the
    failure message can name the offending entries on each side.

    Args:
        declared: The list held at the declaration site.
        effective: The list actually in force.

    Returns:
        A pair of (declared but not effective, effective but not declared),
        each in the order of the list it came from.

    """
    missing = [entry for entry in declared if entry not in effective]
    unexpected = [entry for entry in effective if entry not in declared]
    return missing, unexpected


def _sonar_logical_lines() -> list[str]:
    """Return sonar-project.properties as logical lines, continuations joined.

    Sonar reads the file with Java `.properties` semantics, where a trailing
    backslash continues the value onto the next physical line. A reader that
    splits on newlines alone sees the continued half as an unrelated line, so an
    exclusion written that way is invisible to every assertion built on it.

    Returns:
        One entry per logical property line.

    """
    logical: list[str] = []
    pending = ""
    for physical in SONAR_PROPERTIES.read_text(encoding="utf-8").splitlines():
        pending += physical.lstrip() if pending else physical
        if pending.endswith("\\"):
            pending = pending[:-1]
            continue
        logical.append(pending)
        pending = ""
    if pending:
        logical.append(pending)
    return logical


def sonar_property(name: str) -> list[str]:
    """Return one comma-separated sonar property's entries, as written.

    A repeated key is rejected rather than resolved. Sonar takes the last
    declaration, so a first-match reader would report a cleaned exclusion list
    while the one that ships still named the removed path.

    Args:
        name: The property key, e.g. `sonar.coverage.exclusions`.

    Raises:
        ValueError: If the key is absent, or declared more than once.

    Returns:
        Every entry declared under that key.

    """
    declarations = [
        value
        for key, separator, value in (line.partition("=") for line in _sonar_logical_lines())
        if separator and key.strip() == name
    ]
    if len(declarations) != 1:
        message = f"{SONAR_PROPERTIES.name} declares {name} {len(declarations)} times; exactly one is required"
        raise ValueError(message)
    return [entry.strip() for entry in declarations[0].split(",") if entry.strip()]


def sonar_coverage_exclusions() -> list[str]:
    """Return `sonar.coverage.exclusions` as written in sonar-project.properties.

    The second coverage-exclusion surface: what SonarCloud's merge-blocking
    quality gate drops from the coverage it publishes. See the module docstring
    for why it is a different consumer of the same idea rather than a second
    floor, and `tests/unit/test_coverage_policy.py::CLOSED_SONAR_EXCLUSIONS`
    for the frozen list.

    Returns:
        Every path pattern excluded from SonarCloud coverage.

    """
    return sonar_property(SONAR_COVERAGE_EXCLUSIONS_KEY)


def require_coverage_session(config: pytest.Config) -> Coverage:
    """Return the coverage session measuring this run, given the pytest config.

    Two different situations reach here and only one of them is benign, so they
    are answered differently:

    * **Coverage was never asked for.** `--cov` is absent, there is nothing to
      interrogate, and skipping is right. That is `pixi run test-integration`
      in the inner loop, the one case AD-20's reading sanctions.
    * **Coverage was asked for and no session is live.** `--cov=src` was passed
      and `Coverage.current()` is still None -- `--no-cov` on the same command
      line does exactly this, and so does any plugin that disables measurement.
      Coverage was requested and is not running: that is a gate defect, so it
      fails rather than skips. Skipping here would convert "nothing was
      measured" into a green run in which every live AD-20 assertion silently
      vanished, which is the degradation this story exists to prevent.

    The guard is stated here rather than in each test module because every AD-20
    assertion needs it and one copy is the point. That placement is no longer
    also a way around `tests/unit/test_suite_policy.py`'s ban on a literal
    `pytest.skip` -- Story 1.2's guard against a PostgreSQL failure being dodged
    rather than fixed -- which now scans every `.py` under `tests/` rather than
    only the modules pytest collects. This skip is not that evasion: it guards a
    coverage session never having been requested, not the presence of an
    inconvenient backend. It is recorded, once, in that module's
    `RECORDED_EXEMPTIONS`, and a second skip here fails the gate.

    Args:
        config: The running pytest configuration, from the `request` fixture.

    Returns:
        The active `Coverage` object.

    """
    requested = config.getoption("--cov", default=[])
    if not requested:
        pytest.skip("coverage was never requested: this suite was invoked without --cov")

    session = Coverage.current()
    if session is None:
        pytest.fail(
            f"coverage was requested ({requested!r}) but no session is measuring this run -- "
            "--no-cov, or a plugin that disabled measurement, is in force. Every assertion "
            "about the measurement actually running would otherwise have been skipped, and "
            "the suite would have reported a green run in which nothing was measured."
        )
    return session
