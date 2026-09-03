"""The session engine is stated, not inherited, and it is stated in one place (FR-44, AD-31).

**The property.** `SESSION_ENGINE` is assigned in `src/config/settings/base.py`
to the database-backed engine, it is assigned in no other settings module, and
the line it is assigned on falls inside no AD-24 feature region. Those three
together are what "identical in all six combinations" means once materialization
has run: `base.py` is `core`, so every combination gets the line; nothing else
sets it, so no feature's settings fragment can redefine it; and it is outside
every region, so the materializer cannot remove it from the two combinations
that did not select Redis.

**Why it is worth asserting, and what it prevents.** NFR-3 requires sessions to
be database-backed in every combination, and the failure it guards against is
specific rather than theoretical. Two of the six combinations ship no Redis, so
their cache is Django's in-process LocMem backend; a cache-backed session engine
selected "for performance" alongside the Redis feature therefore means
per-replica sessions in those two, where a user stays signed in or does not
depending on which replica answered the request. That is session behaviour
becoming a property of an unrelated feature toggle, which is the single failure
AD-31 names.

**Why a source-level assertion and not only a settings-level one.** Django's own
global default for `SESSION_ENGINE` *is* `django.contrib.sessions.backends.db`.
A test that read `django.conf.settings.SESSION_ENGINE` alone would therefore pass
with the assignment deleted from the tree entirely, and AC #1 says the engine is
set **explicitly in `base.py`** -- the whole point being that a value nobody
states is a value a Django release note can move and a settings fragment can
quietly redefine. So the resolved value and the assignment are asserted
separately, and both are load-bearing: the source assertion alone would pass on a
line that composed the wrong string, and the settings assertion alone would pass
on Django's default.

Disposition `core`. `src/config/settings/base.py` outside every region travels
into all six combinations, so these run in every combination's gate and are never
pruned.

**Deliberately not asserted here.**

* That the *resolved store class* is the database store, and that it is not the
  file backend --
  `tests/unit/test_payload_properties.py::test_the_session_store_is_the_database_store`
  owns that. It asks a different question: what a freshly imported
  `production.py` composes, resolved through `import_string` so that a
  project-local subclass under another dotted path is still the right answer.
  This module asks whether the value was *declared*, which is a question about
  the text.
* That the markers in `base.py` are non-nested and name a *declared* feature.
  `tests/unit/startup/test_feature_scoped_refusals.py::TestTheFeatureRegionMarkers`
  owns the whole of the AD-24 marker grammar, but only over the paths in its own
  `MARKER_BEARING_PATHS` tuple -- and `src/config/settings/base.py` is not one of
  them, because the tuple is the set of files *that* story wrote markers into.
  So the grammar backstop does not read this file, and delegating the whole of it
  would be delegating to a reader that never opens the file.

  The one clause this module therefore cannot delegate is **balance**, and it is
  asserted directly in
  `test_the_session_engine_assignment_is_enclosed_by_no_feature_region` rather
  than named here: `regions()` is deliberately lenient about an unbalanced pair,
  so a malformed pair drawn around `SESSION_ENGINE` in Epic 7 -- a missing close,
  or a close spelled `# /feature:redis-cache` against an open spelled
  `# feature:redis` -- yields no region at all, and "the assignment is inside no
  region" would then pass on the very file the region was drawn wrongly in.
  Nesting and feature-name validity are left undelegated and unasserted until
  `base.py` joins a reconciler that reads it; balance is the clause that turns
  this module's own assertion vacuous, so balance is the clause it keeps.

  What is otherwise used here is the parser, imported from
  `tests/feature_regions.py`.
* The pruning of expired session rows. `tests/unit/test_process_model.py`
  asserts that the admin process is declared and runnable, and
  `tests/integration/test_prune_command.py` asserts that it prunes.
* Session *cookie* hardening. `SESSION_COOKIE_SECURE` and the `__Secure-`
  cookie name are `production.py`'s and are AD-31's other half; nothing here
  changes or restates them.

These read repository files and Django's already-materialised settings: no
database, no network, no subprocess.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING
from typing import Final

from django.conf import settings as active_settings

from tests.feature_regions import marker_events
from tests.feature_regions import regions
from tests.pixi_manifest import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

#: The setting under test, spelled once.
SESSION_ENGINE_SETTING: Final[str] = "SESSION_ENGINE"

#: The engine AC #1 names. Django's global default is this same string, which is
#: exactly why the source assertion below exists alongside the settings one.
DATABASE_SESSION_ENGINE: Final[str] = "django.contrib.sessions.backends.db"

SETTINGS_DIR: Final[Path] = REPO_ROOT / "src" / "config" / "settings"

#: The one module allowed to set it, and the three that must not. All three
#: leaves are named rather than globbed, and the naming is only safe because
#: `test_the_scanners_see_the_files_they_claim_to` enumerates the directory and
#: fails on anything this tuple does not account for: a fourth settings module
#: added later has to be considered, not scanned silently under a rule nobody
#: revisited -- and not missed entirely, which is what a hand-written tuple with
#: no enumeration behind it would do.
BASE_MODULE: Final[Path] = SETTINGS_DIR / "base.py"
LEAF_MODULES: Final[tuple[Path, ...]] = (
    SETTINGS_DIR / "local.py",
    SETTINGS_DIR / "production.py",
    SETTINGS_DIR / "test.py",
)

#: A file that genuinely carries AD-24 markers today. `base.py` carries none --
#: Epic 7's `redis` region will be the first pair in it -- so every region
#: assertion about `base.py` is trivially true, and a parser that had silently
#: stopped finding markers at all would satisfy it just as well. This is what the
#: vacuity guard reads to prove the parser still works.
MARKER_BEARING_MODULE: Final[Path] = REPO_ROOT / "src" / "config" / "startup" / "stage_one.py"


def _assignment_lines(source: str, name: str) -> list[int]:
    """Return the 1-indexed lines on which one name is assigned.

    Parsed rather than grepped: a substring scan counts the name in this file's
    own comments and in `base.py`'s prose about the setting, and would report a
    line number for neither. `ast.walk` rather than `Module.body`, so an
    assignment tucked inside a module-level `try` or `if` is found too -- one
    there is still a settings module setting the value.

    Args:
        source: The module's text.
        name: The setting name to look for.

    Returns:
        One entry per assignment, in the order the parse yields them.
    """
    tree = ast.parse(source)
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            lines.extend(target.lineno for target in node.targets if isinstance(target, ast.Name) and target.id == name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            lines.append(node.target.lineno)
    return sorted(lines)


def _assigned_strings(source: str, name: str) -> list[str]:
    """Return the string literals one name is assigned, ignoring any other value.

    Both assignment forms are read, and reading both is what keeps this function
    and `_assignment_lines` from answering different questions about the same
    file. `_assignment_lines` has always handled `ast.AnnAssign`, so a correct
    `SESSION_ENGINE: str = "django.contrib.sessions.backends.db"` was counted as
    the one permitted assignment there while being invisible here -- and the
    caller would then have failed with a message claiming `base.py` sets the
    engine to `[]`, sending the reader to look for a missing line that is in fact
    present and correct. `test_base_settings_set_the_session_engine_explicitly` is
    the case that reports that message, and it is the one this keeps truthful.

    Args:
        source: The module's text.
        name: The setting name to look for.

    Returns:
        One entry per assignment whose right-hand side is a string constant, in
        either the plain or the annotated form.
    """
    tree = ast.parse(source)
    values: list[str] = []
    for node in ast.walk(tree):
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            values.append(node.value.value)
    return values


def test_the_scanners_see_the_files_they_claim_to() -> None:
    """Non-vacuity, for the three ways every assertion below could be green over nothing.

    The first is the ordinary one: a settings module moved or renamed makes an
    absence assertion pass by scanning a file that is not there.

    The second is the one `LEAF_MODULES` invites by being a hand-written tuple.
    "No *other* settings module sets the engine" is a claim about the directory,
    and it is asserted against three named files -- so a `staging.py` added later
    and setting a cache-backed engine would ship with every case in this module
    green, because nothing would ever have opened it. The directory is therefore
    enumerated and compared against the names, and the comparison is an equality
    rather than a subset: a module deleted is as much a reason to revisit this
    file as a module added.

    The third is the one worth spelling out. `base.py` carries **no** AD-24
    markers at all today, so "the assignment is inside no region" is satisfied
    by a file with no regions, by a parser that found none, and by a parser that
    had stopped working entirely -- three states one assertion cannot tell apart.
    Reading a file that does carry markers is what distinguishes them, and it is
    read through the same `regions()` the region case uses so that the guard
    fails with it rather than beside it.
    """
    assert BASE_MODULE.is_file(), f"{BASE_MODULE} is missing, so every assertion in this module holds over nothing"
    for module in LEAF_MODULES:
        assert module.is_file(), f"{module} is missing, so the absence assertion below scans nothing"

    present = {path.name for path in SETTINGS_DIR.glob("*.py")} - {"__init__.py"}
    accounted = {BASE_MODULE.name} | {module.name for module in LEAF_MODULES}
    assert present == accounted, (
        f"src/config/settings/ holds {sorted(present)}, but this module is written against "
        f"{sorted(accounted)}. Add the new module to LEAF_MODULES and decide whether it may set "
        f"{SESSION_ENGINE_SETTING} -- AC #2 says only base.py may, and a settings module nothing in this "
        f"file opens is a settings module free to set a cache-backed engine with the whole gate green."
    )

    assert MARKER_BEARING_MODULE.is_file()
    assert regions(MARKER_BEARING_MODULE.read_text(encoding="utf-8")), (
        f"the AD-24 parser finds no region in {MARKER_BEARING_MODULE.name}, which does carry marker pairs. "
        f"Until Epic 7 places the `redis` region in base.py, this is the only thing standing between the "
        f"outside-every-region case and a green result that means nothing."
    )


def test_the_resolved_session_engine_is_the_database_engine() -> None:
    """AC #1: what Django actually composed is the database-backed engine.

    Read off `django.conf.settings` rather than off a fresh import, because this
    is the one assertion whose subject is the *materialised* value -- the thing
    `SessionMiddleware` will hand a request. A fresh import would answer a
    question about composition that the source assertions below answer more
    directly, and would reconfigure structlog for the process to do it.

    On its own this proves nothing about AC #1: Django's global default is this
    same string, so it would pass with the assignment deleted. It is here as the
    other end of the pair -- the source assertion says the line exists, this one
    says the line is what actually reaches the request.
    """
    assert active_settings.SESSION_ENGINE == DATABASE_SESSION_ENGINE, (
        f"the composed SESSION_ENGINE is {active_settings.SESSION_ENGINE!r}, not {DATABASE_SESSION_ENGINE!r}. "
        f"NFR-3 makes sessions database-backed in every combination; a cache engine is per-replica wherever "
        f"the cache is LocMem, which is two of the six combinations."
    )


def test_base_settings_set_the_session_engine_explicitly() -> None:
    """AC #1: the value is *declared* in `base.py`, not inherited from Django (AD-31).

    Exactly one assignment, and the string it assigns. "At least one" would
    accept a second assignment further down the file overriding the first, which
    is a settings module that says the engine twice and means whichever came
    last -- the shape of thing a feature fragment appended to `base.py` would
    take.

    The literal is compared rather than the resolved dotted path because AC #1
    is about the declaration. Whether the *store class* that path resolves to is
    the database store is
    `test_payload_properties.py::test_the_session_store_is_the_database_store`'s
    question, and it is asked there with `import_string` for the reason recorded
    in that case.
    """
    source = BASE_MODULE.read_text(encoding="utf-8")
    lines = _assignment_lines(source, SESSION_ENGINE_SETTING)

    assert len(lines) == 1, (
        f"src/config/settings/base.py assigns {SESSION_ENGINE_SETTING} on lines {lines}, not exactly once. "
        f"AC #1 requires it set explicitly and identically everywhere; two assignments mean the file says "
        f"the engine twice and the last one wins."
    )
    assert _assigned_strings(source, SESSION_ENGINE_SETTING) == [DATABASE_SESSION_ENGINE], (
        f"src/config/settings/base.py sets {SESSION_ENGINE_SETTING} to "
        f"{_assigned_strings(source, SESSION_ENGINE_SETTING)}, not [{DATABASE_SESSION_ENGINE!r}]. "
        f"Relying on Django's default -- which is this same string -- is exactly what the explicit "
        f"assignment removes (FR-44)."
    )


def test_no_other_settings_module_sets_the_session_engine() -> None:
    """AC #2, in its mechanical form: no module but `base.py` may set the engine.

    AC #2 forbids the Redis feature from changing `SESSION_ENGINE`. That feature
    has no settings module of its own today -- Epic 7 will place it as a region
    inside a file that already exists -- so the assertion cannot be written
    against a Redis fragment and be written today. What it is written against
    instead is the general rule the specific one is an instance of: `local.py`,
    `production.py` and `test.py` set it nowhere, so a fragment landing in any of
    them, whatever feature owns it, fails here.

    The region case below closes the remaining route, which is a fragment landing
    in `base.py` itself.
    """
    offenders = sorted(
        f"{module.name}:{line}"
        for module in LEAF_MODULES
        for line in _assignment_lines(module.read_text(encoding="utf-8"), SESSION_ENGINE_SETTING)
    )
    assert not offenders, (
        f"these settings modules assign {SESSION_ENGINE_SETTING}: {offenders}. Only base.py may, and only "
        f"once (AC #1, AC #2): a leaf module that sets it makes session behaviour vary by which module a "
        f"combination loads, which is FR-44's failure under a different name."
    )


def test_the_session_engine_assignment_is_enclosed_by_no_feature_region() -> None:
    """AD-24: the assignment travels into all six combinations, because nothing can remove it.

    A feature-owned region is a span of lines the materializer *deletes*. An
    assignment inside one is an assignment removed from every component that did
    not select that region's feature -- whichever feature that turns out to be,
    since the constraint is over regions in general and not over the one Epic 7
    happens to add -- and what those components would fall back to is Django's
    default, which is the right value today and is exactly the guarantee this
    story exists to stop relying on.

    Computed against the file's own text rather than eyeballed, and computed with
    the same parser the AD-24 marker cases use, because the constraint is
    forward-looking: `base.py` carries no markers today, and Epic 7's `redis`
    region will be the first pair in it. This case is what stops that pair from
    being drawn around this line -- which is the single most natural place for
    an author adding a Redis settings fragment to put it, since `SESSION_ENGINE`
    is the setting a cache-backed engine would want to change.

    **Balance is asserted first, and it is what makes the rest mean anything.**
    `regions()` is lenient about an unbalanced pair on purpose -- it returns one
    entry per *closed* pair and silently drops an open marker nothing closes --
    and `src/config/settings/base.py` is not in
    `test_feature_scoped_refusals.py`'s `MARKER_BEARING_PATHS`, so the module that
    owns the AD-24 grammar never opens this file. Between the two, a pair drawn
    wrongly around this very line -- an opening marker with no close, or a close
    spelled `# /feature:redis-cache` against an open spelled `# feature:redis` --
    produces no region at all, and the enclosure assertion below would pass on
    precisely the file whose region was drawn around the assignment it exists to
    protect. Checking the markers pair up is what turns that vacuous pass into a
    failure, and it is checked here rather than delegated because there is
    currently nowhere to delegate it to.
    """
    source = BASE_MODULE.read_text(encoding="utf-8")

    unmatched: list[str] = []
    open_at: dict[str, int] = {}
    for line_number, closing, feature in marker_events(source):
        if not closing:
            if feature in open_at:
                unmatched.append(f"line {line_number} reopens {feature!r}, already open at line {open_at[feature]}")
            else:
                open_at[feature] = line_number
        elif open_at.pop(feature, None) is None:
            unmatched.append(f"line {line_number} closes {feature!r}, which no earlier marker opened")
    unmatched.extend(
        f"line {line_number} opens {feature!r}, which nothing closes" for feature, line_number in open_at.items()
    )
    assert not unmatched, (
        f"the AD-24 markers in src/config/settings/base.py do not pair up: {sorted(unmatched)}. An unbalanced "
        f"pair yields no region from `regions()`, so the enclosure assertion below would pass over a file "
        f"whose region was drawn around {SESSION_ENGINE_SETTING} and simply spelled wrongly."
    )

    lines = _assignment_lines(source, SESSION_ENGINE_SETTING)
    enclosing = [
        f"line {line} is inside the {region.feature!r} region ({region.first_line}-{region.last_line})"
        for line in lines
        for region in regions(source)
        if region.encloses(line)
    ]

    assert not enclosing, (
        f"the {SESSION_ENGINE_SETTING} assignment falls inside a feature-owned region: {enclosing}. AD-24 "
        f"regions are removed by the materializer, so the engine would be unset in every combination that did "
        f"not select that feature -- and AC #1 requires it identical in all six."
    )
