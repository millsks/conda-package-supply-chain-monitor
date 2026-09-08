"""KEV cross-reference against real tables: the link, the unknowns, the ledger and the constraint.

`CPM-FR-12` asks for one fact a row can say -- this advisory, which we already
recorded against this package, is one the catalog says is being used against
people, and here is when the catalog added it -- and for one thing a row must never
say, which is that a package is clear when nobody cross-referenced anything. Both
are only true or false once a run exists, and the *link* in particular cannot be
asserted anywhere else: `tests/unit/django_apps/test_kev.py` can show that a
cross-reference carries a finding's key, and only a run can show that following the
key arrives back at the observation the row derives from.

**Half of this module exists because the collector reads another collector's
table.** `CPM-AD-7` does not grant that read; `CPM-SECURITY-S02`'s Spec Change Log
records the exception and the Block If hands the judgement to review. What the
cases here pin is the shape of what was taken: only the newest determinate
vulnerability finding per advisory is read, nothing is written to that table, and a
package whose findings are all non-determinate is a package with nothing to
cross-reference.

**No KEV source ships, so every case declares its own.** The adapter is substituted
at the base's seam (`CPM-AD-27`, `CPM-AD-29`) and the slot is process-global, so
`kev_source_slot` clears it around every case -- and the refusal when nothing is
declared is itself one of the cases.

**The constraint is a database rule here, not a convention.** It is asserted by
writing the rows the collector may not write and watching PostgreSQL -- or SQLite
-- refuse them.

**No case reaches the network.** Every case substitutes the *adapter* at the base's
seam, so no outbound request is issued; the `freshness` helper below constructs a
collector without one, which builds a real `RequestsTransport` and its connection
pool, makes no call, and is closed.

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

from conda_sentinel.collectors import kev as kev_module
from conda_sentinel.collectors import tasks as collector_tasks
from conda_sentinel.collectors.advisories import declare_advisory_source
from conda_sentinel.collectors.advisories import declared_advisory_source
from conda_sentinel.collectors.advisories import withdraw_advisory_source
from conda_sentinel.collectors.kev import ADVISORY_ID_FIELD
from conda_sentinel.collectors.kev import ALIASES_FIELD
from conda_sentinel.collectors.kev import COLLECTOR_NAME
from conda_sentinel.collectors.kev import DATE_ADDED_FIELD
from conda_sentinel.collectors.kev import ENTRIES_FIELD
from conda_sentinel.collectors.kev import KEV_FRESHNESS_TARGET
from conda_sentinel.collectors.kev import KEV_HEADERS
from conda_sentinel.collectors.kev import KEV_OBSERVATION_WINDOW
from conda_sentinel.collectors.kev import KEV_RETRIES
from conda_sentinel.collectors.kev import KEV_SOURCE_LOCATOR
from conda_sentinel.collectors.kev import NO_ADVISORY_SOURCE_DETAIL
from conda_sentinel.collectors.kev import NO_CATALOG_DATE_DETAIL
from conda_sentinel.collectors.kev import NOT_LISTED_DETAIL
from conda_sentinel.collectors.kev import NOTHING_MATCHED_DETAIL
from conda_sentinel.collectors.kev import NOTHING_OBSERVED_DETAIL
from conda_sentinel.collectors.kev import ONLY_STALE_FINDINGS_DETAIL
from conda_sentinel.collectors.kev import UNKNOWN_LOCATOR_DETAIL
from conda_sentinel.collectors.kev import UNKNOWN_SCHEME_DETAIL
from conda_sentinel.collectors.kev import UNREADABLE_CATALOG_DATE_DETAIL
from conda_sentinel.collectors.kev import KevCollector
from conda_sentinel.collectors.kev import KevDocumentError
from conda_sentinel.collectors.kev import KevEvidenceError
from conda_sentinel.collectors.kev import KevSourceError
from conda_sentinel.collectors.kev import current_findings
from conda_sentinel.collectors.kev import declare_kev_source
from conda_sentinel.collectors.kev import declared_kev_source
from conda_sentinel.collectors.kev import withdraw_kev_source
from conda_sentinel.collectors.match_confidence import MatchConfidence
from conda_sentinel.collectors.models import KEV_APPLICABILITY_CONSTRAINT
from conda_sentinel.collectors.models import KEV_FACTS_CONSTRAINT
from conda_sentinel.collectors.models import KevFinding
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import KEV_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import KEV_UNKNOWN
from conda_sentinel.collectors.outcomes import LISTED
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.collectors.outcomes import NOT_LISTED
from conda_sentinel.collectors.outcomes import VULNERABILITY_UNKNOWN
from conda_sentinel.collectors.sweep import dispatch
from conda_sentinel.collectors.tasks import COLLECT_KEV_TASK_NAME
from conda_sentinel.collectors.tasks import collect_kev
from conda_sentinel.core.clock import Clock
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.freshness import UNOBSERVED_STATUS
from conda_sentinel.core.models import AppendOnlyError
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.runs import RunLedgerError
from conda_sentinel.core.runs import RunState
from conda_sentinel.core.transport import TransportError
from conda_sentinel.identity.models import Package
from config.celery_app import app
from tests.clocks import FIXED_INSTANT
from tests.collectors import FixedLimiter
from tests.collectors import RecordedTransport
from tests.collectors import RecordingResponseCache
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from collections.abc import Iterator

    from conda_sentinel.core.collection import CollectionResult
    from conda_sentinel.core.rate_limit import RateLimiter
    from conda_sentinel.core.response_cache import ResponseCache
    from conda_sentinel.core.transport import Transport

#: The package the cases ask about, and the identity it carries. Nothing this
#: collector does reads the purl -- the catalog is a document about advisories --
#: but a package without one is not a package this product has resolved, and a
#: fixture that omitted it would be testing a state resolution does not produce.
A_NAME: Final[str] = "aiohttp"
A_PURL: Final[str] = "pkg:pypi/aiohttp@3.9.1"
A_VERSION: Final[str] = "3.9.1"

#: The locator the adapter records for the answer it gives -- deliberately *not*
#: the opaque question the run asked, because a determinate row must name where its
#: facts came from and the catalog is the adapter's business (`CPM-AD-29`).
AN_ANSWERING_SOURCE: Final[str] = "https://kev.invalid/catalog.json"

#: What the catalogs say, and what this product records.
AN_ADVISORY: Final[str] = "CVE-2024-23334"
ANOTHER_ADVISORY: Final[str] = "GHSA-5h86-8mv2-jq9f"
A_THIRD_ADVISORY: Final[str] = "PYSEC-2024-42"
#: Two more CVEs, for the cases that are about *listing* rather than about schemes:
#: `not_listed` is claimed only where the catalog states an advisory in the
#: finding's own scheme, so a case using a GHSA finding against a CVE-only catalog
#: would measure the scheme rule rather than the one it is written about.
ANOTHER_CVE: Final[str] = "CVE-2023-49081"
A_THIRD_CVE: Final[str] = "CVE-2022-33124"
AN_AFFECTED_RANGE: Final[str] = ">=1.0.5,<3.9.2"
A_CATALOG_DATE: Final[str] = "2024-02-06T00:00:00+00:00"
A_CATALOG_INSTANT: Final[datetime] = datetime(2024, 2, 6, tzinfo=UTC)
ANOTHER_CATALOG_DATE: Final[str] = "2023-11-13T00:00:00+00:00"
ANOTHER_CATALOG_INSTANT: Final[datetime] = datetime(2023, 11, 13, tzinfo=UTC)

#: The counts the cases assert against, one named constant per concept.
TWO_ROWS: Final[int] = 2
THREE_ROWS: Final[int] = 3
ONE_REQUEST: Final[int] = 1

#: A primary key nothing has created, for the case about a package that is not
#: there. Far above anything the sequence will issue inside one case.
NO_SUCH_PACKAGE: Final[int] = 9_999_999

#: An instant inside this collector's freshness window, and one outside it. Derived
#: from the target rather than written out, so a target that moved would move these
#: with it -- and the boundary case below is what says which side of it is current.
JUST_INSIDE_THE_WINDOW: Final[datetime] = FIXED_INSTANT - KEV_FRESHNESS_TARGET
JUST_OUTSIDE_THE_WINDOW: Final[datetime] = FIXED_INSTANT - KEV_FRESHNESS_TARGET - timedelta(seconds=1)


@pytest.fixture(autouse=True)
def an_advisory_source() -> Iterator[None]:
    """Declare an advisory source for every case, and take it away again.

    Autouse because the `unknown` row's `detail` asks the advisory slot *first* --
    with no source declared, no advisory could have been recorded about any package,
    and that is a different piece of work for an operator from a package the
    collector observed and matched nothing to. Every case here is about the other
    three reasons, so the declared state is the one they should run in; the case
    that is about the undeclared one withdraws it itself.

    The adapter is never called: this fixture declares the *advisory* slot, and no
    vulnerability collection runs in this module.

    Yields:
        Nothing; an advisory source is declared for the duration of the case.

    """
    declare_advisory_source(RecordedTransport())
    yield
    if declared_advisory_source() is not None:
        withdraw_advisory_source()


@pytest.fixture(autouse=True)
def kev_source_slot() -> Iterator[None]:
    """Assert the one adapter slot starts empty, and leave it empty.

    Autouse because the slot is process-global: a case that left an adapter declared
    would change what every later case in the suite reads, and one that found the
    slot already full would be measuring somebody else's declaration.

    Yields:
        Nothing; the slot is empty for the duration of the case.

    """
    assert declared_kev_source() is None
    yield
    if declared_kev_source() is not None:
        withdraw_kev_source()


def _entry(
    advisory_id: str = AN_ADVISORY,
    *,
    date_added: str | None = A_CATALOG_DATE,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """Return one catalog entry as an adapter would state it.

    Args:
        advisory_id: The advisory's identifier.
        date_added: The date the catalog states, or `None` for a catalog that states
            none.
        aliases: The other identifiers the catalog says the same advisory carries.

    Returns:
        The entry object.

    """
    stated: dict[str, Any] = {ADVISORY_ID_FIELD: advisory_id, DATE_ADDED_FIELD: date_added}
    if aliases is not None:
        stated[ALIASES_FIELD] = aliases
    return stated


def _catalog(*entries: dict[str, Any]) -> str:
    """Return the body a KEV source adapter would record.

    Args:
        *entries: The advisories the catalog lists, in order.

    Returns:
        The JSON body.

    """
    return json.dumps({ENTRIES_FIELD: list(entries)})


def _answering(body: str = "", **payload: Any) -> RecordedTransport:
    """Return an adapter answering with one recorded payload.

    Args:
        body: The catalog it recorded, when the case wants the ordinary answer.
        **payload: Whatever else the payload should carry -- `found`, or a whole
            `failure` for the case where the adapter raises.

    Returns:
        The recorded transport, ready to be declared as the KEV source.

    """
    if "failure" in payload:
        return RecordedTransport(failure=payload["failure"])
    return RecordedTransport(payload=recorded_payload(source=AN_ANSWERING_SOURCE, body=body, **payload))


class _RaisingAdapter:
    """An adapter whose `fetch` raises something that is not a `TransportError`.

    A class rather than `RecordedTransport(failure=...)`, because that helper is
    typed to raise a `TransportError` and the whole point of this one is the
    exception the base does **not** catch.

    Attributes:
        failure: What `fetch` raises.

    """

    def __init__(self, failure: BaseException) -> None:
        """Remember what to raise.

        Args:
            failure: The exception `fetch` raises.

        """
        self.failure = failure

    def fetch(self, source: str, *, headers: Any = None) -> Any:
        """Raise, without recording anything.

        Args:
            source: The locator the base asked for.
            headers: The headers it composed.

        Raises:
            BaseException: Whatever this adapter was built with.

        """
        raise self.failure


def _a_package(name: str = A_NAME, *, purl: str = A_PURL) -> Package:
    """Return a saved package carrying an identity resolution would have produced.

    Args:
        name: The canonical name, unique per case.
        purl: The primary purl.

    Returns:
        The saved row.

    """
    return Package.objects.create(canonical_name=name, primary_purl=purl, resolved_at=FIXED_INSTANT)


def _a_finding(
    package: Package,
    advisory_id: str = AN_ADVISORY,
    *,
    at: datetime = FIXED_INSTANT,
    state: str = MATCHED,
) -> VulnerabilityFinding:
    """Return a saved vulnerability finding for this package to cross-reference.

    Created directly rather than through `VulnerabilityCollector`, because what this
    module is about starts *after* an advisory has been recorded -- and running the
    sibling collector here would make every case depend on its document contract as
    well as on this one's.

    Args:
        package: The package the finding is about.
        advisory_id: The advisory it names.
        at: The instant it was observed, which is what makes one finding supersede
            another.
        state: The state it carries. `matched` unless a case is about a finding this
            collector must *not* read.

    Returns:
        The saved row.

    """
    if state != MATCHED:
        # The table's own constraint: a row that is not determinate carries no
        # advisory fact at all, which is precisely why it has nothing to
        # cross-reference.
        return VulnerabilityFinding.objects.create(
            observed_at=at,
            package=package,
            state=state,
            detail="the advisory source was read and matched nothing",
        )
    return VulnerabilityFinding.objects.create(
        observed_at=at,
        package=package,
        state=MATCHED,
        advisory_id=advisory_id,
        affected_range=AN_AFFECTED_RANGE,
        matched_version=A_VERSION,
        match_confidence=MatchConfidence.EXACT_RANGE.value,
    )


def _collect(  # noqa: PLR0913 - one parameter per seam the base takes; a bundle would hide the one under test
    package: Package,
    *,
    transport: Transport,
    at: datetime = FIXED_INSTANT,
    force: bool = False,
    permitted: bool = True,
    cache: RecordingResponseCache | None = None,
    limiter: FixedLimiter | None = None,
) -> CollectionResult:
    """Run one collection through a substituted adapter.

    Args:
        package: The package to observe.
        transport: The adapter substituted at the base's seam (`CPM-AD-27`).
        at: The instant the run's clock is stopped at.
        force: Whether to bypass the observation window (`CPM-UJ-1`).
        permitted: What the substituted limiter answers, when none is passed.
        cache: The response cache to use, or a fresh recording one.
        limiter: The limiter to use, so a case can read what it was asked.

    Returns:
        What the run did.

    """
    collector = KevCollector(
        clock=FixedClock(instant=at),
        transport=transport,
        limiter=limiter if limiter is not None else FixedLimiter(permitted=permitted),
        response_cache=cache if cache is not None else RecordingResponseCache(),
    )
    try:
        return collector.collect(package_id=package.pk, force=force)
    finally:
        collector.close()


def _rows(package: Package) -> list[KevFinding]:
    """Return this package's cross-references, oldest first.

    Args:
        package: The package to read.

    Returns:
        The rows, ordered by primary key.

    """
    return list(KevFinding.objects.filter(package=package).order_by("pk"))


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
        status: The status the evidence carries, or `None` for a caller holding no
            observation.
        now: The instant staleness is measured from.

    Returns:
        The `FreshnessReport`.

    """
    collector = KevCollector(clock=FixedClock(instant=FIXED_INSTANT))
    try:
        if status is None:
            return collector.freshness(package_id=package.pk, now=now)
        return collector.freshness(package_id=package.pk, now=now, status=status)
    finally:
        collector.close()


