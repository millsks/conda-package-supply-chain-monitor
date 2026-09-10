"""What the static-readiness collector declares, what a specifier admits, and what a silence means.

`CPM-PY314-S01` is four questions, and only the last needs a run. Whether a
`Requires-Python` specifier admits Python 3.14 is a pure function of a string;
what a project document *declares* is a pure function of a body; what this product
may claim from those two signals is a pure function of both; and whether the
question applies at all is a pure function of what `identity` recorded. All four
are here with no database, no socket and no clock (`CPM-AD-27`). What needs a run --
the rows, the ledger, the `not_applicable` path end to end, the constraints, the
task -- is in `tests/integration/django_apps/test_python_readiness.py`.

**The case this module exists for is the silence.** Most projects have not declared
3.14 support, and a collector that read "declares nothing" as "excludes it" would
report most of an inventory as incompatible on no evidence. Every silence in the
matrix has a case here, and every one of them asserts the state is `unknown` **and**
that it is not `inferred_incompatible` -- the second half deliberately, because a
vocabulary rename that made the two the same string would satisfy the first alone.

**The second absence trap has its own cases.** `not_applicable` is reachable only
where identity *established* that the question does not apply, and
`inapplicability_of` is asserted to answer nothing for every other mapping outcome
there is -- parametrized over `MappingOutcome`'s own members rather than over a list
written out here, so the sweep *constrains* an outcome added later: it acquires a
case of its own asserting the question stays applicable, rather than acquiring a
determinate meaning nobody wrote a case about. It does not *fail* on a new member --
`inapplicability_of` answers nothing for it by construction -- and saying it did
would claim a tripwire this file does not have.

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

from conda_sentinel.collectors import pypi_release
from conda_sentinel.collectors import python_readiness
from conda_sentinel.collectors import specifiers
from conda_sentinel.collectors.agent import USER_AGENT
from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.outcomes import INFERRED_COMPATIBLE
from conda_sentinel.collectors.outcomes import INFERRED_INCOMPATIBLE
from conda_sentinel.collectors.outcomes import READINESS_ERROR
from conda_sentinel.collectors.outcomes import READINESS_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import READINESS_NOT_FOUND
from conda_sentinel.collectors.outcomes import READINESS_UNKNOWN
from conda_sentinel.collectors.outcomes import PythonReadinessOutcome
from conda_sentinel.collectors.python_readiness import ABSENT_FROM_INDEX_DETAIL
from conda_sentinel.collectors.python_readiness import CLASSIFIERS_FIELD
from conda_sentinel.collectors.python_readiness import COLLECTOR_NAME
from conda_sentinel.collectors.python_readiness import DISAGREEMENT_DETAIL
from conda_sentinel.collectors.python_readiness import IDENTITY_UNRESOLVED_DETAIL
from conda_sentinel.collectors.python_readiness import INFO_FIELD
from conda_sentinel.collectors.python_readiness import MAX_CLASSIFIERS
from conda_sentinel.collectors.python_readiness import MAX_DOCUMENT_CHARACTERS
from conda_sentinel.collectors.python_readiness import MAX_SENTINEL_DETAIL_CHARACTERS
from conda_sentinel.collectors.python_readiness import NO_CLASSIFIER_FOR_SERIES_DETAIL
from conda_sentinel.collectors.python_readiness import NOTHING_DECLARED_DETAIL
from conda_sentinel.collectors.python_readiness import OVERSIZE_SPECIFIER_DETAIL
from conda_sentinel.collectors.python_readiness import PURL_SCHEME
from conda_sentinel.collectors.python_readiness import PURL_TYPE
from conda_sentinel.collectors.python_readiness import PYPI_HOST
from conda_sentinel.collectors.python_readiness import PYTHON_SERIES
from conda_sentinel.collectors.python_readiness import READINESS_CACHE_TTL
from conda_sentinel.collectors.python_readiness import READINESS_CADENCE
from conda_sentinel.collectors.python_readiness import READINESS_DISPATCH_OFFSET
from conda_sentinel.collectors.python_readiness import READINESS_FRESHNESS_TARGET
from conda_sentinel.collectors.python_readiness import READINESS_HEADERS
from conda_sentinel.collectors.python_readiness import READINESS_OBSERVATION_WINDOW
from conda_sentinel.collectors.python_readiness import READINESS_RATE_LIMIT
from conda_sentinel.collectors.python_readiness import READINESS_RETRIES
from conda_sentinel.collectors.python_readiness import READINESS_TIMEOUT
from conda_sentinel.collectors.python_readiness import REQUIRES_PYTHON_FIELD
from conda_sentinel.collectors.python_readiness import SHORTENED_DETAIL
from conda_sentinel.collectors.python_readiness import TOLERATED_MISSED_RUNS
from conda_sentinel.collectors.python_readiness import UNREADABLE_SPECIFIER_DETAIL
from conda_sentinel.collectors.python_readiness import UNREADABLE_SPECIFIER_EVENT
from conda_sentinel.collectors.python_readiness import Assessment
from conda_sentinel.collectors.python_readiness import DeclaredMetadata
from conda_sentinel.collectors.python_readiness import PythonReadinessAssessmentError
from conda_sentinel.collectors.python_readiness import PythonReadinessCollector
from conda_sentinel.collectors.python_readiness import PythonReadinessDocumentError
from conda_sentinel.collectors.python_readiness import PythonReadinessIdentityError
from conda_sentinel.collectors.python_readiness import ReleaseIdentity
from conda_sentinel.collectors.python_readiness import asks_about
from conda_sentinel.collectors.python_readiness import assess
from conda_sentinel.collectors.python_readiness import declared_metadata
from conda_sentinel.collectors.python_readiness import inapplicability_of
from conda_sentinel.collectors.python_readiness import project_locator
from conda_sentinel.collectors.python_readiness import project_name
from conda_sentinel.collectors.specifiers import ADMITS
from conda_sentinel.collectors.specifiers import CLASSIFIER_PREFIX
from conda_sentinel.collectors.specifiers import EXCLUDES
from conda_sentinel.collectors.specifiers import MAX_CLAUSES
from conda_sentinel.collectors.specifiers import MAX_RELEASE_SEGMENTS
from conda_sentinel.collectors.specifiers import UNDECIDABLE
from conda_sentinel.collectors.specifiers import DecidingSignal
from conda_sentinel.collectors.specifiers import admits_series
from conda_sentinel.collectors.specifiers import classifier_for
from conda_sentinel.collectors.specifiers import declares_version_classifiers
from conda_sentinel.collectors.specifiers import series_of
from conda_sentinel.collectors.tasks import COLLECT_PYTHON_READINESS_TASK_NAME
from conda_sentinel.collectors.tasks import collect_python_readiness
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.collection import CONDITIONAL_HEADERS
from conda_sentinel.core.collection import CollectorConfigurationError
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.queues import Queue
from conda_sentinel.core.queues import queue_for
from conda_sentinel.core.transport import MAX_TIMEOUT
from conda_sentinel.core.transport import worst_case_call_seconds
from conda_sentinel.identity.models import ESTABLISHED
from conda_sentinel.identity.models import MappingOutcome
from tests.clocks import FIXED_INSTANT
from tests.collectors import recorded_payload
from tests.source_scan import SRC_ROOT
from tests.source_scan import parse

if TYPE_CHECKING:
    from pathlib import Path

    from conda_sentinel.core.transport import Payload

#: The two modules this file's source sweeps are about, relative to `src/`.
READINESS_MODULE: Final[str] = "django_apps/conda_sentinel/collectors/python_readiness.py"
SPECIFIERS_MODULE: Final[str] = "django_apps/conda_sentinel/collectors/specifiers.py"

#: The evidence model a *sibling* collector writes, and its table. Named here so
#: the source sweep asserting this module reads neither is asserting about the
#: real names rather than about a spelling of its own.
SIBLING_EVIDENCE_MODEL: Final[str] = "PyPIReleaseSnapshot"
SIBLING_EVIDENCE_TABLE: Final[str] = "pypi_release_snapshots"

#: A purl the cases build locators from, and the locator it produces. Written out
#: rather than composed from the module's own constants, because a locator
#: assembled the same way twice would agree with itself however wrong it was.
A_PURL: Final[str] = "pkg:pypi/Django"
THE_LOCATOR: Final[str] = "https://pypi.org/pypi/django/json"

#: The locator a payload claims to have come from, for the document cases.
A_SOURCE: Final[str] = "https://pypi.org/pypi/a-project/json"

#: The classifier that names the assessed series, and one that names an earlier
#: one. Written out rather than built by `classifier_for`, because a case built
#: from the function under test would agree with it however wrong it was.
THE_CLASSIFIER: Final[str] = "Programming Language :: Python :: 3.14"
AN_EARLIER_CLASSIFIER: Final[str] = "Programming Language :: Python :: 3.12"

#: The umbrella classifier almost every published project declares. A *superset*
#: claim -- "this project supports Python 3", which contains 3.14 -- rather than an
#: enumeration of minor series that left 3.14 out.
THE_UMBRELLA_CLASSIFIER: Final[str] = "Programming Language :: Python :: 3"

#: A classifier inside the Python namespace that names no version, and one
#: outside it altogether. Two cases rather than one, because they take different
#: branches: the first gets past the prefix and fails the version pattern, and the
#: second never reaches the pattern at all.
A_NON_VERSION_CLASSIFIER: Final[str] = "Programming Language :: Python :: Implementation :: CPython"
A_CLASSIFIER_OUTSIDE_THE_NAMESPACE: Final[str] = "License :: OSI Approved :: MIT License"

#: How much of the inherited soft limit one call may spend -- three quarters, so
#: the claim is "with room for the ledger writes around it" rather than "by a
#: hair".
SOFT_LIMIT_SHARE: Final[float] = 0.75

#: A package key the cases that need one use. This tier never reads a row.
A_PACKAGE: Final[int] = 7

#: The marker `_project` treats as "the source did not send this field at all", as
#: distinct from `None`, which is an explicit JSON `null`.
OMITTED: Final[object] = object()

#: How many classifiers the case about an unrelated over-wide one expects back.
#: Named because `PLR2004` is right about a bare number in an assertion.
TWO_CLASSIFIERS: Final[int] = 2


def _padded_specifier(over: int) -> str:
    """Return a readable specifier `over` characters past the width of the column that records it.

    `>=3.000...0`, which PEP 440 makes the same release as `>=3.0` because trailing
    zeros are insignificant -- so the value is determinate at every length and the
    only thing the padding changes is whether it fits.

    Args:
        over: How far past the column's width to pad. Zero is exactly the width.

    Returns:
        The specifier.

    """
    width = PythonReadinessAssessment._meta.get_field("requires_python").max_length  # noqa: SLF001 - Django's API
    assert width is not None
    prefix = ">=3."
    return f"{prefix}{'0' * (width + over - len(prefix))}"


def _project(
    requires_python: str | object | None = OMITTED,
    classifiers: list[Any] | object | None = OMITTED,
    **overrides: Any,
) -> dict[str, Any]:
    """Return one project document, with any field replaced, nulled or omitted.

    Args:
        requires_python: `info.requires_python`. `OMITTED` leaves the field out.
        classifiers: `info.classifiers`. `OMITTED` leaves the field out.
        **overrides: Top-level fields to add or replace; `OMITTED` omits one.

    Returns:
        The document a source would serve.

    """
    info: dict[str, Any] = {
        "name": "a-project",
        REQUIRES_PYTHON_FIELD: requires_python,
        CLASSIFIERS_FIELD: classifiers,
    }
    document: dict[str, Any] = {INFO_FIELD: {name: value for name, value in info.items() if value is not OMITTED}}
    document.update(overrides)
    return {name: value for name, value in document.items() if value is not OMITTED}


def _payload(body: str) -> Payload:
    """Return a recorded payload carrying this body.

    Args:
        body: What the source said.

    Returns:
        The `Payload` a transport would have recorded, built through the shared
        helper so this tier and the integration tier are handed the same shape.

    """
    return recorded_payload(source=A_SOURCE, body=body)


def _declared(requires_python: str = "", *classifiers: str) -> DeclaredMetadata:
    """Return what a project might have declared.

    Args:
        requires_python: The specifier, or blank for a project that declared none.
        *classifiers: The classifiers it declared.

    Returns:
        The metadata value `assess` takes.

    """
    return DeclaredMetadata(requires_python=requires_python, classifiers=classifiers)


def _identity(outcome: str = ESTABLISHED, primary_type: str = PURL_TYPE, primary_purl: str = A_PURL) -> ReleaseIdentity:
    """Return what resolution might have recorded about a package.

    Args:
        outcome: The `release_ecosystem` mapping's outcome.
        primary_type: The recorded primary purl type.
        primary_purl: The recorded primary purl.

    Returns:
        The identity.

    """
    return ReleaseIdentity(outcome=outcome, primary_type=primary_type, primary_purl=primary_purl)


def _collector() -> PythonReadinessCollector:
    """Return a collector with a stopped clock and no transport of its own.

    Returns:
        The collector. The base builds a `RequestsTransport` from the declared
        timeout, which is never asked for anything at this tier.

    """
    return PythonReadinessCollector(clock=FixedClock(instant=FIXED_INSTANT))


def _module(relative: str) -> Path:
    """Return one of the modules this file's source sweeps read.

    Args:
        relative: Its path under `src/`.

    Returns:
        The resolved path.

    """
    return SRC_ROOT / relative


# ---------------------------------------------------------------------------
# The declarations, and the arithmetic behind them.
# ---------------------------------------------------------------------------


def test_the_collector_declares_every_value_the_base_checks() -> None:
    """All nine, written out on the class and carrying the module's own constants.

    Compared by *value* rather than by presence, for the reason every sibling
    collector's case gives: a class attribute rebound to the wrong constant
    declares nine names and behaves like something nobody wrote down.
    """
    declared = vars(PythonReadinessCollector)

    assert PythonReadinessCollector.name == COLLECTOR_NAME
    assert PythonReadinessCollector.evidence_model is PythonReadinessAssessment
    assert PythonReadinessCollector.observation_window == READINESS_OBSERVATION_WINDOW
    assert PythonReadinessCollector.timeout == READINESS_TIMEOUT
    assert PythonReadinessCollector.retries == READINESS_RETRIES
    assert PythonReadinessCollector.rate_limit == READINESS_RATE_LIMIT
    assert PythonReadinessCollector.headers == READINESS_HEADERS
    assert PythonReadinessCollector.freshness_target == READINESS_FRESHNESS_TARGET
    assert PythonReadinessCollector.response_cache_ttl == READINESS_CACHE_TTL
    assert PythonReadinessCollector.cadence == READINESS_CADENCE
    assert {
        "name",
        "evidence_model",
        "observation_window",
        "timeout",
        "retries",
        "rate_limit",
        "headers",
        "freshness_target",
        "response_cache_ttl",
        "cadence",
    } <= set(declared)


def test_the_freshness_target_is_the_arithmetic_open_question_7_settled() -> None:
    """`cadence x (1 + tolerated_missed_runs)`, and strictly greater than the cadence.

    `core/freshness.py` reports stale when `observed_at < now - target`, so a target
    *equal* to the cadence makes every package read stale at exactly the moment its
    next run is due, without a single collection having failed. `CPM-AD-28` and PRD
    Open Question 7a.
    """
    assert READINESS_FRESHNESS_TARGET == READINESS_CADENCE * (1 + TOLERATED_MISSED_RUNS)
    assert READINESS_FRESHNESS_TARGET > READINESS_CADENCE


def test_the_observation_window_cannot_suppress_a_scheduled_run() -> None:
    """Shorter than the cadence, which is the property rather than the halving."""
    assert READINESS_OBSERVATION_WINDOW < READINESS_CADENCE


def test_the_cache_entry_outlives_the_cadence_that_would_revalidate_it() -> None:
    """A TTL inside the cadence makes the cache inert, which is the whole of what it buys.

    This collector's cadence is the longest of any per-package collector's, so the
    trap is nearer here than anywhere else: an entry that expired between two runs
    would have every weekly collection re-transfer a document that lists every file
    of every release the project ever published.
    """
    assert READINESS_CACHE_TTL > READINESS_CADENCE


def test_the_dispatch_offset_is_smaller_than_the_cadence_it_phases() -> None:
    """A phase at or past the cadence is a sweep that never runs at the hour it declares."""
    assert READINESS_DISPATCH_OFFSET < READINESS_CADENCE
    assert timedelta() < READINESS_DISPATCH_OFFSET


def test_one_collection_fits_inside_the_inherited_soft_time_limit() -> None:
    """`CPM-AD-9`: one call, retried, with room left for the ledger writes around it.

    Read from the settings module rather than from a number restated here, so a
    deployment that lowered the limit fails this case rather than the worker.
    """
    limit = settings.CELERY_TASK_SOFT_TIME_LIMIT
    worst = worst_case_call_seconds(timeout=READINESS_TIMEOUT, retries=READINESS_RETRIES)

    assert READINESS_TIMEOUT <= MAX_TIMEOUT
    assert worst <= limit * SOFT_LIMIT_SHARE


def test_the_declared_headers_are_what_the_source_expects_and_nothing_conditional() -> None:
    """`CPM-AD-20`: the collector declares what its source needs; the base composes validators.

    A collector declaring `If-None-Match` would be forging a validator for a body
    this process does not hold, and the base refuses one at construction.
    """
    assert READINESS_HEADERS["Accept"] == "application/json"
    assert READINESS_HEADERS["User-Agent"] == USER_AGENT
    assert not set(READINESS_HEADERS) & set(CONDITIONAL_HEADERS)


def test_the_allowance_is_declared_rather_than_unlimited_by_omission() -> None:
    """`CPM-AD-20`: PyPI publishes no ceiling, so this is a courtesy bound written down."""
    assert READINESS_RATE_LIMIT.calls > 0
    assert READINESS_RATE_LIMIT.per == timedelta(minutes=1)


def test_the_assessed_series_is_the_one_the_story_is_about() -> None:
    """3.14, spelled as two numeric segments and as the string a column records.

    The tuple is what `collectors/specifiers.py` answers containment over and the
    string is what `python_readiness_assessments.python_series` holds; a case that
    built the second from the first would agree with it however wrong it was.
    """
    assert PYTHON_SERIES == (3, 14)
    assert series_of(PYTHON_SERIES) == "3.14"
    assert classifier_for(PYTHON_SERIES) == THE_CLASSIFIER


# ---------------------------------------------------------------------------
# The task: its name, its queue, and the collector it builds.
# ---------------------------------------------------------------------------


def test_the_task_name_routes_to_the_collect_queue_and_not_to_verify() -> None:
    """`CPM-AD-20` and `R-11`: the cheap pass is collection work, the build is not.

    The name is the whole of what routes a task (`core/queues.py`), so a static
    assessment declared under `cpm.verify.` would tick against the compute slots
    `CPM-PY314-S02`'s build needs -- which is `R-11` exactly, arrived at from the
    cheap half of one requirement.
    """
    assert f"cpm.collect.{COLLECTOR_NAME}" == COLLECT_PYTHON_READINESS_TASK_NAME
    assert queue_for(COLLECT_PYTHON_READINESS_TASK_NAME) is Queue.COLLECT


def test_the_task_is_registered_under_the_name_the_module_declares() -> None:
    """The decorator and the constant, reconciled rather than assumed."""
    assert collect_python_readiness.name == COLLECT_PYTHON_READINESS_TASK_NAME


def test_the_task_declares_no_schedule_and_no_time_limit() -> None:
    """`CPM-AD-20`, `CPM-NFR-2`, `CPM-AD-9`: cadence is data and limits are settings'."""
    options = collect_python_readiness.__dict__

    assert "run_every" not in options
    assert collect_python_readiness.soft_time_limit is None
    assert collect_python_readiness.time_limit is None


