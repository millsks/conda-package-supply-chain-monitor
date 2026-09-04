"""`EVIDENCE.01-UNIT-001`: exactly one module declares a precedence order.

`CPM-AD-5` says `core` defines the single total precedence order and "no other
module defines one". That sentence is the whole of `R-01`'s mitigation on the
aggregation side: the failure it prevents is not a wrong order, it is *two*
orders -- a rollup that ranks `unknown` above `not_found` and an export that
ranks them the other way, each internally consistent, disagreeing only on the
rows a reviewer would have had to look at twice to notice.

A second order is cheap to write and invisible in review. It looks like a tuple
of five members near the code that needed it, and it is usually written by
somebody who could not find the first one. So the ban is mechanical.

Matched on the parsed syntax tree, never by text search, for the reason
`tests/unit/test_suite_policy.py` gives: prose about the prohibition -- this
docstring, `core/outcomes.py`'s own -- must not itself be an offence, and a
substring search for `OutcomeState.ERROR` would flag every ordinary reference to
a single member while missing an order built through an alias.

**What counts as a declaration.** An assignment outside any function body whose
value contains a tuple, list, set *or dict* literal with two or more
`OutcomeState` member references in it. That is the shape an order takes, and it
is narrow on purpose: `aggregate([first, second])` passes two members to a call
without declaring anything, and a test parametrizing over pairs is not ranking
them. Both are common and neither is the defect.

**The dict is not a footnote.** A rank map --
`{OutcomeState.ERROR: 0, OutcomeState.UNKNOWN: 1, ...}` -- is a complete total
order, and it is the shape `_RANK` takes inside `core/outcomes.py` itself, so it
is what a developer copying the canonical module reproduces. An earlier version
of this file excluded `ast.Dict` on the reasoning that a mapping would be caught
through its keys or values anyway; that reasoning was simply wrong.
`ast.Dict` holds its keys and values in plain Python lists on the node, so there
is no sequence node for `ast.walk` to find, and a rank map passed the gate
untouched. Keys and values are now counted together. The cost is a small,
accepted false positive: a message table keyed by state -- two members, two
strings -- reads as a declaration here. Centralising that table is not a bad
outcome.

**Outside any function body, not merely at module or class level.** An
assignment nested in a module-level `if TYPE_CHECKING:` or a
`try: ... except ImportError:` is executed at import exactly as a top-level one
is, and an earlier version of this scan read only `scope.body` and never saw it.
That was an accident rather than an evasion, which is the kind this audit is
for, so the walk now descends through every compound statement and stops only at
a `def`.

**What escapes it,** stated rather than left to be discovered. An order built at
runtime (a list appended to, or bound to a local, inside a function), one handed
straight to a helper call rather than bound to a name, and one written over a
type composed by `outcome_type` rather than over `OutcomeState` itself. Each is
a deliberate evasion rather than the accident this audit exists to catch, and
the AST is where the line is drawn -- exactly as
`tests/unit/test_import_roots.py` draws it for an import root reached through
`getattr`.

Reads and parses repository files and nothing else: no database, no network, no
subprocess.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_package_supply_chain_monitor.core import outcomes
from tests.source_scan import REPO_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse
from tests.source_scan import project_files

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The one module permitted to declare an order. Read off the module's own
#: `__file__` rather than rebuilt from the second import root's layout -- that
#: layout is `tests/unit/test_import_roots.py`'s to assert, and a hand-built path
#: here would be a second copy of it that could stop pointing at anything without
#: saying so.
_DECLARING_SOURCE: Final[str | None] = outcomes.__file__
if _DECLARING_SOURCE is None:
    # `Path("")` resolves to the working directory, which is a real path that
    # simply is not this module -- so a `or ""` fallback would silently
    # mis-identify the one file this whole audit exempts, and every assertion
    # here would keep passing.
    _MISSING = "conda_package_supply_chain_monitor.core.outcomes has no __file__; the ordering audit cannot run"
    raise RuntimeError(_MISSING)
DECLARING_MODULE: Final[Path] = Path(_DECLARING_SOURCE).resolve()

#: The class whose members an ordering is made of.
OUTCOME_CLASS: Final[str] = "OutcomeState"

#: The name the declaration is expected to be bound to in the declaring module.
#: Not part of the ban -- a rename is not a second order -- but asserted below so
#: the anti-vacuity guard is about the real constant rather than about whatever
#: the detector happened to find.
DECLARED_ORDER_NAME: Final[str] = "PRECEDENCE"

#: The literals an ordering can be spelled as. `ast.Dict` is here because a rank
#: map is an order and nothing else in the tree reaches its members -- see the
#: module docstring for why the earlier reasoning that excluded it was wrong.
SEQUENCE_NODES: Final = (ast.Tuple, ast.List, ast.Set, ast.Dict)

#: How many members in one sequence make it an ordering. Two: a single member is
#: a default or a fallback, and a pair is already a claim about which of them
#: outranks the other.
ORDERING_LENGTH: Final[int] = 2

#: Calls that are a spelling of a literal rather than a handoff to somebody
#: else's logic. A sequence handed to any *other* call -- `aggregate([a, b])` --
#: declares nothing, and `_call_arguments` below shields it.
SEQUENCE_CONSTRUCTORS: Final[frozenset[str]] = frozenset({"frozenset", "list", "set", "sorted", "tuple"})

# Synthetic modules the detector is measured against, so that a detector which
# had stopped matching anything could not pass this file. Written as source text
# and parsed here rather than as files on disk -- a fixture module in the tree
# would be found by the scan itself and would have to be exempted from the ban it
# exists to demonstrate.
A_SECOND_ORDER = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

ROLLUP_ORDER = (OutcomeState.UNKNOWN, OutcomeState.ERROR, OutcomeState.OK)
"""

