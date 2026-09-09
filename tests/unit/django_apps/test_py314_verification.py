"""What the verification collector declares, what a backend answer means, and what ships with it.

`CPM-PY314-S02` is four questions and only the last needs a run. Which queue the
task reaches is a pure function of its declared name; what a backend document
*means* is a pure function of a body; whether the question applies at all is a pure
function of what `identity` recorded; and what this component ships -- which is a
seam with nothing in it -- is a pure function of the source. All four are here, with
no database, no socket and no clock (`CPM-AD-27`). What needs a run -- the rows, the
ledger, the constraints, the task, the `not_applicable` path end to end -- is in
`tests/integration/django_apps/test_py314_verification.py`.

**The cases this module exists for are the two the story turns on.** The first is
that inferred and verified compatibility are *distinct recorded states* -- asserted
as a comparison of the two vocabularies' values rather than as a spelling of either,
so a rename on either side that collapsed them fails here. The second is that
nothing in this component executes anything: the module is swept for the whole
subprocess and dynamic-execution surface, and `collectors/apps.py` is swept for the
declaration it deliberately does not make.

**The third is AC 3, and it is asserted as a refusal rather than as an absence.**
`selectable_packages` answering `None` is what makes `collectors/sweep.py` refuse to
dispatch this collector **by name**, so the case drives the real dispatch resolver
rather than reading the classmethod's return value: a schedule entry that named this
collector would fail loudly at its first tick, and that is the property AC 3 is
about.

No database, no network: nothing here saves a row, no queryset is evaluated, and
every payload is a literal.
"""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.conf import settings

from conda_sentinel.collectors import py314_verification
from conda_sentinel.collectors import python_readiness
from conda_sentinel.collectors.models import PythonVerificationResult
from conda_sentinel.collectors.outcomes import INFERRED_COMPATIBLE
from conda_sentinel.collectors.outcomes import INFERRED_INCOMPATIBLE
from conda_sentinel.collectors.outcomes import VERIFICATION_ERROR
from conda_sentinel.collectors.outcomes import VERIFICATION_FAILED
from conda_sentinel.collectors.outcomes import VERIFICATION_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import VERIFICATION_NOT_FOUND
from conda_sentinel.collectors.outcomes import VERIFICATION_UNKNOWN
from conda_sentinel.collectors.outcomes import VERIFIED_COMPATIBLE
from conda_sentinel.collectors.outcomes import PythonReadinessOutcome
from conda_sentinel.collectors.outcomes import PythonVerificationOutcome
from conda_sentinel.collectors.py314_verification import ARCHITECTURE_FIELD
from conda_sentinel.collectors.py314_verification import COLLECTOR_NAME
from conda_sentinel.collectors.py314_verification import DETAIL_FIELD
from conda_sentinel.collectors.py314_verification import IDENTITY_UNRESOLVED_DETAIL
from conda_sentinel.collectors.py314_verification import LOG_REFERENCE_FIELD
from conda_sentinel.collectors.py314_verification import MAX_DOCUMENT_CHARACTERS
from conda_sentinel.collectors.py314_verification import MAX_SENTINEL_DETAIL_CHARACTERS
from conda_sentinel.collectors.py314_verification import NOT_BUILT_DETAIL
from conda_sentinel.collectors.py314_verification import NOT_OBTAINABLE_DETAIL
from conda_sentinel.collectors.py314_verification import PLATFORM_FIELD
from conda_sentinel.collectors.py314_verification import PYTHON_SERIES
from conda_sentinel.collectors.py314_verification import REQUIRED_FIELDS
from conda_sentinel.collectors.py314_verification import RESULT_FIELDS
from conda_sentinel.collectors.py314_verification import SHORTENED_DETAIL
from conda_sentinel.collectors.py314_verification import UNNAMEABLE_IDENTITY_SEGMENT
from conda_sentinel.collectors.py314_verification import VERIFICATION_CACHE_TTL
from conda_sentinel.collectors.py314_verification import VERIFICATION_FRESHNESS_TARGET
from conda_sentinel.collectors.py314_verification import VERIFICATION_HEADERS
from conda_sentinel.collectors.py314_verification import VERIFICATION_OBSERVATION_WINDOW
from conda_sentinel.collectors.py314_verification import VERIFICATION_RATE_LIMIT
from conda_sentinel.collectors.py314_verification import VERIFICATION_RETRIES
from conda_sentinel.collectors.py314_verification import VERIFICATION_TIMEOUT
from conda_sentinel.collectors.py314_verification import VERIFIED_FIELD
from conda_sentinel.collectors.py314_verification import VERIFY_LOCATOR_PREFIX
from conda_sentinel.collectors.py314_verification import VERIFY_SCHEME
from conda_sentinel.collectors.py314_verification import Py314VerificationCollector
from conda_sentinel.collectors.py314_verification import Py314VerificationDocumentError
from conda_sentinel.collectors.py314_verification import Py314VerificationIdentityError
from conda_sentinel.collectors.py314_verification import ReleaseIdentity
from conda_sentinel.collectors.py314_verification import asks_about
from conda_sentinel.collectors.py314_verification import inapplicability_of
from conda_sentinel.collectors.py314_verification import package_locator
from conda_sentinel.collectors.py314_verification import result_in
from conda_sentinel.collectors.specifiers import series_of
from conda_sentinel.collectors.sweep import SweepDispatchError
from conda_sentinel.collectors.sweep import cadence_reconciliation_fault
from conda_sentinel.collectors.tasks import VERIFY_PY314_TASK_NAME
from conda_sentinel.collectors.verification import VerificationBackendError
from conda_sentinel.collectors.verification import declare_verification_backend
from conda_sentinel.collectors.verification import declared_verification_backend
from conda_sentinel.collectors.verification import verification_backend
from conda_sentinel.collectors.verification import withdraw_verification_backend
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.collection import NO_CACHE
from conda_sentinel.core.collection import NO_WINDOW
from conda_sentinel.core.collection import CollectorConfigurationError
from conda_sentinel.core.collection import freshness_target_fault
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.queues import Queue
from conda_sentinel.core.queues import queue_for
from conda_sentinel.core.transport import MAX_TIMEOUT
from conda_sentinel.core.transport import Payload
from conda_sentinel.core.transport import worst_case_call_seconds
from conda_sentinel.identity.models import ESTABLISHED
from conda_sentinel.identity.models import MappingOutcome
from tests.clocks import FIXED_INSTANT
from tests.collectors import recorded_payload
from tests.source_scan import SRC_ROOT
from tests.source_scan import parse

