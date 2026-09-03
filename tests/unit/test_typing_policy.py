"""Tests for the typing policy: strict is a gate condition, not an advisory.

NFR-4 and AD-18 make strict type checking part of the gate. AD-18's stated
concern is a check being "disabled by a change nobody understood as
security-relevant" -- and a relaxation of `[tool.mypy]` is exactly that shape:
one line in a configuration table, invisible in review, silently turning the
gate into a warning. These tests assert the configuration rather than trusting
it.

They read the manifests and the source tree, so they are unit tests: no I/O
beyond reading repository files, no network, no database. Nothing here shells
out to mypy -- a second invocation would be a second configuration, which is
precisely what AC #3 forbids. The gate itself proves that mypy fails on an
error, because `pixi run ci` chains `typecheck`.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PIXI_MANIFEST = REPO_ROOT / "pixi.toml"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
SRC_ROOT = REPO_ROOT / "src"

# The one Python this project supports. `requires-python = "==3.14.*"` and
# `python = "3.14.*"` pin it, so 3.14 is the floor and the ceiling both, and
# mypy's `python_version` tracks it rather than a lower matrix floor.
SUPPORTED_PYTHON = "3.14"

# The single override permitted to carry `ignore_errors`. It covers generated
# Django migration files, matching ruff's `extend-exclude` and pre-commit's
# `exclude:`, and it predates strict mode -- it was not added to make strict
# pass. Any other module pattern claiming the same relief is the silencing AC #2
# of Story 1.3 forbids.
MIGRATIONS_MODULE_PATTERN = "*.migrations.*"

# Flags that would let the hook and the task disagree about what "strict" means
# while both still appearing to run mypy over the same tree.
DIVERGENCE_FLAGS = ("--config-file", "--strict", "--no-strict")

# What both invocations must check, and nothing else. Widening this is a real
# change with its own failure surface; it must not happen on one side only.
MYPY_TARGET = ["src/"]

# A file-level directive that switches mypy off for a whole module.
MYPY_IGNORE_ERRORS_DIRECTIVE = re.compile(r"#\s*mypy\s*:.*\bignore-errors\b")

# Every `# type: ignore` in the tree, with its bracketed error code if it has
# one. A bare ignore silences whatever error happens to land on that line,
# including one introduced years later by an unrelated change.
TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore(?P<code>\[[^\]]+\])?")


@pytest.fixture(scope="module")
def pyproject() -> dict[str, Any]:
    """Return the parsed pyproject.toml."""
    with PYPROJECT.open("rb") as handle:
        parsed: dict[str, Any] = tomllib.load(handle)
    return parsed


@pytest.fixture(scope="module")
def mypy_config(pyproject: dict[str, Any]) -> dict[str, Any]:
    """Return the `[tool.mypy]` table."""
    config: dict[str, Any] = pyproject["tool"]["mypy"]
    return config


@pytest.fixture(scope="module")
def pixi_manifest() -> dict[str, Any]:
    """Return the parsed pixi manifest."""
    with PIXI_MANIFEST.open("rb") as handle:
        parsed: dict[str, Any] = tomllib.load(handle)
    return parsed


@pytest.fixture(scope="module")
def pre_commit_config() -> dict[str, Any]:
    """Return the parsed pre-commit configuration."""
    with PRE_COMMIT_CONFIG.open(encoding="utf-8") as handle:
        parsed: dict[str, Any] = yaml.safe_load(handle)
    return parsed


def _mypy_hook(config: dict[str, Any]) -> dict[str, Any]:
    """Return the `mypy` hook definition from the pre-commit configuration.

    Args:
        config: The parsed `.pre-commit-config.yaml`.

    Returns:
        The hook mapping whose id is `mypy`.

    """
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == "mypy":
                hook_definition: dict[str, Any] = hook
                return hook_definition
    pytest.fail("no hook with id 'mypy' is declared in .pre-commit-config.yaml")


def _typecheck_task(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the `typecheck` task definition, wherever the feature puts it.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        The task mapping named `typecheck`.

    """
    tasks: dict[str, Any] = dict(manifest.get("tasks", {}))
    for feature in manifest.get("feature", {}).values():
        tasks.update(feature.get("tasks", {}))
    task: dict[str, Any] = tasks["typecheck"]
    return task