A_SECOND_ORDER_THROUGH_A_MODULE_ALIAS = """
from conda_package_supply_chain_monitor.core import outcomes as vocabulary

SEVERITY = [vocabulary.OutcomeState.ERROR, vocabulary.OutcomeState.NOT_FOUND]
"""

A_SECOND_ORDER_THROUGH_A_CLASS_ALIAS = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState as State


class Serializer:
    ORDER = {State.ERROR, State.UNKNOWN}
"""

A_SECOND_ORDER_INSIDE_A_WRAPPER = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

RANKS = frozenset([OutcomeState.ERROR, OutcomeState.OK])
"""

A_SECOND_ORDER_AS_A_RANK_MAP = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

ROLLUP_RANK = {
    OutcomeState.ERROR: 0,
    OutcomeState.UNKNOWN: 1,
    OutcomeState.NOT_FOUND: 2,
    OutcomeState.NOT_APPLICABLE: 3,
    OutcomeState.OK: 4,
}
"""

A_SECOND_ORDER_AS_A_RANK_MAP_BY_VALUE = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

BY_RANK = {0: OutcomeState.ERROR, 1: OutcomeState.UNKNOWN}
"""

A_SECOND_ORDER_INSIDE_A_CONDITIONAL = """
from typing import TYPE_CHECKING

from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

if TYPE_CHECKING:
    SEVERITY = (OutcomeState.ERROR, OutcomeState.UNKNOWN)
"""

A_SECOND_ORDER_INSIDE_A_TRY = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

try:
    import orjson
except ImportError:
    SEVERITY = [OutcomeState.ERROR, OutcomeState.OK]
"""

AN_ANNOTATED_SECOND_ORDER = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

SEVERITY: tuple[OutcomeState, ...] = (OutcomeState.NOT_FOUND, OutcomeState.OK)
"""

ONE_MEMBER_REFERENCE = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

DEFAULT = OutcomeState.UNKNOWN
FALLBACK = (OutcomeState.UNKNOWN,)
"""

AN_ORDER_INSIDE_A_FUNCTION = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState


def worst_of(states):
    order = (OutcomeState.ERROR, OutcomeState.OK)
    return min(states, key=order.index)
"""

