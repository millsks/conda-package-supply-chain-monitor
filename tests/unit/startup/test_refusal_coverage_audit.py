"""FR-16's audit: every forbidden state is claimed by a test that refuses it.

The suite proves the deployed settings *refuse*, rather than merely proving they
start, only if each of the fourteen distinct forbidden states has a test that
configures that state and asserts `ImproperlyConfigured`. This module is what
makes that true by measurement instead of by review.

**The claim mechanism is a marker, and the audit is two-way.** A refusal test
carries `@pytest.mark.forbidden_state("<state_id>")`. An unclaimed state fails
here, and so does a claim naming a state
`tests/unit/startup/forbidden_states.py` does not declare -- a one-way check
lets a renamed state go dark, because the rename removes the state and the
marker still points somewhere.

**The claims are read out of pytest's own collection, never out of source text.**
A marker applied through `pytest.param(..., marks=...)`, through a class-level
`pytestmark`, or by a hook is exactly as valid a claim and is invisible to a
grep. `tests/conftest.py`'s `pytest_collection_modifyitems` is the collector.

**And it is a child process, which is the part that is easy to get wrong.**
`pixi run test` collects `tests/unit/` alone and `pixi run test-integration`
collects `tests/integration/` alone, so an audit reading whatever the running
session happened to collect would report every state claimed on the other side as
unclaimed -- and would pass or fail on how the suite was invoked rather than on
what it covers. The child collects the whole of `tests/`, once, whatever invoked
the parent. Collection only: no test body runs, nothing connects to anything, and
the whole thing costs about a second.

**What the claim mechanism can and cannot see, said once here.** A marker names a
state; it does not prove the marked test configures it. `TestEveryClaimIsARefusal`
below closes as much of that as a static reading can -- it resolves each claiming
node id back to its function and requires the body to assert a refusal -- and the
residue is recorded in the story rather than left to be discovered.

This is a unit test by this project's established reading: it runs a subprocess
over the repository's own files, as `tests/unit/test_no_network_at_boot.py` and
`tests/unit/test_suite_policy.py` already do. It opens no database and no network
connection, and the one thing it writes is the claim report, into the temporary
directory pytest hands it -- the child inherits `subprocess_env()`, which drops
pytest-cov's subprocess activation along with the database-selection variables,
so no `.coverage.*` file is left in the repository root either.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

import pytest

from tests.conftest import FORBIDDEN_STATE_CLAIMS_KEY
from tests.conftest import FORBIDDEN_STATE_DISABLED_KEY
from tests.conftest import FORBIDDEN_STATE_MARKER
from tests.conftest import FORBIDDEN_STATE_REPORT_ENV_VAR
from tests.conftest import subprocess_env
from tests.unit.startup.forbidden_states import ESCAPE_ROUTE_STATE
from tests.unit.startup.forbidden_states import FORBIDDEN_STATES

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Proportionate to what collection actually costs, which is what makes it a
#: useful ceiling rather than a formality. Collecting the whole suite takes about
#: a second in this tree and the whole suite *runs* in about sixteen, so a child
#: still collecting after a minute is hung rather than slow -- and a ceiling of
#: five minutes would convert that hang into a five-minute CI stall before saying
#: so. Raise it only alongside a measurement showing collection genuinely got
#: slower.
COLLECTION_TIMEOUT_SECONDS: Final[float] = 60.0

#: How many of the fourteen every combination carries. Twelve is the settled
#: count of unconditional states -- seven unconditional conditions, three of which
#: cover more than one state -- and it is a literal here rather than a length of
#: something derived from `FORBIDDEN_STATES`, which would make the assertion
#: agree with whatever the declaration happened to say.
UNCONDITIONAL_STATE_COUNT: Final = 12

#: The numbered conditions every combination carries. Seven of the nine; the
#: other two leave with their features below. Written as the range rather than
#: derived from `FORBIDDEN_STATES` for the reason the count above is a literal.
UNCONDITIONAL_CONDITIONS: Final[frozenset[int]] = frozenset(range(1, 8))

#: The conditional states, and the feature that owns each. A **set** of state ids
#: per feature rather than one id, because a feature that grew a second forbidden
#: state would otherwise overwrite its first here and the declaration could reach
#: fifteen entries with every count in this module still green.
#:
#: Each entry sits inside its own AD-24 marker pair for the reason the records
#: themselves do: a combination materialized without Redis has neither the
#: condition, nor its declaration, nor this expectation of it, and an entry left
#: behind would fail a tree that is correct. Fourteen is therefore
#: `UNCONDITIONAL_STATE_COUNT` plus the states named here rather than a literal,
#: and it shrinks to thirteen or twelve exactly when the tree does.
CONDITIONAL_STATE_OWNERS: Final[dict[str, frozenset[str]]] = {
    # feature:redis
    "redis": frozenset({"in-process-cache-backend"}),
    # /feature:redis
    # feature:celery
    "celery": frozenset({"eager-task-execution"}),
    # /feature:celery
}

#: The numbered condition each feature owns, so that "nine conditions" is asserted
#: as a partition rather than as a count. Marker-delimited alongside the states
#: above, for the same reason.
CONDITIONAL_CONDITIONS: Final[dict[str, int]] = {
    # feature:redis
    "redis": 8,
    # /feature:redis
    # feature:celery
    "celery": 9,
    # /feature:celery
}


@pytest.fixture(scope="module")
def claim_report(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, Mapping[str, list[str]]]:
    """Collect the whole suite in a child process and return everything it recorded.

    Module-scoped so the child runs once for the file rather than once per case.

    The environment is `tests/conftest.py`'s `subprocess_env()` -- the same
    builder every boot probe uses -- rather than a copy of this process's own.
    That matters for more than tidiness: it drops `DJANGO_SETTINGS_MODULE` and
    the whole database-selection set, so the child composes settings the same way
    on a developer's machine with `DATABASE_URL` exported as on one without, and
    it drops pytest-cov's `COV_CORE_*` subprocess activation, which would
    otherwise have every audit run leave a `.coverage.<host>.<pid>` file in the
    repository root that nothing combines.

    Args:
        tmp_path_factory: pytest's session-scoped temporary directory factory,
            used for the report the child writes.

    Returns:
        The child's report: claims by `state_id`, and separately the claims
        carried by tests a disabling marker would stop from running.

    """
    report_path = tmp_path_factory.mktemp("forbidden-state-claims") / "claims.json"

    env = subprocess_env()
    env[FORBIDDEN_STATE_REPORT_ENV_VAR] = str(report_path)
    # A parent that was itself invoked with extra options must not pass them on:
    # `-k`, `-m` or a path filter in PYTEST_ADDOPTS would narrow the child's
    # collection and silently turn "this state is unclaimed" into a report about
    # a subset of the suite.
    env.pop("PYTEST_ADDOPTS", None)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "--collect-only",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=COLLECTION_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0, (
        f"collecting the suite for the refusal audit exited {completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )
    assert report_path.exists(), (
        "the collection child exited cleanly without writing a claim report, so "
        f"{FORBIDDEN_STATE_REPORT_ENV_VAR} reached no collection hook"
    )

    collected: dict[str, dict[str, list[str]]] = json.loads(report_path.read_text(encoding="utf-8"))
    return collected


@pytest.fixture(scope="module")
def claims(claim_report: Mapping[str, Mapping[str, list[str]]]) -> Mapping[str, list[str]]:
    """Return the claims that a run would actually execute.

    Args:
        claim_report: The whole report the collection child wrote.

    Returns:
        Every claimed `state_id`, mapped to the sorted node ids that claimed it.
        Claims carried by a skipped or expected-to-fail test are **not** here;
        `test_no_claim_is_carried_by_a_test_that_never_runs` is what reports
        those, so that a state whose only claim is disabled fails as an
        unclaimed state and is told why in the same run.

    """
    return claim_report[FORBIDDEN_STATE_CLAIMS_KEY]


def _declared_state_ids() -> set[str]:
    """Return every `state_id` the declaration carries, the escape route included."""
    return {state.state_id for state in FORBIDDEN_STATES} | {ESCAPE_ROUTE_STATE.state_id}


#: The spellings a `pytest.raises(...)` argument may use for the one exception
#: type the contract raises. The bare name and the alias the CG-3 module binds it
#: to; a test naming something else is asserting a different promise.
REFUSAL_TYPE_NAMES: Final[frozenset[str]] = frozenset({"ImproperlyConfigured", "REFUSAL_TYPE"})

#: The prefix a module-level "run it and require the refusal" helper is spelled
#: with in this suite -- `_refusal` in four modules today. Matched as a prefix so
#: that `_refusal_message` or `_refusals_for` would count too: what makes the
#: helper a refusal assertion is that it wraps `pytest.raises`, and every
#: spelling of the name in this suite starts here.
REFUSAL_HELPER_PREFIX: Final = "_refusal"


def _dotted(node: ast.expr) -> str:
    """Return the dotted source spelling of a name or attribute expression.

    Args:
        node: The expression to spell.

    Returns:
        The dotted name, or the empty string for anything else.

    """
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _claiming_function(nodeid: str) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, str] | None:
    """Resolve a claiming node id back to the function that carries the claim.

    Node ids are `path::Class::function[param]`. The parameter suffix is
    discarded -- every case of a parametrized function shares one body -- and the
    class path is walked so that a method resolves as reliably as a module-level
    function.

    Args:
        nodeid: The node id pytest reported the claim under.

    Returns:
        The function's parsed definition and the source text it came from, or
        None when the id names nothing this module can find.

    """
    path_part, _, rest = nodeid.partition("::")
    source_path = REPO_ROOT / path_part
    if not rest or not source_path.is_file():
        return None

    source = source_path.read_text(encoding="utf-8")
    scope: list[ast.stmt] = ast.parse(source).body
    found: ast.AST | None = None
    for step in rest.split("::"):
        name = step.split("[", 1)[0]
        found = next(
            (
                child
                for child in scope
                if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and child.name == name
            ),
            None,
        )
        if found is None:
            return None
        scope = found.body

    if not isinstance(found, ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    return found, source


def _asserts_a_refusal(function: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> bool:
    """Report whether one test function's body asserts that a refusal was raised.

    Args:
        function: The claiming test's parsed definition.
        source: The text the definition was parsed from, for reading assertion
            statements back in their written form.

    Returns:
        True when the body contains a `pytest.raises` on the refusal type, a call
        to the owning module's refusal helper, or an assertion naming a refusal.

    """
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            called = _dotted(node.func).rsplit(".", 1)[-1]
            if called == "raises" and any(_dotted(arg).rsplit(".", 1)[-1] in REFUSAL_TYPE_NAMES for arg in node.args):
                return True
            if called.startswith(REFUSAL_HELPER_PREFIX):
                return True
        if isinstance(node, ast.Assert) and "refus" in (ast.get_source_segment(source, node) or "").lower():
            return True
    return False


class TestTheDeclarationItself:
    """The table the audit is measured against, before it is used to measure."""

    def test_every_state_id_is_declared_once(self) -> None:
        """A duplicated identifier makes one of the two states unauditable.

        Both records would be satisfied by the same marker, so the second state
        would be claimed by a test that never configures it -- which is exactly
        the reassurance FR-16 exists to withhold.
        """
        duplicated = [
            state_id for state_id, count in Counter(s.state_id for s in FORBIDDEN_STATES).items() if count > 1
        ]

        assert duplicated == [], f"these state ids are declared more than once: {duplicated}"

    def test_the_escape_route_is_declared_outside_the_fourteen(self) -> None:
        """FR-12's state is not one of the nine conditions and must not be tradeable for one.

        Inside the tuple it could be dropped and replaced by a fifteenth entry
        with every count-based assertion still passing.
        """
        assert ESCAPE_ROUTE_STATE.state_id not in {state.state_id for state in FORBIDDEN_STATES}
        assert ESCAPE_ROUTE_STATE.condition == 0

    def test_the_unconditional_states_are_the_settled_twelve(self) -> None:
        """The count is settled, not re-derivable -- see `forbidden_states.py`.

        Asserted over the unconditional records alone so that it holds unchanged
        in a materialized combination that dropped one feature or both.
        """
        unconditional = [state.state_id for state in FORBIDDEN_STATES if state.feature is None]

        assert len(unconditional) == UNCONDITIONAL_STATE_COUNT, (
            f"the declaration carries {len(unconditional)} unconditional forbidden states, not "
            f"{UNCONDITIONAL_STATE_COUNT}: {unconditional}. Adding a condition without updating "
            "this expectation is the change this assertion exists to stop."
        )

    def test_each_feature_owns_exactly_the_states_recorded_for_it(self) -> None:
        """The conditional half of the count, in the two directions it can be wrong.

        A feature that lost its state fails, and a state naming a feature nothing
        records fails. Together with the twelve above this fixes the total at
        fourteen for this tree, without a literal fourteen that a materialized
        combination would fail on.

        A *set* per feature, not one id. Keyed the other way -- feature to a
        single state id -- a second state declared under `feature="redis"` would
        overwrite the first, and the declaration could grow to fifteen entries
        with the count above and this equality both still green.
        """
        owned: dict[str, set[str]] = {}
        for state in FORBIDDEN_STATES:
            if state.feature is not None:
                owned.setdefault(state.feature, set()).add(state.state_id)

        assert owned == {feature: set(states) for feature, states in CONDITIONAL_STATE_OWNERS.items()}

    def test_the_declared_total_is_the_twelve_plus_the_states_the_features_own(self) -> None:
        """The arithmetic itself, asserted rather than left as a comment.

        Twelve plus two is fourteen in this tree, and until this case existed
        nothing said so: the twelve were counted, the two were reconciled against
        their features, and the *sum* was a sentence in a docstring. A fifteenth
        unconditional state added without touching either expectation would have
        failed the first assertion -- but a fifteenth state added under a feature
        that already had one would have failed nothing at all.
        """
        expected = UNCONDITIONAL_STATE_COUNT + sum(len(states) for states in CONDITIONAL_STATE_OWNERS.values())

        assert len(FORBIDDEN_STATES) == expected, (
            f"the declaration carries {len(FORBIDDEN_STATES)} forbidden states; the twelve unconditional "
            f"plus the states the features own come to {expected}"
        )

    def test_every_state_names_a_condition_and_a_stage_the_contract_has(self) -> None:
        """Nine numbered conditions and two evaluation stages; nothing else exists to belong to."""
        misfiled = [
            state.state_id
            for state in (*FORBIDDEN_STATES, ESCAPE_ROUTE_STATE)
            if state.condition not in range(10) or state.stage not in {1, 2}
        ]

        assert misfiled == [], f"these states name a condition or a stage the contract does not have: {misfiled}"

    def test_every_numbered_condition_owns_at_least_one_state(self) -> None:
        """FR-16 is written per *condition*, and the count above is not.

        "Each of the nine conditions has at least one test that configures the
        forbidden state" -- so the states have to be distributed across all nine,
        not merely to number fourteen. Deleting condition 3's state and adding a
        second under condition 1 keeps every count in this class green while
        leaving condition 3 audited by nothing, which is exactly the trade FR-16's
        sentence forbids.

        Partitioned the way materialization partitions it, so the assertion holds
        on a combination that dropped a feature: seven conditions every tree
        carries, and one per feature that is still present.
        """
        unconditional = {state.condition for state in FORBIDDEN_STATES if state.feature is None}
        per_feature = {
            feature: {state.condition for state in FORBIDDEN_STATES if state.feature == feature}
            for feature in CONDITIONAL_STATE_OWNERS
        }

        assert unconditional == UNCONDITIONAL_CONDITIONS, (
            f"the unconditional states cover conditions {sorted(unconditional)}, not {sorted(UNCONDITIONAL_CONDITIONS)}"
        )
        assert per_feature == {feature: {condition} for feature, condition in CONDITIONAL_CONDITIONS.items()}


class TestEveryStateIsClaimed:
    """AC #1 and AC #2: the audit proper, in both directions."""

    def test_the_collection_child_found_claims_at_all(self, claims: Mapping[str, list[str]]) -> None:
        """An empty report would make every assertion below vacuously true.

        The failure it guards against is not a missing marker but a broken
        collector: a renamed hook, a `tests/conftest.py` that stopped being
        loaded, or a child whose path filter matched nothing would each produce
        an empty report and a green audit.
        """
        assert claims != {}, "the collection child reported no forbidden_state claims at all"

    @pytest.mark.parametrize(
        "state_id",
        [state.state_id for state in FORBIDDEN_STATES],
        ids=str,
    )
    def test_every_forbidden_state_is_claimed_by_a_refusal_test(
        self,
        state_id: str,
        claims: Mapping[str, list[str]],
    ) -> None:
        """FR-16: each state has at least one test that configures it and asserts the raise.

        Parameterized per state so a gap names the state that has none, rather
        than reporting the whole contract as uncovered.
        """
        assert claims.get(state_id), (
            f"no test claims the forbidden state {state_id!r}. Mark the test that configures it "
            f"and asserts ImproperlyConfigured with @pytest.mark.{FORBIDDEN_STATE_MARKER}({state_id!r})."
        )

    def test_the_settings_module_escape_route_is_claimed_separately(self, claims: Mapping[str, list[str]]) -> None:
        """AC #2, asserted on its own so it cannot be traded against the fourteen.

        FR-12's escape route is the frame's own reason to exist: a deployed
        process pointed at `config.settings.local` is the failure a guard living
        inside the settings package could not catch.
        """
        assert claims.get(ESCAPE_ROUTE_STATE.state_id), (
            f"no test claims {ESCAPE_ROUTE_STATE.state_id!r} -- FR-12's escape route "
            "(a deployed component importing config.settings.local)"
        )

    def test_no_claim_names_a_state_the_declaration_does_not_have(self, claims: Mapping[str, list[str]]) -> None:
        """The second direction, without which a rename goes dark.

        Rename a state and the marker still points at the old identifier: the
        state reports as unclaimed *and* the marker reports as unrecognized, so
        whoever made the change is told both halves at once instead of hunting
        for the second one.
        """
        unrecognized = sorted(set(claims) - _declared_state_ids())

        assert unrecognized == [], (
            f"these forbidden_state claims name no declared state: {unrecognized}. "
            "Either the marker is misspelled or the state was renamed in forbidden_states.py."
        )

    def test_no_single_test_claims_more_than_one_state(self, claims: Mapping[str, list[str]]) -> None:
        """FR-16's second sentence: a condition covering several states has each tested separately.

        Conditions 2, 5 and 6 cover four, two and two states. One test claiming
        two of them is the shape the rule forbids -- it asserts one refusal and
        reports two, so the state that is actually unreachable is reported as
        covered.
        """
        claims_per_node: Counter[str] = Counter(nodeid for nodeids in claims.values() for nodeid in nodeids)
        overloaded = sorted(nodeid for nodeid, count in claims_per_node.items() if count > 1)

        assert overloaded == [], (
            f"these tests claim more than one forbidden state: {overloaded}. "
            "Each state needs its own test function, or its own pytest.param(..., marks=...)."
        )


