"""PyPI release collection against real tables: the rows, the ledger, the refusals, and the third answer.

`CPM-FR-8` asks for three things a row can say -- the project's latest version and
metadata, its absence, and that the question does not apply -- and every one of
them is only true or false once a run exists. Which is why this module sits beside
`tests/unit/django_apps/test_pypi_release.py`: the locator, the document, the
declarations and the applicability rule are decided before a run does, and are
asserted there.

**AC 3 is the case this collector exists to add, and it is proved from both
ends.** A non-Python package produces a `not_applicable` row and a `succeeded`
run with no call made, no allowance asked and no cache read -- the recording
fakes are the only way to show the negatives -- and then the freshness read
reports that observation as *not stale* with its status carried, which is the
"never marked stale against PyPI" half. AC 2 is proved the same way, and a paired
case shows the read answering the other thing for a package this collector never
observed.

**An unresolved identity fails the run rather than being guessed at.** A
`release_ecosystem` mapping that is `unknown`, `not_found`, `error` or absent is
refused from `source_for`, on the terms `SourceLocatorError` set in
`CPM-CURRENCY-S01`: a `failed` ledger row carrying the reason and no evidence row.
That is deliberately not the `not_applicable` path -- "resolution has not
decided" is not "does not apply".

**No socket is opened.** Every case substitutes the transport at the base's seam.
The task cases follow `test_source_release.py`'s two moves: one reaches a terminal
state before any call is made -- and for this collector that includes a
`not_applicable` run through the real task with the real transport constructed and
never used -- and the other substitutes the collector the task constructs.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction.
`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

import json
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction

from conda_package_supply_chain_monitor.collectors import tasks as collector_tasks
from conda_package_supply_chain_monitor.collectors.models import PYPI_FACTS_CONSTRAINT
from conda_package_supply_chain_monitor.collectors.models import PyPIReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.pypi_release import COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.pypi_release import NO_RELEASE_DETAIL
from conda_package_supply_chain_monitor.collectors.pypi_release import PURL_TYPE
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_FRESHNESS_TARGET
from conda_package_supply_chain_monitor.collectors.pypi_release import PYPI_RELEASE_HEADERS
from conda_package_supply_chain_monitor.collectors.pypi_release import UNDATED_VERSION_DETAIL
from conda_package_supply_chain_monitor.collectors.pypi_release import PyPIDocumentError
from conda_package_supply_chain_monitor.collectors.pypi_release import PyPILocatorError
from conda_package_supply_chain_monitor.collectors.pypi_release import PyPIReleaseCollector
from conda_package_supply_chain_monitor.collectors.pypi_release import project_locator
from conda_package_supply_chain_monitor.collectors.tasks import collect_pypi_release
from conda_package_supply_chain_monitor.core.clock import Clock
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.freshness import UNOBSERVED_STATUS
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.runs import RunLedgerError
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.core.transport import TransportError
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from conda_package_supply_chain_monitor.identity.models import MappingKind
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import PackageMapping
from tests.clocks import FIXED_INSTANT
from tests.collectors import FixedLimiter
from tests.collectors import RecordedTransport
from tests.collectors import RecordingResponseCache
from tests.collectors import cached_response
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from conda_package_supply_chain_monitor.core.collection import CollectionResult
    from conda_package_supply_chain_monitor.core.rate_limit import RateLimiter
    from conda_package_supply_chain_monitor.core.response_cache import ResponseCache
    from conda_package_supply_chain_monitor.core.transport import Transport

#: The purl the packages in this module are resolved to, and the locator it
#: produces. Derived rather than written out: a case here is about what a *run*
#: does with a locator, and the unit tier is where its spelling is pinned.
A_PURL: Final[str] = "pkg:pypi/Django"
THE_LOCATOR: Final[str] = project_locator(A_PURL)

#: The facts the ordinary document carries, and the upload instant as an instant.
A_VERSION: Final[str] = "5.1.2"
A_LATER_VERSION: Final[str] = "5.2.0"
A_SPECIFIER: Final[str] = ">=3.10"
UPLOADED: Final[str] = "2026-04-11T14:00:00.000000Z"
UPLOADED_INSTANT: Final[datetime] = datetime(2026, 4, 11, 14, 0, tzinfo=UTC)

#: The entity tag a source hands back, for the caching cases.
AN_ETAG: Final[str] = '"e1f2"'

#: How many rows the cases that write twice expect. Named because `PLR2004` is
#: right about a bare number in an assertion.
TWO_ROWS: Final[int] = 2

#: The gap between two observations in the re-observation case, longer than the
#: declared window so the second collection is about re-observation.
A_DAY: Final[timedelta] = timedelta(days=1)

#: A primary key no row in this module holds.
NO_SUCH_PACKAGE: Final[int] = 9_999_999


def _document(version: str | None = A_VERSION, *, requires_python: str | None = A_SPECIFIER, dated: bool = True) -> str:
    """Return the project document a source would serve.

    Args:
        version: `info.version`, or `None` for a project naming no version.
        requires_python: `info.requires_python`, or `None` for none declared.
        dated: Whether the version's one file carries an upload time.

    Returns:
        The JSON body.

    """
    files: list[dict[str, Any]] = [{"filename": "django.whl", "upload_time_iso_8601": UPLOADED}] if dated else []
    document: dict[str, Any] = {
        "info": {"name": "Django", "version": version, "requires_python": requires_python},
        "releases": {} if version is None else {version: files},
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
        outcome: The `release_ecosystem` mapping's outcome, or `None` to record
            no mapping row at all -- a package no resolver has reached.
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
        package: The package to observe.
        transport: The transport substituted at the base's seam (`CPM-AD-27`).
        at: The instant the run's clock is stopped at.
        force: Whether to bypass the observation window (`CPM-UJ-1`).
        permitted: What the substituted limiter answers, when none is passed.
        cache: The response cache to use, or a fresh recording one.
        limiter: The limiter to use, so a case can read what it was asked.

    Returns:
        What the run did.

    """
    collector = PyPIReleaseCollector(
        clock=FixedClock(instant=at),
        transport=transport,
        limiter=limiter if limiter is not None else FixedLimiter(permitted=permitted),
        response_cache=cache if cache is not None else RecordingResponseCache(),
    )
    try:
        return collector.collect(package_id=package.pk, force=force)
    finally:
        collector.close()