if TYPE_CHECKING:
    from pathlib import Path

#: The three modules this file's source sweeps are about, relative to `src/`.
VERIFICATION_MODULE: Final[str] = "django_apps/conda_sentinel/collectors/py314_verification.py"
BACKEND_SLOT_MODULE: Final[str] = "django_apps/conda_sentinel/collectors/verification.py"
COLLECTORS_APP_MODULE: Final[str] = "django_apps/conda_sentinel/collectors/apps.py"

#: The evidence model the *static* half of this epic writes, and its table. Named
#: here so the source sweep asserting this module reads neither is asserting about
#: the real names rather than about a spelling of its own.
STATIC_EVIDENCE_MODEL: Final[str] = "PythonReadinessAssessment"
STATIC_EVIDENCE_TABLE: Final[str] = "python_readiness_assessments"

#: Every name by which a module could hand work to something that executes it.
#:
#: **This is the sweep `CPM-PY314-S02`'s Never list is made of**, and it is the one
#: audit in this file that is about what the module does *not* contain. The story
#: ships the seam and the evidence and no execution backend, so a `subprocess`, an
#: `os.system`, an `exec` or an importlib call appearing here would be this
#: component quietly acquiring an isolation posture nobody chose -- which is the
#: decision the story says is not a story's to make.
#:
#: Swept by *name* over the module's AST rather than by import, because the ban is
#: on reaching any of them by any route: `subprocess.run`, a `from subprocess import
#: run`, and a `getattr(os, "system")` are the same act.
#:
#: `compile` is deliberately **not** in the set, and it is the one name the shape of
#: this sweep cannot carry: `re.compile` is how both modules declare their character
#: patterns, so including it would fail over a compiled regular expression. What it
#: would have caught -- `compile()` feeding `exec` -- is caught by `exec` itself,
#: which is in the set and has no innocent spelling.
EXECUTION_NAMES: Final[frozenset[str]] = frozenset(
    {
        "Popen",
        "call",
        "check_call",
        "check_output",
        "eval",
        "exec",
        "execv",
        "execve",
        "fork",
        "import_module",
        "os",
        "popen",
        "posix_spawn",
        "run",
        "spawn",
        "spawnv",
        "subprocess",
        "system",
    },
)

#: How much of the inherited soft limit one call may spend -- three quarters, so the
#: claim is "with room for the ledger writes around it" rather than "by a hair".
SOFT_LIMIT_SHARE: Final[float] = 0.75

#: A purl the cases build locators from, and the locator it produces. Written out
#: rather than composed from the module's own constants, because a locator assembled
#: the same way twice would agree with itself however wrong it was.
A_PURL: Final[str] = "pkg:pypi/Django"
THE_LOCATOR: Final[str] = "py314-verify://declared-backend/pkg:pypi/Django"

#: A purl naming an ecosystem the *static* collector cannot read. Verification can
#: be asked about it, and that difference is deliberate -- see `asks_about`.
A_CONDA_PURL: Final[str] = "pkg:conda/numpy"

#: The locator a payload claims to have been asked about, for the document cases.
A_SOURCE: Final[str] = "py314-verify://declared-backend/pkg:pypi/a-project"

#: What a backend reports about where it ran. Three values rather than a bundle,
#: because AC 1 names three facts and a case that dropped one should fail on that
#: fact by name.
A_PLATFORM: Final[str] = "linux"
AN_ARCHITECTURE: Final[str] = "x86_64"
A_LOG_REFERENCE: Final[str] = "https://builds.example.invalid/runs/1234/log"

#: A package key the cases that need one use. This tier never reads a row.
A_PACKAGE: Final[int] = 7

#: The marker `_result` treats as "the backend did not send this field at all", as
#: distinct from `None`, which is an explicit JSON `null`.
OMITTED: Final[object] = object()

#: How many fields a result document may carry, and how many of them are required
#: strings. Named because `PLR2004` is right about a bare number in an assertion.
RESULT_FIELD_COUNT: Final[int] = 5
REQUIRED_FIELD_COUNT: Final[int] = 3


class _NotATransport:
    """Something with no `fetch`, for the declaration refusal.

    A class rather than a lambda, so the refusal's message names a type a reader
    recognises.
    """


class _FakeBackend:
    """A `Transport` that answers one recorded payload, for the declaration cases.

    Nothing here executes anything -- which is the point: the seam is measurable
    without a runner, and every case in this file that needs a backend needs only
    something that satisfies the protocol.
    """

    def __init__(self, payload: Payload | None = None) -> None:
        """Remember what to answer with.

        Args:
            payload: The payload to answer, or `None` for the default.

        """
        self._payload = payload if payload is not None else recorded_payload(source=A_SOURCE, body="{}")

    def fetch(self, source: str, *, headers: Any = None) -> Payload:
        """Answer the recorded payload.

        Args:
            source: The locator, ignored.
            headers: The headers, ignored.

        Returns:
            The recorded payload.

        """
        return self._payload


@pytest.fixture
def no_declared_backend() -> Any:
    """Leave the backend slot exactly as empty as it was found.

    The declaration is process-global, so a case that declared one and did not
    withdraw it would change what every later case reads -- including the cases in
    this file that assert the shipped state is *nothing declared*.

    Yields:
        `None`. The fixture is about the teardown.

    """
    assert declared_verification_backend() is None, "a previous case left a backend declared"
    yield None
    if declared_verification_backend() is not None:
        withdraw_verification_backend()


def _result(
    *,
    verified: Any = True,
    platform: Any = A_PLATFORM,
    architecture: Any = AN_ARCHITECTURE,
    log_reference: Any = A_LOG_REFERENCE,
    **overrides: Any,
) -> str:
    """Return one backend result document, with any field replaced, nulled or omitted.

    Args:
        verified: The verdict. `OMITTED` leaves the field out.
        platform: Where it ran. `OMITTED` leaves the field out.
        architecture: What it ran on. `OMITTED` leaves the field out.
        log_reference: Where the log is. `OMITTED` leaves the field out.
        **overrides: Further fields to add; `OMITTED` omits one.

    Returns:
        The document a backend would answer, encoded.

    """
    document: dict[str, Any] = {
        VERIFIED_FIELD: verified,
        PLATFORM_FIELD: platform,
        ARCHITECTURE_FIELD: architecture,
        LOG_REFERENCE_FIELD: log_reference,
    }
    document.update(overrides)
    return json.dumps({name: value for name, value in document.items() if value is not OMITTED})


