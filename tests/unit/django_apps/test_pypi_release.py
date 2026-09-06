"""What the PyPI collector declares, what a locator is, what a document means, and when the question applies.

`CPM-FR-8` is three questions, and only the last needs a run. What a project
document *means* -- which version is latest, when it became installable, what
`Requires-Python` it declares -- is a pure function of a string; so is turning a
purl into the locator that answers it; and so is deciding, from what resolution
recorded, whether PyPI is a question about this package at all. All three are
here with no database, no socket and no clock (`CPM-AD-27`). What needs a run --
the rows, the ledger, the `not_applicable` path end to end, the freshness read --
is in `tests/integration/django_apps/test_pypi_release.py`.

**The declarations are asserted against their derivations rather than against
themselves**, on the terms `tests/unit/django_apps/test_source_release.py` sets:
the target is the cadence times one plus the tolerated misses, the window is
shorter than the cadence, and one collection's worst case fits inside the
inherited Celery soft limit read from the settings module.

No database, no network: nothing here saves a row, no queryset is evaluated, and
every payload is a literal.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.conf import settings

from conda_package_supply_chain_monitor.collectors import agent
from conda_package_supply_chain_monitor.collectors import pypi_release
from conda_package_supply_chain_monitor.collectors import source_release
from conda_package_supply_chain_monitor.collectors.agent import USER_AGENT
from conda_package_supply_chain_monitor.collectors.models import PyPIReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.pypi_release import COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.pypi_release import INFO_FIELD
from conda_package_supply_chain_monitor.collectors.pypi_release import MAX_DOCUMENT_CHARACTERS
from conda_package_supply_chain_monitor.collectors.pypi_release import NO_RELEASE_DETAIL
from conda_package_supply_chain_monitor.collectors.pypi_release import PURL_TYPE
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_HOST
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_CACHE_TTL
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_CADENCE
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_FRESHNESS_TARGET
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_HEADERS
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_OBSERVATION_WINDOW
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_RATE_LIMIT
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_RETRIES
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_TIMEOUT
from conda_package_supply_chain_monitor.collectors.pypi_release import RELEASES_FIELD
from conda_package_supply_chain_monitor.collectors.pypi_release import REQUIRES_PYTHON_FIELD
from conda_package_supply_chain_monitor.collectors.pypi_release import TOLERATED_MISSED_RUNS
from conda_package_supply_chain_monitor.collectors.pypi_release import UNDATED_VERSION_DETAIL
from conda_package_supply_chain_monitor.collectors.pypi_release import UPLOAD_TIME_FIELD
from conda_package_supply_chain_monitor.collectors.pypi_release import VERSION_FIELD
from conda_package_supply_chain_monitor.collectors.pypi_release import PyPIDocumentError
from conda_package_supply_chain_monitor.collectors.pypi_release import PyPILocatorError
from conda_package_supply_chain_monitor.collectors.pypi_release import PyPIReleaseCollector
from conda_package_supply_chain_monitor.collectors.pypi_release import ReleaseIdentity
from conda_package_supply_chain_monitor.collectors.pypi_release import asks_about
from conda_package_supply_chain_monitor.collectors.pypi_release import inapplicability_of
from conda_package_supply_chain_monitor.collectors.pypi_release import project_locator
from conda_package_supply_chain_monitor.collectors.pypi_release import project_name
from conda_package_supply_chain_monitor.collectors.pypi_release import pypi_facts
from conda_package_supply_chain_monitor.collectors.tasks import COLLECT_PYPI_RELEASE_TASK_NAME
from conda_package_supply_chain_monitor.collectors.tasks import collect_pypi_release
from conda_package_supply_chain_monitor.core import transport
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.collection import CONDITIONAL_HEADERS
from conda_package_supply_chain_monitor.core.collection import CollectorConfigurationError
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.queues import Queue
from conda_package_supply_chain_monitor.core.queues import queue_for
from conda_package_supply_chain_monitor.core.transport import MAX_TIMEOUT
from conda_package_supply_chain_monitor.core.transport import worst_case_call_seconds
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from tests.clocks import FIXED_INSTANT
from tests.collectors import recorded_payload
from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse

if TYPE_CHECKING:
    from pathlib import Path

    from conda_package_supply_chain_monitor.core.transport import Payload

#: The module this file's source sweeps are about, relative to `src/`.
PYPI_MODULE: Final[str] = "django_apps/conda_package_supply_chain_monitor/collectors/pypi_release.py"

#: The identity model this collector reads, and the write methods it may not
#: reach for. `CPM-AD-7` says a collector "reads only `identity`", and this one
#: reads it through the mapping row -- so the module may *name* `PackageMapping`
#: and may not write one.
MAPPING_MODEL_NAME: Final[str] = "PackageMapping"
WRITE_METHODS: Final[frozenset[str]] = frozenset(
    {"abulk_create", "acreate", "asave", "bulk_create", "create", "get_or_create", "save", "update_or_create"},
)

#: A purl the cases build locators from, and the locator it produces. Written out
#: rather than composed from the module's own constants, because a locator
#: assembled the same way twice would agree with itself however wrong it was.
A_PURL: Final[str] = "pkg:pypi/Django"
THE_LOCATOR: Final[str] = "https://pypi.org/pypi/django/json"

#: The story's golden example, verbatim.
THE_GOLDEN_PURL: Final[str] = "pkg:pypi/Zope.Interface@6.0?foo=bar#x"
THE_GOLDEN_LOCATOR: Final[str] = "https://pypi.org/pypi/zope-interface/json"

#: The locator a payload claims to have come from, for the document cases.
A_SOURCE: Final[str] = "https://pypi.org/pypi/a-project/json"

#: Two upload instants a document places files at, and the same two as instants.
#: Spelled as the source spells them -- fractional seconds and a `Z` offset.
EARLIER_UPLOAD: Final[str] = "2026-04-11T14:00:00.123456Z"
LATER_UPLOAD: Final[str] = "2026-04-11T14:05:30.000000Z"
EARLIER_INSTANT: Final[datetime] = datetime(2026, 4, 11, 14, 0, 0, 123456, tzinfo=UTC)
LATER_INSTANT: Final[datetime] = datetime(2026, 4, 11, 14, 5, 30, tzinfo=UTC)

#: The facts the ordinary document carries.
A_VERSION: Final[str] = "5.1.2"
A_SPECIFIER: Final[str] = ">=3.10"

#: How much of the inherited soft limit one call may spend -- three quarters, so
#: the claim is "with room for the ledger writes around it" rather than "by a
#: hair".
SOFT_LIMIT_SHARE: Final[float] = 0.75

#: A package key the cases that need one use. This tier never reads a row.
A_PACKAGE: Final[int] = 7

#: The marker `_project` treats as "the source did not send this field at all",
#: as distinct from `None`, which is an explicit JSON `null`.
OMITTED: Final[object] = object()


def _file(uploaded: str | object | None = OMITTED) -> dict[str, Any]:
    """Return one file entry of a release.

    Args:
        uploaded: Its upload time. `OMITTED` leaves the field out; `None` writes
            an explicit JSON `null`.

    Returns:
        The file object a source would list, carrying the one field this
        collector reads and a filename it ignores.

    """
    entry: dict[str, Any] = {"filename": "a-project.whl", UPLOAD_TIME_FIELD: uploaded}
    return {name: value for name, value in entry.items() if value is not OMITTED}


def _project(
    version: str | object | None = A_VERSION,
    requires_python: str | object | None = A_SPECIFIER,
    files: list[Any] | object | None = OMITTED,
    **overrides: Any,
) -> dict[str, Any]:
    """Return one project document, with any field replaced, nulled or omitted.

    Args:
        version: `info.version`.
        requires_python: `info.requires_python`.
        files: The file list under `releases[version]`. `OMITTED` leaves the
            version out of `releases`; `None` writes an explicit `null`.
        **overrides: Top-level fields to add or replace; `OMITTED` omits one.

    Returns:
        The document a source would serve.

    """
    info: dict[str, Any] = {VERSION_FIELD: version, REQUIRES_PYTHON_FIELD: requires_python, "name": "a-project"}
    document: dict[str, Any] = {
        INFO_FIELD: {name: value for name, value in info.items() if value is not OMITTED},
        RELEASES_FIELD: {"1.0.0": [_file(EARLIER_UPLOAD)]},
    }
    if files is not OMITTED and isinstance(version, str):
        document[RELEASES_FIELD][version] = files
    document.update(overrides)
    return {name: value for name, value in document.items() if value is not OMITTED}


def _body(document: dict[str, Any]) -> str:
    """Return the body a source would serve for this document.

    Args:
        document: The project document.

    Returns:
        The JSON body.

    """
    return json.dumps(document)


def _payload(body: str) -> Payload:
    """Return a recorded payload carrying this body.

    Args:
        body: What the source said.

    Returns:
        The `Payload` a transport would have recorded, built through the shared
        helper so this tier and the integration tier are handed the same shape.

    """
    return recorded_payload(source=A_SOURCE, body=body)


def _stopped_clock() -> FixedClock:
    """Return the clock the collector cases inject.

    Returns:
        A `FixedClock` at `tests.clocks.FIXED_INSTANT`.

    """
    return FixedClock(instant=FIXED_INSTANT)


def _pypi_module() -> Path:
    """Return the collector module this file's source sweeps read.

    Returns:
        Its path, resolved from `SRC_ROOT`.

    """
    return SRC_ROOT / PYPI_MODULE


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


# ---------------------------------------------------------------------------
# The declarations, and the arithmetic behind them.
# ---------------------------------------------------------------------------


def test_the_collector_declares_every_value_the_base_checks() -> None:
    """All nine, written out on the class and carrying the module's own constants.

    Compared by *value* rather than by presence, for the reason the upstream
    collector's case gives: a class attribute rebound to the wrong constant
    declares nine names and behaves like something nobody wrote down.
    """
    declared = vars(PyPIReleaseCollector)

    assert PyPIReleaseCollector.name == COLLECTOR_NAME
    assert PyPIReleaseCollector.evidence_model is PyPIReleaseSnapshot
    assert PyPIReleaseCollector.observation_window == PYPI_RELEASE_OBSERVATION_WINDOW
    assert PyPIReleaseCollector.timeout == PYPI_RELEASE_TIMEOUT
    assert PyPIReleaseCollector.retries == PYPI_RELEASE_RETRIES
    assert PyPIReleaseCollector.rate_limit == PYPI_RELEASE_RATE_LIMIT
    assert PyPIReleaseCollector.headers == PYPI_RELEASE_HEADERS
    assert PyPIReleaseCollector.freshness_target == PYPI_RELEASE_FRESHNESS_TARGET
    assert PyPIReleaseCollector.response_cache_ttl == PYPI_RELEASE_CACHE_TTL
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
    } <= set(declared)


def test_the_freshness_target_is_the_arithmetic_open_question_7_settled() -> None:
    """`cadence x (1 + tolerated_missed_runs)`, and strictly greater than the cadence.

    `core/freshness.py` reports stale when `observed_at < now - target`, so a
    target *equal* to the cadence makes every package read stale at exactly the
    moment its next run is due, without a single collection having failed.
    """
    assert PYPI_RELEASE_FRESHNESS_TARGET == PYPI_RELEASE_CADENCE * (1 + TOLERATED_MISSED_RUNS)
    assert PYPI_RELEASE_FRESHNESS_TARGET > PYPI_RELEASE_CADENCE


def test_the_observation_window_cannot_suppress_a_scheduled_run() -> None:
    """Shorter than the cadence, which is the property rather than the halving."""
    assert PYPI_RELEASE_OBSERVATION_WINDOW < PYPI_RELEASE_CADENCE
    assert timedelta(0) < PYPI_RELEASE_OBSERVATION_WINDOW


def test_the_response_cache_outlives_the_cadence() -> None:
    """An entry that expired between runs would make the cache inert.

    This is the collector where that matters most: the project document runs to
    mebibytes for a large project, and the whole value of the cache is that the
    next scheduled collection revalidates it and is answered `304`.
    """
    assert PYPI_RELEASE_CACHE_TTL > PYPI_RELEASE_CADENCE


def test_one_collection_fits_inside_the_inherited_soft_limit_with_room_to_spare() -> None:
    """The bound `core/transport.py` states and now computes.

    Read from the settings module rather than repeated here, so lowering the limit
    there fails this rather than passing quietly; asserted with a margin rather
    than a bare `<`, because the recorder's writes and the evidence write happen
    around the call.
    """
    worst_case = worst_case_call_seconds(timeout=PYPI_RELEASE_TIMEOUT, retries=PYPI_RELEASE_RETRIES)

    assert worst_case <= SOFT_LIMIT_SHARE * settings.CELERY_TASK_SOFT_TIME_LIMIT
    assert PYPI_RELEASE_TIMEOUT <= MAX_TIMEOUT


def test_the_worst_case_arithmetic_has_one_home_and_the_first_collector_re_exports_it() -> None:
    """`CPM-AD-7`: shared pieces move to a shared home, and no collector imports another.

    `worst_case_call_seconds` and the `User-Agent` identity were written in the
    first collector and are needed by the second. They now live in
    `core/transport.py` and `collectors/agent.py`; the first collector re-exports
    them so every existing importer is untouched. Asserted by identity, so a
    second copy that happened to agree today would fail here rather than drift
    tomorrow.
    """
    assert source_release.worst_case_call_seconds is transport.worst_case_call_seconds
    assert source_release.USER_AGENT is agent.USER_AGENT
    assert source_release.distribution_version is agent.distribution_version
    assert source_release.DISTRIBUTION_NAME == agent.DISTRIBUTION_NAME
    assert source_release.PROJECT_URL == agent.PROJECT_URL
    assert source_release.UNKNOWN_VERSION == agent.UNKNOWN_VERSION


def test_the_declared_headers_carry_what_the_source_expects_and_nothing_conditional() -> None:
    """Headers reach the socket only through the base (`CPM-AD-20`, `CPM-AD-27`).

    PyPI asks for an identifying `User-Agent`, and the JSON representation is asked
    for by name. What is not declared is a validator, which the base composes from
    the response cache and refuses at construction.
    """
    lowered = {name.lower(): value for name, value in PYPI_RELEASE_HEADERS.items()}

    assert lowered["user-agent"] == USER_AGENT
    assert lowered["accept"] == "application/json"
    assert set(lowered).isdisjoint({header.lower() for header in CONDITIONAL_HEADERS})


def test_the_declared_allowance_is_a_courtesy_bound_the_base_can_enforce() -> None:
    """PyPI publishes no ceiling, so the declaration has to be one this product chose and can meet.

    Two things worth pinning about a number nobody stated: that a single
    collection fits inside it -- an allowance smaller than `1 + retries` would
    refuse every call -- and that the window it is counted over is a whole number
    of seconds the limiter can key on.
    """
    assert PYPI_RELEASE_RATE_LIMIT.calls >= 1 + PYPI_RELEASE_RETRIES
    assert PYPI_RELEASE_RATE_LIMIT.per >= timedelta(seconds=1)


def test_the_collector_is_constructed_from_its_declarations_alone() -> None:
    """The base's nine refusals, run against the real class rather than a fixture."""
    collector = PyPIReleaseCollector(clock=_stopped_clock())

    try:
        assert collector.request_cost == 1 + PYPI_RELEASE_RETRIES
        assert PYPI_RELEASE_RATE_LIMIT.calls >= collector.request_cost
    finally:
        collector.close()


