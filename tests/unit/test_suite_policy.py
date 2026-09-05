"""Tests for the policy the test suite itself must obey.

Story 1.2 moved the gate onto PostgreSQL (FR-32). Its AC #2 has two halves. The
first -- "every failure arising from sqlite-permissive behaviour is fixed at its
source" -- was vacuous when the story ran, because PostgreSQL surfaced no
failures at all. The second half is not vacuous, and it is not about that run:
no failure may be *dodged* rather than fixed, ever. That obligation was checked
once, by hand, with grep. This file is what keeps it checked.

The forms banned here are the ones a developer reaches for when a test fails
only in CI: skipping it, marking it `xfail`, or branching on the connection's
vendor so the assertion applies on one backend and not the other. Each converts
a refusal into a warning, which CG-3 forbids, and each would make the gate's
move to PostgreSQL cosmetic.

Matched on the parsed syntax tree rather than by text search. Prose about the
prohibition -- which this module and `tests/integration/test_postgres_schema.py`
both contain -- is then not itself an offence, and `assert connection.vendor ==
expected` (an assertion, the opposite of an evasion) is distinguished from
`if connection.vendor == ...` (a branch), which a grep cannot do.

The ban is absolute except where a decision was recorded, and a recorded
exemption is counted rather than described: `RECORDED_EXEMPTIONS` below licenses
a fixed *number* of a fixed form in a fixed file -- one `pytest.skip(...)` in
`integration/test_import_resolution.py`, say, for a dependency that has no build
on one of the three declared platforms. A second `pytest.skip` in that same file
fails the gate exactly as it would anywhere else, which is the point: the
exemption is a licence for one decision that was recorded, not for the file.

The scan reads every `.py` under `tests/`, not only the modules pytest collects.
An evasion written into an imported helper suppresses a test just as effectively
as one written into the test, so a scan keyed on collection names would be a ban
with a door in it -- and the door would open by renaming a file.

This is a unit test: it reads repository files and parses them, and opens no
network or database connection.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]

# Marker attributes that suppress a test outright. `skipif` is included because
# the condition it takes is exactly where "unless we are on sqlite" would go.
BANNED_MARKERS = frozenset({"skip", "skipif", "xfail"})

# Imperative equivalents of the same three, plus `importorskip`, which turns a
# missing driver into a silent pass rather than a failure.
BANNED_CALLS = frozenset({"pytest.skip", "pytest.xfail", "pytest.importorskip"})

# Attribute whose appearance in a branch condition means the test is deciding
# what to assert based on which backend it landed on.
VENDOR_ATTRIBUTE = "vendor"

# Narrowing `django_db` to a subset of configured databases is the same evasion
# expressed as configuration; Task 3 names it alongside the others.
DB_MARKER = "pytest.mark.django_db"

# Recorded exemptions. The module docstring names the one shape that can
# legitimately need a skip -- "a genuinely platform-specific test" -- and
# requires the decision to be recorded in the story that takes it rather than
# added quietly while a CI-only failure is in front of someone. This table is
# that record. It is keyed by module, by the exact evasion *and* by how many
# times that evasion may appear, because keying by form alone would licence the
# form for the whole file: the next "skip if no Postgres" added to the same
# module would be silently permitted, which is precisely the failure Story 1.2's
# ban exists to make loud. The count is one. Both tests below enforce it -- one
# fails on a second occurrence, the other on the first one's removal.
#
# integration/test_import_resolution.py -- Story 1.6, AC #4. The gunicorn leg of
# the three-runtime proof. gunicorn is POSIX-only and has no conda-forge win-64
# build, so pixi.toml declares it (with uvicorn-worker) under
# [target.linux-64.dependencies] and [target.osx-arm64.dependencies] only. On
# win-64 the package is genuinely absent: this is a dependency that cannot be
# installed, not a backend-permissiveness failure being dodged, and AD-18 keeps
# the six-combination harness Linux-only for the same reason. Story 1.6 Task 5
# requires the runtime `pytest.skip` over `@pytest.mark.skip` exactly so the leg
# still runs on every platform that can run it.
# spikes/spike_django_storages_fitness.py -- Story 1.8, Task 6. R-1's
# django-storages fitness spike. Its optional round-trip leg needs a live
# S3-compatible endpoint, which nothing in this repository stands up. The leg is
# armed by an explicit opt-in, `SPIKE_STORAGE_ROUND_TRIP`, rather than by the
# presence of an endpoint variable: gating on "AWS_S3_ENDPOINT_URL is set" meant
# a developer with an AWS profile already exported had the leg write to,
# overwrite in and delete from whatever bucket their shell named, on the
# strength of running the documented command. The skip message reports the
# resulting bound in the same words as the verdict recorded beside the
# declaration in pixi.toml. The spec requires the runtime `pytest.skip` over
# `@pytest.mark.skip` for the same reason Story 1.6 did: the leg still runs
# wherever the resource exists. It is not a dodged gate failure -- the whole
# module runs outside the gate, in the `spike-storage` environment, and cannot
# dodge anything the gate asserts.
# unit/test_release_stage.py -- Story 5.5, Task 1. The Dockerfile half of AD-22's
# "no entrypoint, task or container command runs migrations". `Dockerfile` does
# not exist in this repository yet: Story 5.6 lands it as `machinery` so the
# harness can verify the FR-38/FR-39 payload properties, and materialized
# components ship none at all (AD-15). The assertion is written now, against the
# instruction lines the file will have, and skips with an explicit reason while
# the file is absent -- which is a *sequencing* accommodation and not a dodged
# gate failure: there is no state here to be permissive about, only a file that
# has not been written. The spec requires the runtime `pytest.skip` over
# `@pytest.mark.skip` for the same reason the two entries above do, and this one
# additionally retires itself: the case runs the moment the file appears, and
# Story 5.6's task list carries the obligation that it must pass on that day.
# integration/test_image_payload.py -- Story 5.6, Task 5. The FR-38/FR-39 payload
# properties, verified by building the machinery image and running it under
# `--user 12345:0 --read-only --tmpfs /tmp`. It skips where `docker` is not on
# `PATH`, and the form is the difference: this is a `@pytest.mark.skipif` on a
# *capability* rather than a `pytest.skip` inside a case, because the whole module
# needs the tool and there is no per-case decision to take. It is not a dodged
# gate failure for the same reason the gunicorn entry above is not: the gate runs
# on Linux with Docker available (`.github/workflows/ci.yml`), so every assertion
# here executes there, and what the guard accommodates is a developer machine
# without the tool installed rather than a backend that behaves permissively.
# One occurrence, at module scope: a second `skipif` in this file would be a
# second decision and fails the gate exactly as it would anywhere else.
# coverage_policy.py -- Story 3.6. The AD-20 assertions' shared guard, and the
# entry the widened scan below brought into view rather than a new decision. It
# skips when `--cov` was never passed at all, which is `pixi run
# test-integration` in the inner loop and the one case AD-20's reading sanctions;
# coverage *requested* and not running is the gate defect, and that branch calls
# `pytest.fail`. The guard was written into a helper module partly because the
# scan reached only `test_*.py` and `conftest.py`, which is the door this scan no
# longer leaves open: the decision is recorded here instead, where a second skip
# in that module fails the gate like anywhere else.
# integration/django_apps/test_shared_allowance.py -- CPM-EVIDENCE-S08, AC 4.
# The one claim in this repository that the in-process cache substitution cannot
# even attempt: core/rate_limit.py writes add-then-incr so two worker
# *processes* racing a new window increment one counter rather than one of them
# resetting the other, and under LocMemCache each process holds its own counter,
# so the property cannot fail and every unit case passes against a limiter that
# loses the race. The case starts two real interpreters against a real Redis.
# The form is `@pytest.mark.skipif` on a *capability* rather than a
# `pytest.skip` inside the case, on the same terms as
# integration/test_image_payload.py: the whole module needs the service and
# there is no per-case decision to take. It is not a dodged gate failure for the
# same reason that entry is not one -- .github/workflows/ci.yml declares a
# `redis:7` on the gate job and sets CPM_TEST_REDIS_URL at job level, so the case
# runs on every pull request, and `pixi run gate-redis` runs it locally in one
# command. What the guard accommodates is a developer machine with no Redis.
# tests/unit/test_gate_contract.py pins the service, its health gate and the
# variable, so deleting any of them fails the gate rather than turning these
# cases silently back into skips.
#
# One occurrence, and the occurrence is the *condition* rather than the test.
# The module binds its `pytest.mark.skipif(...)` to a name and applies that name
# to both of its cases, which the detector below counts once because it counts
# expressions -- and that is the right unit: the decision recorded here is "this
# module needs a Redis", taken once, and a further case needing the same service
# is that decision being used again rather than a new one. What the count still
# prevents is a second *condition* -- a skip on another capability, or on this
# one spelled a second way -- which is a second expression and fails the gate
# until somebody records why.
RECORDED_EXEMPTIONS: dict[str, dict[str, int]] = {
    "coverage_policy.py": {"pytest.skip(...)": 1},
    "integration/django_apps/test_shared_allowance.py": {"@pytest.mark.skipif": 1},
    "integration/test_image_payload.py": {"@pytest.mark.skipif": 1},
    "integration/test_import_resolution.py": {"pytest.skip(...)": 1},
    "spikes/spike_django_storages_fitness.py": {"pytest.skip(...)": 1},
    "unit/test_release_stage.py": {"pytest.skip(...)": 1},
}


def _dotted_name(node: ast.expr) -> str:
    """Return the dotted source spelling of an attribute or name expression."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _test_modules() -> list[Path]:
    """Return every Python module under `tests/`, whatever runs it.

    One glob, not three. The three it replaces -- `test_*.py`, `spike_*.py`,
    `conftest.py` -- were the names of the things that get *collected*, and that
    is the wrong question: what the ban is about is where an evasion can be
    written, and a `pytest.skip` in a module the suite imports suppresses a test
    exactly as one written in the test does. `tests/pixi_manifest.py`,
    `tests/coverage_policy.py` and `tests/unit/startup/forbidden_states.py` are
    all imported by cases in the gate and none of them matched any of the three
    globs, so the ban had precisely the door this scan's own docstring says it
    must not acquire: one that opens by naming a file something else.

    Scanning every `.py` under `tests/` is the only rule with no such door,
    because it has no convention in it to satisfy. A helper that legitimately
    needs one is a decision to record in `RECORDED_EXEMPTIONS` above, in the
    open, like any other.
    """
    return sorted(TESTS_ROOT.rglob("*.py"))


