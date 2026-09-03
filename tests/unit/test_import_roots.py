"""Tests for the single import-root declaration (AD-7).

There were six places that declared where Python should look for this project's
source: a ``sys.path`` insert in each of the three entrypoints, ``--app-dir src``
in two pixi tasks, and ``"src"`` in the pytest ``pythonpath``. Six declarations
is how a second source root comes to work under pytest and fail under gunicorn --
the failure AD-7 exists to stop. One is left, and it is
``[tool.hatch.build.targets.wheel]``.

The assertions here are deliberately shaped as "this mechanism is absent"
rather than "this file looks like X": re-adding any of the six for local
convenience is the regression, and it is cheap to do by accident. The story's
Dev Notes name five more mechanisms that would be a second declaration site --
a ``.pth`` file, a ``conftest.py`` ``sys.path`` manipulation, a ``PYTHONPATH``
export in ``[activation.env]``, a ``setup.cfg``/``tox.ini`` path entry, and
pytest-django's own ``django_find_project`` insert -- and each has an assertion
below rather than only a sentence in the story.

Text and TOML only, so this stays a unit test: no subprocess, no build, no I/O
beyond reading repository files.
"""

from __future__ import annotations

import ast
import tomllib
from functools import cache
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PIXI_MANIFEST = REPO_ROOT / "pixi.toml"

# The three files that used to place `src/` on sys.path themselves. They are no
# longer the scan -- the scan is the whole repository -- but they are what AD-7
# names, so a guard below asserts the scan still reaches all three.
NAMED_ENTRYPOINTS = (
    REPO_ROOT / "manage.py",
    REPO_ROOT / "src" / "config" / "asgi.py",
    REPO_ROOT / "src" / "config" / "wsgi.py",
)

# Directories the scan does not enter. `.pixi/` is the installed environment and
# `.git/` is not source; `dist/`, `build/`, `staticfiles/` and `*.egg-info/` are
# generated. `.agents/`, `.claude/`, `_bmad/` and `.bmad-loop/` are vendored
# agent tooling, which this repository already declares is not its own source --
# they are `extend-exclude`d in [tool.ruff] for the same reason. A vendored
# script's `sys.path` handling is that tool's business; it declares nothing
# about where `config` and `django_service` come from.
EXCLUDED_DIRECTORIES = frozenset(
    {
        ".agents",
        ".bmad-loop",
        ".claude",
        ".git",
        ".mypy_cache",
        ".pixi",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "_bmad",
        "build",
        "dist",
        "node_modules",
        "staticfiles",
    },
)

# Attribute calls on `sys.path` that change what is on it. `pop`, `remove` and
# `clear` are here because "this file curates sys.path" is the shape being
# banned, not the direction of the edit.
SYS_PATH_MUTATORS = frozenset({"append", "clear", "extend", "insert", "pop", "remove", "reverse", "sort"})

# The same thing routed through the stdlib rather than through `sys.path`
# directly. `addsitedir` also processes any `.pth` inside the directory it adds.
SITE_MUTATORS = frozenset({"site.addpackage", "site.addsitedir"})

# The one import-root declaration, as it must read. Three *subtree* keys, which
# is not the `packages = [ "src/config", "src/django_service" ]` per-package
# enumeration they replaced: an application added under the second root arrives
# inside an already-mapped subtree and needs no key of its own, which is AD-6's
# graduation promise.
#
# Nor is it the `sources = [ "src", "src/django_apps" ]` an earlier plan (and
# epics.md) called for. hatchling normalises `sources` into a mapping, sorts it
# ascending and applies the *first* matching prefix, so "src" shadows
# "src/django_apps" and the second root becomes a silent no-op -- a wheel that
# builds, and applications that still import as `django_apps.core`. Enumerating
# the subtrees removes the collision at its cause because no key is a prefix of
# another, which is asserted below rather than eyeballed.
EXPECTED_WHEEL_SOURCES = {
    "src/config": "config",
    "src/django_apps": "",
    "src/django_service": "django_service",
}