# ---------------------------------------------------------------------------
# AC 1: each KEV finding links to the vulnerability finding it derives from and
# records the catalog date added.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_listed_advisory_links_to_the_finding_it_derives_from_and_records_the_catalog_date() -> None:
    """AC 1, whole: the link followed back, and the date the catalog stated.

    **The link is asserted by following the foreign key**, not by comparing keys.
    A row carrying the right integer in the wrong column, or a relation pointed at
    the wrong model, would pass a key comparison and fail here -- and following it
    is what a reviewer does when they ask "which observation is this about".
    """
    package = _a_package()
    finding = _a_finding(package)
    adapter = _answering(_catalog(_entry()))

    result = _collect(package, transport=adapter)

    (row,) = _rows(package)
    assert row.state == LISTED
    assert row.vulnerability_finding == finding
    assert row.vulnerability_finding.advisory_id == AN_ADVISORY
    assert row.vulnerability_finding.package_id == package.pk
    assert row.catalog_date_added == A_CATALOG_INSTANT
    assert row.package_id == package.pk
    assert row.source == AN_ANSWERING_SOURCE
    assert row.observed_at == FIXED_INSTANT
    assert result.state is RunState.SUCCEEDED
    assert _run(package).status == RunState.SUCCEEDED.value
    assert adapter.calls == [KEV_SOURCE_LOCATOR]