def _rows(package: Package) -> list[PyPIReleaseSnapshot]:
    """Return this package's observations, oldest first.

    Args:
        package: The package to read.

    Returns:
        The rows, ordered by primary key.

    """
    return list(PyPIReleaseSnapshot.objects.filter(package=package).order_by("pk"))


def _run(package: Package) -> CollectionRun:
    """Return the most recent ledger row for this collector and package.

    Args:
        package: The package the run was scoped to.

    Returns:
        The row, newest first.

    """
    return CollectionRun.objects.filter(collector=COLLECTOR_NAME, package=package).order_by("-pk").first()  # type: ignore[return-value]


def _freshness(package: Package, *, status: str | None = None, now: datetime = FIXED_INSTANT) -> Any:
    """Read this collector's freshness for one package, as a read surface would.

    Args:
        package: The package to ask about.
        status: The status the evidence carries, or `None` for a caller holding
            no observation.
        now: The instant staleness is measured from.

    Returns:
        The `FreshnessReport`.

    """
    collector = PyPIReleaseCollector(clock=FixedClock(instant=FIXED_INSTANT))
    try:
        if status is None:
            return collector.freshness(package_id=package.pk, now=now)
        return collector.freshness(package_id=package.pk, now=now, status=status)
    finally:
        collector.close()


# ---------------------------------------------------------------------------
# AC 1: the observation.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_python_package_on_pypi_is_recorded_with_its_version_date_and_specifier() -> None:
    """AC 1: existence, latest version and date, and `Requires-Python`, on one row.

    Also the things a case about the row alone would not see: the transport was
    asked for the locator this package's purl produces, the request carried the
    declared headers, and the locator reached the row.
    """
    package = _a_package()
    transport = _answering()

    result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == 1
    assert transport.calls == [THE_LOCATOR]
    assert dict(PYPI_RELEASE_HEADERS).items() <= dict(transport.sent_headers[0] or {}).items()

    row = _rows(package)[0]
    assert row.source == THE_LOCATOR
    assert row.state == OutcomeState.OK.value
    assert row.latest_version == A_VERSION
    assert row.released_at == UPLOADED_INSTANT
    assert row.requires_python == A_SPECIFIER
    assert row.detail == ""
    assert row.observed_at == FIXED_INSTANT
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_a_latest_version_the_source_dated_nothing_for_is_recorded_undated() -> None:
    """The version stands and the date does not, and the row says so."""
    package = _a_package()

    result = _collect(package, transport=_answering(_document(dated=False)))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.OK.value
    assert row.latest_version == A_VERSION
    assert row.released_at is None
    assert row.detail == UNDATED_VERSION_DETAIL