# The subtree that is a path root rather than a package. It maps to the wheel
# root (""), which is what makes `django_apps` never appear in an import
# statement, and it carries no `__init__.py`. A `sources` key naming anything
# *inside* it would be the per-application enumeration this table exists to
# avoid.
APPLICATION_ROOT = "src/django_apps"

# Spelled out rather than derived from `EXPECTED_WHEEL_SOURCES`: a count taken
# from that mapping would agree with the file automatically whenever the mapping
# was updated alongside it, and the point of the count is to make a fourth key an
# edit someone has to make here on purpose. It is the "declared in exactly one
# place" claim reduced to a number.
EXPECTED_SOURCE_COUNT = 3

# Files at the repository root that carry a path-declaring section of their own.
# None of them exists here, and each would be a second site if it did:
# `setup.cfg` has `[options] package_dir`, `tox.ini` has `setenv`/`changedir`,
# and `pytest.ini` would take precedence over pyproject.toml's pytest table.
BANNED_ROOT_CONFIG_FILES = ("pytest.ini", "setup.cfg", "tox.ini")

# The environment variable that declares an import root without naming sys.path.
PATH_ENV_VARIABLE = "PYTHONPATH"


def _toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        parsed: dict[str, Any] = tomllib.load(handle)
    return parsed


@pytest.fixture(scope="module")
def pyproject() -> dict[str, Any]:
    """Return the parsed pyproject.toml."""
    return _toml(PYPROJECT)


@pytest.fixture(scope="module")
def pixi_manifest() -> dict[str, Any]:
    """Return the parsed pixi.toml."""
    return _toml(PIXI_MANIFEST)


@cache
def _project_files(suffix: str) -> tuple[Path, ...]:
    """Return every file with `suffix` in this repository that counts as project source.

    Walked rather than listed, because the three files AD-7 names are only the
    three that happened to do it: a `sys.path` insert added to
    `src/config/celery_app.py` or to a `conftest.py` would be exactly the same
    second declaration site and is exactly as easy to write.

    Excluded directories are pruned rather than filtered out afterwards, which
    is what keeps this a unit test: `.pixi/` alone holds tens of thousands of
    files, and walking into it would cost more than every other assertion in the
    suite put together.

    Args:
        suffix: The file extension to collect, leading dot included.

    Returns:
        Every matching file outside the excluded directories, sorted.

    """
    found: list[Path] = []
    pending = [REPO_ROOT]
    while pending:
        for entry in pending.pop().iterdir():
            if entry.is_dir():
                if entry.name not in EXCLUDED_DIRECTORIES:
                    pending.append(entry)
            elif entry.suffix == suffix:
                found.append(entry)
    return tuple(sorted(found))


def _dotted_name(node: ast.expr) -> str:
    """Return the dotted source spelling of an attribute or name expression.

    Args:
        node: The expression to spell out.

    Returns:
        The dotted name, or `""` for anything that is not a plain attribute
        chain rooted in a name.

    """
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ""
    parts.append(current.id)
    return ".".join(reversed(parts))


def _targets_sys_path(node: ast.expr) -> bool:
    """Report whether an assignment target rebinds or slices `sys.path`.

    Args:
        node: The assignment target.

    Returns:
        True for `sys.path = ...`, `sys.path += ...` and `sys.path[...] = ...`.

    """
    if isinstance(node, ast.Subscript):
        return _dotted_name(node.value) == "sys.path"
    return _dotted_name(node) == "sys.path"


def _declares_a_root(dotted: str) -> bool:
    """Report whether a called name mutates the import path.

    Args:
        dotted: The dotted spelling of the call's function.

    Returns:
        True for `sys.path.<mutator>` and for the `site` helpers that do the
        same thing through the stdlib.

    """
    if dotted in SITE_MUTATORS:
        return True
    receiver, _, attribute = dotted.rpartition(".")
    return receiver == "sys.path" and attribute in SYS_PATH_MUTATORS