@pytest.mark.django_db
def test_three_findings_of_which_two_are_listed_are_three_rows_each_linked_to_its_own_finding() -> None:
    """The matrix's plural row: three rows, never merged, and no row links to two findings.

    The count of calls shows the three rows came out of one collection rather than
    out of three runs, which is what the observation window and the ledger row per
    `(collector, package)` require.
    """
    package = _a_package()
    listed = _a_finding(package, AN_ADVISORY)
    also_listed = _a_finding(package, ANOTHER_CVE)
    unlisted = _a_finding(package, A_THIRD_CVE)
    adapter = _answering(_catalog(_entry(), _entry(ANOTHER_CVE, date_added=ANOTHER_CATALOG_DATE)))

    _collect(package, transport=adapter)

    rows = _rows(package)
    by_finding = {row.vulnerability_finding_id: row for row in rows}
    assert len(rows) == THREE_ROWS
    assert set(by_finding) == {listed.pk, also_listed.pk, unlisted.pk}
    assert by_finding[listed.pk].state == LISTED
    assert by_finding[listed.pk].catalog_date_added == A_CATALOG_INSTANT
    assert by_finding[also_listed.pk].state == LISTED
    assert by_finding[also_listed.pk].catalog_date_added == ANOTHER_CATALOG_INSTANT
    assert by_finding[unlisted.pk].state == NOT_LISTED
    assert by_finding[unlisted.pk].catalog_date_added is None
    assert len(adapter.calls) == ONE_REQUEST
    assert CollectionRun.objects.filter(collector=COLLECTOR_NAME, package=package).count() == 1


@pytest.mark.django_db
def test_no_advisory_listed_writes_one_row_per_finding_saying_so_and_succeeds() -> None:
    """A negative that was established, and the run succeeded because the catalog answered.

    **The catalog states an advisory in the findings' own scheme**, which is what
    makes the negative establishable at all: a catalog that used no CVE identifier
    would have nothing to say about a CVE finding, and this collector records
    `unknown` there rather than the reassuring value.

    The `detail` is what stops the value being read as a clean verdict: the advisory
    is still an advisory, and all this row says is that this catalog does not list
    it.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY)
    _a_finding(package, ANOTHER_CVE)

    result = _collect(package, transport=_answering(_catalog(_entry(A_THIRD_CVE))))

    rows = _rows(package)
    assert len(rows) == TWO_ROWS
    assert {row.state for row in rows} == {NOT_LISTED}
    assert {row.detail for row in rows} == {NOT_LISTED_DETAIL}
    assert all(row.catalog_date_added is None for row in rows)
    assert all(row.vulnerability_finding_id is not None for row in rows)
    assert result.state is RunState.SUCCEEDED


@pytest.mark.django_db
def test_an_advisory_in_a_scheme_the_catalog_never_states_is_unknown_rather_than_not_listed() -> None:
    """The aliasing failure, end to end, and the row that refuses to claim the reassuring value.

    A finding recorded under a GHSA identifier against a CVE-only catalog is not an
    advisory the catalog does not list: it is an advisory the catalog never had the
    vocabulary to list. Recording `not_listed` would be an established negative the
    run did not establish, permanently, about whether something is being exploited.
    The row still links to its finding, because it is about that advisory.
    """
    package = _a_package()
    finding = _a_finding(package, ANOTHER_ADVISORY)

    result = _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.state == KEV_UNKNOWN
    assert row.detail == UNKNOWN_SCHEME_DETAIL
    assert row.vulnerability_finding_id == finding.pk
    assert row.catalog_date_added is None
    assert result.state is RunState.SUCCEEDED


@pytest.mark.django_db
def test_an_alias_the_catalog_states_turns_that_unknown_into_a_real_answer() -> None:
    """The other half, and the reason the entry contract carries aliases at all.

    The same GHSA finding, against a catalog that states the GHSA spelling as an
    alias of its CVE entry, is `listed` with that entry's date -- which is what a
    catalog that knows its cross-scheme identifiers can give an operator, and what
    an exact comparison alone could never have found.
    """
    package = _a_package()
    finding = _a_finding(package, ANOTHER_ADVISORY)

    _collect(package, transport=_answering(_catalog(_entry(aliases=[ANOTHER_ADVISORY]))))

    (row,) = _rows(package)
    assert row.state == LISTED
    assert row.vulnerability_finding_id == finding.pk
    assert row.catalog_date_added == A_CATALOG_INSTANT


@pytest.mark.django_db
def test_a_catalog_that_states_no_date_records_a_blank_one_and_says_the_catalog_stated_none() -> None:
    """Blank means missing (PRD Appendix A.1), and the row says which kind of missing it is."""
    package = _a_package()
    _a_finding(package)

    _collect(package, transport=_answering(_catalog(_entry(date_added=None))))

    (row,) = _rows(package)
    assert row.state == LISTED
    assert row.catalog_date_added is None
    assert row.detail == NO_CATALOG_DATE_DETAIL


@pytest.mark.django_db
def test_a_catalog_date_the_collector_cannot_read_is_recorded_as_missing_rather_than_guessed() -> None:
    """The row is still determinate -- the catalog lists the advisory -- and the date is not invented.

    A bare date is the shape a catalogue is likeliest to publish and it parses naive;
    assuming it to be UTC would be a permanent claim about when an advisory became
    known-exploited, shifted by a guess (`CPM-AD-26`).
    """
    package = _a_package()
    _a_finding(package)

    _collect(package, transport=_answering(_catalog(_entry(date_added="2024-02-06"))))

    (row,) = _rows(package)
    assert row.state == LISTED
    assert row.catalog_date_added is None
    assert row.detail.startswith(UNREADABLE_CATALOG_DATE_DETAIL)
    assert "2024-02-06" in row.detail


@pytest.mark.django_db
def test_the_declared_headers_reach_the_adapter_and_nothing_conditional_does() -> None:
    """Headers reach a source only through the base (`CPM-AD-20`, `CPM-AD-27`).

    And no validator is sent, because this collector declares `NO_CACHE`: the cache
    read, the cache write and the conditional header are all short-circuited, so an
    adapter that is not HTTP is never asked a question it cannot answer.
    """
    package = _a_package()
    _a_finding(package)
    adapter = _answering(_catalog(_entry()))
    cache = RecordingResponseCache()

    _collect(package, transport=adapter, cache=cache)

    (sent,) = adapter.sent_headers
    assert sent is not None
    assert set(KEV_HEADERS.items()) <= set(sent.items())
    assert cache.reads == []
    assert cache.writes == []


# ---------------------------------------------------------------------------
# The read of another collector's table, and what "current" means.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_only_the_most_recent_finding_per_advisory_is_cross_referenced() -> None:
    """The matrix's superseded row: append-only evidence, one current answer.

    Re-observation inserts (`CPM-AD-2`), so a package accumulates many rows per
    advisory. Cross-referencing all of them would write one KEV row per historical
    observation, every day, and a reviewer could not tell which one was about today.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY, at=FIXED_INSTANT - timedelta(days=2))
    newest = _a_finding(package, AN_ADVISORY, at=FIXED_INSTANT - timedelta(days=1))

    _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.vulnerability_finding_id == newest.pk
    assert VulnerabilityFinding.objects.filter(package=package).count() == TWO_ROWS


