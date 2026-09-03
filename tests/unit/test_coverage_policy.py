"""Tests for the coverage policy: one floor, and a closed measurement surface.

AD-20 makes coverage the product's only residue detector for content no import
graph, linter or dependency analyzer can see (CG-1), and names the two ways it
goes blind without anything else failing: the floor is lowered, or the measured
set is narrowed. Both are one line in a configuration table. These tests are
what make either of them a gate failure.

Three variances are recorded here so they are read as decisions rather than as
oversights:

* **"carrier-declared" is satisfied by an interim site.** AD-20 speaks of the
  omit/exclude list as *carrier-declared*, and the carrier -- `accelerator.toml`
  -- does not exist yet (Epic 7, Story 7.1). Until it does, "held in exactly one
  place" is satisfied by `pyproject.toml [tool.coverage.run]`. Epic 7's author
  should read that table as the declaration itself, relocated, not as a second
  declaration beside a new one. Every read of it goes through
  `tests/coverage_policy.py`, so the move changes that module and nothing else.

* **The `tools/` measurement bound is recorded, not resolved.**
  `include = ["src/**"]` leaves `tools/materializer/` and `tools/harness/` --
  both drawn by the Structural Seed, neither existing yet -- outside
  measurement. Adding measurable code outside the measured set is the silent
  narrowing CG-1 forbids, and the spine asks for a decision rather than a
  default. This story does not take that decision. It pins the value, so
  widening `include` when those directories arrive is a deliberate change to a
  declared surface rather than an unnoticed one.

* **The second exclusion surface is frozen, not reconciled.**
  `sonar-project.properties` declares `sonar.coverage.exclusions` for the
  merge-blocking SonarCloud gate, and it does not agree entry-for-entry with
  `[tool.coverage.run] omit`. Aligning them means editing the input to an
  external gate, which this story does not own. `CLOSED_SONAR_EXCLUSIONS` below
  pins it exactly as it reads today, divergence included, so the disagreement
  is a recorded state rather than a drifting one.

These read the manifests and the source tree, so they are unit tests: no I/O
beyond reading repository files, no network, no database. The live half of
AD-20 -- that the declared surface is the one actually in force during a
measured run -- is `tests/integration/test_coverage_measurement.py`.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING

import pytest

from tests.coverage_policy import DECLARATION_SITE
from tests.coverage_policy import FLOOR_FLAG
from tests.coverage_policy import FLOOR_SITE
from tests.coverage_policy import FLOOR_TASK
from tests.coverage_policy import PIXI_MANIFEST
from tests.coverage_policy import PYPROJECT
from tests.coverage_policy import REPO_ROOT
from tests.coverage_policy import SONAR_DECLARATION_SITE
from tests.coverage_policy import SONAR_PROPERTIES
from tests.coverage_policy import SRC_ROOT
from tests.coverage_policy import activation_env
from tests.coverage_policy import coverage_paths_table
from tests.coverage_policy import coverage_report_table
from tests.coverage_policy import declared_exclude
from tests.coverage_policy import declared_fail_under
from tests.coverage_policy import declared_floor
from tests.coverage_policy import declared_include
from tests.coverage_policy import declared_omit
from tests.coverage_policy import pixi_tasks
from tests.coverage_policy import pytest_addopts
from tests.coverage_policy import reconcile
from tests.coverage_policy import sonar_coverage_exclusions
from tests.coverage_policy import tasks_in_manifest

if TYPE_CHECKING:
    from pathlib import Path

# The closed surface, frozen. This is what makes the list *closed* rather than
# merely declared: reconciling the declaration against the effective
# configuration cannot notice an entry added to both at once, because adding it
# to the declaration is how it becomes effective. An addition has to be made
# here too, in a file whose whole subject is that additions are deliberate.
#
# `src/config/websocket.py` is deliberately absent: Story 1.4 deleted the module
# and removed its entry. Nothing in this list may name a file that no longer
# exists -- an omit entry outliving its file is a hole waiting for a new file to
# be dropped into it.
CLOSED_OMIT = [
    "*/migrations/*",
    "*/tests/*",
    "**/*.egg-info/**",
    "src/config/wsgi.py",
    "src/config/asgi.py",
]

# The measurement bound. Narrowing this is the other way to blind the detector,
# and it fails the same way an omit addition does.
CLOSED_INCLUDE = ["src/**"]

# The line-exclusion surface, frozen empty. An empty declared surface is still a
# declared surface, and freezing it is what makes it *closed* rather than merely
# absent: `test_no_line_exclusion_surface_is_declared` below has to be deleted
# the first time a genuine exclusion is needed, and this constant is what keeps
# the reconciliation biting after that happens.
CLOSED_EXCLUDE: list[str] = []

# The *other* coverage-exclusion surface: what SonarCloud's merge-blocking
# quality gate drops from the coverage view it publishes. Frozen exactly as it
# reads today, deliberately including its divergence from CLOSED_OMIT above:
#
#   * `**/*.egg-info/**` is omitted from the pytest-cov surface and is not
#     excluded here;
#   * this list writes `tests/**` and `**/migrations/**` where CLOSED_OMIT
#     writes `*/tests/*` and `*/migrations/*` -- the same intent in Sonar's
#     path-matcher rather than in coverage's.
#
# The two are not reconciled against each other, and that is the decision, not
# an oversight: `sonar-project.properties` feeds an external merge-blocking gate
# and aligning the lists is a change to that gate's input, which is outside this
# story. What this constant buys is that the divergence is now a *recorded*
# state rather than a drifting one -- either list moving fails here -- so closing
# it later is a deliberate act with both surfaces in view.
CLOSED_SONAR_EXCLUSIONS = [
    "tests/**",
    "src/config/wsgi.py",
    "src/config/asgi.py",
    "**/migrations/**",
]

# The tree `--cov` names on the floor-carrying task. Under `--cov=src` coverage
# sets a *source*, and a source supersedes `include` -- see
# `test_the_floor_task_measures_the_whole_suite_and_the_whole_source_tree`.
COVERAGE_SOURCE = "src"

# AD-20's constant: ninety percent, including templates, everywhere. Never
# lowered, never per-directory. `FLOOR_FLAG` and `FLOOR_TASK` are imported from
# the reader rather than restated here, because the integration module needs
# them too and a second copy of the floor's spelling is a second declaration.
COVERAGE_FLOOR = 90
FLOOR_ARGUMENT = f"{FLOOR_FLAG}={COVERAGE_FLOOR}"

# Flags that narrow what the floor-carrying task measures, or switch measurement
# off outright, while leaving `tests/`, `--cov=src` and `--cov-fail-under=90`
# all present and correct on the command. Token membership alone does not see
# any of them: `pytest tests/ --cov=src --cov-fail-under=90 --ignore=tests/integration`
# still contains every token the positive assertions look for, and measures
# neither template rendering nor anything else the integration suite reaches.
# `--no-cov` is the worst of them -- pytest-cov accepts it alongside `--cov` and
# disables measurement entirely, which also takes every live assertion in
# `tests/integration/test_coverage_measurement.py` with it.
NARROWING_FLAGS = ("--ignore", "--ignore-glob", "--deselect", "-k", "-m", "--no-cov")

# Files pytest and coverage read *instead of* pyproject.toml when they exist.
# pytest stops at the first of pytest.ini / tox.ini / setup.cfg it finds and
# never reaches `[tool.pytest.ini_options]`; coverage prefers .coveragerc over
# pyproject.toml the same way. Any of them could carry its own `addopts` with a
# last-wins `--cov-fail-under`, or its own `[coverage:run] omit`, and every
# assertion in this file would still read the untouched declaration.
COMPETING_CONFIG_FILES = ("pytest.ini", "tox.ini", "setup.cfg", ".coveragerc")

# django_coverage_plugin is a dynamic file tracer and needs `sys.settrace`.
# Python 3.12+ defaults to the `sysmon` core, under which templates are
# discovered but never traced and silently report 0% -- a measurement that looks
# like a measurement. The environment variable is what keeps that from happening.
COVERAGE_CORE_VARIABLE = "COVERAGE_CORE"
C_TRACE_CORE = "ctrace"

# coverage's own default pragma, in the spelling its default exclude list uses.
# AC #4 forbids clearing the floor with one of these: a pragma on unreached code
# removes the line from the denominator, which raises the percentage without
# anything being covered, and does it from inside a source file where no review
# of the coverage configuration would look.
NO_COVER_PRAGMA = re.compile(r"#\s*pragma[:\s]?\s*no\s*cover", re.IGNORECASE)


def _source_files() -> list[Path]:
    """Return every Python file under `src/`.

    Returns:
        The sorted list of `.py` files in the source tree.

    """
    return sorted(SRC_ROOT.rglob("*.py"))


def _tokens_carrying(command: list[str], flag: str) -> list[str]:
    """Return the tokens in `command` that pass `flag`, in any of its spellings.

    pytest accepts `--ignore=path` and `--ignore path` for long options, and
    `-k expr`, `-k=expr` and `-kexpr` for short ones. A membership test against
    the bare flag sees only the middle spelling of each.

    Args:
        command: The task's command, tokenized.
        flag: The option to look for, e.g. `--ignore` or `-k`.

    Returns:
        Every token carrying that option.

    """
    short = not flag.startswith("--")
    return [
        token
        for token in command
        if token == flag or token.startswith(f"{flag}=") or (short and token.startswith(flag))
    ]


def test_the_declaration_sites_are_present() -> None:
    """The paths resolve from the test file, so the assertions below mean something."""
    assert PYPROJECT.is_file()
    assert PIXI_MANIFEST.is_file()
    assert SRC_ROOT.is_dir()


def test_the_declared_omit_list_is_the_closed_surface() -> None:
    """AC #3: the omit list is closed, and every entry in it is accounted for.

    Reconciled in both directions with the offending entries named on each
    side, because "the two lists differ" is not a message anyone can act on.
    """
    missing, unexpected = reconcile(CLOSED_OMIT, declared_omit())
    assert (missing, unexpected) == ([], []), (
        f"the omit list declared at {DECLARATION_SITE} is not the closed surface: "
        f"dropped {missing}, added {unexpected}. Adding an entry is a deliberate "
        "act -- record the reason, then update CLOSED_OMIT here."
    )


def test_every_omitted_path_still_exists() -> None:
    """A concrete omit entry must name a file that is really there.

    The glob entries (`*/migrations/*` and the rest) are patterns and cannot be
    checked this way, but the two named modules can. An entry that outlives its
    file is a pre-authorised hole: the next module dropped at that path is
    unmeasured from its first line, and nothing in the declaration changed.
    """
    orphans = [entry for entry in declared_omit() if "*" not in entry and not (SRC_ROOT.parent / entry).exists()]
    assert orphans == [], f"these omit entries name files that no longer exist: {orphans}"


def test_the_measurement_bound_is_not_narrowed() -> None:
    """AC #3: `include` is part of the same closed surface as `omit`.

    Narrowing it blinds the detector exactly as effectively as omitting a path,
    and reads as an even smaller change. See the module docstring for the
    recorded -- and deliberately unresolved -- `tools/` question this pins.
    """
    assert declared_include() == CLOSED_INCLUDE, (
        f"the measurement bound declared at {DECLARATION_SITE} is {declared_include()}, not {CLOSED_INCLUDE}"
    )


def test_no_line_exclusion_surface_is_declared() -> None:
    """AC #3: an empty exclude surface is still a declared surface.

    `[tool.coverage.report]` is absent today, so the effective exclude list is
    coverage's own default. Asserting the absence explicitly is what makes
    adding `exclude_lines` later a gate failure rather than a silent widening;
    the effective half of that check lives in the integration module, which
    compares the list in force against coverage's `DEFAULT_EXCLUDE`.
    """
    assert coverage_report_table() is None, (
        f"[tool.coverage.report] is now declared in {PYPROJECT.name} with {coverage_report_table()}; "
        "an exclude surface is a declared surface and must be reconciled, not merely added"
    )


def test_the_declared_exclude_surface_is_the_closed_one() -> None:
    """AC #3: the exclude list is closed the same way the omit list is.

    Deliberately separate from the assertion above, and deliberately not folded
    into it. That one says the table does not exist, and it is the assertion
    that has to be *deleted* the first time an exclusion is genuinely needed.
    This one survives that deletion: it reconciles whatever is declared against
    a frozen list, so the first real entry fails here until it is recorded in
    `CLOSED_EXCLUDE` -- which is the whole point of a closed surface, and is
    what the integration module's reconciliation against coverage's
    `DEFAULT_EXCLUDE` cannot supply on its own, since it folds the declaration
    into its own expectation.
    """
    missing, unexpected = reconcile(CLOSED_EXCLUDE, declared_exclude())
    assert (missing, unexpected) == ([], []), (
        f"the exclude list declared at {DECLARATION_SITE} is not the closed surface: "
        f"dropped {missing}, added {unexpected}. Record the reason, then update CLOSED_EXCLUDE here."
    )


def test_no_per_directory_narrowing_is_declared() -> None:
    """AC #4: the floor is never made per-directory.

    `[tool.coverage.paths]` remaps measured paths onto each other, which is how
    a subtree gets its own accounting. There is no per-package `fail_under`
    either -- coverage has no such setting -- so the table is the shape this
    guards.
    """
    assert coverage_paths_table() is None, f"[tool.coverage.paths] remaps measurement: {coverage_paths_table()}"


def test_the_floor_has_no_competing_declaration() -> None:
    """AC #4: one constant, in one place.

    `[tool.coverage.report] fail_under` would be a second site, and a lower
    value there would be the one that bit -- coverage applies its own setting
    when pytest-cov does not pass the flag, and the two can disagree without
    either looking wrong on its own.
    """
    assert declared_fail_under() is None, (
        f"a second coverage floor is declared in {PYPROJECT.name}: fail_under = {declared_fail_under()}"
    )


def test_pytest_addopts_declares_no_floor() -> None:
    """AC #4: `addopts` is the other place the flag could quietly appear.

    `[tool.pytest.ini_options] addopts` applies to every pytest invocation, so
    a floor there would apply to `pixi run test` as well -- and pytest-cov
    takes the last `--cov-fail-under` on the command line, which would be the
    one in `addopts`, not the one on the task.
    """
    offenders = [token for token in pytest_addopts() if token.startswith(FLOOR_FLAG)]
    assert offenders == [], f"the floor must not be declared in pytest addopts: {offenders}"


def test_no_competing_configuration_file_can_displace_the_declaration() -> None:
    """AC #3 and #4: the declaration is only single if nothing outranks its file.

    pytest reads the first of `pytest.ini`, `tox.ini` and `setup.cfg` it finds
    and never reaches `[tool.pytest.ini_options]`; coverage prefers
    `.coveragerc` to `pyproject.toml` the same way. Any of them could carry an
    `addopts` with a last-wins `--cov-fail-under`, or its own omit list, and
    every other assertion in this file would go on reading the untouched
    declaration and passing. None of them exists today; this is what keeps that
    true.
    """
    present = [name for name in COMPETING_CONFIG_FILES if (REPO_ROOT / name).exists()]
    assert present == [], (
        f"these files outrank or displace the coverage and pytest configuration in {PYPROJECT.name}: {present}. "
        f"The declaration is only held in one place while none of them exists."
    )


def test_the_floor_is_declared_exactly_once_and_is_ninety() -> None:
    """AC #4: ninety percent, and no second declaration anywhere in the manifest.

    Every task is scanned, not only `test-cov`, because a second task carrying
    its own floor is precisely how a combination would get a lower one while
    `test-cov` still read `=90`. Every task *table* is scanned too -- see
    `test_the_task_scan_reaches_a_platform_scoped_table`, which is what makes
    "every task" mean the manifest rather than two of its tables.

    `declared_floor()` is pinned here as well: the integration module asserts
    the floor in force against that reader, so a reader that returned the wrong
    number would make the live assertion agree with nothing.
    """
    carriers = {
        name: [token for token in tokens if token.startswith(FLOOR_FLAG)] for name, tokens in pixi_tasks().items()
    }
    declaring = {name: flags for name, flags in carriers.items() if flags}
    assert list(declaring) == [FLOOR_TASK], f"the floor must be declared only by {FLOOR_SITE}, found {declaring}"
    assert declaring[FLOOR_TASK] == [FLOOR_ARGUMENT], (
        f"{FLOOR_TASK} declares {declaring[FLOOR_TASK]}, not [{FLOOR_ARGUMENT!r}] (AD-20: ninety percent, everywhere)"
    )
    assert declared_floor() == COVERAGE_FLOOR, (
        f"the reader reports a declared floor of {declared_floor()}, not {COVERAGE_FLOOR}"
    )


def test_the_floor_task_measures_the_whole_suite_and_the_whole_source_tree() -> None:
    """AC #3 and #4: the floor covers the full suite, over the full measured set.

    A floor over `tests/unit/` alone would still read `=90` while measuring
    nothing the integration tests reach -- template rendering above all, which
    is the coverage AD-20 exists to protect.

    `--cov=src` is asserted here because it, not `[tool.coverage.run] include`,
    is the measurement bound actually in force during the gate. `--cov=X` sets
    coverage's *source*, and coverage ignores `include` whenever a source is
    set -- it says so on every gate run, as `CoverageWarning: --include is
    ignored because --source is set`. So `--cov=src/config` would narrow
    measurement to a third of the tree with the declared `include` untouched
    and every reconciliation still green. That is the same blinding CG-1
    forbids, reached through the one door the declared surface does not cover,
    and this is the assertion that shuts it.

    Token membership alone does not shut it, which is why the denylist below
    exists: every one of `--ignore=tests/integration`, `-m "not integration"`,
    `-k`, `--deselect` and `--no-cov` leaves `tests/`, `--cov=src` and the floor
    all present on the command while narrowing or disabling exactly what this
    docstring claims is measured.
    """
    command = pixi_tasks()[FLOOR_TASK]
    assert "tests/" in command, f"{FLOOR_TASK} must run the whole suite, got {command}"
    assert f"--cov={COVERAGE_SOURCE}" in command, (
        f"{FLOOR_TASK} must measure the whole of {COVERAGE_SOURCE}/, got {command}; "
        "--cov sets coverage's source and supersedes [tool.coverage.run] include"
    )

    narrowing = {flag: _tokens_carrying(command, flag) for flag in NARROWING_FLAGS}
    offenders = {flag: tokens for flag, tokens in narrowing.items() if tokens}
    assert offenders == {}, (
        f"{FLOOR_TASK} narrows or disables what it measures with {offenders}, while still "
        f"reading `tests/ --cov={COVERAGE_SOURCE} {FLOOR_ARGUMENT}`. The floor is only a floor "
        "over the whole suite and the whole tree."
    )


def test_the_c_trace_core_is_declared_for_every_environment() -> None:
    """AC #1: `COVERAGE_CORE=ctrace` travels with the environment, not with a task.

    It sits in `[activation.env]` rather than in `[feature.dev.activation.env]`
    so that every environment carries it -- AD-20's "travels with every
    combination". The assertion that it is actually *in force* during a run is
    in the integration module; this one only pins where it is declared.
    """
    activation = activation_env()
    assert activation.get(COVERAGE_CORE_VARIABLE) == C_TRACE_CORE, (
        f"{COVERAGE_CORE_VARIABLE} must be {C_TRACE_CORE!r} in [activation.env]; "
        "without it Python 3.12+ selects the sysmon core, which cannot run the "
        "template plugin and reports 0% for every template"
    )


def test_no_source_line_is_excluded_by_a_pragma() -> None:
    """AC #4: the floor is never cleared by a pragma on unreached code.

    A pragma removes the line from the denominator, so the percentage rises
    without anything being covered. `src/django_service/__init__.py` carried the
    one instance in this tree; it was removed and the branch it excluded is now
    genuinely exercised by `tests/unit/test_package_version.py`, which is the
    shape every future case of this must take.

    If an exclusion is ever genuinely needed, it belongs in the closed exclude
    surface as a declared entry -- where this file will see it -- and not as a
    comment in a source file.
    """
    offenders = [
        f"{path.relative_to(SRC_ROOT.parent)}:{number}"
        for path in _source_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if NO_COVER_PRAGMA.search(line)
    ]
    assert offenders == [], f"these lines exclude themselves from the floor: {offenders}"


def test_the_sonar_coverage_exclusions_are_a_closed_surface_too() -> None:
    """AC #3: the second exclusion surface is frozen, divergence and all.

    `sonar.coverage.exclusions` is read by the SonarCloud quality gate, which
    blocks merges, so it decides which files anyone ever looks at coverage for.
    It is not the pytest-cov floor and it is not reconciled against
    `CLOSED_OMIT` here -- see the comment on `CLOSED_SONAR_EXCLUSIONS` for the
    three ways the two lists differ today and why aligning them is a later,
    deliberate act rather than part of this story. What this asserts is that
    neither list can move without someone noticing: a drifting divergence
    becomes a recorded one.
    """
    missing, unexpected = reconcile(CLOSED_SONAR_EXCLUSIONS, sonar_coverage_exclusions())
    assert (missing, unexpected) == ([], []), (
        f"the exclusions declared at {SONAR_DECLARATION_SITE} are not the closed surface: "
        f"dropped {missing}, added {unexpected}. This list and {DECLARATION_SITE} deliberately "
        "differ; record the change in CLOSED_SONAR_EXCLUSIONS with the reason."
    )


def test_the_sonar_surface_is_declared_in_the_file_the_gate_reads() -> None:
    """The frozen list means nothing if the reader is pointed at a missing file."""
    assert SONAR_PROPERTIES.is_file()
    assert sonar_coverage_exclusions(), f"{SONAR_PROPERTIES.name} declares an empty coverage-exclusion list"


# A manifest exercising the two task tables this project does not use today and
# the two `cmd` spellings it does not write. `[target.<platform>.tasks]` and
# `[feature.<name>.target.<platform>.tasks]` are both real pixi tables, and
# `[target.<platform>.dependencies]` is already used in the real manifest, so a
# floor hidden in one of them is a plausible change rather than a contrived one.
# Built here rather than by editing pixi.toml: the scan has to be provably able
# to reach these tables without the gate's own manifest carrying a second floor.
MANIFEST_WITH_SCOPED_TASKS = """
[tasks]
plain = { cmd = "pytest tests/" }
bare = "pytest tests/ --cov-fail-under=30"