def _import_root_declarations(path: Path) -> list[str]:
    """Return every import-root declaration in one module, as `line: form` strings.

    Matched on the parsed syntax tree, not by substring, for the reason
    `tests/unit/test_suite_policy.py` gives: prose about the prohibition -- this
    module's own docstrings, the comments in `asgi.py` and `wsgi.py` -- must not
    itself be an offence, and a textual `"sys.path.insert" not in source` check
    misses every rewrite of the same statement. `sys.path += [...]`,
    `sys.path[0:0] = [...]`, `sys.path.extend(...)` and `site.addsitedir(...)`
    all sail past a substring search and all fail here.

    What still escapes: an insert reached through an alias
    (`from sys import path`, `getattr(sys, "path")`) or through
    `importlib`/`exec`. Nothing in this repository does that, and the AST is
    where the line is drawn -- an evasion that deliberate is not the accident
    this check exists to catch.

    Args:
        path: The module to parse.

    Returns:
        One `line: form` string per declaration found.

    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _declares_a_root(_dotted_name(node.func)):
            found.append(f"{node.lineno}: {_dotted_name(node.func)}(...)")
        elif isinstance(node, ast.Assign) and any(_targets_sys_path(target) for target in node.targets):
            found.append(f"{node.lineno}: assignment to sys.path")
        elif isinstance(node, ast.AugAssign) and _targets_sys_path(node.target):
            found.append(f"{node.lineno}: augmented assignment to sys.path")
    return found


def _command_of(task: object) -> str | None:
    """Return a pixi task's command as a single string, or None if it declares none.

    pixi accepts `cmd` as a string or as an argv array, and a task declared with
    only `depends-on` carries no command at all.

    Args:
        task: One value from a `[...tasks]` table.

    Returns:
        The command, joined with spaces when it is an array, or None.

    """
    if isinstance(task, str):
        return task
    if not isinstance(task, dict):
        return None
    command = task.get("cmd")
    if isinstance(command, str):
        return command
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return None


def _walk_tables(manifest: dict[str, Any], wanted: str) -> list[tuple[str, dict[str, Any]]]:
    """Return every nested table named `wanted`, with its dotted location.

    pixi puts tasks in `[tasks]`, `[feature.<name>.tasks]`,
    `[target.<platform>.tasks]` and `[feature.<name>.target.<platform>.tasks]`,
    and environment tables in `[activation.env]`, `[feature.<name>.activation.env]`
    and a per-task `env`. Walking is what keeps a table added later in scope
    without this helper being touched -- the same reason
    `tests/unit/test_asgi_surface.py::_server_task_commands` walks.

    Args:
        manifest: The parsed pixi manifest.
        wanted: The table name to collect.

    Returns:
        `(dotted prefix, table)` pairs, prefix empty for a top-level table.

    """
    found: list[tuple[str, dict[str, Any]]] = []

    def walk(node: object, prefix: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if not isinstance(value, dict):
                continue
            if key == wanted:
                found.append((prefix, value))
            else:
                walk(value, f"{prefix}{key}.")

    walk(manifest, "")
    return found


def _task_commands(manifest: dict[str, Any]) -> dict[str, str]:
    """Return every declared pixi task's command, keyed by its dotted task name.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Every task that declares a command, including array-form `cmd` and tasks
        under `[target.<platform>.tasks]`.

    """
    commands: dict[str, str] = {}
    for prefix, table in _walk_tables(manifest, "tasks"):
        for name, task in table.items():
            command = _command_of(task)
            if command is not None:
                commands[f"{prefix}{name}"] = command
    return commands


def _declared_environment_variables(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """Return every environment-variable name pixi exports, keyed by variable.

    Covers `[activation.env]`, `[feature.<name>.activation.env]`,
    `[target.<platform>.activation.env]` and any per-task `env` table.

    Args:
        manifest: The parsed pixi manifest.

    Returns:
        Variable name to the list of dotted locations declaring it.

    """
    declared: dict[str, list[str]] = {}
    for prefix, table in _walk_tables(manifest, "env"):
        for name in table:
            declared.setdefault(name, []).append(f"{prefix}env.{name}")
    return declared


def test_the_declaration_sites_this_module_reads_exist() -> None:
    """The paths resolve, so every assertion below is reading something real."""
    assert PYPROJECT.is_file()
    assert PIXI_MANIFEST.is_file()
    for entrypoint in NAMED_ENTRYPOINTS:
        assert entrypoint.is_file(), entrypoint


def test_the_scan_reaches_the_files_ad_7_names() -> None:
    """A scan that excluded the three named entrypoints would pass vacuously."""
    scanned = _project_files(".py")

    assert len(scanned) > len(NAMED_ENTRYPOINTS), f"expected project modules under {REPO_ROOT}, found {scanned}"
    for entrypoint in NAMED_ENTRYPOINTS:
        assert entrypoint in scanned, entrypoint


def test_no_python_file_declares_an_import_root() -> None:
    """No module in this repository puts anything on `sys.path` (AD-7).

    Every project `.py` file, not the three AD-7 happens to name:
    `src/config/celery_app.py` is a process entrypoint too, `conftest.py` is
    where the story's Dev Notes say a second site would most plausibly appear,
    and both are covered here without being listed.
    """
    offenders = {
        str(path.relative_to(REPO_ROOT)): declarations
        for path in _project_files(".py")
        if (declarations := _import_root_declarations(path))
    }

    assert offenders == {}


def test_no_committed_pth_file_declares_an_import_root() -> None:
    """A `.pth` file in the tree would be a second site the story names outright.

    The editable install *generates* one in `.pixi/envs/*/site-packages`, which
    is why that directory is excluded: a build artifact regenerated from
    `[tool.hatch.build.targets.wheel]` is an output of the one declaration, not
    a declaration of its own. A `.pth` committed to the repository would be.
    """
    committed = [str(path.relative_to(REPO_ROOT)) for path in _project_files(".pth")]

    assert committed == []


@pytest.mark.parametrize("filename", BANNED_ROOT_CONFIG_FILES)
def test_no_root_config_file_declares_an_import_root(filename: str) -> None:
    """`setup.cfg`, `tox.ini` and `pytest.ini` are absent, so they declare nothing.

    Asserted as absence of the file rather than absence of a key inside it: any
    of the three appearing is itself the change worth stopping at, because each
    carries a path-declaring section and none of them is read by anything this
    project runs today.
    """
    assert not (REPO_ROOT / filename).exists(), filename


def test_no_pixi_environment_declares_an_import_root(pixi_manifest: dict[str, Any]) -> None:
    """No `PYTHONPATH` export in any activation or task `env` table (AD-7).

    Three lines above the tasks this module already scans, and it would put a
    root on `sys.path` for every command pixi runs -- `--app-dir`'s equivalent
    with none of its visibility.
    """
    declared = _declared_environment_variables(pixi_manifest)

    assert PATH_ENV_VARIABLE not in declared, declared.get(PATH_ENV_VARIABLE)


def test_pytest_declares_no_source_root(pyproject: dict[str, Any]) -> None:
    """``"src"`` is gone from the pytest ``pythonpath``.

    Asserted separately from the key's absence below, because retaining
    ``pythonpath = [ "." ]`` was the fallback resolution and would still have
    had to satisfy this.
    """
    pythonpath = pyproject["tool"]["pytest"]["ini_options"].get("pythonpath", [])

    assert "src" not in pythonpath
    assert "./src" not in pythonpath


def test_pytest_declares_no_pythonpath_at_all(pyproject: dict[str, Any]) -> None:
    """The whole setting is gone, not just its source-root entry.

    ``tests/conftest.py`` does ``from tests.factories import UserFactory`` and
    the ``"."`` entry used to be what made that resolve. It resolves without
    it: ``--import-mode=importlib`` imports ``tests/conftest.py`` under its
    canonical name ``tests.conftest``, which makes pytest import the parent
    package ``tests`` first, by file location and without consulting
    ``sys.path`` (``_pytest/pathlib.py::_import_module_using_spec``). ``tests``
    therefore lands in ``sys.modules`` with a real ``__path__``, and
    ``tests.factories`` is found through it.
    """
    assert "pythonpath" not in pyproject["tool"]["pytest"]["ini_options"]


def test_pytest_django_declares_no_import_root(pyproject: dict[str, Any]) -> None:
    """`django_find_project` is off, so pytest-django inserts nothing.

    It defaults to **true**, and when it is on pytest-django walks up from the
    collected arguments looking for `manage.py` and inserts that directory at
    the front of `sys.path` (`pytest_django/plugin.py::_add_django_project_to_path`).
    That is a live declaration site made on this project's behalf, and it is the
    reason AC #2's "recorded rather than left to coincidence" could otherwise be
    satisfied only inside a throwaway probe run.
    """
    assert pyproject["tool"]["pytest"]["ini_options"]["django_find_project"] is False


def test_the_wheel_target_declares_a_sources_remapping(pyproject: dict[str, Any]) -> None:
    """The one retained site remaps directories rather than listing packages.

    Pinned as the whole mapping, not as "the keys I care about are present": the
    failure this catches is an *addition* -- a fourth key, or a key naming one
    application -- as much as a removal, and a containment check sees neither.
    """
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert "sources" in wheel, "the retained import-root site must declare `sources`"
    assert wheel["sources"] == EXPECTED_WHEEL_SOURCES


def test_the_sources_mapping_declares_exactly_three_subtrees(pyproject: dict[str, Any]) -> None:
    """Cardinality, asserted on its own so a fourth entry fails loudly.

    Three keys, two roots: `src/config` and `src/django_service` both remap onto
    themselves at the wheel root, which is one root (`src`); `src/django_apps`
    maps onto "" and is the second. The count is what the "declared in exactly
    one place" claim reduces to once the declaration is a table -- a table can
    grow without any other test noticing.

    Every assertion reads the parsed `pyproject.toml`. Comparing this module's
    own constants against each other would be a case no repository change can
    fail, which is the shape of an audit test that has stopped auditing.
    """
    sources = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["sources"]

    # A list would still be a valid `sources` declaration to hatchling, and it
    # is what the shadowed spelling this table replaced looked like. Checked
    # first so a regression to one says that, rather than raising a TypeError
    # from indexing a string by a path.
    assert isinstance(sources, dict), sources
    assert len(sources) == EXPECTED_SOURCE_COUNT, sorted(sources)
    assert sources[APPLICATION_ROOT] == "", sources[APPLICATION_ROOT]


def test_no_sources_key_shadows_another(pyproject: dict[str, Any]) -> None:
    """No key is a path prefix of another, so hatchling's first-match cannot shadow.

    hatchling sorts `sources` ascending and returns on the first matching
    prefix, so a key that prefixes another silently wins for everything beneath
    it. That is exactly how `sources = [ "src", "src/django_apps" ]` fails: the
    build succeeds, and the second root does nothing. Asserted as the general
    property rather than as "src is absent", because any future prefix pair
    fails the same way.

    Keys are normalised through `PurePosixPath` before they are compared.
    `"src/django_apps/"` and `"./src/django_apps"` are the same subtree spelled
    two ways, and an unnormalised comparison would see two distinct keys where
    hatchling sees one -- the duplicate would slip past this case and past the
    cardinality check with it.
    """
    declared = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["sources"]
    keys = sorted(PurePosixPath(key) for key in declared)

    duplicates = [key for key in keys if keys.count(key) > 1]
    assert duplicates == [], f"these keys name one subtree under two spellings: {sorted(set(map(str, duplicates)))}"

    shadowed = [
        (str(outer), str(inner)) for outer in keys for inner in keys if outer != inner and outer in inner.parents
    ]

    assert shadowed == [], f"these keys shadow others under hatchling's first-prefix match: {shadowed}"


def test_the_wheel_target_selects_only_the_source_tree(pyproject: dict[str, Any]) -> None:
    """`only-include` is load-bearing, so it is asserted rather than assumed.

    hatchling's default wheel file selection looks for a package named after the
    project (`django_15_factor_base`), which does not exist here. Drop
    `only-include` and the build still succeeds while quietly changing what
    ships -- a failure with no failing step.
    `tests/integration/test_import_resolution.py` checks the built artifact;
    this checks the declaration that produces it.
    """
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel.get("only-include") == ["src"]


def test_the_wheel_target_generates_an_exact_editable_finder(pyproject: dict[str, Any]) -> None:
    """`dev-mode-exact` is the key that keeps the second root from leaking a second spelling.

    Without it hatchling writes the roots into the generated .pth as plain
    directories, and `<repo>/src` on `sys.path` makes `django_apps` resolve as an
    implicit namespace package even with no `__init__.py`. Every application then
    has a working `django_apps.` spelling as well as its real one. With it the
    editable install is a redirecting finder over exactly the three top-level
    names, so the root is not importable at all.

    Asserted here as a declaration; the behaviour it produces is asserted by
    `tests/integration/test_import_resolution.py` and
    `tests/unit/django_apps/test_core_app.py`. Both are needed: the built wheel
    is identical either way, so no build check distinguishes them.
    """
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel.get("dev-mode-exact") is True


def test_the_wheel_target_enumerates_no_applications(pyproject: dict[str, Any]) -> None:
    """No per-application entry, under `packages` or inside `sources`.

    `packages` is banned outright -- it is the key the remapping replaced. What
    `sources` may not do is grow an entry per domain application: the three keys
    it carries are subtrees of ``src/``, and every application lives *inside*
    ``src/django_apps`` rather than beside it. A key under the application root
    would make the "adding an app needs no edit here" promise false again, in
    the one place the promise is kept.
    """
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert "packages" not in wheel
    assert "sources" in wheel

    root = Path(APPLICATION_ROOT)
    enumerated = [entry for entry in wheel["sources"] if root in Path(entry).parents]

    assert enumerated == [], f"these entries enumerate applications inside the second root: {enumerated}"


def test_no_pixi_task_declares_an_import_root(pixi_manifest: dict[str, Any]) -> None:
    """``--app-dir`` is never a declaration mechanism (AC #5).

    It accepts a single directory, so it cannot express the two roots AD-7
    retains -- which is why it is barred outright rather than tolerated in the
    tasks that happen to need only one. Scanning every task, not just `serve`
    and `serve-reload`, is what keeps a task added later from reintroducing it.
    """
    offenders = {name: cmd for name, cmd in _task_commands(pixi_manifest).items() if "--app-dir" in cmd}

    assert offenders == {}


def test_the_task_scan_sees_the_tasks_it_claims_to(pixi_manifest: dict[str, Any]) -> None:
    """The two tasks AD-7 names are in the scan, so the scan above is not vacuous."""
    commands = _task_commands(pixi_manifest)

    assert "serve" in commands, sorted(commands)
    assert "feature.dev.serve-reload" in commands, sorted(commands)


def test_the_serve_tasks_still_serve_the_asgi_application(pixi_manifest: dict[str, Any]) -> None:
    """Removing `--app-dir` removed an argument, not the task's purpose.

    The load-bearing parts only, not the whole command string: adding
    `--host 0.0.0.0` or `--workers 4` is a change to how the task serves, not to
    whether it still serves the ASGI application, and this module's whole
    argument is that the assertions here are about absence of a mechanism.
    `serve-reload` also keeps `--reload-dir src`, which is a file-watch target
    rather than an import root: deleting it would silently stop autoreload.
    """
    commands = _task_commands(pixi_manifest)

    serve = commands.get("serve", "")
    assert "config.asgi:application" in serve, serve
    assert "--app-dir" not in serve, serve

    serve_reload = commands.get("feature.dev.serve-reload", "")
    assert "config.asgi:application" in serve_reload, serve_reload
    assert "--app-dir" not in serve_reload, serve_reload
    assert "--reload-dir src" in serve_reload, serve_reload