def _identity(outcome: str = ESTABLISHED, primary_purl: str = A_PURL) -> ReleaseIdentity:
    """Return what resolution might have recorded about a package.

    Args:
        outcome: The `release_ecosystem` mapping's outcome.
        primary_purl: The recorded primary purl.

    Returns:
        The identity.

    """
    return ReleaseIdentity(outcome=outcome, primary_purl=primary_purl)


def _collector() -> Py314VerificationCollector:
    """Return a collector with a stopped clock and no backend of its own.

    Returns:
        The collector. The base builds a `RequestsTransport` from the declared
        timeout, which is never asked for anything at this tier -- and which in a
        deployment is replaced by the declared backend before the collector is
        constructed at all.

    """
    return Py314VerificationCollector(clock=FixedClock(instant=FIXED_INSTANT))


def _module(relative: str) -> Path:
    """Return one of the modules this file's source sweeps read.

    Args:
        relative: Its path under `src/`.

    Returns:
        The resolved path.

    """
    return SRC_ROOT / relative


def _names_in(relative: str) -> set[str]:
    """Return every bare name and attribute a module mentions.

    Args:
        relative: The module's path under `src/`.

    Returns:
        Every `Name.id` and `Attribute.attr` in its tree, which is what makes a
        sweep for a forbidden call insensitive to how the call was reached.

    """
    tree = parse(_module(relative))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


# ---------------------------------------------------------------------------
# The declarations, and the arithmetic behind them.
# ---------------------------------------------------------------------------


def test_the_collector_declares_every_value_the_base_checks() -> None:
    """All nine, written out on the class and carrying the module's own constants.

    Compared by *value* rather than by presence, for the reason every sibling
    collector's case gives: a class attribute rebound to the wrong constant declares
    nine names and behaves like something nobody wrote down.
    """
    assert Py314VerificationCollector.name == COLLECTOR_NAME
    assert Py314VerificationCollector.evidence_model is PythonVerificationResult
    assert Py314VerificationCollector.observation_window == VERIFICATION_OBSERVATION_WINDOW
    assert Py314VerificationCollector.timeout == VERIFICATION_TIMEOUT
    assert Py314VerificationCollector.retries == VERIFICATION_RETRIES
    assert Py314VerificationCollector.rate_limit == VERIFICATION_RATE_LIMIT
    assert Py314VerificationCollector.headers == VERIFICATION_HEADERS
    assert Py314VerificationCollector.freshness_target == VERIFICATION_FRESHNESS_TARGET
    assert Py314VerificationCollector.response_cache_ttl == VERIFICATION_CACHE_TTL


def test_the_collector_constructs_which_is_the_declarations_being_accepted() -> None:
    """The base checks all nine at construction, so building one is the check.

    A case rather than a corollary: every other case in this file that builds a
    collector would fail with the same message if a declaration were unusable, and a
    failure naming the construction is what says which of the two went wrong.
    """
    with _collector() as collector:
        assert collector.request_cost == 1 + VERIFICATION_RETRIES


def test_the_freshness_target_is_strictly_positive_and_is_not_derived_from_a_cadence() -> None:
    """`CPM-AD-28` with no cadence to derive from, which is PRD Open Question 7c.

    Two halves. The target is strictly positive, which is what `CPM-AD-28` requires
    of every collector and what `freshness_target_fault` sweeps the registry for.
    And it is *not* the `cadence x (1 + tolerated)` every other collector's is,
    because there is no cadence here at all -- asserted as the cadence being `None`
    beside a target that is not, which is the shape 7c describes and the shape the
    reconciliation below accepts.
    """
    assert VERIFICATION_FRESHNESS_TARGET.total_seconds() > 0
    assert Py314VerificationCollector.cadence is None
    assert freshness_target_fault([Py314VerificationCollector]) == ""


def test_the_window_is_no_window_because_the_trigger_is_the_decision_to_run() -> None:
    """A window would discard a request somebody made.

    Asserted against `NO_WINDOW` by identity of value rather than against
    `timedelta(0)`, because the constant is the *declaration* -- `core/collection.py`
    names it beside `NO_CACHE` and `NO_FRESHNESS`, all three of which are
    `timedelta(0)` and only one of which means this.
    """
    assert VERIFICATION_OBSERVATION_WINDOW == NO_WINDOW


def test_a_verification_is_never_replayed_from_the_response_cache() -> None:
    """`NO_CACHE`, and it is the one declaration that could not have been otherwise.

    A replayed body is written through `translate` exactly as a fresh one, which for
    an execution would be a row recording a build that did not run, stamped with the
    instant it did not run at.
    """
    assert VERIFICATION_CACHE_TTL == NO_CACHE


def test_a_failed_verification_is_not_retried_automatically() -> None:
    """Zero retries: a retry here is another build, not another request.

    The one declaration in this module that departs from the shared default every
    sibling takes, so it is asserted as the number *and* as the request cost the
    limiter is charged -- which is what makes the allowance below bound verifications
    rather than bounding something `1 + retries` multiplies underneath it.
    """
    assert VERIFICATION_RETRIES == 0
    with _collector() as collector:
        assert collector.request_cost == 1


def test_the_declared_timeout_fits_inside_the_inherited_soft_limit() -> None:
    """`CPM-AD-9`'s limit is settings', and the declared timeout is reconciled against it.

    What this bounds is the transport the base would build when none is passed -- the
    declared backend is passed instead -- so the assertion is about the collector
    behaving like every sibling if it ever ran unsubstituted, and about the number
    being inside the transport's own ceiling.
    """
    worst_case = worst_case_call_seconds(timeout=VERIFICATION_TIMEOUT, retries=VERIFICATION_RETRIES)

    assert VERIFICATION_TIMEOUT <= MAX_TIMEOUT
    assert worst_case < settings.CELERY_TASK_SOFT_TIME_LIMIT * SOFT_LIMIT_SHARE