def _mypy_arguments(command: str) -> list[str]:
    """Return the arguments a command line passes to mypy.

    The pre-commit hook prefixes its entry with `pixi run -e dev --`, so the
    two command lines are only comparable after the `mypy` token itself.

    Args:
        command: A full command line invoking mypy.

    Returns:
        Every token following `mypy`.

    """
    tokens = shlex.split(command)
    for index, token in enumerate(tokens):
        if Path(token).name == "mypy":
            return tokens[index + 1 :]
    pytest.fail(f"command line does not invoke mypy: {command!r}")


def _source_files() -> list[Path]:
    """Return every Python file mypy checks under `src/`.

    Returns:
        The sorted list of `.py` files in the source tree.

    """
    return sorted(SRC_ROOT.rglob("*.py"))


def test_manifests_are_present() -> None:
    """The paths resolve from the test file, so the assertions below mean something."""
    assert PYPROJECT.is_file()
    assert PIXI_MANIFEST.is_file()
    assert PRE_COMMIT_CONFIG.is_file()
    assert SRC_ROOT.is_dir()


def test_mypy_runs_in_strict_mode(mypy_config: dict[str, Any]) -> None:
    """AC #1: `[tool.mypy]` sets `strict`, not merely `check_untyped_defs`.

    Three planning documents asserted strictness while the configuration
    enabled only `check_untyped_defs`. This is the assertion that keeps the
    documents and the repository saying the same thing.
    """
    assert mypy_config.get("strict") is True, "[tool.mypy] must set strict = true (NFR-4, AD-18)"


def test_check_untyped_defs_is_never_disabled(mypy_config: dict[str, Any]) -> None:
    """`strict` implies `check_untyped_defs`; an explicit `false` would undo it.

    `strict = true` alongside `check_untyped_defs = false` is a legal and
    entirely silent downgrade: the strict flag stays visible in review while
    the behaviour it is trusted for is switched off beside it.
    """
    assert mypy_config.get("check_untyped_defs", True) is True


def test_python_version_tracks_the_supported_runtime(
    mypy_config: dict[str, Any],
    pyproject: dict[str, Any],
    pixi_manifest: dict[str, Any],
) -> None:
    """AC #1: `python_version` continues to track the supported floor.

    This project supports exactly one Python, so the floor and the ceiling are
    the same number. Asserting it against `requires-python` and the pixi pin
    rather than against a literal means the three cannot drift apart.
    """
    assert mypy_config.get("python_version") == SUPPORTED_PYTHON
    assert pyproject["project"]["requires-python"] == f"=={SUPPORTED_PYTHON}.*"
    assert pixi_manifest["dependencies"]["python"] == f"{SUPPORTED_PYTHON}.*"


def test_only_generated_migrations_may_ignore_errors(pyproject: dict[str, Any]) -> None:
    """AC #2: no hand-written module is relieved of type checking.

    The migrations override is the sole exception and is not the silencing AC
    #2 forbids -- it covers files Django generates, it matches ruff's and
    pre-commit's exclusions, and it predates strict mode. Extending its pattern,
    or adding a second override beside it, is how strict mode would be made to
    pass without anything being fixed.
    """
    overrides = pyproject["tool"]["mypy"].get("overrides", [])
    offenders = [
        override.get("module")
        for override in overrides
        if override.get("ignore_errors") and override.get("module") != MIGRATIONS_MODULE_PATTERN
    ]
    assert offenders == [], f"only {MIGRATIONS_MODULE_PATTERN} may set ignore_errors, found {offenders}"

    migrations = [override for override in overrides if override.get("module") == MIGRATIONS_MODULE_PATTERN]
    assert len(migrations) == 1, "the migrations override must be declared exactly once"