# ---------------------------------------------------------------------------
# The locator: a purl becomes one question, or is refused.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("purl", "expected"),
    [
        ("pkg:pypi/Django", "django"),
        ("pkg:pypi/Zope.Interface@6.0?extra=x#sub", "zope-interface"),
        ("pkg:pypi/zope_interface", "zope-interface"),
        ("pkg:PyPI/Django", "django"),
        ("pkg:pypi/a%2Db", "a-b"),
    ],
)
def test_a_purl_becomes_the_pep_503_name_pypi_holds_the_project_under(purl: str, expected: str) -> None:
    """One project, one locator, one cache entry, one spelling of `source`.

    PyPI treats `Zope.Interface`, `zope_interface` and `zope-interface` as one
    project; a collector that did not would ask three questions about one project
    and record three histories.
    """
    assert project_name(purl) == expected


@pytest.mark.parametrize(
    "purl",
    [
        "",
        "   ",
        "django",
        "pkg:conda/django",
        "pkg:pypi/ns/django",
        "pkg:pypi/",
        "pkg:pypi/-django",
        "pkg:pypi/..",
    ],
)
def test_a_purl_that_names_no_pypi_project_is_refused_rather_than_repaired(purl: str) -> None:
    """`CPM-FR-1`: a stored purl is data a resolution wrote, and a broken one is not repaired here.

    The exception *type* is asserted rather than its message, because the message
    is prose and the type is the contract the base and the task are written against.
    """
    with pytest.raises(PythonReadinessIdentityError):
        project_name(purl)