def test_the_collector_sends_no_headers_because_a_backend_need_not_speak_http() -> None:
    """Empty is a complete statement here, unlike on a collector that reads a known host."""
    assert dict(VERIFICATION_HEADERS) == {}


def test_the_allowance_bounds_verifications_rather_than_requests() -> None:
    """Declared rather than left generous, and it is what bounds a trigger loop.

    The allowance is the trigger-side half of AC 3: the schedule side is made
    structural by `selectable_packages`, and this is what stops a scripted caller
    filling the `verify` queue with the whole inventory by hand.
    """
    assert VERIFICATION_RATE_LIMIT.calls > 0
    assert VERIFICATION_RATE_LIMIT.per > timedelta(0)


# ---------------------------------------------------------------------------
# AC 1: the queue, and the name that reaches it.
# ---------------------------------------------------------------------------


def test_the_task_name_routes_to_the_verify_queue_and_to_neither_of_the_others() -> None:
    """AC 1, and it is a property of the declared name rather than of a route table.

    Asserted in both directions: the name resolves to `verify`, and it resolves to
    neither `collect` nor `policy` -- the second half deliberately, because a
    namespace typo that resolved to `None` would satisfy "not collect" and would land
    the build on the inherited default queue, which is `R-11` with nothing saying so.
    """
    resolved = queue_for(VERIFY_PY314_TASK_NAME)

    assert resolved is Queue.VERIFY
    assert resolved is not Queue.COLLECT
    assert resolved is not Queue.POLICY


def test_the_task_name_is_the_one_core_queues_had_been_using_as_its_worked_example() -> None:
    """`core/queues.py` spelled `cpm.verify.py314_build` before there was one.

    Pinned as a literal rather than read from that module's docstring: the point is
    that a reader who followed the example finds the task it describes, and a case
    that derived the string from the same place could not tell.
    """
    assert VERIFY_PY314_TASK_NAME == "cpm.verify.py314_build"


def test_the_collectors_own_name_is_not_the_last_segment_of_its_task_name() -> None:
    """The one collector in this component of which that is true, and it follows from AC 3.

    Every swept collector's task name is *derived* -- `collectors/sweep.py` builds
    `cpm.collect.<name>` to enqueue it -- so its last segment must be the collector's
    name. Nothing derives this one, so it is free to say what the task does. Asserted
    because a later reader "fixing" the mismatch would be adding a constraint the
    sweep does not impose and the queue does not want.
    """
    assert not VERIFY_PY314_TASK_NAME.endswith(COLLECTOR_NAME)
    assert COLLECTOR_NAME not in VERIFY_PY314_TASK_NAME


# ---------------------------------------------------------------------------
# AC 2: inferred and verified are distinct recorded states.
# ---------------------------------------------------------------------------


def test_no_verified_value_is_spelled_the_same_as_any_inferred_one() -> None:
    """`CPM-FR-14`'s "distinct recorded states", asserted as the comparison itself.

    The determinate values of the two vocabularies are compared as *sets of strings*
    rather than checked one spelling at a time, because what the criterion forbids is
    a collision -- and a collision introduced by renaming either side is what a
    per-value assertion would miss.
    """
    inferred = {INFERRED_COMPATIBLE, INFERRED_INCOMPATIBLE}
    proven = {VERIFIED_COMPATIBLE, VERIFICATION_FAILED}

    assert inferred.isdisjoint(proven)


def test_neither_determinate_value_is_a_bare_compatibility_word() -> None:
    """A value called `compatible` on either table would read identically on a queue.

    `CPM-AD-24` carries a state's value verbatim onto every read surface, so the
    prefix is what makes the distinction survive the projection. Asserted over both
    vocabularies rather than over this story's alone: the criterion is about the
    pair, and the static half being renamed is as much a failure as this one being.
    """
    bare = {"compatible", "incompatible", "ok"}

    assert bare & set(PythonVerificationOutcome.values) == set()
    assert bare & set(PythonReadinessOutcome.values) == set()


def test_the_verified_verdicts_say_what_produced_them() -> None:
    """Both determinate values name the run rather than the package's nature.

    `verified_compatible` says a build succeeded; `verification_failed` says a run did
    not come out. Neither says `verified_incompatible`, which would be a claim about
    somebody else's package made from a build log that may have failed for reasons
    that are not the interpreter.
    """
    assert VERIFIED_COMPATIBLE.startswith("verified")
    assert VERIFICATION_FAILED.startswith("verification")
    assert "incompatible" not in set(PythonVerificationOutcome.values)


def test_the_vocabulary_carries_cores_four_sentinels_and_exactly_two_verdicts() -> None:
    """Six values: the four `outcome_type` composes in and the two this story adds.

    The sentinels are asserted through the composed constants rather than through
    `OutcomeState`, because a column's values must be its own choices -- and a
    determinate member added later without a case is exactly what the count catches.
    """
    assert set(PythonVerificationOutcome.values) == {
        VERIFIED_COMPATIBLE,
        VERIFICATION_FAILED,
        VERIFICATION_UNKNOWN,
        VERIFICATION_ERROR,
        VERIFICATION_NOT_FOUND,
        VERIFICATION_NOT_APPLICABLE,
    }


def test_both_halves_of_the_epic_assess_the_same_python_series() -> None:
    """Restated rather than imported, so the two spellings are reconciled here.

    `CPM-AD-7` forbids one collector importing another, so this module declares its
    own `PYTHON_SERIES` -- and two collectors quietly assessing two different Pythons
    would make `CPM-PY314-S03`'s reduction of the two tables meaningless with every
    gate green. Nothing else would have compared them.
    """
    assert PYTHON_SERIES == python_readiness.PYTHON_SERIES
    assert series_of(PYTHON_SERIES) == "3.14"


# ---------------------------------------------------------------------------
# AC 3: triggered, and never swept.
# ---------------------------------------------------------------------------


def test_the_collector_is_not_swept_one_package_at_a_time() -> None:
    """`None` is not an empty selection: it says the sweep is not this collector's mechanism."""
    assert Py314VerificationCollector.selectable_packages() is None


