"""How the suite walks this repository's own source, in one place.

Three audits read the tree and parse it. `tests/unit/test_import_roots.py` asks
which files declare an import root; `tests/unit/django_apps/test_single_ordering_audit.py`
asks which modules declare a precedence order;
`tests/unit/django_apps/test_clock_audit.py` asks which modules read a wall
clock. All three need the same two primitives -- the set of files that count as
this project's source, and the dotted spelling of an attribute chain -- and a
second copy of either is the failure `tests/group_writers.py` was extracted to
prevent: two scans that disagree about what they cover look exactly like two
passing tests.

That is not hypothetical here. `test_import_roots.py` carried its own
`EXCLUDED_DIRECTORIES`, and the two lists had already diverged before either was
a day old. It now imports this one, so a directory excluded from one scan is
excluded from all three, and `tests/unit/test_source_scan.py` holds this module's
own guards.

**`dotted_name` is not the same function as its two namesakes.**
`tests/unit/test_suite_policy.py` and this module both spell out an attribute
chain, and they disagree deliberately on one input: given something that is not
rooted in a plain `Name` -- `f(x).now`, `d["k"].now` -- that one returns the
partial chain (`"now"`) and this one returns `""`. This module's callers compare
the *receiver* against a table of known names, so a partial chain would let
`whatever().timezone.now()` resolve to a receiver nobody imported. A scan taking
its primitives from here needs to know which of the two it is getting.

A helper module, not a collected one. `[tool.pytest.ini_options] python_files`
matches `test_*.py` and `tests.py`, so nothing here is collected, and it sits at
`tests/` rather than under `tests/unit/` for the reason `tests/group_writers.py`
does: a collected test module is not a helper library.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path
from typing import Final

#: Where the repository begins, read off this file rather than off
#: `settings.BASE_DIR`, so the scans work in a collection-only run that never
#: configured Django.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: The one source tree. The clock scan stops here, because it is about what the
#: shipped code does; the ordering scan deliberately does not, because a second
#: precedence order written into a test is still a second precedence order.
SRC_ROOT: Final[Path] = REPO_ROOT / "src"

#: Directories no scan enters.
#:
#: Three groups, and the third is the one that bites. `.git/`, `.mypy_cache/`,
#: `.pixi/`, `.pytest_cache/`, `.ruff_cache/` and `__pycache__/` are tool state.
#: `.agents/`, `.bmad-loop/`, `.claude/`, `_bmad/` and `_bmad-output/` are
#: vendored agent tooling, which `[tool.ruff] extend-exclude` already declares is
#: not this repository's source.
#:
#: The third group is build and environment output: `build/`, `dist/`,
#: `htmlcov/`, `node_modules/`, `site/`, `staticfiles/`, `.eggs/`, `.tox/`,
#: `.hypothesis/`, `.venv/`, `venv/`, `env/` and anything ending `.egg-info`.
#: These are not speculative. `pixi run ci` runs `build` *before* the tests, so
#: `dist/` and an `*.egg-info/` exist by the time any scan runs -- `pyproject.toml`'s
#: coverage `omit` already lists `**/*.egg-info/**` for the same reason -- and a
#: developer who has ever created a virtualenv in the working tree would
#: otherwise have every scan parse thousands of third-party modules, one
#: parametrized case each.
#:
#: Pruned during the walk rather than filtered afterwards. `.pixi/` alone holds
#: tens of thousands of files, and descending into it would cost more than the
#: rest of the unit suite put together.
EXCLUDED_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".agents",
        ".bmad-loop",
        ".claude",
        ".eggs",
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".pixi",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "_bmad",
        "_bmad-output",
        "_build",
        "build",
        "dist",
        "env",
        "htmlcov",
        "node_modules",
        "site",
        "site-packages",
        "staticfiles",
        "venv",
    },
)

#: Directory name suffixes excluded as well as exact names. `*.egg-info` carries
#: the distribution name, so it cannot be listed above.
EXCLUDED_DIRECTORY_SUFFIXES: Final[tuple[str, ...]] = (".egg-info",)

#: The directory whose contents Django's own migration autogenerator writes.
#: Excluded from the clock scan: `0001_initial.py` carries
#: `django.utils.timezone.now` as a field default because `makemigrations` put it
#: there, and failing a gate on generated code would mean hand-editing it
#: forever.
MIGRATIONS_DIRECTORY: Final[str] = "migrations"

#: Directories a walk could not read, recorded rather than raised.
#:
#: A `PermissionError` out of `iterdir()` would otherwise abort *collection* --
#: both audits build their parametrize lists at import time -- and a traceback
#: during collection reports no test at all, which is the least readable failure
#: a suite can produce. `tests/unit/test_source_scan.py` asserts this stays
#: empty, so an unreadable directory is a named failing test instead.
UNREADABLE_DIRECTORIES: set[str] = set()

#: Directory symlinks the walk refused to follow, recorded on the same terms.
#: Following them is how a walk spins forever: a link pointing at an ancestor
#: makes the tree infinite, and there is no depth at which stopping would be
#: principled.
SKIPPED_SYMLINKS: set[str] = set()


@cache
def project_files(root: Path, suffix: str = ".py", *, skip_migrations: bool = False) -> tuple[Path, ...]:
    """Return every file under `root` that counts as this project's source.

    Args:
        root: The directory to walk. `REPO_ROOT` for a repository-wide scan,
            `SRC_ROOT` for one about shipped code only.
        suffix: The file extension to collect, leading dot included.
        skip_migrations: Drop files under any `migrations/` directory. Generated
            code is not a declaration anybody made.

    Returns:
        Every matching file outside the excluded directories, sorted. Symlinked
        directories are not followed and unreadable ones are skipped; both are
        recorded in the module-level sets above rather than raised, because this
        runs during collection.

    """
    found: list[Path] = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            UNREADABLE_DIRECTORIES.add(str(current))
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.is_symlink():
                    SKIPPED_SYMLINKS.add(str(entry))
                elif not _excluded(entry.name) and not (skip_migrations and entry.name == MIGRATIONS_DIRECTORY):
                    pending.append(entry)
            elif entry.suffix == suffix:
                found.append(entry)
    return tuple(sorted(found))


def _excluded(name: str) -> bool:
    """Report whether a directory name is one no scan enters.

    Args:
        name: The directory's own name, not its path.

    Returns:
        True for an exact match in `EXCLUDED_DIRECTORIES` and for any name
        ending in one of `EXCLUDED_DIRECTORY_SUFFIXES`.

    """
    return name in EXCLUDED_DIRECTORIES or name.endswith(EXCLUDED_DIRECTORY_SUFFIXES)


class UnparseableSourceError(Exception):
    """A file a scan had to read could not be read or could not be parsed.

    Named rather than left as whatever `ast.parse` or `Path.read_text` raises,
    because the useful half of the report is *which file* -- a
    `UnicodeDecodeError` carries the offending byte and no path at all, and a
    scan that dies on one file with no name in the message sends its reader
    through the whole tree by hand.
    """


def parse(path: Path) -> ast.Module:
    """Parse one module, naming the file in every failure it can produce.

    Args:
        path: The module to parse.

    Returns:
        The parsed tree.

    Raises:
        UnparseableSourceError: When the file cannot be read as UTF-8, cannot be read
            at all, or is not valid Python. The path is in the message in every
            case.

    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as unreadable:
        message = f"{path} could not be read as UTF-8 source: {unreadable}"
        raise UnparseableSourceError(message) from unreadable
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as invalid:
        message = f"{path} is not valid Python: {invalid}"
        raise UnparseableSourceError(message) from invalid


def dotted_name(node: ast.expr) -> str:
    """Return the dotted source spelling of an attribute or name expression.

    See the module docstring: this returns `""` where the namesake in
    `tests/unit/test_suite_policy.py` returns a partial chain, and the difference
    is load-bearing for every caller that compares a receiver against a table.

    Args:
        node: The expression to spell out.

    Returns:
        The dotted name, or `""` for anything that is not a plain attribute
        chain rooted in a name -- a subscript, a call result, a literal.

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