def _evasions(path: Path) -> list[str]:
    """Return every gate evasion in one module, as `line: description` strings."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in BANNED_MARKERS:
            dotted = _dotted_name(node)
            if dotted.startswith("pytest.mark."):
                found.append(f"{node.lineno}: @{dotted}")
        elif isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            if dotted in BANNED_CALLS:
                found.append(f"{node.lineno}: {dotted}(...)")
            elif dotted == DB_MARKER and any(keyword.arg == "databases" for keyword in node.keywords):
                found.append(f"{node.lineno}: {dotted}(databases=...)")
        elif isinstance(node, ast.If | ast.IfExp) and _branches_on_vendor(node.test):
            found.append(f"{node.lineno}: branch on the backend vendor")
    return found


def _branches_on_vendor(test: ast.expr) -> bool:
    """Report whether a branch condition inspects the connection's vendor."""
    return any(isinstance(child, ast.Attribute) and child.attr == VENDOR_ATTRIBUTE for child in ast.walk(test))


def test_the_suite_has_test_modules_to_check() -> None:
    """The scan below means nothing if its glob resolves to nothing."""
    modules = _test_modules()
    assert len(modules) > 1, f"expected the suite to be discoverable under {TESTS_ROOT}, found {modules}"


@pytest.mark.parametrize("path", _test_modules(), ids=lambda path: str(path.relative_to(TESTS_ROOT)))
def test_no_test_dodges_the_postgresql_gate(path: Path) -> None:
    """AC #2: a PostgreSQL failure is fixed at its source, never suppressed.

    Parameterized per module so a violation names the file that introduced it
    rather than reporting the whole suite as broken.

    If one of these ever needs to be legitimate -- a genuinely
    platform-specific test, say -- that is a deliberate decision to record in
    the story that makes it, not a line to add quietly while a CI-only failure
    is in front of you. The point of the check is that it is in the way at
    exactly that moment.

    `RECORDED_EXEMPTIONS` above is where such a decision is written down, and it
    is spent per occurrence rather than per form: a module that has used its one
    recorded `pytest.skip` gets no second one for free.
    """
    relative = path.relative_to(TESTS_ROOT).as_posix()
    exempted = RECORDED_EXEMPTIONS.get(relative, {})
    counted = Counter(evasion.split(": ", 1)[1] for evasion in _evasions(path))
    over_quota = {form for form, count in counted.items() if count > exempted.get(form, 0)}
    evasions = [evasion for evasion in _evasions(path) if evasion.split(": ", 1)[1] in over_quota]
    assert evasions == [], f"{relative} dodges the gate rather than failing on it: {evasions}"