@pytest.mark.django_db
def test_a_project_declaring_no_requires_python_is_recorded_blank() -> None:
    """Blank means missing, on the real table."""
    package = _a_package()

    _collect(package, transport=_answering(_document(requires_python=None)))

    row = _rows(package)[0]
    assert row.state == OutcomeState.OK.value
    assert row.requires_python == ""


@pytest.mark.django_db
def test_a_document_naming_no_version_is_a_not_found_row_that_says_why() -> None:
    """A `200` with a blank version is an answer, and the row is the informative negative."""
    package = _a_package()

    result = _collect(package, transport=_answering(_document(version=None)))

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_FOUND.value
    assert row.latest_version == ""
    assert row.requires_python == ""
    assert row.detail == NO_RELEASE_DETAIL


# ---------------------------------------------------------------------------
# AC 2: no PyPI presence.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_with_no_pypi_presence_is_observed_as_not_found_rather_than_left_to_go_stale() -> None:
    """AC 2, asserted where the difference shows: the row, the ledger, and the freshness read.

    `succeeded` rather than `failed`: the source answered, and the answer was "no
    such project". No caveat on the row, because PyPI is public and a `404` is
    unambiguous. And `core/freshness.py` -- the module every read surface asks --
    reports the observation as *not stale* carrying `not_found`.
    """
    package = _a_package()
    transport = _answering("", found=False)

    result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_FOUND.value
    assert row.latest_version == ""
    assert row.released_at is None
    assert row.requires_python == ""
    assert row.source == THE_LOCATOR
    assert row.detail == f"{THE_LOCATOR} reports that the resource does not exist"
    assert _run(package).status == RunState.SUCCEEDED.value

    report = _freshness(package, status=row.state)
    assert report.observed_at == FIXED_INSTANT
    assert report.stale is False
    assert report.status == OutcomeState.NOT_FOUND.value


@pytest.mark.django_db
def test_a_package_this_collector_has_not_observed_reads_as_unobserved() -> None:
    """The anti-vacuity half of AC 2 and AC 3: the freshness read can say the other thing."""
    package = _a_package()

    report = _freshness(package)

    assert report.observed_at is None
    assert report.status == UNOBSERVED_STATUS


# ---------------------------------------------------------------------------
# AC 3: a non-Python package.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("outcome", "primary_type", "primary_purl"),
    [
        (OutcomeState.NOT_APPLICABLE.value, "", ""),
        (ESTABLISHED, "npm", "pkg:npm/left-pad"),
        (ESTABLISHED, "cargo", "pkg:cargo/serde"),
    ],
    ids=["recorded-not-applicable", "established-for-npm", "established-for-cargo"],
)
def test_a_non_python_package_is_recorded_not_applicable_with_no_call_and_no_allowance_spent(
    outcome: str,
    primary_type: str,
    primary_purl: str,
) -> None:
    """AC 3, decided from identity and written by the base.

    The mapping says the package's release ecosystem is not PyPI -- recorded as
    inapplicable, or established for another ecosystem -- so the collector says
    the question does not apply and the base writes the `not_applicable` row: no
    transport call, no limiter ask (a limiter that refuses everything changes
    nothing), no cache read, and a `succeeded` run carrying the reason as its
    `detail`, which is the same string the row carries. The row's `source` is
    blank, because no locator was ever built.
    """
    package = _a_package(outcome=outcome, primary_type=primary_type, primary_purl=primary_purl)
    transport = _answering()
    cache = RecordingResponseCache()
    limiter = FixedLimiter(permitted=False)

    result = _collect(package, transport=transport, cache=cache, limiter=limiter)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == 1
    assert transport.calls == []
    assert limiter.asks == []
    assert cache.reads == []
    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_APPLICABLE.value
    assert row.source == ""
    assert row.latest_version == ""
    assert row.released_at is None
    assert row.requires_python == ""
    assert row.detail == result.detail
    assert row.detail != ""
    assert row.observed_at == FIXED_INSTANT
    run = _run(package)
    assert run.status == RunState.SUCCEEDED.value
    assert run.detail == result.detail