A_SINGLE_ENTRY_MAP = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

DEFAULTS = {OutcomeState.UNKNOWN: 0}
"""

A_PAIR_PASSED_TO_A_CALL = """
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import aggregate

WORST = aggregate([OutcomeState.NOT_APPLICABLE, OutcomeState.OK])
"""

PROSE_ONLY = '''
"""The order is OutcomeState.ERROR, then OutcomeState.UNKNOWN, then the rest."""
'''


def outcome_class_prefixes(tree: ast.Module) -> set[str]:
    """Return every dotted prefix that names the `OutcomeState` class in one module.

    Three routes, on the same terms as
    `tests/group_writers.py::group_model_names`: an import of the class itself,
    under its own name or an alias; an import of the module it lives in, from
    which the class is reached as an attribute; and a `class OutcomeState` defined
    in the module being scanned.

    The third is not a formality. `core/outcomes.py` declares the class rather
    than importing it, so a scan that recognised imports alone would find no
    prefixes there, report the declaring module as declaring nothing, and take
    this file's anti-vacuity guard down with it -- which is exactly what it did
    before this branch existed.

    Args:
        tree: The parsed module.

    Returns:
        The dotted spellings that resolve to the class in that module. Empty
        when the module neither imports nor defines it, which is most of them.

    """
    prefixes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == OUTCOME_CLASS:
            prefixes.add(node.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                if alias.name == OUTCOME_CLASS:
                    prefixes.add(alias.asname or alias.name)
                elif node.module.endswith("core") and alias.name == "outcomes":
                    prefixes.add(f"{alias.asname or alias.name}.{OUTCOME_CLASS}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(".outcomes"):
                    bound = alias.asname or alias.name
                    prefixes.add(f"{bound}.{OUTCOME_CLASS}")
    return prefixes


def _member_references(node: ast.expr, prefixes: set[str]) -> bool:
    """Report whether one expression is a reference to an `OutcomeState` member.

    Args:
        node: The element to inspect.
        prefixes: The dotted spellings that name the class in this module.

    Returns:
        True for `OutcomeState.ERROR` and every aliased spelling of it.

    """
    return isinstance(node, ast.Attribute) and dotted_name(node.value) in prefixes


def static_statements(node: ast.AST) -> Iterator[ast.stmt]:
    """Yield every statement reachable from `node` without entering a function body.

    Module level, class level, and everything nested inside an `if`, `try`,
    `with`, `for` or `while` -- all of which execute at import exactly as a
    top-level statement does. A `def` is where the walk stops: an ordering bound
    to a local is documented as outside this scan, and descending into function
    bodies would flag every test that names two states in a row.

    Args:
        node: The tree, or any node within it.

    Yields:
        Each statement, outermost first.

    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(child, ast.stmt):
            yield child
            yield from static_statements(child)
        elif isinstance(child, ast.ExceptHandler):
            # Not a statement itself, but its body holds them -- and
            # `try: ... except ImportError: ORDER = (...)` is a real shape.
            yield from static_statements(child)


def ordering_declarations(tree: ast.Module) -> list[str]:
    """Return every precedence order one module declares, as `line: name` strings.

    Args:
        tree: The parsed module.

    Returns:
        One entry per assignment outside a function body whose value carries a
        tuple, list, set or dict literal holding two or more `OutcomeState`
        members.

    """
    prefixes = outcome_class_prefixes(tree)
    if not prefixes:
        return []

    found: list[str] = []
    for statement in static_statements(tree):
        if isinstance(statement, ast.Assign):
            value, targets = statement.value, statement.targets
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            value, targets = statement.value, [statement.target]
        else:
            continue
        if not _declares_a_sequence(value, prefixes):
            continue
        names = ", ".join(dotted_name(target) or "<unnamed>" for target in targets)
        found.append(f"{statement.lineno}: {names}")
    return found