def test_the_exemption_table_has_entries_to_check() -> None:
    """The parametrize below means nothing if the table it reads is empty.

    An emptied `RECORDED_EXEMPTIONS` would collect one skipped test and report
    nothing at all -- the same silence the sibling
    `test_the_suite_has_test_modules_to_check` exists to prevent for the scan.
    """
    assert RECORDED_EXEMPTIONS != {}


@pytest.mark.parametrize("relative", sorted(RECORDED_EXEMPTIONS), ids=str)
def test_every_recorded_exemption_still_describes_the_file(relative: str) -> None:
    """An exemption that no longer applies is a licence nobody meant to leave open.

    Checked in the same direction as the exemption is granted: the module has to
    be one the scan above actually reaches -- a rename would otherwise leave the
    entry green while the file it licenses goes unscanned -- and it has to still
    contain the recorded evasion exactly as many times as the table records.
    Delete the `pytest.skip` and this fails until the entry above goes with it;
    add a second one and it fails from the other side.
    """
    module = TESTS_ROOT / relative
    assert module in _test_modules(), f"{relative} is exempted but is not a module the scan collects"

    counted = Counter(evasion.split(": ", 1)[1] for evasion in _evasions(module))
    recorded = RECORDED_EXEMPTIONS[relative]
    mismatched = {
        form: (counted.get(form, 0), expected)
        for form, expected in recorded.items()
        if counted.get(form, 0) != expected
    }
    assert mismatched == {}, f"{relative}: recorded exemptions no longer match, found vs recorded {mismatched}"
