"""Tests for `tests/source_scan.py`, the primitive three audits are built on.

`tests/unit/test_import_roots.py`, `tests/unit/django_apps/test_clock_audit.py`
and `tests/unit/django_apps/test_single_ordering_audit.py` all take their file
walk and their dotted-name helper from that module, and each of them argues at
length that an audit which cannot be shown to still detect anything is an audit
that has quietly stopped auditing. The same argument applies to the module they
all depend on, and this file is it. A `dotted_name` that started returning `""`
for everything would make all three report a clean repository, and every
anti-vacuity guard they carry is about their *own* subject rather than about
this.

Two cases write into `tmp_path`, and deliberately. A directory that cannot be
read and a symlink loop are the two failures the walk is hardened against, and
neither can be constructed without a filesystem; asserting them against the
repository would mean committing a symlink loop. It is a handful of entries in a
directory pytest creates and removes, with no network, no database and nothing
left behind -- the same latitude `tests/unit/django_apps/test_core_app.py` takes
when it `stat`s the source tree to prove the import root is not a package.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

import pytest

from tests import source_scan
from tests.source_scan import EXCLUDED_DIRECTORIES
from tests.source_scan import EXCLUDED_DIRECTORY_SUFFIXES
from tests.source_scan import MIGRATIONS_DIRECTORY
from tests.source_scan import REPO_ROOT
from tests.source_scan import SRC_ROOT
from tests.source_scan import UnparseableSourceError
from tests.source_scan import dotted_name
from tests.source_scan import parse
from tests.source_scan import project_files

if TYPE_CHECKING:
    from collections.abc import Iterator

#: A directory that must exist in the tree and must never be walked into. The
#: installed environment: tens of thousands of files, none of them this
#: project's source, and the single largest reason the exclusion happens during
#: the walk rather than after it.
AN_EXCLUDED_DIRECTORY: Final[str] = ".pixi"

#: A migration this repository actually has, so the `skip_migrations` assertion
#: is about a real file rather than about an empty difference.
A_MIGRATION: Final[Path] = SRC_ROOT / "django_service" / "users" / "migrations" / "0001_initial.py"


@pytest.fixture
def _isolated_scan_records() -> Iterator[None]:
    """Restore the module-level walk records, so a `tmp_path` case cannot leak.

    `UNREADABLE_DIRECTORIES` and `SKIPPED_SYMLINKS` are module state that the
    guard below asserts is empty for the repository. A case that deliberately
    creates an unreadable directory would otherwise leave that guard failing for
    every later run in the session, and the failure would name a temporary path
    that no longer exists.

    Yields:
        None. The restore is the effect.

    """
    unreadable = set(source_scan.UNREADABLE_DIRECTORIES)
    symlinks = set(source_scan.SKIPPED_SYMLINKS)
    try:
        yield
    finally:
        source_scan.UNREADABLE_DIRECTORIES.clear()
        source_scan.UNREADABLE_DIRECTORIES.update(unreadable)
        source_scan.SKIPPED_SYMLINKS.clear()
        source_scan.SKIPPED_SYMLINKS.update(symlinks)


def test_the_walk_finds_this_repositorys_source() -> None:
    """The guard every other assertion here rests on."""
    found = project_files(REPO_ROOT)

    assert len(found) > 1
    assert Path(__file__).resolve() in found


def test_the_walk_never_enters_an_excluded_directory() -> None:
    """Asserted against a directory that exists, so the case cannot pass vacuously.

    A scan that had simply stopped walking would satisfy "no path is under
    `.pixi/`" perfectly. The `is_dir` assertion is what makes the exclusion the
    thing being tested.
    """
    excluded = REPO_ROOT / AN_EXCLUDED_DIRECTORY

    assert excluded.is_dir(), excluded
    assert list(excluded.rglob("*.py")), "the excluded directory must actually hold modules"

    offenders = [path for path in project_files(REPO_ROOT) if AN_EXCLUDED_DIRECTORY in path.parts]

    assert offenders == []


@pytest.mark.parametrize("name", sorted(EXCLUDED_DIRECTORIES), ids=str)
def test_no_scanned_file_sits_under_any_excluded_name(name: str) -> None:
    """Every name in the table, not only the one that is easy to check.

    The table grew because `pixi run ci` builds before it tests -- `dist/` and an
    `*.egg-info/` exist by the time any scan runs -- and because a developer's
    stray virtualenv would otherwise put thousands of third-party modules through
    every parametrized audit.

    **Matched against the repository-relative path, never the absolute one.** The
    exclusion table is a statement about directories *inside* this repository, and
    an absolute path carries whatever the checkout happens to live under. A
    checkout under `~/.claude/worktrees/` -- which is where a worktree-isolated
    agent session runs -- puts `.claude` in `parts` for every file in the tree, so
    an absolute match failed this case while the walk it checks was behaving
    correctly. The bug was here, in the guard, not in `project_files`: the walk
    excludes by directory name as it descends and never enters `.claude` under
    the repository root at all.
    """
    offenders = [str(path) for path in project_files(REPO_ROOT) if name in path.relative_to(REPO_ROOT).parts]

    assert offenders == []


def test_the_guard_above_judges_the_repository_and_not_the_path_it_is_checked_out_at() -> None:
    """A checkout below an excluded name must not make the guard fail.

    Anchoring the regression rather than the symptom: the guard is parametrized
    over every excluded name, so the case that broke depended entirely on where
    the repository sat on disk -- green in GitHub CI, red in a worktree under
    `~/.claude/worktrees/`, with nothing in the repository different between them.

    Asserted on the shape of what the guard compares rather than by relocating a
    checkout, which no unit test can do: every scanned path is under `REPO_ROOT`,
    so `relative_to` is total, and none of the relative paths carries a name the
    table excludes even when the absolute ones do.
    """
    scanned = project_files(REPO_ROOT)

    assert scanned, f"expected files under {REPO_ROOT}"
    assert all(path.is_relative_to(REPO_ROOT) for path in scanned)

    excluded_anywhere = {
        name
        for path in scanned
        for name in path.relative_to(REPO_ROOT).parts
        if source_scan._excluded(name)  # noqa: SLF001 - the predicate this module exists to guard
    }

    assert excluded_anywhere == set()


def test_a_directory_name_suffix_is_excluded_as_well_as_an_exact_name() -> None:
    """`*.egg-info` carries the distribution name, so it cannot be listed by hand.

    `pyproject.toml`'s coverage `omit` already carries `**/*.egg-info/**` for the
    same reason, which is the evidence that these directories really do appear.
    """
    for suffix in EXCLUDED_DIRECTORY_SUFFIXES:
        assert source_scan._excluded(f"conda_package_supply_chain_monitor{suffix}"), suffix  # noqa: SLF001

    assert not source_scan._excluded("conda_package_supply_chain_monitor")  # noqa: SLF001


def test_skipping_migrations_drops_generated_modules_and_nothing_else() -> None:
    """Both directions, because either alone would pass on a broken filter.

    A `skip_migrations` that dropped everything would satisfy "no migration is
    present"; one that dropped nothing would satisfy "the rest is still there".
    """
    everything = project_files(SRC_ROOT)
    without_migrations = project_files(SRC_ROOT, skip_migrations=True)

    assert A_MIGRATION in everything, A_MIGRATION
    assert A_MIGRATION not in without_migrations
    assert set(everything) - set(without_migrations)
    assert all(MIGRATIONS_DIRECTORY not in path.parts for path in without_migrations)
    assert set(without_migrations) < set(everything)


def test_a_different_suffix_collects_a_different_file_set() -> None:
    """`test_import_roots.py` asks this walk for `.pth` files as well as `.py` ones.

    The parameter exists for that caller, so it is asserted here rather than only
    exercised there. Checked against `.toml`, which this repository has, rather
    than only against `.pth`, which it deliberately has none of: a suffix filter
    that had stopped filtering and one that returned nothing at all are
    indistinguishable when the expected answer is the empty set.
    """
    modules = project_files(REPO_ROOT)
    manifests = project_files(REPO_ROOT, ".toml")

    assert modules
    assert REPO_ROOT / "pyproject.toml" in manifests
    assert REPO_ROOT / "pixi.toml" in manifests
    assert set(modules).isdisjoint(manifests)
    assert all(path.suffix == ".toml" for path in manifests)


def test_the_walk_read_every_directory_it_entered() -> None:
    """`UNREADABLE_DIRECTORIES` is empty, and this is where that is reported.

    The walk records an unreadable directory rather than raising, because both
    audits build their parametrize lists at import time and a `PermissionError`
    during collection reports no test at all. This case is the other half of that
    bargain: the failure becomes one named, readable assertion.
    """
    project_files(REPO_ROOT)
    project_files(SRC_ROOT, skip_migrations=True)

    assert not source_scan.UNREADABLE_DIRECTORIES


@pytest.mark.usefixtures("_isolated_scan_records")
def test_an_unreadable_directory_is_recorded_rather_than_raised(tmp_path: Path) -> None:
    """A permission failure must not abort collection.

    Constructed rather than asserted about the repository, because a directory
    nobody can read is not something to commit. Skipped where the process can
    read anything regardless -- running as root, or on a filesystem with no
    permission bits -- since there the state under test cannot exist.
    """
    reachable = tmp_path / "reachable"
    reachable.mkdir()
    (reachable / "module.py").write_text("x = 1\n", encoding="utf-8")
    closed = tmp_path / "closed"
    closed.mkdir()
    (closed / "hidden.py").write_text("y = 2\n", encoding="utf-8")
    closed.chmod(0o000)

    try:
        list(closed.iterdir())
    except PermissionError:
        unreadable = True
    else:
        unreadable = False

    if not unreadable:
        # Running as root, or on a filesystem with no permission bits. The state
        # under test cannot exist here, so what is left to assert is that the
        # walk still returns both halves rather than silently returning nothing.
        closed.chmod(0o700)

        assert set(project_files(tmp_path)) == {reachable / "module.py", closed / "hidden.py"}
        return

    try:
        found = project_files(tmp_path)
    finally:
        closed.chmod(0o700)

    assert found == (reachable / "module.py",)
    assert str(closed) in source_scan.UNREADABLE_DIRECTORIES


@pytest.mark.usefixtures("_isolated_scan_records")
def test_a_directory_symlink_is_recorded_rather_than_followed(tmp_path: Path) -> None:
    """A link pointing at an ancestor makes the tree infinite.

    `Path.is_dir()` follows symlinks, so the walk would descend through the loop
    until it ran out of path length or patience -- during collection, with no
    test to attribute it to. There is no depth at which stopping would be
    principled, so the walk does not follow directory symlinks at all.
    """
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "module.py").write_text("x = 1\n", encoding="utf-8")
    loop = inner / "loop"
    loop.symlink_to(tmp_path, target_is_directory=True)

    found = project_files(tmp_path)

    assert found == (inner / "module.py",)
    assert str(loop) in source_scan.SKIPPED_SYMLINKS


def test_the_repository_walk_followed_no_symlink() -> None:
    """Nothing in the tree needed the guard, which is worth knowing rather than assuming.

    If a directory symlink is ever committed, this is what says so -- and says it
    as a finding rather than as a scan that silently covered more, or less, than
    the file it lives in claims.
    """
    project_files(REPO_ROOT)

    assert not source_scan.SKIPPED_SYMLINKS


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("timezone.now", "timezone.now"),
        ("django.utils.timezone.now", "django.utils.timezone.now"),
        ("now", "now"),
        ("build().now", ""),
        ("registry['clock'].now", ""),
        ("'a string'.upper", ""),
    ],
    ids=["attribute", "deep-attribute", "bare-name", "call-result", "subscript", "literal"],
)
def test_dotted_name_spells_out_only_chains_rooted_in_a_name(source: str, expected: str) -> None:
    """The three `""` cases are the ones that make this function different from its namesakes.

    `tests/unit/test_suite_policy.py` returns the partial chain (`"now"`) for the
    last three; this returns `""`. Callers here compare the *receiver* against a
    table of imported names, and a partial chain would let
    `whatever().timezone.now()` resolve to a receiver nobody imported. The
    difference is recorded in `tests/source_scan.py`'s docstring and pinned here,
    so the next scan that "takes its primitives from there" is not surprised.
    """
    expression = ast.parse(source, mode="eval").body

    assert dotted_name(expression) == expected


def test_parse_returns_the_tree_of_a_real_module() -> None:
    """The positive case, so the refusals below are not the whole contract."""
    tree = parse(Path(__file__).resolve())

    assert isinstance(tree, ast.Module)
    assert tree.body


def test_parse_names_the_file_that_will_not_compile(tmp_path: Path) -> None:
    """A `SyntaxError` from a scan must say which of a thousand files it was.

    The audits parse every module in the repository, and the useful half of that
    failure is the path.
    """
    broken = tmp_path / "broken.py"
    broken.write_text("def (:\n", encoding="utf-8")

    with pytest.raises(UnparseableSourceError, match=r"broken\.py"):
        parse(broken)


def test_parse_names_the_file_that_is_not_utf_8(tmp_path: Path) -> None:
    """A `UnicodeDecodeError` carries the offending byte and no path at all.

    Which is the least actionable failure a whole-tree scan can produce: the
    reader is told a byte was wrong and has to find the file by hand.
    """
    binary = tmp_path / "binary.py"
    binary.write_bytes(b"\xff\xfe\x00 = 1\n")

    with pytest.raises(UnparseableSourceError, match=r"binary\.py"):
        parse(binary)


def test_parse_names_a_file_that_is_not_there() -> None:
    """The third way reading fails, on the same terms as the other two."""
    with pytest.raises(UnparseableSourceError, match=r"absent\.py"):
        parse(REPO_ROOT / "absent.py")


def test_the_roots_are_the_directories_they_claim_to_be() -> None:
    """`REPO_ROOT` and `SRC_ROOT` are derived from this file's location.

    They are read off `__file__` rather than from `settings.BASE_DIR` so the
    scans work in a collection-only run that never configured Django -- which
    means a file moved to a different depth would silently retarget every audit.
    """
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert SRC_ROOT.is_dir()
    assert (SRC_ROOT / "config").is_dir()


def test_the_helper_module_is_not_collected() -> None:
    """A helper library, not a test module -- the reason it sits at `tests/`.

    `[tool.pytest.ini_options] python_files` matches `test_*.py` and `tests.py`,
    so importing this one ties no two files' collection together, exactly as
    `tests/group_writers.py` argues for itself.
    """
    assert Path(str(source_scan.__file__)).name == "source_scan.py"
    assert not any(item.startswith("test_") for item in dir(sys.modules[source_scan.__name__]))