@pytest.mark.django_db
def test_a_non_python_package_is_never_marked_stale_against_pypi() -> None:
    """AC 3's second clause, asserted through the read every surface asks.

    A package with *no* row would read as `unknown` and age into stale; this one
    has an observation carrying `not_applicable`, and the read reports it fresh
    with the status carried through. That is the whole of "never marked stale
    against PyPI for not being published there".
    """
    package = _a_package(outcome=OutcomeState.NOT_APPLICABLE.value, primary_type="", primary_purl="")
    _collect(package, transport=_answering())

    report = _freshness(package, status=_rows(package)[0].state)

    assert report.observed_at == FIXED_INSTANT
    assert report.stale is False
    assert report.status == OutcomeState.NOT_APPLICABLE.value


@pytest.mark.django_db
def test_a_not_applicable_observation_ages_like_any_other() -> None:
    """The spec's reading of AC 3, made explicit: the row is fresh when observed and ages like every other.

    What AC 3 forbids is staleness *caused by* PyPI absence -- a package with no
    row, which reads `unknown` and ages from nowhere. It does not ask
    `core/freshness.py` to treat one status differently from another, and the
    story's Block-If says a status-aware staleness rule would halt it. So a
    `not_applicable` observation read one second past the declared target is
    stale, with its status carried, exactly as an `ok` row would be: the fact is
    old, and the remedy is the next scheduled run writing it again. The case is
    the negative control for the one above -- a read that always answered "not
    stale" would pass that case and fail this one.
    """
    package = _a_package(outcome=OutcomeState.NOT_APPLICABLE.value, primary_type="", primary_purl="")
    _collect(package, transport=_answering())
    past_target = FIXED_INSTANT + PYPI_RELEASE_FRESHNESS_TARGET + timedelta(seconds=1)

    report = _freshness(package, status=_rows(package)[0].state, now=past_target)

    assert report.observed_at == FIXED_INSTANT
    assert report.stale is True
    assert report.status == OutcomeState.NOT_APPLICABLE.value


@pytest.mark.django_db
def test_a_not_applicable_observation_inside_the_window_is_skipped_and_force_writes_again() -> None:
    """`CPM-AD-7`: the window applies to a question that does not apply, and `force` bypasses it."""
    package = _a_package(outcome=OutcomeState.NOT_APPLICABLE.value, primary_type="", primary_purl="")
    _collect(package, transport=_answering())

    suppressed = _collect(package, transport=_answering())
    forced = _collect(package, transport=_answering(), force=True)

    assert suppressed.state == RunState.SKIPPED
    assert suppressed.evidence_rows == 0
    assert forced.state == RunState.SUCCEEDED
    assert [row.state for row in _rows(package)] == [OutcomeState.NOT_APPLICABLE.value] * TWO_ROWS


# ---------------------------------------------------------------------------
# The failing paths.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_unreachable_source_is_an_error_row_and_a_failed_run() -> None:
    """`CPM-NFR-3`: never a clean result, never no row."""
    package = _a_package()
    transport = RecordedTransport(failure=TransportError("the source did not answer", source=THE_LOCATOR))

    result = _collect(package, transport=transport)

    assert result.state == RunState.FAILED
    assert result.evidence_rows == 1
    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert row.source == THE_LOCATOR
    assert row.detail != ""
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_document_that_cannot_be_read_writes_an_error_row_before_it_raises() -> None:
    """A parser that no longer matches its source is an `error`, on the record first."""
    package = _a_package()

    with pytest.raises(PyPIDocumentError):
        _collect(package, transport=_answering("not a project document"))

    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_spent_allowance_refuses_the_call_and_records_it() -> None:
    """`CPM-AD-20`: never issued unlimited, and never silently not issued either."""
    package = _a_package()
    transport = _answering()

    result = _collect(package, transport=transport, permitted=False)

    assert result.state == RunState.FAILED
    assert transport.calls == []
    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert "allowance" in row.detail


