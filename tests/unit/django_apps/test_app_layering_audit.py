"""`core` imports a domain application's *vocabulary*, never its *models*.

The rule was real and unwritten until `CPM-APP-S02` walked into it. `core` holds the
pass machinery, the policy-run orchestrator and the rollup writer, and every one of
them reaches a pass through the registry `policies/apps.py` fills at `ready()` --
never by importing a pass or a derived model. That inversion is what lets a pass be
added without touching the orchestrator, and it is why `core/policy_run.py` walks
`registered_passes()` instead of naming eight modules.

Nothing enforced it. `CPM-APP-S02` first put the health projection in `core`, where
it had to import six derived models by name, and nothing failed -- the inversion
would have been gone and the diff would have looked like six ordinary imports. The
projection moved to `conda_sentinel.surface`, where the dependency runs the ordinary
way round, and this is what stops the next one drifting back.

**The line is between a vocabulary and a table, and `core` is on both sides of it
deliberately.** `core/models.py` imports `CurrencyOutcome`, `PriorityBucket` and
`WorkType` from `policies.outcomes`, because `PackageHealth`'s contributed columns
declare those as their `choices` -- and a rollup that restated the vocabularies would
be the second declaration of a closed set that this codebase refuses everywhere else.
Importing `PackageCurrency` would be a different thing entirely: the rollup would
then know which *table* a pass writes, which is exactly what the registry exists to
keep it from knowing. So vocabulary modules are permitted by name and everything else
is refused.

**`identity` is a dependency rather than a client, and its models are recorded.**
`CPM-AD-11` gives the rollup one row per inventory package -- there is no version of
it that does not know what a `Package` is -- and `CPM-AD-4`'s gate is a rule *about*
identity confidence. Four modules need `identity.models` and all four are named
below, so a fifth reaching for it is a decision somebody has to write down.

**The direction is asserted, not the absence.** A layering audit that only checked
`core` would pass on a repository where `policies` had stopped importing `core` at
all, which is a different architecture and not this one.

Reads source: no database, no network, no imports of the modules under test.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING
from typing import Final

import pytest

from tests.source_scan import SRC_ROOT
from tests.source_scan import parse
from tests.source_scan import project_files

if TYPE_CHECKING:
    from pathlib import Path

#: The package every application under test is a subpackage of.
IMPORT_ROOT: Final[str] = "conda_sentinel"

#: The application whose imports are constrained.
LOWER_APPLICATION: Final[str] = "core"

#: The applications `core` orchestrates or is read by, and must not depend on the
#: internals of. `collectors` and `policies` are domain applications reached through
#: the registry; `surface` is the read layer and sits above all four, so a `core`
#: module importing it is the most obviously wrong direction of the three.
DOWNSTREAM: Final[frozenset[str]] = frozenset({"collectors", "policies", "surface"})

#: The module names that hold a closed vocabulary rather than a table or behaviour.
#:
#: Permitted to `core` because a column's `choices` have to come from somewhere and
#: the alternative is restating them. Named as a small closed list rather than
#: matched by a pattern: a module called `outcomes_helpers` should not inherit the
#: licence by being spelled similarly.
VOCABULARY_MODULES: Final[frozenset[str]] = frozenset({"outcomes", "confidence"})

#: Which `core` modules may import `identity`'s models, and what each imports.
#:
#: Spelled exactly and spent exactly, on the terms
#: `tests/unit/django_apps/test_clock_audit.py` sets: a module that has used its
#: recorded import gets no second one for free, and a recorded import that has been
#: deleted fails below rather than going on licensing nothing.
RECORDED_IDENTITY_MODELS: Final[frozenset[str]] = frozenset(
    {
        "core/ledger.py",
        "core/policy.py",
        "core/policy_run.py",
        "core/rollup.py",
    },
)

#: Which application must still depend on `core`, so the audit is about a direction
#: rather than about two packages that merely do not speak.
UPPER_APPLICATION: Final[str] = "policies"


def sibling_imports(tree: ast.Module) -> list[str]:
    """Return every sibling application module a file imports, by dotted name.

    Both import forms, because they are the same dependency written two ways and
    only one of them is the one anybody writes by hand. Imports inside a
    `TYPE_CHECKING` block count: a dependency that exists only for a type annotation
    is still a module this one had to be told the name of.

    Args:
        tree: The parsed module.

    Returns:
        The `conda_sentinel.<app>.<module>` names imported, deduplicated and sorted.

    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(f"{IMPORT_ROOT}."):
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith(f"{IMPORT_ROOT}."))
    return sorted(found)


def parts_of(dotted: str) -> tuple[str, str]:
    """Return which application and which module a dotted name refers to.

    Args:
        dotted: A `conda_sentinel.<app>.<module>` name.

    Returns:
        The application segment and the last segment.

    """
    segments = dotted.split(".")
    return segments[1], segments[-1]


#: Every module of the constrained application, and its path relative to the package.
CORE_MODULES: Final[tuple[Path, ...]] = tuple(
    path
    for path in project_files(SRC_ROOT, skip_migrations=True)
    if f"{IMPORT_ROOT}/{LOWER_APPLICATION}/" in path.as_posix()
)