def test_the_task_name_routes_to_the_collect_queue() -> None:
    """`cpm.collect.*` is what puts external I/O on the `collect` queue (`R-11`).

    The Celery binding is asserted too: the constant is what routes, and a task
    registered under a name the constant does not spell would route nowhere.
    """
    assert queue_for(COLLECT_PYPI_RELEASE_TASK_NAME) == Queue.COLLECT
    assert COLLECT_PYPI_RELEASE_TASK_NAME.endswith(COLLECTOR_NAME)
    assert collect_pypi_release.name == COLLECT_PYPI_RELEASE_TASK_NAME


# ---------------------------------------------------------------------------
# The locator (`project_name`, `project_locator`).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("purl", "expected"),
    [
        (A_PURL, "django"),
        (THE_GOLDEN_PURL, "zope-interface"),
        ("pkg:pypi/Foo_Bar@1.0?x=y#sub", "foo-bar"),
        ("pkg:pypi/typing--extensions", "typing-extensions"),
        ("pkg:pypi/a.b_c-d", "a-b-c-d"),
        ("pkg:pypi/foo%2Dbar", "foo-bar"),
        ("pkg:pypi/Foo%5FBar", "foo-bar"),
        ("PKG:PyPI/Django", "django"),
        ("pkg://pypi/django", "django"),
        ("  pkg:pypi/django  ", "django"),
        ("pkg:pypi/django@", "django"),
        ("pkg:pypi/django?", "django"),
    ],
    ids=[
        "plain",
        "golden-example",
        "version-qualifiers-subpath",
        "doubled-hyphen",
        "mixed-separators",
        "percent-encoded-hyphen",
        "percent-encoded-underscore",
        "mixed-case-scheme-and-type",
        "double-slash-after-scheme",
        "surrounded-by-space",
        "empty-version",
        "empty-qualifiers",
    ],
)
def test_every_spelling_of_one_project_reaches_one_name(purl: str, expected: str) -> None:
    """PEP 503: PyPI treats these as one project, and so must every key built from the result.

    A resolution writes whatever purl it derived, and `Zope.Interface`,
    `zope_interface` and `zope-interface` are one project to the index. Reading
    them as three would mean three cache entries, three spellings of `source` and
    three observation histories for one package. The version, qualifiers and
    subpath are dropped because the question is "what is latest", not "what is
    this version"; the name is percent-decoded first because a purl encodes what
    a name cannot carry raw.
    """
    assert project_name(purl) == expected