@pytest.mark.django_db
@pytest.mark.parametrize(
    "outcome",
    [OutcomeState.UNKNOWN.value, OutcomeState.NOT_FOUND.value, OutcomeState.ERROR.value, None],
    ids=["unknown", "not-found", "error", "no-mapping-row"],
)
def test_a_package_whose_release_ecosystem_is_unresolved_fails_the_run_and_writes_nothing(
    outcome: str | None,
) -> None:
    """Refused, not recorded: "resolution has not decided" is not "does not apply".

    `source_for` is asked before the window, the allowance and the transport, so
    the refusal leaves a ledger row saying why and no evidence -- the terms
    `SourceLocatorError` set in `CPM-CURRENCY-S01`. Writing a `not_applicable`
    row here instead would record a fact about the package nobody established.
    """
    package = _a_package(outcome=outcome, primary_type="", primary_purl="")
    transport = _answering()

    with pytest.raises(PyPILocatorError):
        _collect(package, transport=transport)

    assert _rows(package) == []
    assert transport.calls == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_an_established_pypi_identity_with_an_unreadable_purl_fails_the_run_and_writes_nothing() -> None:
    """The purl is data a resolution wrote, and one this collector cannot read is refused rather than repaired."""
    package = _a_package(primary_purl="pkg:npm/django")
    transport = _answering()

    with pytest.raises(PyPILocatorError):
        _collect(package, transport=transport)

    assert _rows(package) == []
    assert transport.calls == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_an_established_mapping_with_a_blank_type_fails_the_run_and_writes_nothing() -> None:
    """An inconsistent identity row is refused, not recorded as either kind of observation.

    `established` with no primary type is a resolution defect rather than a fact
    about the package. The hook says nothing, so no `not_applicable` row is
    written; `source_for` refuses, so no locator is built; the ledger says why.
    """
    package = _a_package(primary_type="", primary_purl="")
    transport = _answering()

    with pytest.raises(PyPILocatorError):
        _collect(package, transport=transport)

    assert _rows(package) == []
    assert transport.calls == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_asking_about_a_package_that_is_not_there_is_refused_rather_than_answered() -> None:
    """`source_for` is public, and a caller reaching it directly is not the base."""
    collector = PyPIReleaseCollector(clock=FixedClock(instant=FIXED_INSTANT))

    try:
        with pytest.raises(PyPILocatorError, match="mapping row"):
            collector.source_for(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()


@pytest.mark.django_db
def test_collecting_a_package_that_is_not_there_leaves_nothing_behind_at_all() -> None:
    """The base's actual surface for "no package row": the recorder refuses before any hook runs.

    `core/ledger.py` checks the key before it writes the opening row
    (`CPM-EVIDENCE-S09`), so neither `inapplicability` nor `source_for` is
    reached, no evidence row is written, and -- unlike every other refusal in this
    module -- no ledger row exists either. This is the one exit from `collect()`
    that mirrors no run, because there was no run.
    """
    transport = _answering()
    collector = PyPIReleaseCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=transport,
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )

    try:
        with pytest.raises(RunLedgerError):
            collector.collect(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()

    assert transport.calls == []
    assert not PyPIReleaseSnapshot.objects.filter(package_id=NO_SUCH_PACKAGE).exists()
    assert not CollectionRun.objects.filter(collector=COLLECTOR_NAME, package_id=NO_SUCH_PACKAGE).exists()


@pytest.mark.django_db
def test_one_instance_collecting_twice_reads_identity_fresh_on_the_second_run() -> None:
    """The identity read is remembered for one run, not for the instance's lifetime.

    A resolution can change between two runs of one long-lived instance -- the
    task constructs a fresh collector today, but a future sweep may not -- and a
    collector answering the second run from the first's read would refuse a
    package that has since been established, or ask about one that has since
    been withdrawn. The first run here fails on an `unknown` mapping; the mapping
    is then established; the second run collects. The window does not intervene,
    because a `failed` run never suppresses.
    """
    package = _a_package(outcome=OutcomeState.UNKNOWN.value, primary_type="", primary_purl="")
    transport = _answering()
    collector = PyPIReleaseCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=transport,
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )

    try:
        with pytest.raises(PyPILocatorError):
            collector.collect(package_id=package.pk)

        mapping = PackageMapping.objects.get(package=package, kind=MappingKind.RELEASE_ECOSYSTEM.value)
        mapping.outcome = ESTABLISHED
        mapping.save(update_fields=["outcome"])
        package.primary_type = PURL_TYPE
        package.primary_purl = A_PURL
        package.save(update_fields=["primary_type", "primary_purl"])

        result = collector.collect(package_id=package.pk)
    finally:
        collector.close()

    assert result.state == RunState.SUCCEEDED
    assert transport.calls == [THE_LOCATOR]
    assert _rows(package)[0].state == OutcomeState.OK.value