def test_a_dispatch_that_named_this_collector_would_be_refused_by_name() -> None:
    """AC 3 as a refusal rather than as an absence.

    Driven through `collectors/sweep.py`'s own resolver rather than by reading the
    classmethod, because the property AC 3 is about is what happens when somebody
    adds a beat entry: the dispatch refuses, loudly, at the first tick -- rather than
    enqueueing nothing every tick forever, which is what an empty selection would
    have looked like.

    The private helper is reached deliberately: the public `dispatch` opens a ledger
    row, which is a database write, and the refusal under test happens before any of
    that matters.
    """
    with pytest.raises(SweepDispatchError, match=r"not a per-package collector|not swept"):
        py314_verification_selection()


def py314_verification_selection() -> None:
    """Ask `collectors/sweep.py` for this collector's selection, as a dispatch would.

    A module-level function rather than a lambda in the case above, so the refusal's
    traceback names something a reader can find.

    Raises:
        SweepDispatchError: Always, which is what the case asserts.

    """
    from conda_sentinel.collectors.sweep import _selection_of  # noqa: PLC0415 - see the case above

    _selection_of(Py314VerificationCollector)


def test_declaring_no_cadence_and_no_selection_reconciles_with_any_schedule() -> None:
    """The pair is a checked statement rather than two omissions.

    `collectors/sweep.py` fails a collector declaring a cadence without a selection
    (a schedule would dispatch it and the dispatch would refuse every tick) and one
    declaring a selection without a cadence (nothing would ever sweep it). Declaring
    neither is the shape a triggered collector takes, and this is the rule saying so.
    """
    assert cadence_reconciliation_fault([Py314VerificationCollector], {}) == ""


def test_no_shipped_schedule_entry_names_this_collector() -> None:
    """AC 3 against the schedule this component actually ships.

    The reconciliation above proves the *rule*; this proves the shipped
    `CELERY_BEAT_SCHEDULE` obeys it. A future entry added by somebody who read the
    other nine and copied one would fail here as well as at its first tick.
    """
    scheduled = [
        entry.get("kwargs", {}).get("collector")
        for entry in settings.CELERY_BEAT_SCHEDULE.values()
        if isinstance(entry, dict)
    ]

    assert COLLECTOR_NAME not in scheduled
    assert VERIFY_PY314_TASK_NAME not in {
        entry.get("task") for entry in settings.CELERY_BEAT_SCHEDULE.values() if isinstance(entry, dict)
    }


# ---------------------------------------------------------------------------
# The shipped state: a seam with nothing in it, and nothing that executes.
# ---------------------------------------------------------------------------


def test_this_component_ships_with_no_execution_backend_declared() -> None:
    """The absence is the declaration, and it is asserted against the live process.

    Every application's `ready()` has run by the time the suite imports anything, so
    a `declare_verification_backend` call added to `collectors/apps.py` would make
    this fail -- which is the point: what ships is a component that executes nothing.
    """
    assert declared_verification_backend() is None


def test_the_collectors_app_declares_no_execution_backend() -> None:
    """The same claim made against the source, so it survives an import-order accident.

    The case above reads a process; this reads the file. Both, because a declaration
    made somewhere else and imported would satisfy one of them and not the other, and
    "which backend does this component execute through" is exactly the question
    `CPM-AD-29` will not have answered by import order.
    """
    named = _names_in(COLLECTORS_APP_MODULE)

    assert "declare_verification_backend" not in named
    assert "verification_backend" not in named


def test_the_verification_collector_executes_nothing() -> None:
    """`CPM-PY314-S02`'s Never list, swept over the module's own tree.

    No subprocess, no `os`, no `exec`, no dynamic import -- by any route, because the
    sweep is over every name and attribute the module mentions rather than over its
    imports. A backend that runs a build is a declared adapter an operator supplies;
    a build started from here would be this component choosing an isolation posture
    for third-party code, which is the decision this story refuses to make.
    """
    named = _names_in(VERIFICATION_MODULE)

    assert named & EXECUTION_NAMES == set()


def test_the_backend_slot_module_executes_nothing_either() -> None:
    """The same sweep over the seam, which is the module a reader would reach for first.

    Swept separately rather than folded into the case above, because the two modules
    are tempting in different ways: this one is where "and here is a default backend"
    would most plausibly be added.
    """
    named = _names_in(BACKEND_SLOT_MODULE)

    assert named & EXECUTION_NAMES == set()


def test_the_verification_collector_reads_neither_the_static_table_nor_its_model() -> None:
    """`CPM-AD-7`: no collector reads another's evidence, and the temptation here is real.

    The static half records where verification is worth spending, so a collector that
    consulted it before building would look reasonable -- and would be one collector
    reading another's rows, with the ranking of the two belonging to
    `CPM-PY314-S03`'s policy (`CPM-AD-8`).
    """
    tree = parse(_module(VERIFICATION_MODULE))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}

    assert STATIC_EVIDENCE_MODEL not in _names_in(VERIFICATION_MODULE)
    assert "conda_sentinel.collectors.python_readiness" not in imported
    spelled = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "\n" not in node.value
    }

    assert STATIC_EVIDENCE_TABLE not in spelled


# ---------------------------------------------------------------------------
# The declared-adapter slot.
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("no_declared_backend")
def test_a_declared_backend_is_what_the_reader_answers_with() -> None:
    """One declaration, and both reads see it."""
    backend = _FakeBackend()

    assert declare_verification_backend(backend) is backend
    assert declared_verification_backend() is backend
    assert verification_backend() is backend


@pytest.mark.usefixtures("no_declared_backend")
def test_a_second_declaration_is_refused_rather_than_allowed_to_replace_the_first() -> None:
    """One slot: a second backend would change what code runs on which machine.

    The message is asserted to name both types, because an operator meeting this
    refusal needs to know what is already declared as well as what was rejected.
    """
    first = _FakeBackend()
    declare_verification_backend(first)

    with pytest.raises(VerificationBackendError, match="already this component"):
        declare_verification_backend(_FakeBackend())

    assert declared_verification_backend() is first


@pytest.mark.usefixtures("no_declared_backend")
def test_something_that_is_not_a_transport_is_refused_at_the_declaration() -> None:
    """Refused where it is declared rather than where it is called.

    `Transport` is `runtime_checkable`, so this sees one method name -- which is
    exactly why `collectors/verification.py` writes out what an adapter owes beyond
    the protocol, and why the refusal's message points at that contract.
    """
    with pytest.raises(VerificationBackendError, match="is not a Transport"):
        declare_verification_backend(_NotATransport())  # type: ignore[arg-type]

    assert declared_verification_backend() is None