@pytest.mark.django_db
def test_two_findings_at_one_instant_resolve_by_primary_key_so_a_replay_reproduces_the_row() -> None:
    """The tie-break every cut-off-bound read in this product states (`CPM-FR-22`).

    Two rows sharing an observation instant is not hypothetical -- one collection
    stamps every row it writes with the same instant -- so an ordering on
    `observed_at` alone would pick whichever the database returned last, and a
    replay of the same evidence could link to a different row.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY)
    later_key = _a_finding(package, AN_ADVISORY)

    _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.vulnerability_finding_id == later_key.pk


@pytest.mark.django_db
def test_one_advisory_spelled_two_ways_across_observations_is_still_one_advisory() -> None:
    """Grouped without regard to case, and the row keeps the newest observation's own spelling.

    Two spellings would otherwise be two current advisories, so one advisory would
    be cross-referenced twice and a reviewer would have two rows to reconcile.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY.upper(), at=FIXED_INSTANT - timedelta(days=1))
    newest = _a_finding(package, AN_ADVISORY.lower())

    _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.vulnerability_finding_id == newest.pk
    assert row.state == LISTED


@pytest.mark.django_db
def test_a_non_determinate_vulnerability_finding_is_nothing_to_cross_reference() -> None:
    """A finding that names no advisory has nothing in it to ask the catalog about.

    `vulnerability_findings` refuses an `unknown` row that carries an advisory
    identifier, so this is not a filter this collector could omit and get right by
    accident -- it would build a cross-reference with a blank identifier, which the
    value object refuses.
    """
    package = _a_package()
    _a_finding(package, state=VULNERABILITY_UNKNOWN)

    _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.state == KEV_UNKNOWN
    assert row.vulnerability_finding_id is None


@pytest.mark.django_db
def test_the_read_of_the_sibling_table_writes_nothing_to_it() -> None:
    """The half of the `CPM-AD-7` exception that is not taken, measured rather than promised.

    The Spec Change Log takes a read: one table, read-only. This runs a whole
    collection and compares the sibling table's rows before and after, by key and by
    every column a run could plausibly touch -- which is the assertion a reviewer
    weighing that exception actually wants.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY)
    _a_finding(package, ANOTHER_ADVISORY)
    before = list(VulnerabilityFinding.objects.order_by("pk").values())

    _collect(package, transport=_answering(_catalog(_entry())))

    assert list(VulnerabilityFinding.objects.order_by("pk").values()) == before


@pytest.mark.django_db
def test_current_findings_reads_one_advisory_per_package_and_ignores_another_packages() -> None:
    """The read itself, at its own seam, because `translate` can only show it indirectly.

    A read that dropped its package filter would cross-reference the whole
    inventory's advisories against every package, and every row would still carry a
    link that resolved -- to a finding about a different package. The package each
    finding carries is asserted for the same reason: it is what the row is built
    from, so a row pairing two packages is unreachable from this writer.
    """
    package = _a_package()
    mine = _a_finding(package, AN_ADVISORY)
    _a_finding(_a_package("somebody-else"), ANOTHER_CVE)

    read = current_findings(package_id=package.pk, now=FIXED_INSTANT)

    assert [finding.finding_id for finding in read.findings] == [mine.pk]
    assert [finding.advisory_id for finding in read.findings] == [AN_ADVISORY]
    assert [finding.package_id for finding in read.findings] == [package.pk]
    assert read.excluded == 0
    assert read.observed
    assert read.matched


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("at", "current"),
    [(JUST_INSIDE_THE_WINDOW, True), (JUST_OUTSIDE_THE_WINDOW, False)],
    ids=["at-the-boundary", "one-second-past-it"],
)
def test_a_matched_finding_is_current_only_while_it_is_no_older_than_the_freshness_target(
    at: datetime,
    *,
    current: bool,
) -> None:
    """The bound that retires an advisory, and the boundary it turns on.

    The sibling collector records "nothing matched today" as one row naming no
    advisory, so nothing there ever retires an advisory: without this bound, one
    match would be cross-referenced for the life of the package. The target is the
    natural bound because the two tables are the same signal class -- a
    cross-reference computed from evidence this product already reports as stale is
    a fresh-looking row about a stale fact.

    Inclusive at the boundary, which is the same direction `core/freshness.py`
    reports staleness in: a package does not stop being current at exactly the
    instant its target elapses.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY, at=at)

    read = current_findings(package_id=package.pk, now=FIXED_INSTANT)

    assert bool(read.findings) is current
    assert read.excluded == (0 if current else 1)
    assert read.matched


@pytest.mark.django_db
def test_a_run_that_excluded_a_stale_observation_says_so_on_every_row_it_writes() -> None:
    """A reader holds one row, not a run, so the row says it was computed against a partial view.

    On every row rather than one of them, and the duplication is the point: a row
    that did not say so would be indistinguishable from one computed against the
    whole of what this product records.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY)
    _a_finding(package, ANOTHER_CVE, at=JUST_OUTSIDE_THE_WINDOW)

    _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.state == LISTED
    assert "excluded 1 advisory observation(s)" in row.detail
    assert str(KEV_FRESHNESS_TARGET) in row.detail


@pytest.mark.django_db
def test_a_package_whose_every_advisory_is_stale_records_that_rather_than_a_clean_answer() -> None:
    """The fourth of the four ways there is nothing to cross-reference, and it is its own sentence.

    "Everything we matched has gone stale" is not "we matched nothing": the first
    says the advisory collector has stopped running, and the second says it ran and
    found nothing. `CPM-FR-6` is why they are not one sentence.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY, at=JUST_OUTSIDE_THE_WINDOW)

    result = _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.state == KEV_UNKNOWN
    assert row.detail.startswith(ONLY_STALE_FINDINGS_DETAIL)
    assert "excluded 1 advisory observation(s)" in row.detail
    assert row.vulnerability_finding_id is None
    assert result.state is RunState.SUCCEEDED