@pytest.mark.django_db
def test_one_collection_reads_identity_once_for_both_hooks(django_assert_num_queries: Any) -> None:
    """The identity read is remembered between `inapplicability` and `source_for`.

    Counted rather than trusted: the two hooks are asked about the same package in
    the same run, and a second query would be a window in which they could
    disagree as well as a cost on every collection.
    """
    package = _a_package()
    collector = PyPIReleaseCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=_answering(),
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )

    try:
        with django_assert_num_queries(1):
            assert collector.inapplicability(package_id=package.pk) == ""
            assert collector.source_for(package_id=package.pk) == THE_LOCATOR
    finally:
        collector.close()


# ---------------------------------------------------------------------------
# The window and the cache, as this collector declares them.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_second_collection_inside_the_window_is_skipped_without_a_call() -> None:
    """`CPM-AD-7`'s window, and the only assertion that shows it: no call was made."""
    package = _a_package()
    _collect(package, transport=_answering())

    second = _answering()
    result = _collect(package, transport=second)

    assert result.state == RunState.SKIPPED
    assert second.calls == []
    assert len(_rows(package)) == 1


@pytest.mark.django_db
def test_an_answer_carrying_a_validator_is_remembered_after_its_evidence_is_written() -> None:
    """This collector declares a cache lifetime, so the base's caching is live for it."""
    package = _a_package()
    cache = RecordingResponseCache()

    _collect(package, transport=_answering(etag=AN_ETAG), cache=cache)

    assert cache.reads == [(COLLECTOR_NAME, THE_LOCATOR)]
    assert [collector for collector, _, _, _ in cache.writes] == [COLLECTOR_NAME]
    assert cache.entries[(COLLECTOR_NAME, THE_LOCATOR)].etag == AN_ETAG


@pytest.mark.django_db
def test_a_revalidated_answer_writes_the_same_evidence_a_body_would_have() -> None:
    """The `304` replay: the same row a `200` would have written, from the remembered body."""
    package = _a_package()
    cache = RecordingResponseCache(
        entries={(COLLECTOR_NAME, THE_LOCATOR): cached_response(body=_document(), etag=AN_ETAG)},
    )
    transport = _answering("", not_modified=True, etag=AN_ETAG)

    result = _collect(package, transport=transport, cache=cache, force=True)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.OK.value
    assert row.latest_version == A_VERSION
    assert row.released_at == UPLOADED_INSTANT
    assert row.requires_python == A_SPECIFIER
    assert transport.sent_headers[0] is not None
    assert AN_ETAG in dict(transport.sent_headers[0]).values()


# ---------------------------------------------------------------------------
# The task.
# ---------------------------------------------------------------------------


class SubstitutedCollector(PyPIReleaseCollector):
    """The collector the task builds, with every seam already filled.

    The same move `tests/integration/django_apps/test_source_release.py` makes and
    for the same reason: a task takes a package key and nothing else, so the
    collector it constructs is the only seam a case about the task has.
    """

    fixed_transport: ClassVar[Transport | None] = None
    fixed_clock: ClassVar[Clock | None] = None

    def __init__(
        self,
        *,
        clock: Clock,
        transport: Transport | None = None,
        limiter: RateLimiter | None = None,
        response_cache: ResponseCache | None = None,
    ) -> None:
        """Build the collector the task asked for, on the case's own seams.

        Args:
            clock: What the task passed, replaced by the case's stopped one.
            transport: What the task passed, which is nothing.
            limiter: What the task passed, which is nothing.
            response_cache: What the task passed, which is nothing.

        """
        super().__init__(
            clock=type(self).fixed_clock or clock,
            transport=type(self).fixed_transport or transport,
            limiter=FixedLimiter(permitted=True) if limiter is None else limiter,
            response_cache=RecordingResponseCache() if response_cache is None else response_cache,
        )


@pytest.mark.django_db
def test_the_task_records_a_non_python_package_as_not_applicable_without_a_socket() -> None:
    """The real task, the real transport constructed, and no call made -- because none is due.

    The one terminal state this task can reach end to end in a suite that opens no
    socket: the collector says the question does not apply before any locator
    exists, so the `RequestsTransport` the base built is never asked. The returned
    value is the ledger row's state as a string.
    """
    package = _a_package(outcome=OutcomeState.NOT_APPLICABLE.value, primary_type="", primary_purl="")

    returned = collect_pypi_release(package_id=package.pk)

    assert returned == RunState.SUCCEEDED.value
    assert _rows(package)[0].state == OutcomeState.NOT_APPLICABLE.value
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_the_task_lets_an_unresolved_identity_out_as_a_failed_run() -> None:
    """The task wires `package_id` through to the base and lets the refusal out."""
    package = _a_package(outcome=None, primary_type="", primary_purl="")

    with pytest.raises(PyPILocatorError):
        collect_pypi_release(package_id=package.pk)

    assert _run(package).status == RunState.FAILED.value
    assert _rows(package) == []