def test_asking_for_a_backend_when_none_is_declared_refuses_and_says_why() -> None:
    """The shipped state, and the refusal is what an unconfigured component does instead of verifying.

    It happens before the collector is constructed and therefore before the recorder
    opens, which is the matrix row saying an unconfigured component leaves no row
    claiming a result.
    """
    with pytest.raises(VerificationBackendError, match=r"no Python 3\.14 execution backend is declared"):
        verification_backend()


def test_withdrawing_nothing_is_refused_rather_than_ignored() -> None:
    """A silent no-op turns a mistaken withdrawal into a declaration that stays live."""
    with pytest.raises(VerificationBackendError, match="nothing to withdraw"):
        withdraw_verification_backend()


@pytest.mark.usefixtures("no_declared_backend")
def test_withdrawing_returns_the_component_to_the_state_it_ships_in() -> None:
    """Symmetric with the declaration rather than a test hook bolted on."""
    declare_verification_backend(_FakeBackend())
    withdraw_verification_backend()

    assert declared_verification_backend() is None


# ---------------------------------------------------------------------------
# The locator.
# ---------------------------------------------------------------------------


def test_the_locator_names_the_package_and_no_host() -> None:
    """`CPM-AD-29`: the backend knows where it runs, so the locator names what is asked about."""
    built = package_locator(A_PURL)

    assert built == THE_LOCATOR
    assert built.startswith(VERIFY_LOCATOR_PREFIX)
    assert VERIFY_SCHEME in built


@pytest.mark.parametrize("purl", ["", "   "], ids=["blank", "whitespace"])
def test_a_package_naming_no_purl_gets_the_unnameable_form(purl: str) -> None:
    """Unreachable through the shipped trigger, and present anyway.

    `source_for` refuses such a package before a locator is built, so this is the
    pure function being complete rather than a path a run takes -- a builder that
    raised here would move a refusal from where it is argued to where it is not.

    Args:
        purl: What identity recorded, or did not.

    """
    assert package_locator(purl) == f"{VERIFY_LOCATOR_PREFIX}{UNNAMEABLE_IDENTITY_SEGMENT}"


# ---------------------------------------------------------------------------
# Applicability: identity's rule, inherited whole.
# ---------------------------------------------------------------------------


def test_an_established_mapping_naming_a_purl_is_a_package_this_collector_can_be_asked_about() -> None:
    """The question applies, and no reason is answered."""
    identity = _identity()

    assert asks_about(identity) is True
    assert inapplicability_of(identity) == ""


def test_a_purl_from_an_ecosystem_the_static_collector_cannot_read_is_still_verifiable() -> None:
    """The one place this module's applicability is *broader* than the static half's.

    The static collector reads `pypi.org` and can answer for nothing else; this one
    hands a purl to a backend that already knows what it can build. Asserted, because
    a later reader copying the sibling's PyPI filter across would silently make conda
    packages unverifiable and nothing else would fail.
    """
    assert asks_about(_identity(primary_purl=A_CONDA_PURL)) is True


def test_only_identitys_own_not_applicable_reaches_the_not_applicable_state() -> None:
    """The single path, and the message names identity as what established it."""
    reason = inapplicability_of(_identity(outcome=OutcomeState.NOT_APPLICABLE.value))

    assert reason != ""
    assert "identity established" in reason


@pytest.mark.parametrize(
    "outcome",
    [member.value for member in MappingOutcome if member.value != OutcomeState.NOT_APPLICABLE.value],
    ids=str,
)
def test_no_other_mapping_outcome_makes_the_question_inapplicable(outcome: str) -> None:
    """The absence trap, swept over the mapping vocabulary's own members.

    Parametrized over `MappingOutcome` rather than over a list written out here, so an
    outcome added later acquires a case asserting the question stays applicable rather
    than acquiring a determinate meaning nobody wrote a case about.

    Args:
        outcome: One of the mapping outcomes that is not `not_applicable`.

    """
    assert inapplicability_of(_identity(outcome=outcome)) == ""


@pytest.mark.parametrize(
    ("outcome", "purl"),
    [
        (OutcomeState.UNKNOWN.value, A_PURL),
        (OutcomeState.ERROR.value, A_PURL),
        (OutcomeState.NOT_FOUND.value, A_PURL),
        (ESTABLISHED, ""),
        (ESTABLISHED, "   "),
    ],
    ids=["unknown", "error", "not_found", "established-no-purl", "established-blank-purl"],
)
def test_identity_that_established_nothing_is_not_a_package_to_verify(outcome: str, purl: str) -> None:
    """Every one of these is identity having established nothing, and none is inapplicable.

    Args:
        outcome: The mapping outcome recorded.
        purl: The purl recorded beside it.

    """
    identity = _identity(outcome=outcome, primary_purl=purl)

    assert asks_about(identity) is False
    assert inapplicability_of(identity) == ""


# ---------------------------------------------------------------------------
# Reading a backend's answer.
# ---------------------------------------------------------------------------


def test_a_successful_build_records_the_verified_state_and_where_it_ran() -> None:
    """AC 1 and AC 2 in one document: the verdict, and all three facts beside it."""
    result = result_in(_result(), source=A_SOURCE)

    assert result.state == VERIFIED_COMPATIBLE
    assert result.platform == A_PLATFORM
    assert result.architecture == AN_ARCHITECTURE
    assert result.log_reference == A_LOG_REFERENCE


def test_a_failed_build_is_a_determinate_result_and_not_an_error() -> None:
    """The matrix row: a failed build is a result, with its log reference.

    Asserted as the state *and* as the log reference surviving, because a
    verification that failed is exactly the row an engineer opens -- and one that
    dropped its reference on the way would be a determinate verdict nobody can check.
    """
    result = result_in(_result(verified=False), source=A_SOURCE)

    assert result.state == VERIFICATION_FAILED
    assert result.state != VERIFICATION_ERROR
    assert result.log_reference == A_LOG_REFERENCE
    assert result.detail == NOT_BUILT_DETAIL


def test_a_backends_own_note_is_preserved_rather_than_replaced() -> None:
    """`detail` is the backend's where it offered one, and this module's sentence where it did not."""
    stated = "the extension module failed to compile: missing libffi"
    result = result_in(_result(verified=False, **{DETAIL_FIELD: stated}), source=A_SOURCE)

    assert result.detail == stated