def test_the_golden_example_reaches_the_golden_locator() -> None:
    """The story's own example, verbatim, and the anti-vacuity half of the case above.

    Every case above compares against an expected *name*; this one reconciles the
    whole locator against the module's declared host and the JSON endpoint's
    shape, so a constant that was wrong would fail here rather than agree with
    itself.
    """
    assert project_locator(THE_GOLDEN_PURL) == THE_GOLDEN_LOCATOR
    assert project_locator(A_PURL) == THE_LOCATOR
    assert THE_LOCATOR.startswith(f"https://{PYPI_HOST}/pypi/")
    assert THE_LOCATOR.endswith("/json")


@pytest.mark.parametrize(
    "purl",
    [
        "",
        "   ",
        "pypi/django",
        "django",
        "npm:django",
        "pkg:npm/django",
        "pkg:/django",
        "pkg:pypi/a-namespace/django",
        "pkg:pypi/",
        "pkg:pypi",
        "pkg:pypi/-django",
        "pkg:pypi/django-",
        "pkg:pypi/foo%20bar",
        "pkg:pypi/f%C3%BCr",
        "pkg:pypi/@1.0",
        "pkg:pypi/.",
        "pkg:pypi/..",
    ],
    ids=[
        "blank",
        "whitespace",
        "no-scheme",
        "bare-name",
        "another-scheme",
        "another-type",
        "empty-type",
        "namespace",
        "no-name",
        "type-only",
        "leading-hyphen",
        "trailing-hyphen",
        "space-in-name",
        "non-ascii",
        "version-only",
        "dot",
        "dot-dot",
    ],
)
def test_a_purl_that_is_not_a_readable_pypi_project_is_refused(purl: str) -> None:
    """Refused rather than guessed at, and refused where the answer already exists.

    Every one of these could be turned into *some* locator by enough string
    surgery, and every such locator would be a request aimed at something nobody
    established (`CPM-FR-1`). The two relative references are the ones worth
    naming: PEP 503 collapses `.` and `..` to `-`, which the name grammar then
    refuses -- so a purl that would have navigated the locator's path is refused
    by the normalisation rather than by luck.
    """
    with pytest.raises(PyPILocatorError):
        project_locator(purl)