def relative_to_package(path: Path) -> str:
    """Return a module's path relative to the import root's own directory.

    Args:
        path: The module.

    Returns:
        For example `core/rollup.py`.

    """
    return path.as_posix().split(f"{IMPORT_ROOT}/", 1)[-1]


@pytest.mark.parametrize("path", CORE_MODULES, ids=relative_to_package)
def test_core_imports_no_domain_table_or_behaviour(path: Path) -> None:
    """`core` reaches a pass through the registry, never by importing one.

    The failure this prevents is not a crash -- Python imports it fine. It is that
    "walk the registered passes" stops being the only way a pass reaches the
    orchestrator, and the next pass added has two places to be wired into.

    Args:
        path: The `core` module under test.

    """
    offences = [
        dotted
        for dotted in sibling_imports(parse(path))
        if (parts := parts_of(dotted))[0] in DOWNSTREAM and parts[1] not in VOCABULARY_MODULES
    ]

    assert offences == [], (
        f"{relative_to_package(path)} imports {offences}. `core` orchestrates the domain applications through "
        f"the pass registry and may know their vocabularies but not their tables; a module that has to name a "
        f"derived model belongs in conda_sentinel.surface, which sits above them."
    )


@pytest.mark.parametrize("path", CORE_MODULES, ids=relative_to_package)
def test_core_reaches_identity_models_only_where_it_is_recorded(path: Path) -> None:
    """The one exception, spent per module.

    `identity` is `core`'s dependency rather than its client: the rollup is one row
    per package and the confidence gate is a rule about identity confidence. Four
    modules need the model and all four are named; a fifth is a decision somebody
    should have to write down.

    Args:
        path: The `core` module under test.

    """
    relative = relative_to_package(path)
    reaches = any(parts_of(dotted) == ("identity", "models") for dotted in sibling_imports(parse(path)))

    assert reaches == (relative in RECORDED_IDENTITY_MODELS), relative


def test_every_recorded_exception_is_still_taken() -> None:
    """A licence for an import nobody makes is a hole with a paragraph beside it.

    The case above spends each entry; this is the other direction, so an entry whose
    import has been deleted fails here rather than going on licensing something.
    """
    for relative in sorted(RECORDED_IDENTITY_MODELS):
        module = SRC_ROOT / "django_apps" / IMPORT_ROOT / relative

        assert module.is_file(), relative
        assert any(parts_of(dotted) == ("identity", "models") for dotted in sibling_imports(parse(module))), relative


def test_the_vocabulary_licence_is_actually_used() -> None:
    """The permitted half is asserted too, or the rule above is stricter than it reads.

    `core/models.py` really does import `policies.outcomes` -- `PackageHealth`'s
    contributed columns take their `choices` from it -- and if it ever stopped, the
    licence would be describing a case that no longer arises and the next reader
    would tighten it into a ban.
    """
    used = [
        relative_to_package(path)
        for path in CORE_MODULES
        if any(
            (parts := parts_of(dotted))[0] in DOWNSTREAM and parts[1] in VOCABULARY_MODULES
            for dotted in sibling_imports(parse(path))
        )
    ]

    assert used != []


def test_the_dependency_runs_the_other_way() -> None:
    """The direction, asserted from above as well as from below.

    Without this the audit would pass on a repository where `policies` had stopped
    importing `core` entirely -- two packages that do not speak, which is a different
    architecture and not the one the rule is about.
    """
    reaching_down = [
        relative_to_package(path)
        for path in project_files(SRC_ROOT, skip_migrations=True)
        if f"{IMPORT_ROOT}/{UPPER_APPLICATION}/" in path.as_posix()
        and any(parts_of(dotted)[0] == LOWER_APPLICATION for dotted in sibling_imports(parse(path)))
    ]

    assert reaching_down != [], (
        f"no module of {UPPER_APPLICATION} imports {LOWER_APPLICATION}, so the audit above is asserting that "
        f"two packages do not speak rather than that one depends on the other."
    )


def test_the_read_layer_is_allowed_what_core_is_not() -> None:
    """The move `CPM-APP-S02` made, asserted as a fact rather than left in a docstring.

    `conda_sentinel.surface` imports the derived models by name -- that is what a
    read surface *is* -- and the whole argument for the rule above is that there is
    somewhere for such a module to live. If this stopped being true the rule would be
    a ban rather than a direction.
    """
    naming_a_derived_model = [
        relative_to_package(path)
        for path in project_files(SRC_ROOT, skip_migrations=True)
        if f"{IMPORT_ROOT}/surface/" in path.as_posix()
        and any(parts_of(dotted) == ("policies", "models") for dotted in sibling_imports(parse(path)))
    ]

    assert naming_a_derived_model != []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import conda_sentinel.policies.models", ["conda_sentinel.policies.models"]),
        ("from conda_sentinel.policies.models import PackageCurrency", ["conda_sentinel.policies.models"]),
        ("from django.db import models", []),
        ("from conda_sentinel.core.outcomes import OutcomeState", ["conda_sentinel.core.outcomes"]),
    ],
    ids=["plain-import", "from-import", "third-party", "own-application"],
)
def test_the_detector_reads_both_import_forms(source: str, expected: list[str]) -> None:
    """Measured before it is trusted: two spellings of one dependency, and two misses.

    Args:
        source: The import to read.
        expected: What the detector should report.

    """
    assert sibling_imports(ast.parse(source)) == expected