@pytest.mark.parametrize("field", sorted(REQUIRED_FIELDS), ids=str)
@pytest.mark.parametrize("value", [OMITTED, None, "", "   ", 7], ids=["omitted", "null", "blank", "spaces", "number"])
def test_a_verification_that_cannot_say_where_it_ran_is_refused(field: str, value: Any) -> None:
    """AC 1 is not optional, and it is not conditional on the verdict either.

    Swept over all three facts and over every way a backend could fail to state one,
    because "records the platform and architecture it ran on and a log reference" is
    one requirement and a reader that enforced two thirds of it would let a
    determinate row through with nowhere attached.

    Args:
        field: Which of the three the document omits or mistypes.
        value: What it says instead.

    """
    document = _result(**{field: value})

    with pytest.raises(Py314VerificationDocumentError, match=r"CPM-PY314-S02 AC 1"):
        result_in(document, source=A_SOURCE)


@pytest.mark.parametrize("verified", [OMITTED, None, "true", 1, "yes"], ids=["omitted", "null", "string", "int", "yes"])
def test_a_verdict_that_is_not_a_boolean_is_refused_rather_than_read_as_truthy(verified: Any) -> None:
    """The one field a backend cannot leave to interpretation.

    `1` and `"yes"` are both truthy in Python, and either read as success would be
    this product recording a build it has no answer about.

    Args:
        verified: What the document says instead of a boolean.

    """
    with pytest.raises(Py314VerificationDocumentError, match="rather than a boolean"):
        result_in(_result(verified=verified), source=A_SOURCE)


def test_a_field_the_schema_does_not_define_is_refused_rather_than_dropped() -> None:
    """A backend that grew a flag has changed what its verdict means.

    Named in the message, so an operator whose backend added a field learns which one
    rather than being told the document is unreadable.
    """
    with pytest.raises(Py314VerificationDocumentError, match="partial"):
        result_in(_result(partial=True), source=A_SOURCE)


def test_the_schema_defines_exactly_the_five_fields_a_backend_may_send() -> None:
    """Pinned, because the refusal above is only as good as the set it is measured against."""
    declared = {VERIFIED_FIELD, PLATFORM_FIELD, ARCHITECTURE_FIELD, LOG_REFERENCE_FIELD, DETAIL_FIELD}

    assert set(RESULT_FIELDS) == declared
    assert len(RESULT_FIELDS) == RESULT_FIELD_COUNT
    assert len(REQUIRED_FIELDS) == REQUIRED_FIELD_COUNT


def test_a_detail_that_is_not_a_string_is_refused() -> None:
    """A backend whose shape has changed is refused rather than read past."""
    with pytest.raises(Py314VerificationDocumentError, match="rather than a string"):
        result_in(_result(**{DETAIL_FIELD: [1, 2]}), source=A_SOURCE)


@pytest.mark.parametrize("field", sorted(REQUIRED_FIELDS), ids=str)
def test_a_value_wider_than_its_column_is_refused_and_never_truncated(field: str) -> None:
    """A truncated log reference resolves to nothing.

    Refused rather than recorded, which is where this module parts company with the
    static half: there an over-wide specifier is context for a verdict the run still
    reached, and here the over-wide value *is* the verdict's evidence.

    Args:
        field: Which column the value overflows.

    """
    width = PythonVerificationResult._meta.get_field(field).max_length  # noqa: SLF001 - Django's API
    assert width is not None

    with pytest.raises(Py314VerificationDocumentError, match="refused rather than"):
        result_in(_result(**{field: "x" * (width + 1)}), source=A_SOURCE)


@pytest.mark.parametrize("field", sorted(REQUIRED_FIELDS), ids=str)
def test_a_value_exactly_as_wide_as_its_column_is_accepted(field: str) -> None:
    """The bound is a refusal of what does not fit rather than of what only just does.

    Asserted because an off-by-one in the other direction is silent: it would refuse
    honest documents and look like a backend misbehaving.

    Args:
        field: Which column the value exactly fills.

    """
    width = PythonVerificationResult._meta.get_field(field).max_length  # noqa: SLF001 - Django's API
    assert width is not None
    exact = "x" * width

    assert getattr(result_in(_result(**{field: exact}), source=A_SOURCE), field) == exact


@pytest.mark.parametrize(
    ("value", "expected"),
    [("a\x00b", "NUL byte"), ("a\ud800b", "not encodable")],
    ids=["nul", "surrogate"],
)
def test_a_value_no_database_will_hold_is_refused_where_it_enters(value: str, expected: str) -> None:
    """Refused here rather than several frames inside the driver.

    Both shapes decode out of JSON perfectly well and are refused by psycopg from
    inside the driver, outside the guard that would have recorded the failure.

    Args:
        value: What the backend answered.
        expected: What the refusal says.

    """
    with pytest.raises(Py314VerificationDocumentError, match=expected):
        result_in(_result(platform=value), source=A_SOURCE)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("not json at all", "did not answer a readable"),
        ("[]", "rather than a result object"),
        ('"a string"', "rather than a result object"),
        ("null", "rather than a result object"),
    ],
    ids=["not-json", "list", "string", "null"],
)
def test_a_body_that_is_not_a_result_object_is_refused(body: str, expected: str) -> None:
    """A backend whose shape has changed is refused rather than read for whatever parses.

    Args:
        body: What the backend answered.
        expected: What the refusal says.

    """
    with pytest.raises(Py314VerificationDocumentError, match=expected):
        result_in(body, source=A_SOURCE)


def test_a_payload_body_that_is_not_a_string_is_refused_by_name() -> None:
    """Checked here rather than left to a `TypeError` from a length check naming no source."""
    with pytest.raises(Py314VerificationDocumentError, match="rather than a string"):
        result_in(object(), source=A_SOURCE)


def test_a_document_past_the_decode_bound_is_refused_before_it_is_parsed() -> None:
    """A backend answering with the build log rather than with a result.

    The log belongs behind `log_reference`, and parsing it would spend a worker's soft
    time limit finding out (`CPM-AD-9`).
    """
    with pytest.raises(Py314VerificationDocumentError, match="decodes at most"):
        result_in("x" * (MAX_DOCUMENT_CHARACTERS + 1), source=A_SOURCE)


# ---------------------------------------------------------------------------
# The rows the collector shapes.
# ---------------------------------------------------------------------------