def test_no_error_code_is_disabled_globally(pyproject: dict[str, Any]) -> None:
    """AC #2: a rule is not relaxed for the whole tree to make one file pass.

    `disable_error_code` is the table-level equivalent of a module-wide
    `# type: ignore`: it fixes nothing and it removes the error everywhere, not
    only where it was inconvenient.
    """
    mypy_config = pyproject["tool"]["mypy"]
    assert "disable_error_code" not in mypy_config
    offenders = [
        override.get("module") for override in mypy_config.get("overrides", []) if "disable_error_code" in override
    ]
    assert offenders == [], f"no override may disable an error code, found {offenders}"


def test_the_hook_and_the_task_check_the_same_tree(
    pre_commit_config: dict[str, Any],
    pixi_manifest: dict[str, Any],
) -> None:
    """AC #3: both invocations name the same target.

    Agreement here is structural rather than coincidental: both run the same
    conda-forge mypy from the pixi `dev` feature and both read the same
    `[tool.mypy]` table. What remains variable is the target, so that is what
    is pinned -- to each other first, and then to `src/`, so that widening one
    side alone fails rather than quietly checking two different trees.
    """
    hook_arguments = _mypy_arguments(str(_mypy_hook(pre_commit_config)["entry"]))
    task_arguments = _mypy_arguments(str(_typecheck_task(pixi_manifest)["cmd"]))
    assert hook_arguments == task_arguments, (
        f"the mypy hook checks {hook_arguments} but pixi run typecheck checks {task_arguments}"
    )
    assert hook_arguments == MYPY_TARGET


def test_neither_invocation_can_diverge_on_configuration(
    pre_commit_config: dict[str, Any],
    pixi_manifest: dict[str, Any],
) -> None:
    """AC #3: neither side passes a flag that could override the shared table.

    `--config-file` would point one invocation at a different table entirely;
    `--strict` or `--no-strict` would let one side enforce something the other
    does not, and `--no-strict` in particular would leave `strict = true` in
    pyproject.toml looking untouched.
    """
    hook_entry = str(_mypy_hook(pre_commit_config)["entry"])
    task_command = str(_typecheck_task(pixi_manifest)["cmd"])
    for command in (hook_entry, task_command):
        offenders = [flag for flag in DIVERGENCE_FLAGS if flag in shlex.split(command)]
        assert offenders == [], f"{command!r} passes {offenders}, which lets the two invocations disagree"


def test_the_hook_brings_no_dependencies_of_its_own(pre_commit_config: dict[str, Any]) -> None:
    """AC #3: the hook uses the pixi `dev` mypy, not a copy pre-commit installed.

    `language: system` plus no `additional_dependencies` is what makes the hook
    and the task the same program. A hook environment of its own would resolve
    its own mypy, its own django-stubs and its own plugins, and the two could
    then disagree on a version without either configuration file changing.
    """
    hook = _mypy_hook(pre_commit_config)
    assert hook.get("language") == "system"
    assert "additional_dependencies" not in hook


def test_no_source_file_disables_mypy_wholesale() -> None:
    """AC #2: nothing is silenced with a file-level `mypy:` directive.

    A single comment at the top of a module removes it from the gate entirely,
    and does so from inside the file, where no configuration review would look.
    """
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in _source_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if MYPY_IGNORE_ERRORS_DIRECTIVE.search(line)
    ]
    assert offenders == [], f"these files switch mypy off for the whole module: {offenders}"


def test_every_type_ignore_names_the_error_it_silences() -> None:
    """AC #2: an ignore is narrow, or it is not an ignore worth keeping.

    A bracketed code silences one known error on one line. Without it the
    comment silences whatever error lands there next, which may be a real
    defect introduced long after the ignore was justified. `warn_unused_ignores`
    then removes the coded form as soon as upstream makes it unnecessary --
    a property a bare ignore does not have.
    """
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in _source_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for match in TYPE_IGNORE.finditer(line)
        if match.group("code") is None
    ]
    assert offenders == [], f"these ignores name no error code: {offenders}"