def test_a_purl_that_is_not_a_string_is_refused_rather_than_crashing() -> None:
    """The column is a `CharField` and the read is a `values_list`, but the guard is stated anyway.

    A `None` reaching `str.strip` would be an `AttributeError` several frames
    from the row that was wrong; a refusal names the purl and the rule.
    """
    with pytest.raises(PyPILocatorError, match="primary_purl"):
        project_name(None)  # type: ignore[arg-type]


def test_the_refusals_name_the_purl_they_are_about() -> None:
    """A failure an operator can act on names what was being read."""
    with pytest.raises(PyPILocatorError, match=re.escape("pkg:npm/django")):
        project_name("pkg:npm/django")


def test_a_locator_wider_than_the_source_column_is_refused_and_one_that_fits_is_not() -> None:
    """`R-5`'s parity gap, closed for the locator as it is for the two other text columns.

    `Package.primary_purl` is as wide as `PyPIReleaseSnapshot.source`, and the
    locator adds a host and an endpoint around the name -- so a valid purl near
    the width builds a locator PostgreSQL refuses at insert, after the call was
    spent, and SQLite stores. Both sides of the boundary are asserted: the widest
    locator the column holds passes, and one character more is refused before
    the window or the allowance is reached.
    """
    width = PyPIReleaseSnapshot._meta.get_field("source").max_length  # noqa: SLF001 - Django's own public-by-convention API
    assert width is not None
    overhead = len(project_locator("pkg:pypi/a")) - 1

    widest = project_locator(f"pkg:pypi/{'a' * (width - overhead)}")
    assert len(widest) == width

    with pytest.raises(PyPILocatorError, match=str(width)):
        project_locator(f"pkg:pypi/{'a' * (width - overhead + 1)}")