@pytest.mark.django_db
def test_the_task_carries_force_through_to_the_base_and_returns_how_the_run_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CPM-UJ-1`'s manual recollection is this task, and the flag is live here.

    Three calls through the task -- collect, suppressed, forced -- so the
    difference between them is the flag and nothing else, and the returned string
    is asserted each time.
    """
    monkeypatch.setattr(SubstitutedCollector, "fixed_clock", FixedClock(instant=FIXED_INSTANT))
    monkeypatch.setattr(SubstitutedCollector, "fixed_transport", _answering())
    monkeypatch.setattr(collector_tasks, "PyPIReleaseCollector", SubstitutedCollector)
    package = _a_package()

    first = collect_pypi_release(package_id=package.pk)
    suppressed = collect_pypi_release(package_id=package.pk)
    forced = collect_pypi_release(package_id=package.pk, force=True)

    assert first == RunState.SUCCEEDED.value
    assert suppressed == RunState.SKIPPED.value
    assert forced == RunState.SUCCEEDED.value
    assert len(_rows(package)) == TWO_ROWS


# ---------------------------------------------------------------------------
# The table's own rules, on a migrated schema.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_determinate_row_without_a_version_is_refused_by_the_database() -> None:
    """The first conjunct, isolated: a determinate row names what it observed."""
    package = _a_package()

    with pytest.raises(IntegrityError, match=PYPI_FACTS_CONSTRAINT), transaction.atomic():
        PyPIReleaseSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.OK.value,
            latest_version="",
            released_at=UPLOADED_INSTANT,
        )


@pytest.mark.django_db
def test_a_sentinel_row_carrying_a_version_is_refused_by_the_database() -> None:
    """The second conjunct, isolated."""
    package = _a_package()

    with pytest.raises(IntegrityError, match=PYPI_FACTS_CONSTRAINT), transaction.atomic():
        PyPIReleaseSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.ERROR.value,
            latest_version=A_VERSION,
        )


@pytest.mark.django_db
def test_a_sentinel_row_carrying_a_release_date_is_refused_by_the_database() -> None:
    """The third conjunct, isolated, which no other case here reaches on its own."""
    package = _a_package()

    with pytest.raises(IntegrityError, match=PYPI_FACTS_CONSTRAINT), transaction.atomic():
        PyPIReleaseSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.NOT_FOUND.value,
            released_at=UPLOADED_INSTANT,
        )


@pytest.mark.django_db
def test_a_sentinel_row_carrying_a_specifier_is_refused_by_the_database() -> None:
    """The fourth conjunct, and the one this table adds: a `not_applicable` row observed no metadata."""
    package = _a_package()

    with pytest.raises(IntegrityError, match=PYPI_FACTS_CONSTRAINT), transaction.atomic():
        PyPIReleaseSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.NOT_APPLICABLE.value,
            requires_python=A_SPECIFIER,
        )


@pytest.mark.django_db
def test_a_determinate_row_may_carry_a_version_and_neither_a_date_nor_a_specifier() -> None:
    """The permission the constraint has to grant: a dated version and a declared specifier are not required."""
    package = _a_package()

    PyPIReleaseSnapshot.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=OutcomeState.OK.value,
        latest_version=A_VERSION,
    )

    assert _rows(package)[0].latest_version == A_VERSION


@pytest.mark.django_db
def test_re_observation_inserts_rather_than_updating() -> None:
    """`CPM-AD-2`, on the real table: two observations of one package are two rows."""
    package = _a_package()
    _collect(package, transport=_answering())

    later = FIXED_INSTANT + A_DAY
    _collect(package, transport=_answering(_document(A_LATER_VERSION)), at=later)

    rows = _rows(package)
    assert [row.latest_version for row in rows] == [A_VERSION, A_LATER_VERSION]
    assert [row.observed_at for row in rows] == [FIXED_INSTANT, later]