class TestEveryClaimIsARefusal:
    """AC #1's second half: the marked test has to *assert the raise*, not merely exist."""

    def test_no_claim_is_carried_by_a_test_that_never_runs(
        self,
        claim_report: Mapping[str, Mapping[str, list[str]]],
    ) -> None:
        """A skipped or expected-to-fail test satisfies a marker and asserts nothing.

        `@pytest.mark.skip`, `skipif` and `xfail` all produce a collected item
        carrying the claim, so an audit reading collection alone counts a state
        as covered by a test that will not execute -- which is the reassurance
        FR-16 exists to withhold, restored by a decorator.

        Reported separately from "unclaimed" on purpose: a state whose only claim
        is disabled fails the case above as unclaimed, and fails here with the
        node id and the reason, so whoever reads the run is not sent looking for
        a marker that is already there.
        """
        disabled = claim_report[FORBIDDEN_STATE_DISABLED_KEY]

        assert disabled == {}, (
            f"these forbidden_state claims are carried by tests a disabling marker would stop from "
            f"running: {dict(sorted(disabled.items()))}"
        )

    def test_every_claiming_node_resolves_to_a_test_function(self, claims: Mapping[str, list[str]]) -> None:
        """The claim's node id has to name something this module can still read.

        Not a formality: the assertion below is written over the resolved
        function, so a node id that resolved to nothing would make it pass by
        having nothing to inspect.
        """
        unresolved = sorted(
            nodeid for nodeids in claims.values() for nodeid in nodeids if _claiming_function(nodeid) is None
        )

        assert unresolved == [], f"these claiming node ids resolve to no test function on disk: {unresolved}"

    def test_every_claiming_test_asserts_a_refusal(self, claims: Mapping[str, list[str]]) -> None:
        """The marker is otherwise self-certifying, and that is its one real weakness.

        `@pytest.mark.forbidden_state("sqlite-backend")` on `def test_nothing():
        pass` satisfies every other assertion in this module, while AC #1 asks
        for a test that "configures that state and asserts `ImproperlyConfigured`".
        Read statically -- pytest offers nothing at collection time that would
        answer it -- each claiming function's own body must contain one of:

        * `pytest.raises(ImproperlyConfigured)`, the direct form;
        * a call to the owning module's `_refusal(...)` helper, which is that
          form factored out and is what most of this suite uses; or
        * an assertion naming the refusal, which is the shape the served-path
          cases take: the raise happened in a child process and what the case
          asserts is the refusal that child reported.

        **What this does not prove, stated rather than implied.** The third
        clause is satisfied by any assertion mentioning a refusal, so it
        establishes that the test asserts *something* about one rather than that
        it asserts the right thing -- and none of the three clauses says the
        state configured is the state claimed. That residue is the story's
        recorded risk; what is closed here is the marker on a test that asserts
        no refusal at all.
        """
        silent = sorted(
            nodeid
            for nodeids in claims.values()
            for nodeid in nodeids
            if (resolved := _claiming_function(nodeid)) is not None and not _asserts_a_refusal(*resolved)
        )

        assert silent == [], (
            f"these tests claim a forbidden state without asserting a refusal: {silent}. "
            "A claim says the refusal was raised, not that the test exists."
        )