def test_a_purl_this_collector_cannot_read_says_the_question_is_unanswered() -> None:
    """The absence trap, asserted on the words the operator actually reads.

    A message that said "does not apply" would invite exactly the reading
    `CPM-PY314-S01` forbids: identity naming another ecosystem, or naming nothing,
    leaves the compatibility question *unanswered*. The row it produces is never
    `not_applicable`, and neither is the sentence that explains it.
    """
    with pytest.raises(PythonReadinessIdentityError) as refused:
        project_name("pkg:cran/ggplot2")

    assert OutcomeState.NOT_APPLICABLE.value not in str(refused.value)
    assert "unanswered" in str(refused.value)


def test_a_locator_is_the_project_document_on_the_declared_host() -> None:
    """The one document this collector reads, spelled out rather than composed."""
    assert project_locator(A_PURL) == THE_LOCATOR
    assert project_locator(A_PURL).startswith(f"https://{PYPI_HOST}/")


def test_a_locator_wider_than_the_column_that_records_it_is_refused() -> None:
    """`R-5`: PostgreSQL enforces `max_length` and SQLite ignores it.

    An over-wide locator is a stored row on a developer's machine and a failed run
    in the gate, so it is refused before the window and the allowance rather than at
    the insert -- after the call was already spent.
    """
    width = PythonReadinessAssessment._meta.get_field("source").max_length  # noqa: SLF001 - Django's own API
    assert width is not None

    with pytest.raises(PythonReadinessIdentityError):
        project_locator(f"{PURL_SCHEME}{PURL_TYPE}/{'a' * (width + 1)}")


def test_a_locator_exactly_as_wide_as_the_column_that_records_it_is_built() -> None:
    """The accepting side of the same bound, which a refusal-only case leaves free to drift.

    `>` read as `>=` refuses the widest locator the column really holds, and a
    package would then be refused for ever on a locator PostgreSQL would have taken.
    """
    width = PythonReadinessAssessment._meta.get_field("source").max_length  # noqa: SLF001 - Django's own API
    assert width is not None
    prefix = f"https://{PYPI_HOST}/pypi/"
    name = "a" * (width - len(prefix) - len("/json"))

    locator = project_locator(f"{PURL_SCHEME}{PURL_TYPE}/{name}")

    assert len(locator) == width


# ---------------------------------------------------------------------------
# The specifier grammar: containment, and the shapes this product will not read.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "specifier",
    [
        ">=3.9",
        ">=3.9,<4",
        ">=3.14",
        ">=3.14.0",
        ">3.14",
        "<3.15",
        "<=3.14",
        "==3.14",
        "==3.14.*",
        "==3.*",
        "!=3.13.*",
        ">=3.9,!=3.13.*",
        "~=3.9",
        ">= 3.9 , < 4",
        ">=3.9,!=3.14.0",
    ],
)
def test_a_specifier_that_admits_the_series_is_read_as_admitting_it(specifier: str) -> None:
    """The containment question, answered over the interval `[3.14, 3.15)`.

    `>3.14` is in the list on purpose: it excludes `3.14.0` and admits `3.14.1`, and
    a reader asking "is this project ready for 3.14" means the series rather than
    one patch release. A point comparison would answer `excludes` and send
    verification somewhere it is not needed.
    """
    assert admits_series(specifier, series=PYTHON_SERIES).verdict == ADMITS


@pytest.mark.parametrize(
    "specifier",
    [
        "<3.14",
        "<3.13",
        ">=3.15",
        ">3.15",
        "==3.13",
        "==3.13.*",
        ">=3.9,<3.13",
        ">=3.9,!=3.14.*",
        "~=3.9.1",
        "==3.14,!=3.14",
        ">=3.9,<4,!=3.14.*",
    ],
)
def test_a_specifier_that_cannot_admit_the_series_is_read_as_excluding_it(specifier: str) -> None:
    """The one determinate negative this product reaches, and it rests on a published claim.

    `>=3.9,!=3.14.*` is the case a coverage check alone would miss: the bounds admit
    the series and the exclusion removes every release in it, so a reader that
    stopped at the bounds would answer `admits` for a specifier that admits nothing.
    """
    assert admits_series(specifier, series=PYTHON_SERIES).verdict == EXCLUDES