# ---------------------------------------------------------------------------
# Applicability (`inapplicability_of`).
# ---------------------------------------------------------------------------


def test_an_established_pypi_identity_is_a_question_this_collector_asks() -> None:
    """AC 1's precondition, read from identity: `established` and `pypi`, in any case."""
    assert asks_about(_identity())
    assert asks_about(_identity(primary_type="PyPI"))
    assert inapplicability_of(_identity()) == ""
    assert inapplicability_of(_identity(primary_type="PyPI")) == ""


def test_an_established_mapping_with_a_blank_type_is_neither_asked_nor_declared_inapplicable() -> None:
    """An inconsistent identity row is refused, not recorded as either kind of observation.

    `established` says a release ecosystem was found; a blank `primary_type` says
    none was named. A row saying both is a resolution defect, and turning it into
    a `not_applicable` observation would write a fact about the package that the
    row does not support. The hook says nothing, `asks_about` says no, and
    `source_for` refuses.
    """
    inconsistent = _identity(primary_type="", primary_purl="")

    assert not asks_about(inconsistent)
    assert inapplicability_of(inconsistent) == ""


def test_a_mapping_recorded_not_applicable_is_not_a_question_and_says_why() -> None:
    """AC 3, decided where `CPM-FR-1` says it was decided: by resolution.

    "A package whose type makes a mapping inapplicable records `not_applicable`
    for that mapping" -- so the collector reads that answer rather than inferring
    one from a name, and the reason it hands the base names the recorded outcome.
    """
    reason = inapplicability_of(_identity(outcome=OutcomeState.NOT_APPLICABLE.value, primary_type="", primary_purl=""))

    assert reason != ""
    assert OutcomeState.NOT_APPLICABLE.value in reason


def test_a_mapping_established_for_another_ecosystem_is_not_a_question_and_names_it() -> None:
    """AC 3's other route: resolution did establish a release ecosystem, and it is not PyPI."""
    reason = inapplicability_of(_identity(primary_type="npm", primary_purl="pkg:npm/left-pad"))

    assert reason != ""
    assert "'npm'" in reason
    assert PURL_TYPE in reason


@pytest.mark.parametrize(
    "outcome",
    [OutcomeState.UNKNOWN.value, OutcomeState.NOT_FOUND.value, OutcomeState.ERROR.value],
)
def test_an_unresolved_mapping_is_neither_applicable_nor_inapplicable(outcome: str) -> None:
    """ "Resolution has not decided" is not "does not apply", and the two must stay apart.

    Answering a reason here would turn every unresolved package into a
    `not_applicable` observation nobody made -- the guess `CPM-FR-1` forbids. So
    the hook says nothing, and `source_for` is where the refusal lands: a `failed`
    run and no row, on the terms `SourceLocatorError` set in `CPM-CURRENCY-S01`.
    """
    assert inapplicability_of(_identity(outcome=outcome, primary_type="", primary_purl="")) == ""


# ---------------------------------------------------------------------------
# The project document (`pypi_facts`).
# ---------------------------------------------------------------------------


def test_a_project_document_records_its_latest_version_its_date_and_its_specifier() -> None:
    """AC 1: the four facts, from the one document that carries them all.

    `released_at` is the *earliest* upload instant among the latest version's
    files -- the moment the version became installable -- so the later file here
    is what the case exists to ignore.
    """
    facts = pypi_facts(_body(_project(files=[_file(LATER_UPLOAD), _file(EARLIER_UPLOAD)])), source=A_SOURCE)

    assert facts.state == OutcomeState.OK
    assert facts.latest_version == A_VERSION
    assert facts.released_at == EARLIER_INSTANT
    assert facts.requires_python == A_SPECIFIER
    assert facts.detail == ""
    assert facts.source == A_SOURCE


@pytest.mark.parametrize(
    "files",
    [[], OMITTED, None],
    ids=["empty-list", "version-absent-from-releases", "explicit-null"],
)
def test_a_latest_version_with_no_files_is_recorded_undated_and_says_so(files: list[Any] | object | None) -> None:
    """The version is a fact PyPI stated; the date is one it did not.

    A row that is `ok` with no `released_at` is permitted by the table's own
    constraint precisely for this case, and `detail` says why the date is missing
    rather than leaving a reader to wonder whether the collector forgot.
    """
    facts = pypi_facts(_body(_project(files=files)), source=A_SOURCE)

    assert facts.state == OutcomeState.OK
    assert facts.latest_version == A_VERSION
    assert facts.released_at is None
    assert facts.detail == UNDATED_VERSION_DETAIL