@pytest.mark.django_db
def test_a_matched_finding_naming_no_advisory_is_refused_rather_than_cross_referenced() -> None:
    """`vulnerability_findings` tests for the empty string, so a blank-looking identifier reaches here.

    Answering `not_listed` about it would be the reassuring value written about an
    advisory nobody named -- so the run records `error` and an operator learns their
    advisory table holds a row that should not exist.
    """
    package = _a_package()
    VulnerabilityFinding.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=MATCHED,
        advisory_id="   ",
        affected_range=AN_AFFECTED_RANGE,
        matched_version=A_VERSION,
        match_confidence=MatchConfidence.EXACT_RANGE.value,
    )

    with pytest.raises(KevEvidenceError, match="names no advisory"):
        _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.state == OutcomeState.ERROR.value
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_package_with_more_current_advisories_than_one_collection_records_is_refused() -> None:
    """The bound on what one run writes, measured against a stand-in rather than the real number.

    Two thousand rows in one `bulk_create` is not a fixture worth building, so the
    bound itself is substituted and the *behaviour* is asserted: refused rather than
    truncated, because recording the first N without saying so would be a permanent
    partial answer nothing could tell from a complete one.
    """
    package = _a_package()
    _a_finding(package, AN_ADVISORY)
    _a_finding(package, ANOTHER_CVE)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(kev_module, "MAX_CROSS_REFERENCES", 1)
        with pytest.raises(KevEvidenceError, match="records at most"):
            _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.state == OutcomeState.ERROR.value
    assert KevFinding.objects.filter(package=package, state=LISTED).count() == 0


# ---------------------------------------------------------------------------
# Nothing to cross-reference is `unknown`, never a clean answer.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_with_no_current_finding_writes_one_unknown_row_and_reads_no_catalog() -> None:
    """The matrix's no-findings row, end to end, and the assertion this case exists to make honestly.

    The adapter is scripted with a catalog that *would* have produced a determinate
    row, so what is asserted is that the answer was not read: a `translate` that fell
    through to the reader would find nothing to cross-reference against it and write
    nothing at all.

    **The call to the adapter is asserted rather than withheld.**
    `core/collection.py` charges the allowance and calls the transport before
    `translate` is reached, and the only call-free path it offers writes
    `not_applicable`, which this table refuses -- so one *is* made, and the row does
    not claim otherwise. `CPM-SECURITY-S01` shipped a row denying a call it had made
    and was patched for it; this is the one place that would fail again.
    """
    package = _a_package()
    _a_finding(package, state=VULNERABILITY_UNKNOWN)
    adapter = _answering(_catalog(_entry()))

    result = _collect(package, transport=adapter)

    (row,) = _rows(package)
    assert row.state == KEV_UNKNOWN
    assert row.detail == NOTHING_MATCHED_DETAIL
    assert row.vulnerability_finding_id is None
    assert row.catalog_date_added is None
    assert row.source == KEV_SOURCE_LOCATOR
    assert result.state is RunState.SUCCEEDED
    # The call happened. The row does not claim otherwise.
    assert adapter.calls == [KEV_SOURCE_LOCATOR]
    assert "no question was asked" not in row.detail
    assert KevFinding.objects.filter(package=package, state=LISTED).count() == 0


@pytest.mark.django_db
def test_an_unreadable_catalog_is_still_unread_when_there_is_nothing_to_cross_reference() -> None:
    """The claim the case above cannot make on its own, because its catalog parses.

    "The payload is not read" is asserted there by a catalog that *would* have
    produced a determinate row -- but a `translate` that read it anyway would find
    nothing to cross-reference against it and write the same `unknown` row, so the
    case passes either way. A catalog that cannot be read at all is what makes the
    claim falsifiable: reading it would raise, write an `error` row and fail the
    run, and none of that happens.
    """
    package = _a_package()

    result = _collect(package, transport=_answering("<html>gateway timeout</html>"))

    (row,) = _rows(package)
    assert row.state == KEV_UNKNOWN
    assert result.state is RunState.SUCCEEDED
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("declared", "expected"),
    [(True, NOTHING_OBSERVED_DETAIL), (False, NO_ADVISORY_SOURCE_DETAIL)],
    ids=["advisory-source-declared", "advisory-source-withdrawn"],
)
def test_the_unknown_row_says_which_of_the_four_ways_there_was_nothing_to_cross_reference(
    *,
    declared: bool,
    expected: str,
) -> None:
    """`CPM-FR-6` again, on the one row this table writes most often.

    Four different pieces of work hide behind "nothing to cross-reference": no
    advisory source is declared, so no advisory could have been recorded about
    anything; the vulnerability collector has not observed this package; it observed
    it and matched nothing; or everything it matched is stale. Only the third is a
    statement about the package. The two here are the two a package with no
    vulnerability row at all can be in, and they are told apart by asking the
    advisory slot -- which is a read of a *declaration* rather than of another
    collector.
    """
    package = _a_package()
    if not declared:
        withdraw_advisory_source()

    _collect(package, transport=_answering(_catalog(_entry())))

    (row,) = _rows(package)
    assert row.state == KEV_UNKNOWN
    assert row.detail == expected


@pytest.mark.django_db
def test_an_unknown_row_reads_back_as_an_observation_rather_than_as_never_observed() -> None:
    """The whole of why a package with nothing to cross-reference writes a row (`CPM-FR-6`).

    A package with no row reads as unobserved, which then ages into stale -- so "we
    had nothing to cross-reference" and "nobody looked" would be the same answer on
    every read surface.

    **What this proves is the instant, not the status.** `freshness` takes the
    status from its caller, so asserting it back is a tautology; what the *table*
    supplies is `observed_at`, and it is read here off the row rather than off the
    constant a caller passed. The control beside it is what makes the claim
    falsifiable: the same read, against a package no run has touched, answers the
    other thing -- no instant at all, and a status this collector never wrote.
    """
    package = _a_package()

    _collect(package, transport=_answering(_catalog()))

    (row,) = _rows(package)
    observed = _freshness(package, status=row.state)
    never = _freshness(_a_package("another-package"))

    assert observed.observed_at == row.observed_at
    assert not observed.stale
    assert never.observed_at is None
    assert never.status == UNOBSERVED_STATUS
    # And the two are told apart by the *instant* rather than by the status, which
    # is the whole reason the row has to exist: `UNOBSERVED_STATUS` is `unknown`
    # too, so a surface reading the status alone cannot tell "we had nothing to
    # cross-reference" from "nobody looked". `observed_at` is what can.
    assert never.status == row.state
    assert observed.observed_at is not None


@pytest.mark.django_db
def test_a_cross_reference_ages_like_any_other_observation() -> None:
    """It is evidence, so it goes stale on this collector's declared target.

    Which is the point of writing it: an answer that never aged would let a collector
    that stopped running go on reporting yesterday's catalog for ever -- and a
    catalog is the one source in this product whose *additions* are the news.
    """
    package = _a_package()
    _a_finding(package)

    _collect(package, transport=_answering(_catalog(_entry())))

    fresh = _freshness(package, now=FIXED_INSTANT + KEV_FRESHNESS_TARGET)
    stale = _freshness(package, now=FIXED_INSTANT + KEV_FRESHNESS_TARGET + timedelta(seconds=1))

    assert not fresh.stale
    assert stale.stale