@pytest.mark.parametrize(
    "specifier",
    [
        "===3.14",
        ">=1!3.9",
        ">=3.9rc1",
        ">=3.9.post1",
        ">=3.9.dev0",
        ">=3.9+local",
        ">=",
        "3.9",
        ">=3.9,",
        ">=*",
        ">=3.*",
        "~=3",
        "~=3.*",
        ">=" + ".".join("1" * (MAX_RELEASE_SEGMENTS + 1)),
        ",".join([">=3.9"] * (MAX_CLAUSES + 1)),
    ],
    # Explicit ids for the same reason as the document-shape case below: the last
    # two are generated, and a node id built from a generated specifier is what
    # overran Windows' 32 767-character environment-variable limit.
    ids=[
        "arbitrary-equality",
        "epoch",
        "pre-release",
        "post-release",
        "development-release",
        "local-version",
        "bare-operator",
        "no-operator",
        "trailing-comma",
        "wildcard-without-release",
        "wildcard-mid-release",
        "compatible-release-too-short",
        "compatible-release-wildcard",
        "too-many-release-segments",
        "too-many-clauses",
    ],
)
def test_a_specifier_shape_this_product_will_not_read_is_undecidable_and_never_excluding(specifier: str) -> None:
    """`CPM-PY314-S01`'s Block If: an unreadable claim is not a negative claim.

    Deciding these needs the ordering rules `CPM-SECURITY-S06` established nobody
    owns -- epochs, pre-releases, post-releases, development releases, local
    versions, and PEP 440's arbitrary equality, which compares *strings*. Every one
    of them records `unknown` with the reason rather than a verdict, and the case
    asserts the negative as well as the verdict: `EXCLUDES` here would be a
    determinate claim about somebody's package made from a shape nobody read.
    """
    reading = admits_series(specifier, series=PYTHON_SERIES)

    assert reading.verdict == UNDECIDABLE
    assert reading.verdict != EXCLUDES
    assert reading.reason


def test_an_undecidable_reading_always_carries_a_reason_and_a_decidable_one_never_does() -> None:
    """The gap is recorded rather than merely refused, which is the Block If's second half."""
    assert admits_series(">=3.9", series=PYTHON_SERIES).reason == ""
    assert admits_series("<3.9", series=PYTHON_SERIES).reason == ""
    assert admits_series("===3.14", series=PYTHON_SERIES).reason != ""


def test_the_series_is_an_interval_rather_than_a_release() -> None:
    """Asserted against a second series, so the answer is not a constant this file agreed with.

    `>=3.14` admits 3.14 and cannot admit 3.13; `<3.14` is the mirror. A containment
    check that had degenerated into "always admits" passes the first list above and
    fails here.
    """
    assert admits_series(">=3.14", series=(3, 13)).verdict == EXCLUDES
    assert admits_series("<3.14", series=(3, 13)).verdict == ADMITS


@pytest.mark.parametrize(
    ("classifiers", "enumerated"),
    [
        ((), False),
        ((A_CLASSIFIER_OUTSIDE_THE_NAMESPACE,), False),
        ((A_NON_VERSION_CLASSIFIER,), False),
        (("Programming Language :: Python :: 3 :: Only",), False),
        ((THE_UMBRELLA_CLASSIFIER,), False),
        ((THE_UMBRELLA_CLASSIFIER, "Programming Language :: Python :: 3 :: Only"), False),
        ((AN_EARLIER_CLASSIFIER,), True),
        ((THE_UMBRELLA_CLASSIFIER, AN_EARLIER_CLASSIFIER), True),
        ((THE_CLASSIFIER,), True),
    ],
)
def test_enumerating_pythons_is_distinguishable_from_declaring_classifiers(
    classifiers: tuple[str, ...],
    *,
    enumerated: bool,
) -> None:
    """Two different silences, and the row's `detail` depends on telling them apart.

    A project that declares no version classifier has said nothing about any
    Python; one that lists several and omits this one has said something a reviewer
    should see. Neither is a claim of incompatibility -- a classifier list is
    positive-only -- but a reader that collapsed them would lose the difference the
    matrix keeps.

    **The bare umbrella is not an enumeration**, and that is the case the shape of
    this function turns on: `Programming Language :: Python :: 3` is a *superset*
    claim containing 3.14 rather than a list that left it out, so it corroborates
    nothing and contradicts nothing. A dotted version beside it makes the list an
    enumeration; the umbrella alone, with or without `:: 3 :: Only`, does not.
    """
    assert declares_version_classifiers(classifiers) is enumerated


def test_the_classifier_prefix_is_pinned_to_its_literal() -> None:
    """A constant both readers build from is a constant a rename would hide.

    `classifier_for` and `declares_version_classifiers` are built from
    `CLASSIFIER_PREFIX`, so a renamed prefix would keep them agreeing with each
    other while agreeing with nothing PyPI publishes.
    """
    assert CLASSIFIER_PREFIX == "Programming Language :: Python :: "


# ---------------------------------------------------------------------------
# The document: what a project declared, and what is refused rather than read.
# ---------------------------------------------------------------------------


def test_an_ordinary_document_yields_the_two_static_signals() -> None:
    """Both fields, verbatim, and nothing else taken from the document."""
    metadata = declared_metadata(
        json.dumps(_project(requires_python=">=3.9", classifiers=[THE_CLASSIFIER, A_NON_VERSION_CLASSIFIER])),
        source=A_SOURCE,
    )

    assert metadata.requires_python == ">=3.9"
    assert metadata.classifiers == (THE_CLASSIFIER, A_NON_VERSION_CLASSIFIER)


@pytest.mark.parametrize(
    "document",
    [
        _project(),
        _project(requires_python=None, classifiers=None),
        _project(requires_python="   ", classifiers=[]),
    ],
)
def test_a_project_that_declared_nothing_is_read_rather_than_refused(document: dict[str, Any]) -> None:
    """The commonest row this table holds is not a document error.

    An absent field, an explicit `null` and whitespace all mean "the project
    declares none", and PyPI really sends all three. A reader that refused any of
    them would fail most of an inventory on every run.
    """
    metadata = declared_metadata(json.dumps(document), source=A_SOURCE)

    assert metadata.requires_python == ""
    assert metadata.classifiers == ()


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[]",
        '"a string"',
        json.dumps({INFO_FIELD: []}),
        json.dumps(_project(requires_python=3.9)),
        json.dumps(_project(classifiers="a string")),
        json.dumps(_project(classifiers=[1])),
        json.dumps(_project(classifiers=[THE_CLASSIFIER] * (MAX_CLASSIFIERS + 1))),
    ],
    # Explicit ids because two of these bodies are generated and long. pytest
    # would otherwise build a node id from the body itself, and on Windows the
    # runner puts that id in an environment variable, which caps at 32 767
    # characters -- the suite then errors before the case runs.
    ids=[
        "not-json",
        "a-list",
        "a-string",
        "info-is-a-list",
        "requires-python-is-a-number",
        "classifiers-is-a-string",
        "classifiers-holds-a-number",
        "too-many-classifiers",
    ],
)
def test_a_document_whose_shape_has_changed_is_refused_rather_than_read_past(body: str) -> None:
    """Refused rather than partly read, and the stakes here are the whole story.

    Reading around a shape change would record "this project declared nothing" for a
    project that declared something in a shape the reader skipped -- an `unknown`
    row that looks exactly like an honest one, for every package, with nothing
    failing.
    """
    with pytest.raises(PythonReadinessDocumentError):
        declared_metadata(body, source=A_SOURCE)


def test_a_body_that_is_not_a_string_is_refused_by_name() -> None:
    """A `Payload` is a value a transport built, so its body is checked here.

    Left to `len()` the failure would be a `TypeError` naming no source, several
    frames from the collector that was handed it.
    """
    with pytest.raises(PythonReadinessDocumentError):
        declared_metadata(b"{}", source=A_SOURCE)


def test_a_document_past_the_decode_bound_is_refused_before_it_is_parsed() -> None:
    """`CPM-AD-9`: what the bound protects is the parse, which is where a soft limit goes."""
    with pytest.raises(PythonReadinessDocumentError):
        declared_metadata("x" * (MAX_DOCUMENT_CHARACTERS + 1), source=A_SOURCE)


def test_a_document_exactly_at_the_decode_bound_is_read() -> None:
    """The accepting side, so `>` cannot quietly become `>=` and refuse a document that fits.

    Padded with the trailing whitespace JSON permits, so the body really is
    `MAX_DOCUMENT_CHARACTERS` long and the only thing under test is the comparison.
    """
    document = json.dumps(_project(requires_python=">=3.9"))
    body = document + " " * (MAX_DOCUMENT_CHARACTERS - len(document))
    assert len(body) == MAX_DOCUMENT_CHARACTERS

    assert declared_metadata(body, source=A_SOURCE).requires_python == ">=3.9"


def test_a_document_naming_exactly_the_classifier_bound_is_read() -> None:
    """The accepting side of `MAX_CLASSIFIERS`, on the same terms."""
    classifiers = [AN_EARLIER_CLASSIFIER] * (MAX_CLASSIFIERS - 1) + [THE_CLASSIFIER]

    metadata = declared_metadata(json.dumps(_project(classifiers=classifiers)), source=A_SOURCE)

    assert len(metadata.classifiers) == MAX_CLASSIFIERS
    assert assess(metadata, series=PYTHON_SERIES).matching_classifier == THE_CLASSIFIER