def _declares_a_sequence(value: ast.expr, prefixes: set[str]) -> bool:
    """Report whether an assigned value carries a sequence of two or more members.

    Args:
        value: The assigned expression.
        prefixes: The dotted spellings that name the class in this module.

    Returns:
        True when any tuple, list, set or dict literal anywhere in the expression
        holds two or more member references, other than one handed straight to a
        call. Nested rather than top-level only, so `frozenset([...])` and a
        mapping of orders are caught as readily as a bare tuple.

    """
    handed_to_a_call = _call_arguments(value)
    return any(
        _members_in(node, prefixes) >= ORDERING_LENGTH
        for node in ast.walk(value)
        if isinstance(node, SEQUENCE_NODES) and id(node) not in handed_to_a_call
    )


def _members_in(node: ast.Tuple | ast.List | ast.Set | ast.Dict, prefixes: set[str]) -> int:
    """Count the `OutcomeState` members one literal holds.

    A dict is counted across its keys *and* its values, because both spellings
    are a rank map: `{ERROR: 0, OK: 4}` ranks by key and `{0: ERROR, 4: OK}`
    ranks by value. `node.keys` may hold `None` where a `**expansion` appears,
    which is why the key list is filtered rather than indexed.

    Args:
        node: The literal to count.
        prefixes: The dotted spellings that name the class in this module.

    Returns:
        How many of its elements are `OutcomeState` member references.

    """
    elements = [key for key in node.keys if key is not None] + node.values if isinstance(node, ast.Dict) else node.elts
    return sum(1 for element in elements if _member_references(element, prefixes))


def _call_arguments(value: ast.expr) -> set[int]:
    """Return the identities of every sequence handed straight to a call.

    `aggregate([first, second])` passes two states to a reducer; it does not rank
    them, and the module that wrote it is not the module that decides which one
    wins. Flagging it would make the ban fire on the vocabulary's own intended
    use, which is how an audit gets switched off.

    The sequence *constructors* are excluded from this shielding, because
    `frozenset([...])` and `tuple([...])` are spellings of a literal rather than
    a handoff to somebody else's logic.

    What this concedes: an order handed to a helper -- `RANKS = build(
    [ERROR, OK])` -- is not caught here. It is caught wherever `build` puts it,
    if it puts it anywhere; and if it does not, the ordering lives inside a
    function, which the module docstring already records as outside this scan.

    Args:
        value: The assigned expression.

    Returns:
        The `id()` of every expression that is a direct argument of a call other
        than a sequence constructor.

    """
    shielded: set[int] = set()
    for node in ast.walk(value):
        if not isinstance(node, ast.Call):
            continue
        if dotted_name(node.func).rpartition(".")[2] in SEQUENCE_CONSTRUCTORS:
            continue
        shielded.update(id(argument) for argument in node.args)
        shielded.update(id(keyword.value) for keyword in node.keywords)
    return shielded


def declarations_in(path: Path) -> list[str]:
    """Return every ordering declaration in one file.

    Args:
        path: The module to scan.

    Returns:
        One `line: name` string per declaration.

    """
    return ordering_declarations(parse(path))


def test_the_scan_reaches_the_declaring_module() -> None:
    """A scan that missed `core/outcomes.py` would pass on an empty repository."""
    scanned = project_files(REPO_ROOT)

    assert len(scanned) > 1, f"expected project modules under {REPO_ROOT}, found {scanned}"
    assert DECLARING_MODULE in scanned, DECLARING_MODULE


def test_the_declaring_module_declares_the_order() -> None:
    """The anti-vacuity guard: the detector finds the one order that must exist.

    Named, not merely counted. A detector that had stopped recognising member
    references would report zero declarations everywhere and this file's central
    assertion -- that nothing *else* declares one -- would pass while checking
    nothing at all.
    """
    declared = declarations_in(DECLARING_MODULE)

    assert declared, f"{DECLARING_MODULE} declares no precedence order"
    assert any(entry.endswith(f": {DECLARED_ORDER_NAME}") for entry in declared), declared