[target.osx-arm64.tasks]
mac-only = { cmd = "pytest tests/ --cov=src --cov-fail-under=50" }

[feature.dev.tasks]
listed = { cmd = ["pytest", "tests/", "--cov-fail-under=40"] }

[feature.dev.target.linux-64.tasks]
linux-only = { cmd = "pytest tests/ --cov-fail-under=60" }
"""

MANIFEST_WITH_A_TASK_COLLISION = """
[tasks]
test-cov = { cmd = "pytest tests/ --cov=src --cov-fail-under=90" }

[target.osx-arm64.tasks]
test-cov = { cmd = "pytest tests/ --cov=src --cov-fail-under=50" }
"""


def test_the_task_scan_reaches_a_platform_scoped_table() -> None:
    """AC #4: "declared exactly once" means the manifest, not two of its tables.

    A reader that looks only in `[tasks]` and `[feature.<name>.tasks]` cannot
    see a floor in `[target.<platform>.tasks]` or in
    `[feature.<name>.target.<platform>.tasks]`, so
    `test_the_floor_is_declared_exactly_once_and_is_ninety` would pass with a
    second, lower floor in the manifest it just scanned. The three `cmd`
    spellings are exercised in the same pass: a bare string raises on a
    `.get("cmd")` reader, and a list is shredded into non-matching tokens by a
    `shlex.split(str(...))` one. Either shape hides a floor just as well as a
    table the walk never enters.
    """
    tasks = tasks_in_manifest(tomllib.loads(MANIFEST_WITH_SCOPED_TASKS))

    assert sorted(tasks) == ["bare", "linux-only", "listed", "mac-only", "plain"]
    assert tasks["listed"] == ["pytest", "tests/", "--cov-fail-under=40"]
    assert tasks["bare"] == ["pytest", "tests/", "--cov-fail-under=30"]

    carriers = sorted(name for name, tokens in tasks.items() if any(t.startswith(FLOOR_FLAG) for t in tokens))
    assert carriers == ["bare", "linux-only", "listed", "mac-only"], (
        f"the walk saw floors declared by {carriers}; a table or a cmd spelling it cannot reach "
        "is a floor the gate's own scan would miss"
    )


def test_a_task_declared_in_two_tables_is_surfaced_rather_than_overwritten() -> None:
    """The collision is the interesting case, so it must not resolve silently.

    A platform-scoped `test-cov` beside the real one is how a lower floor would
    run on one platform while the scan read `=90` from the other. Whichever of
    the two a dict merge kept, the answer would be a single tidy command and no
    sign that a second one exists.
    """
    with pytest.raises(ValueError, match="test-cov"):
        tasks_in_manifest(tomllib.loads(MANIFEST_WITH_A_TASK_COLLISION))