@pytest.mark.parametrize("value", [">=3.9\x00", ">=3.9\ud800"])
@pytest.mark.parametrize("field", [REQUIRES_PYTHON_FIELD, CLASSIFIERS_FIELD])
def test_a_value_the_driver_will_not_hold_at_all_is_refused_where_it_enters(field: str, value: str) -> None:
    """A NUL byte and a lone surrogate are refused from *inside* psycopg, and on both signals.

    Several frames past the guard that would have recorded the failure, so an
    unrefused one escapes as neither a document refusal nor a recorded observation
    and repeats every cadence. Asked on the classifiers as well as the specifier,
    because the two enter by different readers and only one of them would have been
    checked by a guard written for the field under test.
    """
    document = _project(classifiers=[value]) if field == CLASSIFIERS_FIELD else _project(requires_python=value)

    with pytest.raises(PythonReadinessDocumentError):
        declared_metadata(json.dumps(document), source=A_SOURCE)


def test_a_classifier_wider_than_the_column_is_read_rather_than_refused() -> None:
    """The over-refusal this guard used to make, and it turned a readable document into an `error` row.

    Only the classifier equal to the series marker is ever stored, and its width is
    fixed by the series rather than by the document -- so measuring *every* declared
    classifier against `matching_classifier` refused a document for a value that
    could never have reached that column. The assessment below is the one the
    specifier earns, from a document carrying one absurd and entirely unrelated
    classifier beside it.
    """
    width = PythonReadinessAssessment._meta.get_field("matching_classifier").max_length  # noqa: SLF001 - Django's API
    assert width is not None
    document = _project(requires_python=">=3.9", classifiers=["c" * (width + 1), THE_CLASSIFIER])

    metadata = declared_metadata(json.dumps(document), source=A_SOURCE)

    assert len(metadata.classifiers) == TWO_CLASSIFIERS
    assert assess(metadata, series=PYTHON_SERIES).state == INFERRED_COMPATIBLE


def test_the_classifier_this_collector_would_store_fits_the_column_that_holds_it() -> None:
    """What replaces the width guard the document reader used to carry.

    `matching_classifier` never holds a value a document chose: it holds either
    nothing or the classifier `classifier_for` builds from the series, whose width
    the series fixes. That is the property the removed guard was reaching for, and it
    is asserted here once rather than asked of every unrelated classifier a project
    happens to declare.
    """
    width = PythonReadinessAssessment._meta.get_field("matching_classifier").max_length  # noqa: SLF001 - Django's API
    assert width is not None

    assert len(classifier_for(PYTHON_SERIES)) <= width


def test_a_classifier_is_stripped_of_the_whitespace_around_it_and_nothing_inside_it() -> None:
    """`DeclaredMetadata.classifiers` says so, and a padded classifier still names its Python.

    PyPI's own list carries no padding, and a project that indented one declared the
    classifier it names. What is compared against the series marker and what would be
    stored are therefore the same string -- a reader that kept the padding would fail
    to match a classifier the project plainly declared.
    """
    padded = f"  {THE_CLASSIFIER}  "

    metadata = declared_metadata(json.dumps(_project(classifiers=[padded])), source=A_SOURCE)

    assert metadata.classifiers == (THE_CLASSIFIER,)
    assert assess(metadata, series=PYTHON_SERIES).matching_classifier == THE_CLASSIFIER


def test_a_specifier_wider_than_its_column_is_unknown_rather_than_a_document_error() -> None:
    """`CPM-PY314-S01`'s Spec Change Log: this module has a vocabulary for a specifier it will not read.

    An over-wide `Requires-Python` is squarely one. Refusing the *document* for it
    recorded `error` -- "looking failed" -- for a source that answered perfectly well,
    every run, for ever. The row is `unknown` instead, and it carries **no**
    specifier: a truncated specifier is a different specifier, and the row must not
    claim the project declared what this product had to shorten.
    """
    metadata = declared_metadata(
        json.dumps(_project(requires_python=_padded_specifier(1))),
        source=A_SOURCE,
    )

    assessed = assess(metadata, series=PYTHON_SERIES)

    assert assessed.state == READINESS_UNKNOWN
    assert assessed.state != INFERRED_INCOMPATIBLE
    assert assessed.requires_python == ""
    assert assessed.deciding_signal == ""
    assert OVERSIZE_SPECIFIER_DETAIL in assessed.detail


def test_a_specifier_exactly_as_wide_as_its_column_is_read_rather_than_refused() -> None:
    """The accepting side of the bound, so a `>` that became a `>=` cannot survive.

    Every bound in this module is otherwise tested only from the side that refuses,
    which leaves an off-by-one free to reject the widest value the column really
    holds. The specifier is `>=3.000...0`, which is `>=3.0` with PEP 440's
    insignificant trailing zeros -- readable, determinate, and exactly as wide as the
    column that records it.
    """
    specifier = _padded_specifier(0)

    assessed = assess(_declared(specifier), series=PYTHON_SERIES)

    assert assessed.requires_python == specifier
    assert assessed.state == INFERRED_COMPATIBLE


def test_a_column_that_declares_no_width_is_a_refusal_rather_than_a_skip() -> None:
    """A guard that quietly stops guarding is worse than one that never existed.

    A caller writing `if width is not None and ...` would let a field renamed or
    turned into a `TextField` store whatever a source sends on SQLite and fail the
    run on PostgreSQL (`R-5`). `detail` is the `TextField` this collector really has,
    so the refusal is asked with a column that exists rather than with a fixture.
    """
    with pytest.raises(CollectorConfigurationError):
        python_readiness._column_width("detail")  # noqa: SLF001 - the guard under test


@pytest.mark.parametrize(
    ("specifier", "verdict"),
    [
        (">=3.9,!=3.13.*,!=3.15.*", ADMITS),
        (">=3.9,!=3.14.0.*,!=3.14.1.*", ADMITS),
        (">=3.9,!=3.14.0.*,!=3.14.*", EXCLUDES),
        (">=3.9,!=3.14.*,!=3.14.0.*", EXCLUDES),
        (">=3.14,<3.14.2,!=3.14.0.*,!=3.14.1.*", EXCLUDES),
    ],
)
def test_several_exclusions_are_merged_before_the_coverage_question_is_asked(specifier: str, verdict: str) -> None:
    """Two adjacent exclusions cover what neither covers alone, and a check that asked them one at a time would miss it.

    The first four are the shapes one exclusion can take against the series: two that
    miss it entirely, two that overlap it without covering it, and the two orders of
    one exclusion swallowing another. A reader that stopped at the bounds would
    answer `admits` for a specifier that admits nothing.

    **The fifth is the only case the merge itself decides**, and without it the whole
    sort-and-merge block was line-covered and behaviour-covered by nothing: every
    other case is spanned by a single exclusion, so replacing the merge with a
    per-range `any(...)` left the suite green. Here neither `!=3.14.0.*` nor
    `!=3.14.1.*` spans `[3.14, 3.14.2)` alone and the two together do -- so an
    unmerged reader answers `admits` for a specifier that admits nothing, and the
    sort key, the merge loop, `_lower_at_most` and `_upper_at_least` are all load
    bearing here rather than merely executed.
    """
    assert admits_series(specifier, series=PYTHON_SERIES).verdict == verdict


@pytest.mark.parametrize(
    "specifier",
    [
        ">=" + ".".join("1" * MAX_RELEASE_SEGMENTS),
        ",".join([">=3.9"] * MAX_CLAUSES),
    ],
)
def test_a_specifier_exactly_at_each_bound_is_read_rather_than_refused(specifier: str) -> None:
    """The accepting side of `MAX_RELEASE_SEGMENTS` and `MAX_CLAUSES`.

    Both are otherwise asserted only from the side that refuses, which leaves a `>`
    that became a `>=` free to record `unknown` for a specifier the product really
    does read -- an `unknown` row that looks exactly like an honest one, which is the
    failure this whole module is written against.
    """
    assert admits_series(specifier, series=PYTHON_SERIES).verdict != UNDECIDABLE


@pytest.mark.parametrize(
    ("specifier", "verdict"),
    [
        (">=3.14,<=3.14", ADMITS),
        (">=3.14,==3.14", ADMITS),
        (">3.14,<=3.14", EXCLUDES),
        (">=3.14,<3.14", EXCLUDES),
    ],
)
def test_a_bound_meeting_its_opposite_turns_on_which_end_is_inclusive(specifier: str, verdict: str) -> None:
    """Where the two bounds meet at one release, and the one determinate negative this collector may reach.

    Every other specifier case here spans a range wide enough to survive a flipped
    inclusivity, so `>=` read as `>` and `>` read as `>=` both passed the suite while
    turning a project *pinned to this very series* into `inferred_incompatible` -- a
    determinate claim that it cannot run on the Python it pinned itself to. The four
    cases meet at `3.14` from each combination of ends, so each operator's own
    inclusivity is load bearing, and with it the tie-break disjuncts in
    `_raise_lower`, `_lower_upper`, `_lower_at_most` and `_upper_at_least`.
    """
    assert admits_series(specifier, series=PYTHON_SERIES).verdict == verdict