# ---------------------------------------------------------------------------
# The paths the base decides.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_adapter_that_fails_writes_an_error_row_and_fails_the_run() -> None:
    """The base's own path, with the reason on both the row and the ledger."""
    package = _a_package()
    _a_finding(package)
    unreachable = TransportError("the KEV catalog is unreachable", source=KEV_SOURCE_LOCATOR)

    result = _collect(package, transport=_answering(failure=unreachable))

    (row,) = _rows(package)
    assert row.state == OutcomeState.ERROR.value
    assert "unreachable" in row.detail
    assert row.source == KEV_SOURCE_LOCATOR
    assert row.vulnerability_finding_id is None
    assert result.state is RunState.FAILED
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_an_adapter_that_answers_not_modified_fails_the_run_because_nothing_asked() -> None:
    """This collector declares `NO_CACHE`, so a `304` is an answer to a question nobody asked.

    No validator was sent and no body is held, so there is nothing to replay and the
    base refuses rather than recording an empty observation. An adapter that
    revalidates against its own remembered state must return the body it is
    revalidating; the module's adapter contract says so, and every other obligation
    it states has a case -- this is the one that did not.
    """
    package = _a_package()
    _a_finding(package)

    result = _collect(package, transport=_answering(not_modified=True))

    (row,) = _rows(package)
    assert row.state == OutcomeState.ERROR.value
    assert "nothing asked it what changed" in row.detail
    assert result.state is RunState.FAILED


@pytest.mark.django_db
def test_an_adapter_that_raises_anything_but_a_transport_error_leaves_no_row_at_all() -> None:
    """The one way to get no row out of this collector, and it is the seam this story makes pluggable.

    `core/collection.py` catches `TransportError` and nothing else, so any other
    exception escapes `collect()` **before** an evidence row is written -- which is
    `CPM-NFR-3`'s "never no row" defeated by an adapter rather than by the collector.
    Characterised here rather than defended: defending it would mean catching every
    exception around a third-party call in `core/collection.py`, which is not this
    story's to change. What this buys is that the consequence is a fact an adapter
    author can be pointed at.
    """
    package = _a_package()
    _a_finding(package)

    with pytest.raises(RuntimeError, match="a client library that was not converted"):
        _collect(package, transport=_RaisingAdapter(RuntimeError("a client library that was not converted")))

    assert _rows(package) == []
    # The ledger still records the run: the recorder finalizes `failed` from the
    # exception on its way out, so the run is not invisible -- only the evidence is.
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_spent_allowance_writes_an_error_row_and_issues_no_call() -> None:
    """`CPM-AD-20`: refused rather than issued unlimited, and the refusal is on the record."""
    package = _a_package()
    _a_finding(package)
    adapter = _answering(_catalog(_entry()))
    limiter = FixedLimiter(permitted=False)

    result = _collect(package, transport=adapter, permitted=False, limiter=limiter)

    (row,) = _rows(package)
    assert row.state == OutcomeState.ERROR.value
    assert adapter.calls == []
    assert result.state is RunState.FAILED
    (asked,) = limiter.asks
    assert asked[0] == COLLECTOR_NAME
    assert asked[-1] == 1 + KEV_RETRIES


@pytest.mark.django_db
def test_a_source_that_reports_the_locator_does_not_exist_says_it_is_not_a_clear_package() -> None:
    """The one row in this table a reader could mistake for reassuring, and it says so itself.

    The base writes `not_found` and finalizes the run `succeeded`, because the source
    answered -- but on this table that answer is about the *locator*, and a row that
    did not say so would be the only place `CPM-SM-2` could be defeated without
    anybody writing a determinate row.
    """
    package = _a_package()
    _a_finding(package)

    result = _collect(package, transport=_answering(found=False))

    (row,) = _rows(package)
    assert row.state == OutcomeState.NOT_FOUND.value
    assert UNKNOWN_LOCATOR_DETAIL in row.detail
    assert row.vulnerability_finding_id is None
    assert result.state is RunState.SUCCEEDED


@pytest.mark.django_db
def test_an_unreadable_catalog_writes_an_error_row_before_it_raises() -> None:
    """`CPM-NFR-3` on the parse path: never a clean result and never no row.

    The row is written first and the exception is re-raised unchanged, so the ledger
    row is `failed` and the evidence says why.
    """
    package = _a_package()
    _a_finding(package)

    with pytest.raises(KevDocumentError):
        _collect(package, transport=_answering("<html>gateway timeout</html>"))

    (row,) = _rows(package)
    assert row.state == OutcomeState.ERROR.value
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_catalog_that_lists_one_advisory_twice_is_refused_rather_than_read_for_one_of_them() -> None:
    """A document defect, not two dates: the source contradicted itself about one advisory."""
    package = _a_package()
    _a_finding(package)
    body = _catalog(_entry(), _entry(AN_ADVISORY, date_added=ANOTHER_CATALOG_DATE))

    with pytest.raises(KevDocumentError, match="more than one entry"):
        _collect(package, transport=_answering(body))

    (row,) = _rows(package)
    assert row.state == OutcomeState.ERROR.value
    assert KevFinding.objects.filter(package=package, state=LISTED).count() == 0


@pytest.mark.django_db
def test_the_observation_window_suppresses_a_second_run_and_force_bypasses_it() -> None:
    """`CPM-AD-7`'s window and `CPM-UJ-1`'s manual recollection, on the real declarations."""
    package = _a_package()
    _a_finding(package)
    adapter = _answering(_catalog(_entry()))

    first = _collect(package, transport=adapter)
    inside = KEV_OBSERVATION_WINDOW / 2
    suppressed = _collect(package, transport=adapter, at=FIXED_INSTANT + inside)
    forced = _collect(package, transport=adapter, at=FIXED_INSTANT + inside, force=True)

    assert first.state is RunState.SUCCEEDED
    assert suppressed.state is RunState.SKIPPED
    assert forced.state is RunState.SUCCEEDED
    assert len(_rows(package)) == TWO_ROWS


@pytest.mark.django_db
def test_re_observing_one_cross_reference_inserts_a_second_row_rather_than_updating_the_first() -> None:
    """`CPM-AD-2`: evidence is append-only, and the tuple that looks unique is what a re-run repeats.

    `(package, vulnerability_finding)` is exactly the pair a daily run repeats for as
    long as that finding stays the current one for its advisory, so a unique
    constraint over it would turn every second day into an `IntegrityError`.
    """
    package = _a_package()
    finding = _a_finding(package)
    adapter = _answering(_catalog(_entry()))

    _collect(package, transport=adapter)
    _collect(package, transport=adapter, at=FIXED_INSTANT + timedelta(days=1))

    rows = _rows(package)
    assert len(rows) == TWO_ROWS
    assert [row.vulnerability_finding_id for row in rows] == [finding.pk, finding.pk]
    assert rows[0].observed_at != rows[1].observed_at