def test_a_document_with_no_releases_at_all_is_still_a_version() -> None:
    """`releases` may be absent entirely, and the version stands."""
    facts = pypi_facts(_body(_project(**{RELEASES_FIELD: OMITTED})), source=A_SOURCE)

    assert facts.state == OutcomeState.OK
    assert facts.released_at is None
    assert facts.detail == UNDATED_VERSION_DETAIL


@pytest.mark.parametrize(
    "requires_python",
    [None, OMITTED, "", "   "],
    ids=["explicit-null", "omitted", "empty", "whitespace"],
)
def test_a_project_declaring_no_requires_python_records_a_blank(requires_python: str | object | None) -> None:
    """Blank means missing (PRD Appendix A.1), and a project may legitimately declare none."""
    facts = pypi_facts(_body(_project(requires_python=requires_python)), source=A_SOURCE)

    assert facts.state == OutcomeState.OK
    assert facts.requires_python == ""


def test_a_specifier_is_stored_trimmed_and_otherwise_as_the_project_spelled_it() -> None:
    """Surrounding whitespace goes and nothing else does.

    No normalisation of the specifier itself -- comparing it against an
    interpreter is a policy pass (`CPM-AD-8`) -- but a stored value padded with
    whitespace would break every later comparison for no fact the source stated,
    so the trim is the one liberty taken, and the internal spelling survives.
    """
    facts = pypi_facts(_body(_project(requires_python="  >=3.8, <4  ")), source=A_SOURCE)

    assert facts.requires_python == ">=3.8, <4"


def test_a_padded_version_is_stored_trimmed_and_still_dated_from_its_files() -> None:
    """`releases` is keyed by whatever `info.version` spelled, padding included.

    The row stores the trimmed version, and the files are looked up by the
    trimmed key first and by the raw spelling when that finds nothing -- so a
    source that padded its own version does not produce an `ok` row that dates
    nothing for a version whose files are right there under the padded key.
    """
    padded = f"  {A_VERSION}  "
    document = _project(version=padded, files=OMITTED)
    document[RELEASES_FIELD][padded] = [_file(EARLIER_UPLOAD)]

    facts = pypi_facts(_body(document), source=A_SOURCE)

    assert facts.latest_version == A_VERSION
    assert facts.released_at == EARLIER_INSTANT
    assert facts.detail == ""


@pytest.mark.parametrize(
    "version",
    [None, OMITTED, "", "   "],
    ids=["explicit-null", "omitted", "empty", "whitespace"],
)
def test_a_document_naming_no_version_is_not_found_and_says_why(version: str | object | None) -> None:
    """A `200` whose `info.version` is blank is an answer, and the honest row is the informative negative.

    Every other fact is blanked with it -- a `not_found` row carrying a specifier
    would be claiming to have observed metadata about a release that does not
    exist, and the table's constraint refuses exactly that.
    """
    facts = pypi_facts(_body(_project(version=version)), source=A_SOURCE)

    assert facts.state == OutcomeState.NOT_FOUND
    assert facts.latest_version == ""
    assert facts.released_at is None
    assert facts.requires_python == ""
    assert facts.detail == NO_RELEASE_DETAIL


@pytest.mark.parametrize(
    "uploaded",
    [OMITTED, None, "", "   ", "not-a-date", "2026-04-11T14:00:00"],
    ids=["omitted", "explicit-null", "empty", "whitespace", "unparseable", "naive"],
)
def test_a_file_whose_upload_time_is_unusable_dates_nothing_and_the_others_still_may(
    uploaded: str | object | None,
) -> None:
    """Missing rather than fatal, and never invented.

    A file this collector cannot date cannot be the earliest, so it is passed over
    and the file it can date is the answer. Assuming an instant for the naive one
    in particular would write a date shifted by a guess into a row nothing may
    correct (`CPM-AD-26`).
    """
    facts = pypi_facts(_body(_project(files=[_file(uploaded), _file(LATER_UPLOAD)])), source=A_SOURCE)

    assert facts.state == OutcomeState.OK
    assert facts.released_at == LATER_INSTANT
    assert facts.detail == ""


def test_a_version_whose_every_file_is_undated_is_recorded_undated() -> None:
    """The anti-vacuity half of the case above: the pass-over is a pass-over, not a default."""
    facts = pypi_facts(_body(_project(files=[_file("not-a-date"), _file(None)])), source=A_SOURCE)

    assert facts.released_at is None
    assert facts.detail == UNDATED_VERSION_DETAIL


@pytest.mark.parametrize(
    "body",
    ["", "not json", "[]", '["info"]', "42", '"a string"', "null"],
    ids=["empty", "not-json", "list", "list-of-strings", "number", "string", "null"],
)
def test_a_document_that_is_not_an_object_is_refused(body: str) -> None:
    """Refused rather than read for whatever still parses.

    The base answers the refusal by writing an `error` row and re-raising, so the
    run is on the record either way.
    """
    with pytest.raises(PyPIDocumentError):
        pypi_facts(body, source=A_SOURCE)