# ---------------------------------------------------------------------------
# The judgement: three outcomes, and no path from an absence to a claim.
# ---------------------------------------------------------------------------


def test_metadata_that_admits_the_series_on_both_signals_is_inferred_compatible() -> None:
    """AC 1: a determinate row, naming the signals that said so, and never "verified"."""
    assessed = assess(_declared(">=3.9", THE_CLASSIFIER), series=PYTHON_SERIES)

    assert assessed.state == INFERRED_COMPATIBLE
    assert assessed.deciding_signal == DecidingSignal.BOTH.value
    assert assessed.requires_python == ">=3.9"
    assert assessed.matching_classifier == THE_CLASSIFIER
    assert assessed.detail == ""


def test_a_specifier_alone_can_reach_a_determinate_verdict() -> None:
    """No second signal to disagree with, so the specifier decides and the row says so."""
    assessed = assess(_declared(">=3.9"), series=PYTHON_SERIES)

    assert assessed.state == INFERRED_COMPATIBLE
    assert assessed.deciding_signal == DecidingSignal.REQUIRES_PYTHON.value
    assert assessed.matching_classifier == ""


@pytest.mark.parametrize(
    "classifiers",
    [
        (THE_UMBRELLA_CLASSIFIER,),
        (THE_UMBRELLA_CLASSIFIER, "Programming Language :: Python :: 3 :: Only"),
    ],
)
def test_the_commonest_published_shape_is_inferred_compatible_rather_than_a_disagreement(
    classifiers: tuple[str, ...],
) -> None:
    """`>=3.9` with the umbrella classifier, which is most of PyPI -- and it must not read as `unknown`.

    `Programming Language :: Python :: 3` is a claim *containing* 3.14 rather than an
    enumeration that omitted it, so there is no second signal to disagree with and
    the specifier decides. Counting the umbrella as an enumeration made this shape a
    disagreement, which is `unknown`, which is exactly where `CPM-PY314-S02` spends
    expensive verification -- so the defect ran in the direction this story exists to
    prevent, inflating the bucket the epic is written to keep small. Note the
    asymmetry it produced: `:: 3 :: Only` was already excluded, so the umbrella *with*
    it behaved better than the umbrella alone.
    """
    assessed = assess(_declared(">=3.9", *classifiers), series=PYTHON_SERIES)

    assert assessed.state == INFERRED_COMPATIBLE
    assert assessed.deciding_signal == DecidingSignal.REQUIRES_PYTHON.value
    assert assessed.detail == ""


def test_a_project_declaring_only_the_umbrella_classifier_has_declared_nothing_about_this_python() -> None:
    """The other half of the same correction, on the `detail` a reader is handed.

    With no specifier, a bare umbrella leaves the row `unknown` -- a superset claim
    is not a claim about the series -- and the silence it records is "declared
    nothing", not "enumerated its Pythons and left this one out". The second sentence
    would be false about a project that never named a minor version at all.
    """
    assessed = assess(_declared("", THE_UMBRELLA_CLASSIFIER), series=PYTHON_SERIES)

    assert assessed.state == READINESS_UNKNOWN
    assert assessed.detail == NOTHING_DECLARED_DETAIL
    assert assessed.detail != NO_CLASSIFIER_FOR_SERIES_DETAIL


def test_a_classifier_alone_can_reach_a_determinate_verdict() -> None:
    """The second static signal, which is why this collector reads the source itself.

    `PyPIReleaseSnapshot` stores a specifier and stores no classifiers, so a
    collector that had read the sibling's row instead of the document would have
    lost this branch entirely.
    """
    assessed = assess(_declared("", THE_CLASSIFIER), series=PYTHON_SERIES)

    assert assessed.state == INFERRED_COMPATIBLE
    assert assessed.deciding_signal == DecidingSignal.CLASSIFIER.value
    assert assessed.requires_python == ""


def test_metadata_that_cannot_admit_the_series_is_inferred_incompatible_and_stores_the_specifier() -> None:
    """The one determinate negative, and the specifier verbatim beside it.

    A row claiming a package cannot run on this Python is only argue-able if the
    claim that produced it is on the row, so the specifier is asserted character for
    character rather than merely present.
    """
    assessed = assess(_declared(">=3.9,<3.13"), series=PYTHON_SERIES)

    assert assessed.state == INFERRED_INCOMPATIBLE
    assert assessed.deciding_signal == DecidingSignal.REQUIRES_PYTHON.value
    assert assessed.requires_python == ">=3.9,<3.13"


@pytest.mark.parametrize(
    ("metadata", "detail"),
    [
        (_declared(), NOTHING_DECLARED_DETAIL),
        (_declared("", A_NON_VERSION_CLASSIFIER), NOTHING_DECLARED_DETAIL),
        (_declared("", AN_EARLIER_CLASSIFIER), NO_CLASSIFIER_FOR_SERIES_DETAIL),
    ],
)
def test_a_metadata_silence_is_unknown_and_never_incompatible(metadata: DeclaredMetadata, detail: str) -> None:
    """The single property `CPM-PY314-S01` turns on, asserted from both sides.

    Most projects have not declared 3.14 support. If "declares nothing" read as
    "excludes it", this collector would report most of an inventory as incompatible
    on no evidence and send `CPM-PY314-S02`'s expensive verification exactly where it
    is least warranted -- the opposite of what the story exists to do.

    The two silences carry different details, because a project that enumerated its
    Pythons and left this one out has said something a project that declared nothing
    has not -- and neither of them has said "no".
    """
    assessed = assess(metadata, series=PYTHON_SERIES)

    assert assessed.state == READINESS_UNKNOWN
    assert assessed.state != INFERRED_INCOMPATIBLE
    assert assessed.deciding_signal == ""
    assert assessed.detail == detail


@pytest.mark.parametrize(
    "metadata",
    [
        _declared(">=3.9", AN_EARLIER_CLASSIFIER),
        _declared("<3.13", THE_CLASSIFIER),
    ],
)
def test_two_signals_that_disagree_are_recorded_as_the_disagreement_they_are(metadata: DeclaredMetadata) -> None:
    """Never silently resolved, in either direction.

    Ranking one signal above the other would be this collector picking a winner in a
    claim about somebody else's package -- and it would do it invisibly, in the one
    column a policy pass reads first. Both transcribed columns survive on the row so
    a reviewer can see what disagreed.
    """
    assessed = assess(metadata, series=PYTHON_SERIES)

    assert assessed.state == READINESS_UNKNOWN
    assert assessed.deciding_signal == ""
    assert DISAGREEMENT_DETAIL in assessed.detail
    assert assessed.requires_python == metadata.requires_python


def test_an_unreadable_specifier_is_unknown_with_the_raw_value_preserved_and_the_reason() -> None:
    """The Block If, on the row rather than only in the reading.

    The specifier is what makes the row reviewable, and the reason is what makes the
    shape findable; a row carrying neither would be an absence of information about
    a project that declared something.
    """
    assessed = assess(_declared("===3.14"), series=PYTHON_SERIES)

    assert assessed.state == READINESS_UNKNOWN
    assert assessed.state != INFERRED_INCOMPATIBLE
    assert assessed.requires_python == "===3.14"
    assert UNREADABLE_SPECIFIER_DETAIL in assessed.detail


def test_an_unreadable_specifier_is_unknown_even_where_a_classifier_claims_support() -> None:
    """A classifier cannot overrule a range nobody read.

    Taking the classifier here would answer `inferred_compatible` from a document
    whose only *range* went unread -- a determinate claim resting on half the
    evidence, which is the guess the Block If forbids.
    """
    assessed = assess(_declared("===3.14", THE_CLASSIFIER), series=PYTHON_SERIES)

    assert assessed.state == READINESS_UNKNOWN
    assert assessed.matching_classifier == THE_CLASSIFIER


