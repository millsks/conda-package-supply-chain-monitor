"""`CPM-RENAME-S01` AC 1: the former import root appears nowhere under `src/` or `tests/`.

`CPM-EP-RENAME` moved the Django import root from the project's original
underscored spelling to `conda_sentinel`. The move itself is a mechanical edit
that either compiles or does not; what survives the story is this file. One
hundred and forty-eight files under the two trees this gate scans named the old
identifier the day before the rename -- one hundred and eighty-six across the
whole repository, the rest of them under `docs/`, which `CPM-RENAME-S02` cleared,
and `_bmad-output/`, which is `CPM-RENAME-S03`'s: it *corrects* the planning
artifacts, whose Code Maps must name paths that exist, and leaves only the merged
story files alone as a record -- and without a gate the name comes back one import at a
time: a docstring copied out of a merged story, a path in a comment, an import
somebody hand-wrote from memory. None of those fails a build.

**Text, not syntax.** Every other audit in this suite matches on the parsed tree
and argues at length for doing so, and this one deliberately does the opposite.
The acceptance criterion is that the name appears *nowhere*: not in an import,
and equally not in a docstring, a comment, a test id, a settings key or a data
file. An AST scan keyed on import statements would report a clean repository
while half of `src/` still narrated the old module path, which is the failure
mode this gate exists to close rather than a case it may skip.

**Bytes, not decoded text, and every file rather than every module.**
`src/django_service/static/images/favicons/favicon.ico` is in the tree, and so
are templates, a CSV watchlist and a TOML parameter file. A scan that decoded
each file would either raise on the first binary one or need a suffix allow-list
that the next file type quietly escapes; a scan keyed on `".py"` would not look
at the watchlist at all. Comparing bytes needs neither list: a file type added
tomorrow is covered the day it lands.

**Paths as well as contents.** A directory or a file *named* for the former
import root whose bytes never spell it is the case a contents-only scan reports
clean, and it is not a hypothetical: `[tool.hatch.build.targets.wheel.sources]`
maps `src/django_apps` to the wheel root, so a directory restored at
`src/django_apps/<former name>/` is importable under the old top-level name while
every file inside it -- a CSV watchlist, a TOML parameter file, an `__init__.py`
-- passes a byte comparison. The per-file case below therefore checks the
repository-relative path first and the bytes second, and a `tmp_path` case proves
the path check fires on exactly the file the byte check misses.

**Why this module does not spell the name it forbids.** The scan below reads
every file under `tests/`, this one included, so a module that wrote the former
identifier out in full would be the first thing its own gate failed on. It is
assembled from its segments instead. That opens a failure of its own -- a typo in
the segments would make the guard search for a string nothing ever contained and
pass on every file forever -- so the assembled value is pinned by digest, and a
`tmp_path` case below writes the name into a synthetic file and asserts the
detector still finds it. An audit that cannot be shown to detect anything has
quietly stopped auditing.

**The hyphenated spelling is not this gate's subject.** What is forbidden is the
underscored module identifier. The hyphenated spelling of the same five words
survived `CPM-RENAME-S02` under `src/` in two places. `CPM-RENAME-S04` then
renamed the repository and moved one of them, so exactly one remains:

* `config/observability/telemetry.py`'s `DEFAULT_SERVICE_NAME` names the
  **product**, and `CPM-RENAME-S02` deliberately left it. It is an *emitted*
  value -- every span's `service.name` -- so moving it silently breaks any
  dashboard or alert keyed on the old one. `docs/observability.md`'s
  `OTEL_SERVICE_NAME` row records that decision. Do not "finish the rename" here
  on the strength of this gate being green; a story that wants the trace identity
  moved owns the migration note, and nothing in this suite pins the literal, so
  the change would pass silently.

The two spellings are different strings, so the scan cannot confuse them, and a
case below asserts that separation rather than leaving it to be inferred. It is
asserted rather than observed because the near-miss is close: same words, one
separator apart.

**Scope is `src/` and `tests/`, and no further.** `_bmad-output/` holds merged
story files that are a historical record of what was decided when;
`CPM-RENAME-S03` decides what happens there and deliberately leaves the merged
ones alone. A gate that reached into it would fail on work no story has done yet.

The four application labels are asserted here too. They are the reason the rename
was cheap: Django derives a label from the last segment of `AppConfig.name`, so
moving the parent package cannot touch them, and migration dependencies and
`django_content_type` both reference the short labels. `test_identity_app.py` and
`test_policies_app.py` each assert their own application's label as a property of
that application's adoption; the assertion here is the different claim the rename
rests on -- that all four survived the move together.

Reads repository files and the populated app registry. No database, no network,
no subprocess.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.apps import apps

from tests.source_scan import REPO_ROOT
from tests.source_scan import project_files

if TYPE_CHECKING:
    from pathlib import Path

#: The identifier this gate forbids, assembled rather than written out -- see
#: "Why this module does not spell the name it forbids" above. `FLY002` is
#: suppressed rather than obeyed: the fix it offers is to write the forbidden
#: name into this file as a literal, which is precisely the offence every case
#: below exists to catch, and this module is inside its own scan.
FORMER_IMPORT_ROOT: Final[str] = "_".join(("conda", "package", "supply", "chain", "monitor"))  # noqa: FLY002

#: `sha256(FORMER_IMPORT_ROOT)`. The assembly above is the only place the name is
#: constructed, and a typo in it would be invisible: the scan would search for a
#: string this repository never contained and report every file clean. The digest
#: is what makes that a failing test instead of a silent pass. It is a constant of
#: the *former* name, so it never needs updating.
FORMER_IMPORT_ROOT_DIGEST: Final[str] = "d852798cb66f54b5bd2efda5134ffad8b08e7d822189dcdf428f879de9536b66"

#: What the import root is now.
CURRENT_IMPORT_ROOT: Final[str] = "conda_sentinel"

#: The hyphenated spelling of the forbidden identifier's five words. It was
#: `pyproject.toml`'s `[project] name` until `CPM-RENAME-S02` made that
#: `conda-sentinel`. One live example under `src/` carries it still --
#: `config/observability/telemetry.py`'s `DEFAULT_SERVICE_NAME`, which names the
#: product and was deliberately left because it is emitted (see the module
#: docstring). `CPM-RENAME-S04` moved the other, `collectors/agent.py`'s
#: `PROJECT_URL`, when it renamed the repository. Spelled in full because the
#: point of the case below is that the
#: scan does *not* match it.
NEAR_MISS_HYPHENATED_SPELLING: Final[str] = "conda-package-supply-chain-monitor"

#: The two trees `CPM-RENAME-S01` AC 1 names, and nothing else.
SCANNED_ROOTS: Final[tuple[Path, ...]] = (REPO_ROOT / "src", REPO_ROOT / "tests")

#: Every file under those two trees, migrations included. Migrations are in scope
#: here and out of scope for the syntax audits for opposite reasons: what those
#: read is code Django generated, while what this reads is an import path a human
#: has to keep correct for the migration to load at all.
SUBJECT_FILES: Final[tuple[Path, ...]] = tuple(
    sorted(path for root in SCANNED_ROOTS for path in project_files(root, suffix=None)),
)

#: Files the scan must reach, so the sweep above cannot pass by covering nothing.
#: Modules under both roots, one migration and two data files that are not Python
#: at all -- the last two being exactly what a walk keyed on `".py"` would miss.
#:
#: The three entries under `tests/` are deliberately one per level. Pinning only
#: `tests/conftest.py` pins the tree's root file and nothing below it, so an
#: exclusion that dropped `tests/unit/` or `tests/integration/` from the walk
#: would leave this case and the file-type case below both green while roughly
#: two thirds of `tests/` stopped being scanned -- and the file-type case would
#: still pass because `src/` alone satisfies every suffix it names.
NAMED_FILES_THE_SCAN_MUST_REACH: Final[tuple[str, ...]] = (
    "src/config/settings/base.py",
    "src/django_apps/conda_sentinel/collectors/data/watchlist.csv",
    "src/django_apps/conda_sentinel/core/apps.py",
    "src/django_apps/conda_sentinel/identity/migrations/0004_version_authority_order.py",
    "src/django_apps/conda_sentinel/policies/data/policy-parameters.toml",
    "tests/conftest.py",
    "tests/integration/conftest.py",
    "tests/unit/django_apps/test_core_app.py",
)

#: The four labels the rename was not allowed to change, and the dotted names
#: they are derived from.
APPLICATION_LABELS: Final[tuple[str, ...]] = ("collectors", "core", "identity", "policies")


def _path_names_the_former_import_root(path: Path, root: Path) -> bool:
    """Report whether where `path` sits under `root` spells the former import root.

    Args:
        path: The file to judge.
        root: The tree the answer is relative to -- `REPO_ROOT` for the sweep, and
            a `tmp_path` for the falsification case, which is why this is a
            parameter rather than the constant it always is in practice.

    Returns:
        True when any segment of the relative path carries the forbidden name, in
        a directory component or in the file's own. Matching the joined relative
        path rather than the segments is deliberate: the name is a single
        identifier that cannot straddle a separator, and a substring match also
        catches the near-misses -- `<former name>_helpers.py`, `old_<former
        name>/` -- that a segment-equality test would wave through.

    """
    return FORMER_IMPORT_ROOT in str(path.relative_to(root))


def _offending_lines(path: Path) -> list[str]:
    """Return the numbered lines of `path` that carry the former import root.

    Args:
        path: The file to read, as bytes -- the tree holds a favicon, and a
            decode step would raise on it before any comparison happened.

    Returns:
        One `"<line number>: <text>"` entry per offending line, so a failure
        points at the edit rather than only at the file. Empty when the file is
        clean, and empty for a file whose bytes are not UTF-8 once the name is
        known to be absent from them.

    """
    needle = FORMER_IMPORT_ROOT.encode()
    content = path.read_bytes()
    if needle not in content:
        return []
    return [
        f"{number}: {line.decode(errors='replace')}"
        for number, line in enumerate(content.splitlines(), start=1)
        if needle in line
    ]


@pytest.mark.parametrize(
    "path",
    SUBJECT_FILES,
    # `as_posix()` so a case id names the same file on every runner: `str()`
    # would report `src\config\...` on Windows and `src/config/...` elsewhere,
    # and a guard whose failures are grepped wants one spelling.
    ids=lambda path: path.relative_to(REPO_ROOT).as_posix(),
)
def test_no_file_under_src_or_tests_names_the_former_import_root(path: Path) -> None:
    """AC 1: the former identifier appears nowhere in either tree.

    Parametrized per file rather than swept into one assertion because the
    criterion is that a test fails *naming the file*: a single case listing two
    hundred offenders is a failure somebody skims, and the name creeps back in
    ones and twos.

    Both halves of "appears nowhere" are checked. The path assertion comes first
    because it is the one that catches the file whose bytes are innocent -- a
    watchlist CSV restored under a directory named for the old root -- and
    because a report saying the *location* is wrong is more useful than one
    pointing at a line inside it.
    """
    assert not _path_names_the_former_import_root(path, REPO_ROOT), (
        f"{path.relative_to(REPO_ROOT)} names the former import root in its path"
    )
    assert _offending_lines(path) == [], f"{path.relative_to(REPO_ROOT)} names the former import root"


def test_the_scan_reaches_the_files_it_claims_to() -> None:
    """The sweep is not vacuous, and it is not Python-only.

    Every assertion in this module is "the name is absent", which is what an
    empty scan also reports. The named files are the ones an exclusion added
    later would most plausibly take out of view.
    """
    # `as_posix()` rather than `str()`: the named files above are written with
    # forward slashes, and `str()` on a Windows path yields backslashes, so the
    # comparison would fail on the compatibility runner for a reason that has
    # nothing to do with what this case is about.
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in SUBJECT_FILES}

    assert set(NAMED_FILES_THE_SCAN_MUST_REACH) <= scanned


def test_the_scan_covers_the_file_types_that_are_not_python() -> None:
    """A name in a template or a data file is the same offence as one in a module.

    Stated as a property of the scanned set rather than as a count, so adding a
    template or a CSV does not need an edit here; what would need one is a change
    that narrowed the walk back to modules.
    """
    suffixes = {path.suffix for path in SUBJECT_FILES}

    assert {".csv", ".html", ".md", ".py", ".toml"} <= suffixes


def test_the_detector_finds_the_former_name_when_it_is_present(tmp_path: Path) -> None:
    """The gate is falsifiable: reintroduce the name and a case fails naming the file.

    Written into `tmp_path` rather than under `src/`, because a fixture file
    carrying the forbidden name would be found by the sweep itself and would need
    an exemption -- and an exemption is the one thing a gate like this must not
    have.
    """
    offender = tmp_path / "regression.py"
    offender.write_text(
        f"from {FORMER_IMPORT_ROOT}.core.models import PolicyRun\n",
        encoding="utf-8",
    )

    found = _offending_lines(offender)

    assert found == [f"1: from {FORMER_IMPORT_ROOT}.core.models import PolicyRun"]


def test_the_detector_finds_the_former_name_in_a_path_whose_bytes_are_clean(tmp_path: Path) -> None:
    """The gate is falsifiable on the case the byte scan alone cannot see.

    The file written here is the real shape of the miss rather than a contrived
    one: a watchlist CSV, whose contents are package names and never a module
    path, restored under a directory named for the former import root. Because
    `[tool.hatch.build.targets.wheel.sources]` maps `src/django_apps` to the wheel
    root, such a directory is importable under the old top-level name, so a gate
    that passed it would be reporting success while the former import root was
    plainly present.

    The two assertions are one claim: the byte detector finds nothing, and the
    path detector finds it anyway.
    """
    offender = tmp_path / "src" / "django_apps" / FORMER_IMPORT_ROOT / "collectors" / "data" / "watchlist.csv"
    offender.parent.mkdir(parents=True)
    offender.write_text("package_name\nnumpy\nscipy\n", encoding="utf-8")

    assert _offending_lines(offender) == []
    assert _path_names_the_former_import_root(offender, tmp_path)


def test_the_detector_ignores_the_hyphenated_spelling(tmp_path: Path) -> None:
    """The hyphenated spelling of the same words is not an offence here.

    It named the distribution until `CPM-RENAME-S02`. One file under `src/`
    carries it today and must keep passing:
    `config/observability/telemetry.py`'s `DEFAULT_SERVICE_NAME`, which names the
    product and was deliberately left. The separation is asserted rather than left
    to the fact that the two strings happen to differ.

    Asserted for the path detector as well as the byte one, which also pins that
    the path detector answers False for something: a detector that returned True
    unconditionally would satisfy the falsification case above and fail every file
    in the sweep, but one that matched the hyphenated spelling too would fail only
    the handful of files that legitimately carry it.
    """
    innocent = tmp_path / NEAR_MISS_HYPHENATED_SPELLING / "packaging.py"
    innocent.parent.mkdir(parents=True)
    innocent.write_text(f'PROJECT_URL = "{NEAR_MISS_HYPHENATED_SPELLING}"\n', encoding="utf-8")

    assert _offending_lines(innocent) == []
    assert not _path_names_the_former_import_root(innocent, tmp_path)


def test_the_forbidden_identifier_is_the_one_the_rename_replaced() -> None:
    """A typo in the assembly above would make every case in this module vacuous.

    The digest is of the former name, which cannot change again, so this pin needs
    no maintenance -- unlike the name itself, which this module may not spell.
    """
    digest = hashlib.sha256(FORMER_IMPORT_ROOT.encode()).hexdigest()

    assert digest == FORMER_IMPORT_ROOT_DIGEST


def test_the_import_root_that_replaced_it_is_the_one_in_use() -> None:
    """The name is gone *because* it moved, not because the applications did.

    Absence on its own is also what deleting `src/django_apps/` would produce.
    """
    names = {app_config.name for app_config in apps.get_app_configs()}
    moved = {name for name in names if name.startswith(f"{CURRENT_IMPORT_ROOT}.")}

    assert moved == {f"{CURRENT_IMPORT_ROOT}.{label}" for label in APPLICATION_LABELS}


def test_the_four_application_labels_survived_the_move() -> None:
    """AC 2's precondition, asserted rather than assumed.

    Django takes a label from the last segment of `AppConfig.name`, so moving the
    parent package leaves all four alone. Migration dependencies name these short
    labels and so do the rows in `django_content_type`; a label that moved with
    the package would have made this a schema change and a different story.

    Filtered on the trailing dot, exactly as the case above is: a bare prefix also
    sweeps in a hypothetical sibling distribution whose root merely starts with
    the same characters, and the two cases disagreeing about what counts as "in
    the package" is how one of them quietly stops testing what it says.
    """
    labels = {
        app_config.label
        for app_config in apps.get_app_configs()
        if app_config.name.startswith(f"{CURRENT_IMPORT_ROOT}.")
    }

    assert labels == set(APPLICATION_LABELS)


def test_no_model_carries_the_former_or_current_import_root_in_its_table_name() -> None:
    """No `db_table` names the package, which is why no table had to be renamed.

    The former spelling and the current one are both asserted: a table named for
    the old package would have made this story a migration, and one named for the
    new package would make the *next* rename one.
    """
    tables = {
        model._meta.db_table  # noqa: SLF001
        for model in apps.get_models()
        if model._meta.app_label in APPLICATION_LABELS  # noqa: SLF001
    }
    offenders = {table for table in tables if FORMER_IMPORT_ROOT in table or CURRENT_IMPORT_ROOT in table}

    assert offenders == set()