@pytest.mark.django_db
def test_collecting_a_package_that_is_not_there_leaves_nothing_behind_at_all() -> None:
    """`CPM-EVIDENCE-S09`: the recorder checks the key before it opens a row."""
    collector = KevCollector(clock=FixedClock(instant=FIXED_INSTANT), transport=_answering(_catalog()))

    try:
        with pytest.raises(RunLedgerError):
            collector.collect(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()

    assert CollectionRun.objects.filter(collector=COLLECTOR_NAME).count() == 0
    assert KevFinding.objects.count() == 0


# ---------------------------------------------------------------------------
# The declared adapter, and what a component with none does.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_run_with_no_declared_kev_source_records_a_failed_run_and_writes_no_evidence() -> None:
    """A misconfiguration rather than a cross-reference failure, so it leaves no observation.

    An evidence row here would be a permanent claim that this run looked at a
    catalog, for every package in the inventory, produced by a component that has no
    catalog at all.

    **The run is still recorded**, which is the correction this case exists for. An
    adapter withdrawn between a dispatch drawing its selection and its tasks running
    leaves ten thousand enqueued tasks that each refuse; refusing before the recorder
    opened -- which is what the first pass did -- would leave no trace of any of
    them, a day on which nothing was observed and nothing anywhere says so.
    """
    package = _a_package()
    _a_finding(package)

    with pytest.raises(KevSourceError, match="declare_kev_source"):
        collect_kev(package_id=package.pk)

    assert _rows(package) == []
    (run,) = CollectionRun.objects.filter(collector=COLLECTOR_NAME)
    assert run.status == RunState.FAILED.value
    assert run.package_id == package.pk
    assert "declare_kev_source" in run.detail


@pytest.mark.django_db
def test_a_run_for_a_package_that_is_not_there_still_leaves_nothing_behind_with_no_source() -> None:
    """The recorder checks the key before it opens a row, and that ordering survives the change above.

    Opening a ledger row to record the refusal must not turn a bad package key into
    a row about a package that does not exist: `CPM-EVIDENCE-S09` puts the key check
    first, and this asserts the two rules compose rather than trading one for the
    other.
    """
    with pytest.raises(RunLedgerError):
        collect_kev(package_id=NO_SUCH_PACKAGE)

    assert CollectionRun.objects.filter(collector=COLLECTOR_NAME).count() == 0
    assert KevFinding.objects.count() == 0


@pytest.mark.django_db
def test_the_task_reads_the_declared_adapter_and_writes_the_cross_reference_through_the_base() -> None:
    """The whole path a worker takes, with the adapter declared exactly as an operator would."""
    package = _a_package()
    # Observed *now* rather than at the suite's fixed instant, because the task
    # builds a `SystemClock` and this collector calls an advisory observation
    # current only inside its freshness window. A fixture stamped three days ago
    # would be honestly stale, and this case is not about that.
    finding = _a_finding(package, at=datetime.now(UTC))
    declare_kev_source(_answering(_catalog(_entry())))

    ended = collect_kev(package_id=package.pk)

    (row,) = _rows(package)
    assert ended == RunState.SUCCEEDED.value
    assert row.state == LISTED
    assert row.vulnerability_finding_id == finding.pk


@pytest.mark.django_db
def test_the_task_carries_force_through_to_the_base_rather_than_dropping_it() -> None:
    """`CPM-UJ-1`'s manual recollection always bypasses the window and always writes.

    The task constructs its own collector, so the only way to see what it did with
    `force` -- and to see it without a socket -- is to substitute the class the task
    names.
    """
    package = _a_package()
    _a_finding(package)
    declare_kev_source(_answering(_catalog(_entry())))
    recorded: list[tuple[int, bool]] = []
    shared = SubstitutedCollector.collected

    try:
        collector_tasks.KevCollector = SubstitutedCollector  # type: ignore[misc]
        SubstitutedCollector.collected = recorded
        first = collect_kev(package_id=package.pk)
        second = collect_kev(package_id=package.pk, force=True)
    finally:
        collector_tasks.KevCollector = KevCollector  # type: ignore[misc]
        SubstitutedCollector.collected = shared

    assert first == RunState.SUCCEEDED.value
    assert second == RunState.SUCCEEDED.value
    assert recorded == [(package.pk, False), (package.pk, True)]
    assert len(_rows(package)) == TWO_ROWS


class SubstitutedCollector(KevCollector):
    """A collector whose limiter, cache and clock are the case's, recording what it was asked.

    The transport is deliberately *not* substituted here: the task passes the
    declared adapter, and what this class exists to observe is that the task's own
    arguments reach the base.

    **The recording list is replaced per case rather than appended to a module-level
    one**, on the terms the sibling module's own substitution states: a `ClassVar`
    every case shared would carry one case's calls into the next under any ordering
    the suite happens to pick.

    Attributes:
        collected: Every `(package_id, force)` pair `collect` was called with, for
            the duration of one case.

    """

    collected: ClassVar[list[tuple[int, bool]]] = []

    def __init__(
        self,
        *,
        clock: Clock,
        transport: Transport | None = None,
        limiter: RateLimiter | None = None,
        response_cache: ResponseCache | None = None,
    ) -> None:
        """Build the collector with the case's seams rather than the task's defaults.

        Args:
            clock: Ignored: the case's fixed clock is used instead, so the rows a
                task writes carry a known instant.
            transport: The adapter the task passed, which is what is used.
            limiter: Ignored, in favour of a permitting one.
            response_cache: Ignored, in favour of a recording one.

        """
        super().__init__(
            clock=FixedClock(instant=FIXED_INSTANT),
            transport=transport,
            limiter=FixedLimiter(permitted=True),
            response_cache=RecordingResponseCache(),
        )

    def collect(self, *, package_id: int, force: bool = False) -> CollectionResult:
        """Record what the task asked for, then collect.

        Args:
            package_id: The package the task named.
            force: Whether the task asked to bypass the window.

        Returns:
            What the run did.

        """
        type(self).collected.append((package_id, force))
        return super().collect(package_id=package_id, force=force)


# ---------------------------------------------------------------------------
# The selection the sweep offers.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_undeclared_component_offers_the_sweep_no_package_at_all() -> None:
    """The shipped state: one `succeeded` dispatch a day saying nothing was selected."""
    _a_package()

    assert list(KevCollector.selectable_packages()) == []


@pytest.mark.django_db
def test_a_declared_component_offers_every_package_including_those_with_nothing_to_cross_reference() -> None:
    """The `unknown` row needs a *scheduled* run to write it, so the sweep offers every package.

    Selecting only packages that already carry a vulnerability finding would look
    like an optimisation and would be the defect `CPM-SECURITY-S01` was patched for,
    in a second table: the package with nothing to cross-reference would never be
    enqueued, would write no row, and would read as never-observed.
    """
    declare_kev_source(_answering(_catalog()))
    with_finding = _a_package()
    _a_finding(with_finding)
    without = _a_package("nothing-recorded")

    assert sorted(KevCollector.selectable_packages()) == sorted([with_finding.pk, without.pk])


@pytest.mark.django_db
def test_a_sweep_writes_the_unknown_row_for_a_package_with_nothing_to_cross_reference() -> None:
    """The half the selection case cannot make on its own: the row a scheduled run actually writes.

    A selection is a list of keys; what `CPM-SM-2` is about is a *row*. This runs the
    collection the dispatch would have enqueued and reads back what a later surface
    would see -- an `unknown` observation with an instant, rather than a package
    nobody ever looked at.
    """
    declare_kev_source(_answering(_catalog()))
    without = _a_package("nothing-recorded")

    assert without.pk in set(KevCollector.selectable_packages())

    _collect(without, transport=_answering(_catalog()))

    (row,) = _rows(without)
    assert row.state == KEV_UNKNOWN
    assert _freshness(without, status=row.state).observed_at == FIXED_INSTANT


@pytest.mark.django_db
def test_the_dispatch_enqueues_this_collectors_own_task_for_every_selected_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep end to end, which is the only place the selection and the task name meet.

    `collectors/sweep.py` derives `cpm.collect.<name>` from the registry key, so a
    task declared under any other name would be enqueued into a queue nothing
    consumes -- silent non-delivery rather than an error. The task's `apply_async` is
    intercepted rather than left to the eager suite, which would otherwise run a real
    collection per package.
    """
    declare_kev_source(_answering(_catalog()))
    with_finding = _a_package()
    _a_finding(with_finding)
    without = _a_package("nothing-recorded")
    accepted: list[int] = []

    def _apply_async(*, kwargs: dict[str, Any], **_options: Any) -> None:
        accepted.append(int(kwargs["package_id"]))

    monkeypatch.setattr(app.tasks[COLLECT_KEV_TASK_NAME], "apply_async", _apply_async)
    outcome = dispatch(collector=COLLECTOR_NAME, clock=FixedClock(instant=FIXED_INSTANT))

    assert outcome.state is RunState.SUCCEEDED
    # Both, including the package with nothing to cross-reference: the `unknown` row
    # this story guarantees is only written if a scheduled run writes it.
    assert sorted(accepted) == sorted([with_finding.pk, without.pk])


# ---------------------------------------------------------------------------
# The constraints, as the database enforces them.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("state", [LISTED, NOT_LISTED], ids=[LISTED, NOT_LISTED])
def test_a_determinate_row_that_names_no_vulnerability_finding_is_refused_by_the_database(state: str) -> None:
    """AC 1 made a rule the table enforces rather than a rule one writer follows.

    A cross-reference with no link is a claim about an advisory that nothing ties to
    the observation that found it -- and nothing else in this product would ever
    create that link, so there would be no way to reconstruct it afterwards.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=KEV_FACTS_CONSTRAINT), transaction.atomic():
        KevFinding.objects.create(observed_at=FIXED_INSTANT, package=package, state=state)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [OutcomeState.NOT_FOUND.value, OutcomeState.ERROR.value],
    ids=["not-found", "error"],
)
def test_a_sentinel_row_may_not_name_a_finding(state: str) -> None:
    """A sentinel is written for a call that produced no catalog, so it derives from nothing.

    A link there would be a fact about a document that does not exist. The `unknown`
    row is deliberately not in this list: it may carry a link or not, and the two are
    different facts -- one is a specific advisory the catalog cannot speak to, the
    other a package with nothing to cross-reference at all.
    """
    package = _a_package()
    finding = _a_finding(package)

    with pytest.raises(IntegrityError, match=KEV_FACTS_CONSTRAINT), transaction.atomic():
        KevFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=state,
            vulnerability_finding=finding,
        )