def test_an_unreadable_specifier_records_the_gap_as_an_event(caplog: pytest.LogCaptureFixture) -> None:
    """ "Record the gap" is an operator-facing event, not only a column nobody aggregates.

    A shape that turns out to be common shows up in a log this way; recorded only on
    the row it would be one detail among ten thousand.
    """
    with caplog.at_level("INFO"):
        assess(_declared(">=1!3.9"), series=PYTHON_SERIES)

    assert any(UNREADABLE_SPECIFIER_EVENT in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    ("detail", "says", "never_says"),
    [
        (IDENTITY_UNRESOLVED_DETAIL, ("unanswered", "release ecosystem"), (READINESS_NOT_APPLICABLE,)),
        (NOTHING_DECLARED_DETAIL, ("neither", "nothing either way"), (INFERRED_INCOMPATIBLE, "unanswered")),
        (NO_CLASSIFIER_FOR_SERIES_DETAIL, ("classifiers", "establishes nothing"), (INFERRED_INCOMPATIBLE,)),
        (DISAGREEMENT_DETAIL, ("disagree", "recorded rather than"), (INFERRED_COMPATIBLE, INFERRED_INCOMPATIBLE)),
        (UNREADABLE_SPECIFIER_DETAIL, ("will not read", "exactly as stated"), (INFERRED_INCOMPATIBLE,)),
        (
            OVERSIZE_SPECIFIER_DETAIL,
            ("too wide", "carries no specifier", "not a negative claim"),
            (INFERRED_INCOMPATIBLE, READINESS_NOT_APPLICABLE),
        ),
        (
            ABSENT_FROM_INDEX_DETAIL,
            ("does not know this project", "absence from the index", "rather than"),
            (INFERRED_INCOMPATIBLE, READINESS_NOT_APPLICABLE),
        ),
    ],
)
def test_each_operator_facing_detail_says_the_thing_it_is_relied_on_to_say(
    detail: str,
    says: tuple[str, ...],
    never_says: tuple[str, ...],
) -> None:
    """Pinned to its words rather than to itself, which is the only way this can fail.

    Every case that reads one of these constants asserts `CONSTANT in row.detail`,
    where the expected value *is* the code under test -- so rewording
    `IDENTITY_UNRESOLVED_DETAIL` to say the question does not *apply* would keep every
    one of them green while inverting the distinction the whole story turns on. These
    are the sentences an operator and `docs/conda-sentinel/operations.md` are handed, so they are
    asserted against their words the way `CLASSIFIER_PREFIX` and the state values
    already are.
    """
    for phrase in says:
        assert phrase in detail
    for phrase in never_says:
        assert phrase not in detail


def test_an_assessment_that_is_not_determinate_may_not_name_a_deciding_signal() -> None:
    """The table's own rule, applied where the value is built.

    The constraint fires inside `bulk_create`, with a message about a column and
    nothing about the branch that produced it; refusing here names the branch.
    """
    with pytest.raises(PythonReadinessAssessmentError):
        Assessment(
            state=READINESS_UNKNOWN,
            requires_python="",
            matching_classifier="",
            deciding_signal=DecidingSignal.BOTH.value,
            detail="",
        )


def test_a_determinate_assessment_must_name_the_signal_that_reached_it() -> None:
    """An inference that cannot say what it inferred from is a claim with no argument."""
    with pytest.raises(PythonReadinessAssessmentError):
        Assessment(
            state=INFERRED_COMPATIBLE,
            requires_python=">=3.9",
            matching_classifier="",
            deciding_signal="",
            detail="",
        )


# ---------------------------------------------------------------------------
# Applicability: the one path to `not_applicable`, and the absence trap beside it.
# ---------------------------------------------------------------------------


def test_only_an_established_pypi_identity_is_a_question_this_collector_asks() -> None:
    """The one spelling of the rule the selection and the locator both rest on."""
    assert asks_about(_identity()) is True
    assert asks_about(_identity(primary_type="PyPI")) is True
    assert asks_about(_identity(primary_type="cran")) is False
    assert asks_about(_identity(primary_type="")) is False
    assert asks_about(_identity(outcome=OutcomeState.UNKNOWN.value)) is False


def test_identity_that_established_no_ecosystem_is_the_only_path_to_not_applicable() -> None:
    """AC 2, and the reason names identity rather than this collector's own judgement."""
    reason = inapplicability_of(_identity(outcome=OutcomeState.NOT_APPLICABLE.value, primary_type="", primary_purl=""))

    assert reason
    assert "identity" in reason
    assert OutcomeState.NOT_APPLICABLE.value in reason


@pytest.mark.parametrize(
    "outcome",
    sorted({member.value for member in MappingOutcome} - {OutcomeState.NOT_APPLICABLE.value}),
)
def test_no_other_mapping_outcome_makes_the_question_inapplicable(outcome: str) -> None:
    """The absence trap, swept over the vocabulary rather than over a list written here.

    `unknown`, `error` and `not_found` are identity having established **nothing**,
    so the compatibility question is unanswered rather than inapplicable -- and
    `established` is the question applying. Parametrized over `MappingOutcome`'s own
    members rather than over a list written here, so an outcome added later is
    *constrained* by this case rather than escaping it: it arrives as a new
    parametrization asserting the question stays applicable. It does not make this
    case fail -- `inapplicability_of` answers nothing for it by construction -- and
    the tripwire for a member that should mean something else is the reviewer reading
    a new green case, not a red one.
    """
    assert inapplicability_of(_identity(outcome=outcome)) == ""


def test_an_established_mapping_for_another_ecosystem_is_not_inapplicable_here() -> None:
    """The one place this collector diverges from `collectors/pypi_release.py`'s identical hook.

    That sibling reads it as "PyPI is not where this package is released", which is
    true of the question *it* asks. Here the question is whether a package is ready
    for a Python, and identity having named a non-Python ecosystem is not identity
    having established that no Python question exists -- and `CPM-PY314-S01` makes the
    mapping's own `not_applicable` the only path to that state.
    """
    assert inapplicability_of(_identity(primary_type="cran")) == ""
    assert pypi_release.inapplicability_of(
        pypi_release.ReleaseIdentity(outcome=ESTABLISHED, primary_type="cran", primary_purl=A_PURL),
    )


# ---------------------------------------------------------------------------
# The hooks, without a database.
# ---------------------------------------------------------------------------


def test_translate_writes_one_row_carrying_the_series_and_the_assessment() -> None:
    """One row and never none: the base reads an empty translation as a broken parser."""
    rows = _collector().translate(
        _payload(json.dumps(_project(requires_python=">=3.9", classifiers=[THE_CLASSIFIER]))),
        package_id=A_PACKAGE,
        observed_at=FIXED_INSTANT,
    )

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, PythonReadinessAssessment)
    assert row.state == INFERRED_COMPATIBLE
    assert row.python_series == series_of(PYTHON_SERIES)
    assert row.observed_at == FIXED_INSTANT
    assert row.package_id == A_PACKAGE
    assert row.source == A_SOURCE
    assert row.deciding_signal == DecidingSignal.BOTH.value


@pytest.mark.parametrize(
    "state",
    [OutcomeState.ERROR, OutcomeState.NOT_FOUND, OutcomeState.NOT_APPLICABLE],
)
def test_a_sentinel_row_carries_the_state_verbatim_and_names_the_series(state: OutcomeState) -> None:
    """`CPM-AD-24`, and the series column the table requires of every row.

    A row that could not say which Python it was about would make an assessment of
    3.14 indistinguishable from `CPM-PY314-S02`'s verified result about the same
    series -- which is the distinction the whole epic exists to keep.
    """
    row = _collector().sentinel_evidence(
        state=state,
        package_id=A_PACKAGE,
        observed_at=FIXED_INSTANT,
        detail="a reason",
    )

    assert isinstance(row, PythonReadinessAssessment)
    assert row.state == state.value
    assert row.python_series == series_of(PYTHON_SERIES)
    assert row.deciding_signal == ""
    assert row.requires_python == ""
    assert row.detail


def test_a_not_found_row_says_the_index_does_not_know_the_project() -> None:
    """The two rows on this table a reader could most plausibly confuse.

    "The index has never heard of this project" and "the project declared nothing
    about this Python" are different facts, and the base's own sentence says neither
    -- so the caveat is appended rather than left to be inferred.
    """
    row = _collector().sentinel_evidence(
        state=OutcomeState.NOT_FOUND,
        package_id=A_PACKAGE,
        observed_at=FIXED_INSTANT,
        detail="the source reports that the resource does not exist",
    )

    assert ABSENT_FROM_INDEX_DETAIL in row.detail


@pytest.mark.parametrize("state", [OutcomeState.OK, OutcomeState.UNKNOWN])
def test_a_sentinel_state_this_collector_has_no_row_shape_for_is_refused_at_the_call(state: OutcomeState) -> None:
    """Refused where the call was wrong rather than at the insert, several frames later.

    `ok` is not in this vocabulary at all, and `unknown` is `translate`'s to write
    with the reason the run actually established -- a sentinel path has no reason of
    that kind, so a blank-detail `unknown` would be an absence of information.
    """
    with pytest.raises(CollectorConfigurationError):
        _collector().sentinel_evidence(
            state=state,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="a reason",
        )