@pytest.mark.parametrize(
    "document",
    [
        {},
        {INFO_FIELD: None},
        {INFO_FIELD: "5.1.2"},
        {INFO_FIELD: [A_VERSION]},
        _project(version=5),
        _project(version=[A_VERSION]),
        _project(requires_python=3.10),
        _project(requires_python={"min": "3.10"}),
        _project(**{RELEASES_FIELD: []}),
        _project(**{RELEASES_FIELD: "5.1.2"}),
        _project(files="2026-04-11"),
        _project(files={UPLOAD_TIME_FIELD: EARLIER_UPLOAD}),
        _project(files=["2026-04-11T14:00:00Z"]),
        _project(files=[_file(1_760_000_000)]),
        _project(files=[_file({"at": EARLIER_UPLOAD})]),
    ],
    ids=[
        "no-info",
        "info-null",
        "info-string",
        "info-list",
        "version-number",
        "version-list",
        "specifier-number",
        "specifier-object",
        "releases-list",
        "releases-string",
        "files-string",
        "files-object",
        "file-string",
        "upload-time-number",
        "upload-time-object",
    ],
)
def test_a_document_whose_shape_has_changed_is_refused(document: dict[str, Any]) -> None:
    """One rule for every field this collector reads: the wrong *type* is the shape changing.

    A date that is a string this collector cannot read is one file's problem and
    is treated as missing; a date that is a number is a source this collector no
    longer understands, and reading past it would record a latest version chosen
    from a fragment, permanently.
    """
    with pytest.raises(PyPIDocumentError):
        pypi_facts(_body(document), source=A_SOURCE)


def test_a_version_wider_than_its_column_is_refused_rather_than_truncated() -> None:
    """`R-5`'s parity gap, closed where the value enters.

    `max_length` is a constraint on PostgreSQL and a suggestion on SQLite, so an
    over-long version is a stored row on a developer's machine and a failed run in
    the gate.
    """
    width = PyPIReleaseSnapshot._meta.get_field("latest_version").max_length  # noqa: SLF001 - Django's own public-by-convention API
    assert width is not None

    with pytest.raises(PyPIDocumentError, match="characters"):
        pypi_facts(_body(_project(version="9" * (width + 1))), source=A_SOURCE)


def test_a_specifier_wider_than_its_column_is_refused_rather_than_truncated() -> None:
    """The same bound on the second text column, which is narrower and so easier to overflow."""
    width = PyPIReleaseSnapshot._meta.get_field("requires_python").max_length  # noqa: SLF001 - Django's own public-by-convention API
    assert width is not None

    with pytest.raises(PyPIDocumentError, match="characters"):
        pypi_facts(_body(_project(requires_python=">=3." + "9" * width)), source=A_SOURCE)


def test_a_document_larger_than_the_ceiling_is_refused_before_it_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker has a sixty-second soft limit, and the decode is where a huge body would spend it (`CPM-AD-9`).

    The ceiling is high because the project document is genuinely large -- it
    lists every file of every release -- and it exists because a source can
    always serve something larger still. The bound is lowered for the case rather
    than met, so the suite does not allocate thirty-two mebibytes to prove a
    comparison; the function reads the module constant at call time, and the
    message is asserted to name the bound it was refused against.
    """
    small_bound = 64
    monkeypatch.setattr(pypi_release, "MAX_DOCUMENT_CHARACTERS", small_bound)

    with pytest.raises(PyPIDocumentError, match=rf"at most {small_bound}\b"):
        pypi_facts("{" + " " * small_bound, source=A_SOURCE)

    assert small_bound < MAX_DOCUMENT_CHARACTERS


def test_a_deeply_nested_document_is_refused_rather_than_crashing_the_worker() -> None:
    """`json.loads` recurses per level, and raises `RecursionError` rather than a decode error."""
    with pytest.raises(PyPIDocumentError):
        pypi_facts("[" * 200_000, source=A_SOURCE)


def test_the_refusals_name_the_source_they_are_about() -> None:
    """A failure an operator can act on names what was being read."""
    with pytest.raises(PyPIDocumentError, match=re.escape(A_SOURCE)):
        pypi_facts("not json", source=A_SOURCE)


# ---------------------------------------------------------------------------
# The rows (`translate`, `sentinel_evidence`, `__str__`).
# ---------------------------------------------------------------------------


def test_a_translated_row_carries_the_facts_and_the_instant_it_was_handed() -> None:
    """One row, stamped with *this* observation's moment (`CPM-AD-7`), with the locator on it."""
    collector = PyPIReleaseCollector(clock=_stopped_clock())
    try:
        rows = collector.translate(
            _payload(_body(_project(files=[_file(EARLIER_UPLOAD)]))),
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
        )
    finally:
        collector.close()

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, PyPIReleaseSnapshot)
    assert row.observed_at == FIXED_INSTANT
    assert row.package_id == A_PACKAGE
    assert row.source == A_SOURCE
    assert row.state == OutcomeState.OK.value
    assert row.latest_version == A_VERSION
    assert row.released_at == EARLIER_INSTANT
    assert row.requires_python == A_SPECIFIER