#: Every module the ban applies to: the repository, less the one module that
#: holds the declaration. Filtered out of the parametrize list rather than
#: skipped inside the case, because a `pytest.skip` is an evasion
#: `tests/unit/test_suite_policy.py` bans outright -- and rightly: a skip here
#: would report a green case for the one file where a second declaration would
#: mean the most.
SUBJECT_MODULES: Final[tuple[Path, ...]] = tuple(path for path in project_files(REPO_ROOT) if path != DECLARING_MODULE)


@pytest.mark.parametrize(
    "path",
    SUBJECT_MODULES,
    ids=lambda path: str(path.relative_to(REPO_ROOT)),
)
def test_no_module_but_core_declares_a_precedence_order(path: Path) -> None:
    """`CPM-AD-5`: one total order, in `core`, and nowhere else.

    Parameterized per file so that a violation names the module that introduced
    it rather than reporting the repository as broken.

    There is no exemption table here, unlike the clock audit next door. Nothing
    is grandfathered because nothing predates the rule: `core/outcomes.py` is the
    first module in this repository to know what an `OutcomeState` is, so a
    second order can only ever be new.
    """
    assert declarations_in(path) == [], f"{path.relative_to(REPO_ROOT)} declares a second precedence order"


@pytest.mark.parametrize(
    "source",
    [
        A_SECOND_ORDER,
        A_SECOND_ORDER_THROUGH_A_MODULE_ALIAS,
        A_SECOND_ORDER_THROUGH_A_CLASS_ALIAS,
        A_SECOND_ORDER_INSIDE_A_WRAPPER,
        A_SECOND_ORDER_AS_A_RANK_MAP,
        A_SECOND_ORDER_AS_A_RANK_MAP_BY_VALUE,
        A_SECOND_ORDER_INSIDE_A_CONDITIONAL,
        A_SECOND_ORDER_INSIDE_A_TRY,
        AN_ANNOTATED_SECOND_ORDER,
    ],
    ids=[
        "plain",
        "module-alias",
        "class-alias",
        "frozenset",
        "rank-map",
        "rank-map-by-value",
        "conditional",
        "try-except",
        "annotated",
    ],
)
def test_the_detector_matches_a_second_declaration(source: str) -> None:
    """The other half of the guard: a real second order is caught, however spelled.

    Nine spellings, because an audit that recognised only the one form its author
    happened to imagine is an audit with a rename-shaped door in it -- which is
    the failure `tests/unit/test_suite_policy.py::_test_modules` documents at
    length for its own scan.

    Five of these were found by review, not by design: the two rank maps, which
    `ast.Dict` hides from a walk over sequence nodes, and the two nested
    assignments plus the annotated one, which a scan reading only `scope.body`
    never reaches. Each was a complete second total order passing the gate.
    """
    assert ordering_declarations(ast.parse(source)) != []


@pytest.mark.parametrize(
    "source",
    [
        ONE_MEMBER_REFERENCE,
        A_PAIR_PASSED_TO_A_CALL,
        A_SINGLE_ENTRY_MAP,
        AN_ORDER_INSIDE_A_FUNCTION,
        PROSE_ONLY,
    ],
    ids=["single-member", "call-argument", "single-entry-map", "function-local", "prose"],
)
def test_the_detector_ignores_what_is_not_a_declaration(source: str) -> None:
    """The negative control, and the reason the ban is narrow.

    A module holding a default state, a one-element tuple, a pair handed to
    `aggregate`, a single-entry map, or a docstring that names two members in a
    sentence, all declare nothing. A detector that flagged any of them would be
    turned off within a week, which is the way an audit really fails.

    `AN_ORDER_INSIDE_A_FUNCTION` is here as documentation rather than as
    approval: an order bound to a local really does escape this scan, the module
    docstring says so, and pinning it as a case is what keeps that sentence
    honest if the walk is ever widened.
    """
    assert ordering_declarations(ast.parse(source)) == []