def test_a_sentinel_reason_is_cleaned_and_bounded_rather_than_refused() -> None:
    """`CPM-NFR-3` requires the row, so the reason is shortened rather than raised over.

    The reason reaching this hook is the base's own sentence with a third party's
    exception message inside it; raising over its shape would turn "the source
    failed" into "no row at all".
    """
    row = _collector().sentinel_evidence(
        state=OutcomeState.ERROR,
        package_id=A_PACKAGE,
        observed_at=FIXED_INSTANT,
        detail="x" * (MAX_SENTINEL_DETAIL_CHARACTERS + 10) + "\x00\ud800",
    )

    assert SHORTENED_DETAIL in row.detail
    assert "\x00" not in row.detail
    row.detail.encode("utf-8")


def test_an_instance_no_run_has_reached_remembers_nothing() -> None:
    """The blank a sentinel row carries when no locator was ever built.

    Declared as class attributes rather than left to `__init__`, so a hook reached
    before any run answers a blank rather than an `AttributeError` -- and so the
    `not_applicable` path, which never builds a locator, records an empty `source`
    rather than the previous package's. The *reset between runs* needs the identity
    read and is asserted in the integration tier.
    """
    collector = _collector()

    assert collector._locator == ""  # noqa: SLF001 - the remembered state is the property under test
    assert collector._identity is None  # noqa: SLF001 - as above
    assert collector._identity_package is None  # noqa: SLF001 - as above


def test_the_selection_is_the_two_outcomes_identity_can_answer_for() -> None:
    """A lazy queryset over `identity`, ordered by key and never materialised.

    Asserted as a query rather than as rows, because this tier reads no database:
    what matters is that the selection is over the mapping table, is ordered, and
    carries a `WHERE` -- the whole inventory would be a sweep enqueueing a failed run
    for every package identity has not resolved.
    """
    selected = PythonReadinessCollector.selectable_packages()

    assert selected.model.__name__ == "PackageMapping"  # type: ignore[union-attr]
    assert selected.query.order_by == ("package_id",)  # type: ignore[union-attr]
    assert str(selected.query).count("WHERE")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# The vocabulary: inference is named, and a silence has no determinate value.
# ---------------------------------------------------------------------------


def test_a_row_says_which_python_it_is_about_when_a_reader_prints_it() -> None:
    """An admin list and a debugger both render this, and the series is what tells rows apart.

    Asserted for a saved-looking row and for one carrying nothing, because the second
    is what a debugger meets while a row is being built and a `None` reaching a
    format string there would raise rather than describe.
    """
    described = str(
        PythonReadinessAssessment(
            observed_at=FIXED_INSTANT,
            package_id=A_PACKAGE,
            state=INFERRED_COMPATIBLE,
            python_series=series_of(PYTHON_SERIES),
        ),
    )

    assert series_of(PYTHON_SERIES) in described
    assert INFERRED_COMPATIBLE in described
    assert str(A_PACKAGE) in described
    assert "no package" in str(PythonReadinessAssessment())


def test_the_determinate_values_name_the_inference() -> None:
    """`CPM-FR-14`: inferred and verified compatibility are distinct recorded states.

    `CPM-AD-24` carries a state's value verbatim onto every read surface, so a value
    called `compatible` would appear on a queue beside `CPM-PY314-S02`'s verified
    result and read identically. Asserted as the words rather than as "not ok",
    because a rename to `compatible` would satisfy that weaker claim.
    """
    assert INFERRED_COMPATIBLE == "inferred_compatible"
    assert INFERRED_INCOMPATIBLE == "inferred_incompatible"
    assert "inferred" in INFERRED_COMPATIBLE
    assert "inferred" in INFERRED_INCOMPATIBLE
    assert OutcomeState.OK.value not in {member.value for member in PythonReadinessOutcome}


def test_the_vocabulary_is_the_four_sentinels_plus_the_two_inferred_verdicts() -> None:
    """`CPM-AD-5`: composed by `core.outcomes.outcome_type`, so no sentinel can drift.

    There is deliberately **no** determinate member for a silence: "the metadata said
    nothing" is `unknown`, the sentinel `core` already has, and a value of its own
    would put most of an inventory into a claim nobody made.
    """
    assert {member.value for member in PythonReadinessOutcome} == {
        READINESS_ERROR,
        READINESS_UNKNOWN,
        READINESS_NOT_FOUND,
        READINESS_NOT_APPLICABLE,
        INFERRED_COMPATIBLE,
        INFERRED_INCOMPATIBLE,
    }


def test_the_sentinels_are_the_ones_core_declares() -> None:
    """Reached through the composed type rather than beside it, so a drift fails at import."""
    assert OutcomeState.ERROR.value == READINESS_ERROR
    assert OutcomeState.UNKNOWN.value == READINESS_UNKNOWN
    assert OutcomeState.NOT_FOUND.value == READINESS_NOT_FOUND
    assert OutcomeState.NOT_APPLICABLE.value == READINESS_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Source sweeps: the read this collector does not take, and the constants it restates.
# ---------------------------------------------------------------------------


def _names_in(relative: str) -> set[str]:
    """Return every name, attribute and string literal one module mentions.

    Args:
        relative: The module's path under `src/`.

    Returns:
        The set the sweeps below ask membership of.

    """
    tree = parse(_module(relative))
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    named |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    named |= {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    return named


def test_this_collector_never_reads_the_sibling_evidence_table_that_already_stores_a_specifier() -> None:
    """`CPM-AD-7`, and this is the module where the shortcut is most tempting.

    `PyPIReleaseSnapshot.requires_python` already holds the specifier and reading it
    would be quicker. The exemption list holds exactly one entry, for a collector
    whose question is inherently about another's rows, and this one's is not -- so
    the source is read directly, which is also what makes the *classifiers*
    reachable at all.
    """
    named = _names_in(READINESS_MODULE)

    assert SIBLING_EVIDENCE_MODEL not in named
    assert SIBLING_EVIDENCE_TABLE not in named
    assert "pypi_release" not in named


@pytest.mark.parametrize("relative", [READINESS_MODULE, SPECIFIERS_MODULE])
def test_neither_module_reads_the_clock_or_prints(relative: str) -> None:
    """`CPM-AD-26` and the repository's own bans: time is injected and nothing prints.

    Each token is asserted absent on its own. Written as a disjunction -- "one of the
    two is missing" -- the claim was satisfied by either half, so
    `from datetime import datetime; datetime.now()` passed it. The registry-wide
    sweep in `tests/unit/django_apps/test_clock_audit.py` reaches these modules
    automatically and is the real backstop; what this case owes is an honest local
    claim.
    """
    named = _names_in(relative)

    assert "now" not in named
    assert "timezone" not in named
    assert "print" not in named


def test_the_restated_host_and_purl_grammar_agree_with_the_sibling_that_reads_the_same_source() -> None:
    """Restating them is right under `CPM-AD-7`; nothing else would have compared them.

    `collectors/pypi_release.py` reads the same host with the same purl grammar, and
    this collector spells both again rather than importing them -- so a rename there
    would silently make this collector ask a different question, or none.
    """
    assert PYPI_HOST == pypi_release.PYPI_HOST
    assert PURL_SCHEME == pypi_release.PURL_SCHEME
    assert PURL_TYPE == pypi_release.PURL_TYPE
    assert MAX_DOCUMENT_CHARACTERS == pypi_release.MAX_DOCUMENT_CHARACTERS
    assert REQUIRES_PYTHON_FIELD == pypi_release.REQUIRES_PYTHON_FIELD
    assert INFO_FIELD == pypi_release.INFO_FIELD


def test_the_document_field_names_are_pinned_to_their_literals() -> None:
    """Both tiers build fixtures from these constants, so a rename would keep them green."""
    assert INFO_FIELD == "info"
    assert REQUIRES_PYTHON_FIELD == "requires_python"
    assert CLASSIFIERS_FIELD == "classifiers"


def test_the_specifier_module_imports_no_collector_and_no_model() -> None:
    """A leaf, on the terms `collectors/spdx.py` is one.

    `collectors/models.py` declares `DecidingSignal` as a column's `choices` and the
    collector reads the containment rule beside the decision that uses it, so a type
    bound in either would close an import cycle and fail at start-up.
    """
    imported = {
        node.module
        for node in ast.walk(parse(_module(SPECIFIERS_MODULE)))
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not any(name.startswith("conda_sentinel") for name in imported)


def test_the_collector_module_declares_the_names_it_exports() -> None:
    """`__all__` is the module's contract, and both test tiers import through it."""
    assert set(python_readiness.__all__) <= set(vars(python_readiness))
    assert set(specifiers.__all__) <= set(vars(specifiers))