def test_translation_never_returns_nothing() -> None:
    """A document naming no version is a `not_found` row, not an empty translation."""
    collector = PyPIReleaseCollector(clock=_stopped_clock())
    try:
        rows = collector.translate(
            _payload(_body(_project(version=None))), package_id=A_PACKAGE, observed_at=FIXED_INSTANT
        )
    finally:
        collector.close()

    assert len(rows) == 1
    assert rows[0].state == OutcomeState.NOT_FOUND.value  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "state",
    [OutcomeState.ERROR, OutcomeState.NOT_FOUND, OutcomeState.NOT_APPLICABLE],
    ids=lambda state: state.value,
)
def test_a_sentinel_row_carries_the_state_and_no_fact(state: OutcomeState) -> None:
    """Three shapes, one per sentinel the base may ask for, and every fact absent.

    `not_applicable` is the one `CPM-CURRENCY-S01`'s collector refuses and this one
    shapes, because this is the first collector whose question can fail to apply.
    The `detail` is carried verbatim on every one of them: a `not_found` from PyPI
    needs no caveat, and a `not_applicable` carries the reason the collector gave.
    The locator is blank on a fresh instance -- no `source_for` has answered --
    which is what a `not_applicable` row records.
    """
    collector = PyPIReleaseCollector(clock=_stopped_clock())
    try:
        row = collector.sentinel_evidence(
            state=state,
            package_id=A_PACKAGE,
            observed_at=FIXED_INSTANT,
            detail="a reason",
        )
    finally:
        collector.close()

    assert isinstance(row, PyPIReleaseSnapshot)
    assert row.state == state.value
    assert row.observed_at == FIXED_INSTANT
    assert row.package_id == A_PACKAGE
    assert row.source == ""
    assert row.latest_version == ""
    assert row.released_at is None
    assert row.requires_python == ""
    assert row.detail == "a reason"


@pytest.mark.parametrize("state", [OutcomeState.OK, OutcomeState.UNKNOWN], ids=lambda state: state.value)
def test_a_sentinel_state_this_collector_has_no_row_for_is_refused(state: OutcomeState) -> None:
    """Refused at the call rather than at the insert, which is where it would land.

    `ok` because a row carrying it and no version is refused by the table's own
    constraint; `unknown` because it is what a package with *no* row reads as, and
    writing it would be recording "we have not looked" as an observation.
    """
    collector = PyPIReleaseCollector(clock=_stopped_clock())
    try:
        with pytest.raises(CollectorConfigurationError, match=state.value):
            collector.sentinel_evidence(
                state=state,
                package_id=A_PACKAGE,
                observed_at=FIXED_INSTANT,
                detail="a reason",
            )
    finally:
        collector.close()


def test_an_unsaved_snapshot_renders_its_absences_rather_than_raising() -> None:
    """A `__str__` that raises is what a failure message would have been."""
    rendered = str(PyPIReleaseSnapshot())

    # "no version" rather than "no release": every sentinel row lacks a version,
    # and a `not_applicable` row is not a claim that nothing was released.
    assert "no version" in rendered
    assert "no release" not in rendered
    assert "no package" in rendered
    assert "never" in rendered


def test_a_saved_snapshots_rendering_names_what_it_observed() -> None:
    """The anti-vacuity half: the placeholders are placeholders rather than the answer."""
    rendered = str(
        PyPIReleaseSnapshot(
            observed_at=FIXED_INSTANT,
            package_id=A_PACKAGE,
            state=OutcomeState.OK.value,
            latest_version=A_VERSION,
        ),
    )

    assert A_VERSION in rendered
    assert str(A_PACKAGE) in rendered
    assert OutcomeState.OK.value in rendered
    assert FIXED_INSTANT.isoformat() in rendered


# ---------------------------------------------------------------------------
# The module's own source.
# ---------------------------------------------------------------------------


def test_the_collector_module_writes_no_row_of_any_kind() -> None:
    """`CPM-AD-7` and `CPM-AD-14`: this collector reads `identity` and writes evidence through the base."""
    tree = parse(_pypi_module())
    written = sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted_name(node.func).rpartition(".")[2] in WRITE_METHODS
    )

    assert written == [], f"the collector reaches a table directly at lines {written}"


def test_the_collector_module_reads_the_mapping_row_it_is_allowed_to_read() -> None:
    """The anti-vacuity half: a module that named no model would sweep clean.

    `CPM-AD-7` is "a collector writes its own evidence table and reads only
    `identity`", and this collector's read is the `release_ecosystem` mapping row
    joined to the two `Package` columns it owns. The mapping model is named; the
    package's columns are reached through the join and never as a model of their
    own, which is what keeps the read to the columns this collector is about.
    """
    named = {node.id for node in ast.walk(parse(_pypi_module())) if isinstance(node, ast.Name)}

    assert MAPPING_MODEL_NAME in named
    assert "Package" not in named


def test_the_collector_module_opens_no_transaction_of_its_own() -> None:
    """The per-package transaction is the base's, around the evidence write (`CPM-AD-23`)."""
    tree = parse(_pypi_module())
    opened = sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted_name(node.func).endswith("transaction.atomic")
    )

    assert opened == []


def test_the_collector_module_imports_no_other_collector() -> None:
    """`CPM-AD-7`: "never imports another collector", asserted rather than assumed.

    The shared pieces this collector needs -- the `User-Agent` identity, the
    worst-case arithmetic -- were moved to shared homes so that this assertion
    could be true; a later edit that reached for `source_release` for convenience
    would fail here.
    """
    imported = {
        node.module
        for node in ast.walk(parse(_pypi_module()))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(module.endswith((".source_release", ".tasks")) for module in imported), imported
    assert any(module.endswith(".collectors.agent") for module in imported)