@pytest.mark.django_db
def test_an_unknown_row_may_name_the_advisory_the_catalog_could_not_speak_to() -> None:
    """The one relaxation the scheme rule needs, and it is a fact rather than a loosening.

    A finding whose identifier uses a scheme the catalog never states is an advisory
    the catalog cannot speak to, and the row saying so is about *that* advisory --
    so it names it. The row for a package with nothing to cross-reference at all
    names none, and both are permitted by the same constraint.
    """
    package = _a_package()
    finding = _a_finding(package)

    KevFinding.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=KEV_UNKNOWN,
        vulnerability_finding=finding,
        detail=UNKNOWN_SCHEME_DETAIL,
    )
    KevFinding.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=KEV_UNKNOWN,
        detail=NOTHING_MATCHED_DETAIL,
    )

    assert [row.vulnerability_finding_id for row in _rows(package)] == [finding.pk, None]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [NOT_LISTED, KEV_UNKNOWN, OutcomeState.NOT_FOUND.value, OutcomeState.ERROR.value],
    ids=["not-listed", "unknown", "not-found", "error"],
)
def test_a_catalog_date_on_a_row_the_catalog_did_not_list_is_refused_by_the_database(state: str) -> None:
    """A date is something only a listed advisory has.

    On a `not_listed` row it would say the catalog both does and does not list the
    advisory; on an `unknown` or sentinel row it would be a date for an advisory
    nothing named.
    """
    package = _a_package()
    finding = _a_finding(package)

    with pytest.raises(IntegrityError, match=KEV_FACTS_CONSTRAINT), transaction.atomic():
        KevFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=state,
            vulnerability_finding=finding if state == NOT_LISTED else None,
            catalog_date_added=A_CATALOG_INSTANT,
        )


@pytest.mark.django_db
def test_the_table_takes_a_listed_row_that_states_no_catalog_date() -> None:
    """The anti-vacuity half: the constraint refuses what it must and permits what it must.

    A rule that required a date on every `listed` row would make the honest answer
    unwritable and push the collector into inventing one -- which is exactly what
    the catalog-date cases above are written against.
    """
    package = _a_package()
    finding = _a_finding(package)

    KevFinding.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=LISTED,
        vulnerability_finding=finding,
        detail=NO_CATALOG_DATE_DETAIL,
    )

    (row,) = _rows(package)
    assert row.catalog_date_added is None
    assert row.vulnerability_finding_id == finding.pk


@pytest.mark.django_db
def test_a_row_claiming_the_question_was_never_about_this_package_is_refused_by_the_database() -> None:
    """The rule the collector argues at length, made a rule the table enforces.

    `KevCollector.sentinel_evidence` refuses `not_applicable` and the applicability
    hook never answers a reason, but both are one writer's rules -- and
    `not_applicable` is in this vocabulary by construction, because `outcome_type`
    supplies all four sentinels and refuses a type that drops one.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=KEV_APPLICABILITY_CONSTRAINT), transaction.atomic():
        KevFinding.objects.create(observed_at=FIXED_INSTANT, package=package, state=KEV_NOT_APPLICABLE)


@pytest.mark.django_db
def test_a_row_pairing_one_package_with_another_packages_observation_is_refused_at_the_write() -> None:
    """The rule SQL cannot express as a check, held where every constructed write passes.

    A `CHECK` is per row over that row's own columns and the predicate spans two
    tables; the composite foreign key that would express it needs a
    `UniqueConstraint` on `vulnerability_findings`, which `EVIDENCE.02-AUDIT-003`
    bans outright. So `KevFinding.save` refuses it -- which is `objects.create()`
    and every hand-written save -- and `collectors/kev.py` takes the row's package
    from the finding, so its own `bulk_create` cannot produce one. The model
    docstring names what that leaves.
    """
    mine = _a_package()
    theirs = _a_package("somebody-else")
    about_theirs = _a_finding(theirs)

    with pytest.raises(AppendOnlyError, match="which is an observation of package"), transaction.atomic():
        KevFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=mine,
            state=LISTED,
            vulnerability_finding=about_theirs,
        )

    assert _rows(mine) == []


@pytest.mark.django_db
def test_the_table_takes_a_row_whose_finding_is_about_the_same_package() -> None:
    """The anti-vacuity half: the guard refuses a pair rather than the relation."""
    package = _a_package()
    finding = _a_finding(package)

    KevFinding.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=LISTED,
        vulnerability_finding=finding,
    )

    (row,) = _rows(package)
    assert row.vulnerability_finding_id == finding.pk


@pytest.mark.django_db
def test_the_table_takes_every_other_state_this_vocabulary_carries() -> None:
    """The anti-vacuity half: the applicability rule refuses one value rather than narrowing the column."""
    package = _a_package()

    for state in (KEV_UNKNOWN, OutcomeState.NOT_FOUND.value, OutcomeState.ERROR.value):
        KevFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=state,
            detail="something happened",
        )

    assert {row.state for row in _rows(package)} == {
        KEV_UNKNOWN,
        OutcomeState.NOT_FOUND.value,
        OutcomeState.ERROR.value,
    }