def test_translate_builds_one_row_carrying_the_verdict_the_series_and_where_it_ran() -> None:
    """One row and never none: the base reads an empty translation as a broken parser."""
    payload = recorded_payload(source=A_SOURCE, body=_result())

    with _collector() as collector:
        rows = collector.translate(payload, package_id=A_PACKAGE, observed_at=FIXED_INSTANT)

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, PythonVerificationResult)
    assert row.state == VERIFIED_COMPATIBLE
    assert row.python_series == series_of(PYTHON_SERIES)
    assert row.platform == A_PLATFORM
    assert row.architecture == AN_ARCHITECTURE
    assert row.log_reference == A_LOG_REFERENCE
    assert row.source == A_SOURCE
    assert row.observed_at == FIXED_INSTANT


@pytest.mark.parametrize(
    "state",
    [OutcomeState.ERROR, OutcomeState.NOT_FOUND, OutcomeState.NOT_APPLICABLE],
    ids=lambda state: str(state.value),
)
def test_a_sentinel_row_names_the_series_and_nowhere_it_ran(state: OutcomeState) -> None:
    """The three states this collector shapes a sentinel for, and what each row may say.

    Every fact about the execution is absent, and it has to be: no run produced them.
    The series is present on every row, sentinel rows included, because
    `CPM-PY314-S03` reduces this table and the static one together.

    Args:
        state: The sentinel the base decided on.

    """
    with _collector() as collector:
        row = collector.sentinel_evidence(
            state=state,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="something happened",
        )

    assert isinstance(row, PythonVerificationResult)
    assert row.state == state.value
    assert row.python_series == series_of(PYTHON_SERIES)
    assert row.platform == ""
    assert row.architecture == ""
    assert row.log_reference == ""


def test_a_not_found_row_says_the_artifact_was_not_obtainable_rather_than_that_it_failed_to_build() -> None:
    """The two rows on this table a reader could most plausibly confuse.

    The caveat is appended by the collector because the base cannot know to write it:
    what the base knows is that the locator was not there.
    """
    with _collector() as collector:
        row = collector.sentinel_evidence(
            state=OutcomeState.NOT_FOUND,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="the backend says so",
        )

    assert NOT_OBTAINABLE_DETAIL in row.detail


@pytest.mark.parametrize("state", [OutcomeState.OK, OutcomeState.UNKNOWN], ids=lambda state: str(state.value))
def test_a_sentinel_state_this_collector_has_no_row_shape_for_is_refused_at_the_call(state: OutcomeState) -> None:
    """Refused where the wrong state is asked for, not where the row would fail to insert.

    Args:
        state: A state this collector shapes no sentinel row for.

    """
    with _collector() as collector, pytest.raises(CollectorConfigurationError, match="was asked for"):
        collector.sentinel_evidence(state=state, package_id=A_PACKAGE, observed_at=FIXED_INSTANT, detail="x")


def test_a_sentinel_reason_too_long_is_shortened_rather_than_refused() -> None:
    """A sentinel row is written on a path already recording a failure, and must still be written.

    The opposite posture from the document reader: raising over a reason's shape would
    turn "the backend failed" into "no row at all", which is what `CPM-NFR-3` forbids.
    """
    with _collector() as collector:
        row = collector.sentinel_evidence(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="x" * (MAX_SENTINEL_DETAIL_CHARACTERS + 10),
        )

    assert row.detail.endswith(SHORTENED_DETAIL)


def test_a_sentinel_reason_carrying_a_control_character_is_cleaned_rather_than_refused() -> None:
    """The same posture, over the characters the driver refuses rather than over the length."""
    with _collector() as collector:
        row = collector.sentinel_evidence(
            state=OutcomeState.ERROR,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="before\x00after\ud800end",
        )

    assert "\x00" not in row.detail
    assert "\ud800" not in row.detail
    row.detail.encode("utf-8")


# ---------------------------------------------------------------------------
# The refusal a caller triggering an unresolvable package meets.
# ---------------------------------------------------------------------------


def test_the_identity_refusal_says_the_question_is_unanswered_rather_than_inapplicable() -> None:
    """The distinction the `not_applicable` state exists to keep.

    Asserted on the shared sentence rather than on a message built in the case,
    because what matters is that a caller reading the refusal is told the package is
    unresolved rather than told this product need never build it.
    """
    assert "unanswered rather than inapplicable" in IDENTITY_UNRESOLVED_DETAIL
    assert issubclass(Py314VerificationIdentityError, ValueError)


def test_a_column_that_declares_no_width_is_a_refusal_rather_than_a_skip() -> None:
    """A guard that quietly stops guarding is worse than one that never existed.

    A caller writing `if width is not None and ...` would let a field renamed or
    turned into a `TextField` store whatever a backend sends on SQLite and fail the
    run on PostgreSQL (`R-5`). `detail` is the `TextField` this table really has, so
    the refusal is asked with a column that exists rather than with a fixture.
    """
    with pytest.raises(CollectorConfigurationError, match="declares no max_length"):
        py314_verification._column_width("detail")  # noqa: SLF001 - the guard under test


def test_a_row_renders_the_series_the_verdict_and_where_it_ran() -> None:
    """What an admin list and a debugger show, and it names all four facts.

    Rendered for an unsaved row, which is the state a `translate` result is in when
    a failure is being read: `package_id` and `observed_at` are the two that can be
    absent, and both have their own wording rather than a bare `None`.
    """
    rendered = str(
        PythonVerificationResult(
            state=VERIFIED_COMPATIBLE,
            python_series=series_of(PYTHON_SERIES),
            platform=A_PLATFORM,
            architecture=AN_ARCHITECTURE,
        ),
    )

    assert series_of(PYTHON_SERIES) in rendered
    assert VERIFIED_COMPATIBLE in rendered
    assert f"{A_PLATFORM}/{AN_ARCHITECTURE}" in rendered
    assert "no package" in rendered
    assert "never" in rendered


def test_a_row_that_names_nowhere_says_so_rather_than_rendering_a_bare_slash() -> None:
    """The sentinel half of the same rendering, where the three columns are blank."""
    rendered = str(PythonVerificationResult(state=VERIFICATION_ERROR, python_series=""))

    assert "(nowhere named)" in rendered
    assert "(no series)" in rendered
