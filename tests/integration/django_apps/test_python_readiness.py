"""Static readiness against real tables: the three outcomes, the two absences, and the constraints.

`CPM-PY314-S01` asks for three things a row can say about a project's declared
metadata -- it admits this Python, it cannot admit it, or it said nothing either
way -- plus the two rows identity decides. Every one of them is only true or false
once a run exists, which is why this module sits beside
`tests/unit/django_apps/test_python_readiness.py`: the specifier grammar, the
document reader, the judgement and the declarations are decided before a run does,
and are asserted there.

**The property this story turns on is proved end to end here.** A project that
declared nothing produces an `unknown` row -- not `inferred_incompatible` -- and the
row carries the detail saying which silence it is. That is the case
`CPM-PY314-S02` depends on: verification is spent where this table says it is worth
spending, and a table that read silence as a negative would send it everywhere it is
least warranted.

**Both absence traps are proved from both ends.** A package whose release-ecosystem
mapping is `not_applicable` produces AC 2's row with no call made, no allowance
asked and no cache read -- the recording fakes are the only way to show the
negatives. A package whose mapping is `unknown`, `error` or `not_found` produces
**no** `not_applicable` row at all: the run is refused, the ledger says so in words
that call the question unanswered, and the selection never offered the package in
the first place.

**The constraints are asserted against a real backend rather than against the
collector's own discipline.** `readiness_signal_present_exactly_when_inferred` is
asserted from both sides, `readiness_not_applicable_states_its_reason` from the one
that matters, and `readiness_names_the_series_it_assessed` on a row that would
otherwise look ordinary. SQLite enforces `CHECK` constraints; `pixi run
gate-postgres` runs the same cases against `postgres:17`.

**No socket is opened.** Every case substitutes the transport at the base's seam.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction.
`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction

from conda_sentinel.collectors import tasks as collector_tasks
from conda_sentinel.collectors.models import READINESS_REASON_CONSTRAINT
from conda_sentinel.collectors.models import READINESS_SERIES_CONSTRAINT
from conda_sentinel.collectors.models import READINESS_SIGNAL_CONSTRAINT
from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.outcomes import INFERRED_COMPATIBLE
from conda_sentinel.collectors.outcomes import INFERRED_INCOMPATIBLE
from conda_sentinel.collectors.outcomes import READINESS_UNKNOWN
from conda_sentinel.collectors.python_readiness import ABSENT_FROM_INDEX_DETAIL
from conda_sentinel.collectors.python_readiness import COLLECTOR_NAME
from conda_sentinel.collectors.python_readiness import DISAGREEMENT_DETAIL
from conda_sentinel.collectors.python_readiness import IDENTITY_UNRESOLVED_DETAIL
from conda_sentinel.collectors.python_readiness import NO_CLASSIFIER_FOR_SERIES_DETAIL
from conda_sentinel.collectors.python_readiness import NOTHING_DECLARED_DETAIL
from conda_sentinel.collectors.python_readiness import PURL_TYPE
from conda_sentinel.collectors.python_readiness import PYTHON_SERIES
from conda_sentinel.collectors.python_readiness import READINESS_FRESHNESS_TARGET
from conda_sentinel.collectors.python_readiness import READINESS_HEADERS
from conda_sentinel.collectors.python_readiness import UNREADABLE_SPECIFIER_DETAIL
from conda_sentinel.collectors.python_readiness import PythonReadinessCollector
from conda_sentinel.collectors.python_readiness import PythonReadinessDocumentError
from conda_sentinel.collectors.python_readiness import PythonReadinessIdentityError
from conda_sentinel.collectors.python_readiness import project_locator
from conda_sentinel.collectors.specifiers import DecidingSignal
from conda_sentinel.collectors.specifiers import classifier_for
from conda_sentinel.collectors.specifiers import series_of
from conda_sentinel.collectors.tasks import collect_python_readiness
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.freshness import UNOBSERVED_STATUS
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.runs import RunLedgerError
from conda_sentinel.core.runs import RunState
from conda_sentinel.core.transport import TransportError
from conda_sentinel.identity.models import ESTABLISHED
from conda_sentinel.identity.models import MappingKind
from conda_sentinel.identity.models import Package
from conda_sentinel.identity.models import PackageMapping
from tests.clocks import FIXED_INSTANT
from tests.collectors import AN_ETAG
from tests.collectors import FixedLimiter
from tests.collectors import RecordedTransport
from tests.collectors import RecordingResponseCache
from tests.collectors import cached_response
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from conda_sentinel.core.collection import CollectionResult

#: The purl the packages in this module are resolved to, and the locator it
#: produces. Derived rather than written out: a case here is about what a *run*
#: does with a locator, and the unit tier is where its spelling is pinned.
A_PURL: Final[str] = "pkg:pypi/Django"
THE_LOCATOR: Final[str] = project_locator(A_PURL)

#: The classifier that names the assessed series, and one that names an earlier
#: one.
THE_CLASSIFIER: Final[str] = classifier_for(PYTHON_SERIES)
AN_EARLIER_CLASSIFIER: Final[str] = "Programming Language :: Python :: 3.12"

#: The two specifiers the determinate cases turn on: one that admits the series
#: and one that cannot.
AN_ADMITTING_SPECIFIER: Final[str] = ">=3.9"
AN_EXCLUDING_SPECIFIER: Final[str] = ">=3.9,<3.13"

#: A specifier this product will not read as a containment question, on the terms
#: `CPM-SECURITY-S06` establishes: PEP 440's arbitrary equality compares strings.
AN_UNREADABLE_SPECIFIER: Final[str] = "===3.14"

#: How many rows the cases that write twice expect. Named because `PLR2004` is
#: right about a bare number in an assertion.
TWO_ROWS: Final[int] = 2

#: The gap between two observations in the re-observation case, longer than the
#: declared window so the second collection is about re-observation.
A_WEEK: Final[timedelta] = timedelta(days=7)

#: A primary key no row in this module holds.
NO_SUCH_PACKAGE: Final[int] = 9_999_999


def _document(requires_python: str | None = None, classifiers: list[str] | None = None) -> str:
    """Return the project document a source would serve.

    Args:
        requires_python: `info.requires_python`, or `None` for a project that
            declared none -- which is what PyPI really sends for one.
        classifiers: `info.classifiers`, or `None` for a project that declared
            none.

    Returns:
        The JSON body.

    """
    document: dict[str, Any] = {
        "info": {
            "name": "Django",
            "requires_python": requires_python,
            "classifiers": classifiers,
        },
    }
    return json.dumps(document)


def _answering(body: str = _document(), **payload: Any) -> RecordedTransport:
    """Return a transport that answers the locator with this body.

    Args:
        body: What the source serves.
        **payload: Further `Payload` fields -- `found`, `not_modified`, `etag`.

    Returns:
        The recorded transport.

    """
    return RecordedTransport(payload=recorded_payload(source=THE_LOCATOR, body=body, **payload))


def _a_package(
    name: str = "django",
    *,
    outcome: str | None = ESTABLISHED,
    primary_type: str = PURL_TYPE,
    primary_purl: str = A_PURL,
) -> Package:
    """Return a saved package with a recorded release-ecosystem identity.

    Created directly rather than through `identity`'s resolution service, because
    what this module is about starts *after* an identity exists.

    Args:
        name: The canonical name, unique per case.
        outcome: The `release_ecosystem` mapping's outcome, or `None` to record no
            mapping row at all -- a package no resolver has reached.
        primary_type: What resolution recorded as the primary purl type.
        primary_purl: What resolution recorded as the primary purl.

    Returns:
        The saved row.

    """
    package = Package.objects.create(
        canonical_name=name,
        resolved_at=FIXED_INSTANT,
        primary_type=primary_type,
        primary_purl=primary_purl,
    )
    if outcome is not None:
        PackageMapping.objects.create(
            package=package,
            kind=MappingKind.RELEASE_ECOSYSTEM.value,
            outcome=outcome,
            resolved_at=FIXED_INSTANT,
        )
    return package


def _collect(  # noqa: PLR0913 - one parameter per seam the base takes; a bundle would hide the one under test
    package: Package,
    *,
    transport: RecordedTransport,
    at: datetime = FIXED_INSTANT,
    force: bool = False,
    permitted: bool = True,
    cache: RecordingResponseCache | None = None,
    limiter: FixedLimiter | None = None,
) -> CollectionResult:
    """Run one collection through a scripted transport.

    Args:
        package: The package to assess.
        transport: The transport substituted at the base's seam (`CPM-AD-27`).
        at: The instant the run's clock is stopped at.
        force: Whether to bypass the observation window (`CPM-UJ-1`).
        permitted: What the substituted limiter answers, when none is passed.
        cache: The response cache to use, or a fresh recording one.
        limiter: The limiter to use, so a case can read what it was asked.

    Returns:
        What the run did.

    """
    collector = PythonReadinessCollector(
        clock=FixedClock(instant=at),
        transport=transport,
        limiter=limiter if limiter is not None else FixedLimiter(permitted=permitted),
        response_cache=cache if cache is not None else RecordingResponseCache(),
    )
    try:
        return collector.collect(package_id=package.pk, force=force)
    finally:
        collector.close()


def _rows(package: Package) -> list[PythonReadinessAssessment]:
    """Return this package's assessments, oldest first.

    Args:
        package: The package to read.

    Returns:
        The rows, ordered by primary key.

    """
    return list(PythonReadinessAssessment.objects.filter(package=package).order_by("pk"))


def _run(package: Package) -> CollectionRun:
    """Return the most recent ledger row for this collector and package.

    Args:
        package: The package the run was scoped to.

    Returns:
        The row, newest first.

    """
    return CollectionRun.objects.filter(collector=COLLECTOR_NAME, package=package).order_by("-pk").first()  # type: ignore[return-value]


def _row(**overrides: Any) -> PythonReadinessAssessment:
    """Return an unsaved assessment row a constraint case can try to insert.

    Args:
        **overrides: Columns to replace on an otherwise ordinary determinate row.

    Returns:
        The unsaved row.

    """
    fields: dict[str, Any] = {
        "observed_at": FIXED_INSTANT,
        "source": THE_LOCATOR,
        "state": INFERRED_COMPATIBLE,
        "python_series": series_of(PYTHON_SERIES),
        "requires_python": AN_ADMITTING_SPECIFIER,
        "matching_classifier": "",
        "deciding_signal": DecidingSignal.REQUIRES_PYTHON.value,
        "detail": "",
        "trace_id": "",
    }
    fields.update(overrides)
    return PythonReadinessAssessment(**fields)


# ---------------------------------------------------------------------------
# AC 1: the static metadata check, recorded as inferred evidence.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_metadata_that_admits_the_series_records_inferred_compatibility_naming_the_signal() -> None:
    """AC 1: a static check, recorded as *inferred* evidence and never as verification.

    Also the things a case about the row alone would not see: the transport was
    asked for the locator this package's purl produces, the request carried the
    declared headers, and the locator reached the row.

    The state is asserted to carry the word `inferred` as well as its value, because
    `CPM-FR-14` requires inferred and verified compatibility to be distinct recorded
    states and `CPM-AD-24` carries the value verbatim onto every read surface -- a
    rename to `compatible` would satisfy an equality against a constant this file
    imported and would defeat the requirement outright.
    """
    package = _a_package()
    transport = _answering(_document(AN_ADMITTING_SPECIFIER, [THE_CLASSIFIER]))

    result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == 1
    assert transport.calls == [THE_LOCATOR]
    assert dict(READINESS_HEADERS).items() <= dict(transport.sent_headers[0] or {}).items()

    row = _rows(package)[0]
    assert row.state == INFERRED_COMPATIBLE
    assert "inferred" in row.state
    assert row.deciding_signal == DecidingSignal.BOTH.value
    assert row.python_series == series_of(PYTHON_SERIES)
    assert row.requires_python == AN_ADMITTING_SPECIFIER
    assert row.matching_classifier == THE_CLASSIFIER
    assert row.source == THE_LOCATOR
    assert row.observed_at == FIXED_INSTANT
    assert row.detail == ""
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_a_classifier_alone_reaches_a_determinate_row_which_a_sibling_snapshot_could_not_have() -> None:
    """The second static signal, and the reason this collector reads the source itself.

    `pypi_release_snapshots` stores a `requires_python` and stores no classifiers, so
    a collector that had taken the quicker read would have lost this row entirely --
    which is why `CPM-AD-7`'s rule is not merely principled here.
    """
    package = _a_package()

    result = _collect(package, transport=_answering(_document(None, [THE_CLASSIFIER])))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == INFERRED_COMPATIBLE
    assert row.deciding_signal == DecidingSignal.CLASSIFIER.value
    assert row.requires_python == ""


@pytest.mark.django_db
def test_metadata_that_excludes_the_series_records_the_specifier_verbatim() -> None:
    """The one determinate negative, and the claim that produced it sits beside it.

    A row saying a package cannot run on this Python is only argue-able if the range
    the project published is on the row, so the specifier is asserted character for
    character rather than merely non-empty.
    """
    package = _a_package()

    result = _collect(package, transport=_answering(_document(AN_EXCLUDING_SPECIFIER)))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == INFERRED_INCOMPATIBLE
    assert row.deciding_signal == DecidingSignal.REQUIRES_PYTHON.value
    assert row.requires_python == AN_EXCLUDING_SPECIFIER


# ---------------------------------------------------------------------------
# The property the story turns on: a silence is unknown, never incompatible.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_project_that_declared_nothing_records_unknown_and_never_incompatible() -> None:
    """The common case, and the whole of why this collector is worth having.

    Most projects have not declared 3.14 support. A table that recorded this row as
    `inferred_incompatible` would report most of an inventory as incompatible on no
    evidence and would send `CPM-PY314-S02`'s expensive verification exactly where it
    is least warranted -- the opposite of what the story exists to do.

    The run still *succeeds*: the source answered and the answer was read. A silence
    is an observation.
    """
    package = _a_package()

    result = _collect(package, transport=_answering(_document()))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == READINESS_UNKNOWN
    assert row.state != INFERRED_INCOMPATIBLE
    assert row.deciding_signal == ""
    assert row.detail == NOTHING_DECLARED_DETAIL
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_a_project_that_enumerated_its_pythons_without_this_one_is_still_unknown() -> None:
    """A classifier list states what a project claims and never what it denies.

    A distinct `detail` from the row above, because a project that took the trouble
    to list its Pythons and left this one out has said something a reviewer should
    weigh -- and still has not said "no".
    """
    package = _a_package()

    result = _collect(package, transport=_answering(_document(None, [AN_EARLIER_CLASSIFIER])))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == READINESS_UNKNOWN
    assert row.detail == NO_CLASSIFIER_FOR_SERIES_DETAIL
    assert row.detail != NOTHING_DECLARED_DETAIL


@pytest.mark.django_db
def test_two_signals_that_disagree_are_recorded_as_the_disagreement_they_are() -> None:
    """Never silently resolved: both transcribed columns survive on an `unknown` row.

    Picking a winner here would be this collector deciding a claim about somebody
    else's package, invisibly, in the one column a policy pass reads first.
    """
    package = _a_package()

    result = _collect(package, transport=_answering(_document(AN_ADMITTING_SPECIFIER, [AN_EARLIER_CLASSIFIER])))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == READINESS_UNKNOWN
    assert row.deciding_signal == ""
    assert DISAGREEMENT_DETAIL in row.detail
    assert row.requires_python == AN_ADMITTING_SPECIFIER


@pytest.mark.django_db
def test_an_unreadable_specifier_records_unknown_with_the_raw_value_preserved() -> None:
    """`CPM-PY314-S01`'s Block If, on the real table.

    The specifier is what makes the row reviewable and the reason is what makes the
    shape findable; a row carrying neither would be an absence of information about
    a project that declared something.
    """
    package = _a_package()

    result = _collect(package, transport=_answering(_document(AN_UNREADABLE_SPECIFIER)))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == READINESS_UNKNOWN
    assert row.state != INFERRED_INCOMPATIBLE
    assert row.requires_python == AN_UNREADABLE_SPECIFIER
    assert UNREADABLE_SPECIFIER_DETAIL in row.detail


# ---------------------------------------------------------------------------
# AC 2, and the absence trap beside it.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_identity_that_established_no_ecosystem_records_not_applicable_naming_identity() -> None:
    """AC 2: the only path to `not_applicable`, and no call is made to reach it.

    The recording fakes are the only way to show the negatives: no locator was
    asked, no allowance was spent and no cache entry was read. The run *succeeds* --
    the collector answered, and the answer was "this question is not about this
    package" (`CPM-FR-6`).
    """
    package = _a_package(outcome=OutcomeState.NOT_APPLICABLE.value, primary_type="", primary_purl="")
    transport = _answering()
    cache = RecordingResponseCache()
    limiter = FixedLimiter(permitted=True)

    result = _collect(package, transport=transport, cache=cache, limiter=limiter)

    assert result.state == RunState.SUCCEEDED
    assert transport.calls == []
    assert limiter.asks == []
    assert cache.reads == []

    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_APPLICABLE.value
    assert row.source == ""
    assert row.deciding_signal == ""
    assert row.python_series == series_of(PYTHON_SERIES)
    assert "identity" in row.detail
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
@pytest.mark.parametrize(
    "outcome",
    [OutcomeState.UNKNOWN.value, OutcomeState.ERROR.value, OutcomeState.NOT_FOUND.value, None],
)
def test_identity_that_established_nothing_never_records_not_applicable(outcome: str | None) -> None:
    """The absence trap, refused rather than answered -- and never with a determinate claim.

    `unknown`, `error`, `not_found` and *no mapping row at all* are identity having
    established nothing, so the compatibility question is unanswered rather than
    inapplicable. The run is refused from `source_for` before the window, the
    allowance and the transport, so the ledger row is `failed` carrying a reason that
    says exactly that -- and **no evidence row exists**, least of all a
    `not_applicable` one, which would be a determinate claim made from an absence.
    The ledger's reason is the one sentence both refusal paths share, so a reader of
    a failed row learns the same thing whether identity recorded a sentinel or
    recorded no mapping row at all.

    The exception *type* is asserted rather than its message: the message is prose
    and the type is what the task and the base are written against.
    """
    package = _a_package(name=f"pkg-{outcome}", outcome=outcome, primary_purl="")
    transport = _answering()

    with pytest.raises(PythonReadinessIdentityError):
        _collect(package, transport=transport)

    assert transport.calls == []
    assert _rows(package) == []
    assert not PythonReadinessAssessment.objects.filter(
        package=package,
        state=OutcomeState.NOT_APPLICABLE.value,
    ).exists()
    ledger = _run(package)
    assert ledger.status == RunState.FAILED.value
    assert IDENTITY_UNRESOLVED_DETAIL in ledger.detail


@pytest.mark.django_db
def test_an_established_mapping_for_another_ecosystem_is_refused_rather_than_called_inapplicable() -> None:
    """The one divergence from `collectors/pypi_release.py`'s otherwise identical hook.

    That sibling records such a package `not_applicable`; this collector may not,
    because identity's own `not_applicable` is the only path to that state here. The
    package is not offered by the selection either, so this refusal is what a *forced*
    recollection meets rather than what a sweep produces daily.
    """
    package = _a_package(name="ggplot2", primary_type="cran", primary_purl="pkg:cran/ggplot2")

    with pytest.raises(PythonReadinessIdentityError):
        _collect(package, transport=_answering())

    assert _rows(package) == []


@pytest.mark.django_db
def test_the_selection_offers_only_the_packages_identity_can_answer_for() -> None:
    """The complement of the refusal, expressed as the query the refusal is written against.

    Offering the whole inventory would have a scheduled sweep record one `failed`
    collection per unresolved package per cadence, for ever -- the "ledger fills with
    failed runs" shape every selection in this package exists to prevent.
    """
    askable = _a_package(name="askable")
    inapplicable = _a_package(name="inapplicable", outcome=OutcomeState.NOT_APPLICABLE.value, primary_purl="")
    unresolved = _a_package(name="unresolved", outcome=OutcomeState.UNKNOWN.value, primary_purl="")
    unmapped = _a_package(name="unmapped", outcome=None, primary_purl="")
    elsewhere = _a_package(name="elsewhere", primary_type="cran", primary_purl="pkg:cran/x")

    offered = set(PythonReadinessCollector.selectable_packages())

    assert {askable.pk, inapplicable.pk} <= offered
    assert offered.isdisjoint({unresolved.pk, unmapped.pk, elsewhere.pk})


@pytest.mark.django_db
@pytest.mark.parametrize("primary_purl", ["", "pkg:npm/left-pad"])
def test_the_selection_never_offers_a_package_the_locator_would_then_refuse(primary_purl: str) -> None:
    """An `established` PyPI *type* beside a purl that names no PyPI project, which identity permits.

    `identity/services.py` validates an established mapping by asking whether *any*
    of its fields carries a value, so `primary_type='pypi'` with a blank or non-PyPI
    `primary_purl` is a legal, writable row. Selected on the type alone such a
    package is offered, passes `asks_about` -- which reads the type and nothing else
    -- and then raises from `project_locator`, which the base calls **outside** every
    `try`: a `failed` run with no evidence row, every cadence, for ever. That is the
    "ledger fills with failed runs" shape `selectable_packages` exists to prevent, so
    the query filters the purl as well as the type.

    Both halves are asserted: the selection withholds the package, *and* the refusal
    it was spared is real -- a forced recollection still raises and still writes no
    row, which is what makes the first half worth having.
    """
    package = _a_package(name=f"mismatched-{primary_purl or 'blank'}", primary_purl=primary_purl)

    assert package.pk not in set(PythonReadinessCollector.selectable_packages())

    with pytest.raises(PythonReadinessIdentityError):
        _collect(package, transport=_answering(), force=True)

    assert _rows(package) == []
    assert _run(package).status == RunState.FAILED.value


# ---------------------------------------------------------------------------
# The base's own paths: absence, failure, a spent allowance, an unreadable document.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_project_the_index_does_not_know_records_not_found_with_the_caveat() -> None:
    """Distinct from "declared nothing", which is the confusion this caveat prevents.

    The base finalizes the run `succeeded`, because the source answered and the
    answer was "no such project"; the row says which absence it is.
    """
    package = _a_package()

    result = _collect(package, transport=_answering(found=False))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_FOUND.value
    assert row.state != READINESS_UNKNOWN
    assert ABSENT_FROM_INDEX_DETAIL in row.detail
    assert row.python_series == series_of(PYTHON_SERIES)


@pytest.mark.django_db
def test_a_transport_failure_writes_an_error_row_and_fails_the_ledger() -> None:
    """`CPM-NFR-3`: never a clean result, and never no row."""
    package = _a_package()

    result = _collect(
        package, transport=RecordedTransport(failure=TransportError("the host went away", source=THE_LOCATOR))
    )

    assert result.state == RunState.FAILED
    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert row.deciding_signal == ""
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_spent_allowance_writes_an_error_row_without_calling_the_source() -> None:
    """`CPM-AD-20`: the limiter refuses before the call, and the refusal is on the record."""
    package = _a_package()
    transport = _answering()

    result = _collect(package, transport=transport, permitted=False)

    assert result.state == RunState.FAILED
    assert transport.calls == []
    assert _rows(package)[0].state == OutcomeState.ERROR.value


@pytest.mark.django_db
def test_an_unreadable_document_writes_an_error_row_and_re_raises() -> None:
    """Refused rather than partly read, and the row exists before the exception leaves.

    Reading around a shape change would record "this project declared nothing" for a
    project that declared something in a shape the reader skipped -- an `unknown` row
    that looks exactly like an honest one.
    """
    package = _a_package()

    with pytest.raises(PythonReadinessDocumentError):
        _collect(package, transport=_answering("not a document"))

    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert row.state != READINESS_UNKNOWN
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_package_that_has_no_row_leaves_nothing_behind_at_all() -> None:
    """`CPM-EVIDENCE-S09`: the ledger checks the key before it opens a row."""
    collector = PythonReadinessCollector(clock=FixedClock(instant=FIXED_INSTANT), transport=_answering())
    try:
        with pytest.raises(RunLedgerError):
            collector.collect(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()

    assert CollectionRun.objects.filter(collector=COLLECTOR_NAME).count() == 0


# ---------------------------------------------------------------------------
# Re-observation, the window, and the identity a second run reads afresh.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_project_that_declares_support_later_inserts_a_new_row_and_the_old_one_stands() -> None:
    """`CPM-AD-2`: re-observation always inserts, which is how a reader sees *when*.

    The two rows are the whole of what makes this table worth keeping over time: a
    package that was `unknown` in one run and `inferred_compatible` in the next has a
    date attached to the change.
    """
    package = _a_package()

    _collect(package, transport=_answering(_document()))
    _collect(package, transport=_answering(_document(AN_ADMITTING_SPECIFIER)), at=FIXED_INSTANT + A_WEEK)

    rows = _rows(package)
    assert len(rows) == TWO_ROWS
    assert rows[0].state == READINESS_UNKNOWN
    assert rows[1].state == INFERRED_COMPATIBLE
    assert rows[0].observed_at < rows[1].observed_at


@pytest.mark.django_db
def test_a_second_run_inside_the_window_is_skipped_and_writes_nothing() -> None:
    """`CPM-AD-7`: a decision not to observe is not an observation."""
    package = _a_package()
    _collect(package, transport=_answering(_document()))

    result = _collect(package, transport=_answering(_document(AN_ADMITTING_SPECIFIER)))

    assert result.state == RunState.SKIPPED
    assert len(_rows(package)) == 1


@pytest.mark.django_db
def test_one_instance_collecting_two_packages_reads_identity_afresh_for_the_second() -> None:
    """The reset `inapplicability` performs, proved where it can actually be reached.

    Without it the second run would be answered from the first package's identity --
    and on the `not_applicable` path would record the first package's locator on the
    second package's row.
    """
    askable = _a_package(name="askable")
    inapplicable = _a_package(name="inapplicable", outcome=OutcomeState.NOT_APPLICABLE.value, primary_purl="")
    collector = PythonReadinessCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=_answering(_document(AN_ADMITTING_SPECIFIER)),
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )
    try:
        collector.collect(package_id=askable.pk)
        collector.collect(package_id=inapplicable.pk)
    finally:
        collector.close()

    assert _rows(askable)[0].state == INFERRED_COMPATIBLE
    second = _rows(inapplicable)[0]
    assert second.state == OutcomeState.NOT_APPLICABLE.value
    assert second.source == ""


@pytest.mark.django_db
def test_an_assessment_is_current_for_as_long_as_its_declared_target() -> None:
    """`CPM-AD-28`: the target is strictly greater than the cadence, read through the base."""
    package = _a_package()
    _collect(package, transport=_answering(_document()))

    collector = PythonReadinessCollector(clock=FixedClock(instant=FIXED_INSTANT))
    try:
        fresh = collector.freshness(package_id=package.pk, now=FIXED_INSTANT)
        stale = collector.freshness(
            package_id=package.pk,
            now=FIXED_INSTANT + READINESS_FRESHNESS_TARGET + timedelta(seconds=1),
        )
    finally:
        collector.close()

    assert fresh.stale is False
    assert stale.stale is True


@pytest.mark.django_db
def test_a_package_this_collector_has_not_observed_reads_as_unobserved() -> None:
    """The mechanism the first `deferred` entry's whole argument rests on, asserted rather than asserted *about*.

    A package identity has not resolved gets **no row on this table**: the selection
    does not offer it and a forced recollection is refused. What the story claims in
    its place is that every read surface still reports it `unknown` for want of an
    observation -- `core/freshness.py`'s `UNOBSERVED_STATUS` -- rather than carrying a
    determinate claim nobody established. This is that claim, and every sibling suite
    in this directory has the same case.
    """
    package = _a_package(name="never-observed", outcome=OutcomeState.UNKNOWN.value, primary_purl="")

    collector = PythonReadinessCollector(clock=FixedClock(instant=FIXED_INSTANT))
    try:
        report = collector.freshness(package_id=package.pk, now=FIXED_INSTANT)
    finally:
        collector.close()

    assert _rows(package) == []
    assert report.observed_at is None
    assert report.status == UNOBSERVED_STATUS


@pytest.mark.django_db
def test_a_revalidated_answer_writes_the_same_assessment_a_body_would_have() -> None:
    """The `304` replay, which `READINESS_CACHE_TTL` argues for at length and nothing exercised.

    This collector declares a cache lifetime deliberately longer than its cadence, so
    a weekly run against a project that published nothing new revalidates rather than
    re-transferring a document listing every file of every release. The base replays
    the remembered body through `translate`, and the row it writes must be the row a
    `200` would have written -- otherwise a project's assessment would silently depend
    on whether its document happened to be transferred that week.
    """
    package = _a_package()
    cache = RecordingResponseCache(
        entries={
            (COLLECTOR_NAME, THE_LOCATOR): cached_response(
                body=_document(AN_ADMITTING_SPECIFIER, [THE_CLASSIFIER]),
                etag=AN_ETAG,
            ),
        },
    )
    transport = _answering("", not_modified=True, etag=AN_ETAG)

    result = _collect(package, transport=transport, cache=cache, force=True)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == INFERRED_COMPATIBLE
    assert row.deciding_signal == DecidingSignal.BOTH.value
    assert row.requires_python == AN_ADMITTING_SPECIFIER
    assert row.matching_classifier == THE_CLASSIFIER
    assert row.source == THE_LOCATOR
    assert transport.sent_headers[0] is not None
    assert AN_ETAG in dict(transport.sent_headers[0]).values()


# ---------------------------------------------------------------------------
# The constraints, against a real backend.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_database_refuses_an_inferred_row_that_names_no_deciding_signal() -> None:
    """An inference that cannot say what it inferred from is a claim with no argument."""
    package = _a_package()

    row = _row(deciding_signal="")
    row.package = package

    with pytest.raises(IntegrityError, match=READINESS_SIGNAL_CONSTRAINT), transaction.atomic():
        row.save()


@pytest.mark.django_db
def test_the_database_refuses_a_row_that_is_not_inferred_and_names_a_deciding_signal() -> None:
    """The other half of the biconditional: a signal under any other state claims a decision."""
    package = _a_package()

    row = _row(state=READINESS_UNKNOWN, deciding_signal=DecidingSignal.BOTH.value)
    row.package = package

    with pytest.raises(IntegrityError, match=READINESS_SIGNAL_CONSTRAINT), transaction.atomic():
        row.save()


@pytest.mark.django_db
def test_the_database_permits_the_transcribed_columns_on_a_row_that_inferred_nothing() -> None:
    """The load-bearing *omission* from the constraint, asserted from the permitting side.

    The specifier and the classifier are what make an `unknown` row reviewable, so a
    constraint that had tidied them away would delete the evidence this table exists
    to leave behind. A case asserting only the two refusals above would pass against
    a constraint that forbade them everywhere.
    """
    package = _a_package()
    row = _row(
        state=READINESS_UNKNOWN,
        deciding_signal="",
        requires_python=AN_UNREADABLE_SPECIFIER,
        matching_classifier=THE_CLASSIFIER,
        detail=UNREADABLE_SPECIFIER_DETAIL,
    )
    row.package = package
    row.save()

    stored = _rows(package)[0]
    assert stored.requires_python == AN_UNREADABLE_SPECIFIER
    assert stored.matching_classifier == THE_CLASSIFIER


@pytest.mark.django_db
def test_the_database_refuses_a_not_applicable_row_that_states_no_reason() -> None:
    """The only honest reason is one identity established, so a silent one is refused.

    A `not_applicable` row with a blank `detail` is indistinguishable from one
    written out of an *absence* of identity, which is precisely what this story
    forbids -- and the collector's own discipline is one writer's rule, while this is
    the table's.
    """
    package = _a_package()

    row = _row(state=OutcomeState.NOT_APPLICABLE.value, deciding_signal="", requires_python="", detail="")
    row.package = package

    with pytest.raises(IntegrityError, match=READINESS_REASON_CONSTRAINT), transaction.atomic():
        row.save()


@pytest.mark.django_db
def test_the_database_refuses_a_row_that_does_not_name_the_series_it_assessed() -> None:
    """`CPM-PY314-S02` writes a verified result about a series, and `CPM-PY314-S03` reduces both.

    A row that could not say which Python it was about would make the two
    indistinguishable at exactly the moment the distinction is being read.
    """
    package = _a_package()

    row = _row(python_series="")
    row.package = package

    with pytest.raises(IntegrityError, match=READINESS_SERIES_CONSTRAINT), transaction.atomic():
        row.save()


@pytest.mark.django_db
def test_the_table_carries_no_unique_constraint_a_re_observation_could_violate() -> None:
    """`CPM-AD-2`: the tuple that looks unique is the one every run repeats."""
    package = _a_package()
    for _ in range(TWO_ROWS):
        row = _row()
        row.package = package
        row.save()

    assert len(_rows(package)) == TWO_ROWS


# ---------------------------------------------------------------------------
# The task.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_task_collects_the_package_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """The task builds the collector the module names, and returns the run's state.

    The collector the task constructs is substituted so the real transport is never
    asked for a socket, on the terms the sibling collectors' task cases set.
    """
    package = _a_package()
    transport = _answering(_document(AN_ADMITTING_SPECIFIER))

    def _substituted(*, clock: Any) -> PythonReadinessCollector:
        return PythonReadinessCollector(
            clock=clock,
            transport=transport,
            limiter=FixedLimiter(permitted=True),
            response_cache=RecordingResponseCache(),
        )

    monkeypatch.setattr(collector_tasks, "PythonReadinessCollector", _substituted)

    assert collect_python_readiness(package_id=package.pk) == RunState.SUCCEEDED.value
    assert _rows(package)[0].state == INFERRED_COMPATIBLE


@pytest.mark.django_db
def test_the_task_refuses_a_package_identity_has_not_resolved_before_any_call() -> None:
    """The real task with the real transport constructed and never used.

    An unresolved identity is refused from `source_for`, which is before the window,
    the allowance and the socket -- so this case runs the shipped task end to end
    without opening one.
    """
    package = _a_package(outcome=OutcomeState.UNKNOWN.value, primary_purl="")

    with pytest.raises(PythonReadinessIdentityError):
        collect_python_readiness(package_id=package.pk)

    assert _rows(package) == []
    assert _run(package).status == RunState.FAILED.value
