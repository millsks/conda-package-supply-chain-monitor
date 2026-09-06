"""Upstream release collection against real tables: the rows, the ledger and the refusals.

`CPM-FR-7` asks for four things, and every one of them is only true or false once
a run exists: the row is written, the lookup status is on it, the ledger says how
the run ended, and a repository that publishes nothing is recorded rather than
left to age into staleness. Which is why this module sits beside
`tests/unit/django_apps/test_source_release.py`: the locators, the documents and
the declarations are decided before a run does, and are asserted there.

**Everything here drives `collect()` or the task, and that is what puts it in this
tier.** `collect()` opens `core/ledger.py`'s recorder, whose first act is to
insert a `running` row, and the tag fallback reads the package's repository URL --
so a case about the window, about a sentinel row, about the fallback, or about how
a run ended touches a database by construction. This is the same split
`CPM-EVIDENCE-S05` recorded for its own I/O matrix and resolved the same way.

**AC 1's "or tag" and AC 2 are two cases here, and the second is narrower than it
looks.** A repository that publishes no releases falls back to its tags, so
`not_found` is reached only by one that has neither -- and the case that proves it
does not stop at the row. "Records that fact rather than reporting the package
stale" is a claim about what a *later* reader sees, and a case that stopped at "a
`not_found` row exists" would pass identically if the row were never written at
all. `test_a_repository_with_neither_releases_nor_tags_is_observed_rather_than_left_to_go_stale`
asks `core/freshness.py` the question the read surfaces will ask, and a paired
case shows that read answering the other thing.

**No socket is opened.** Every case substitutes the transport at the base's seam,
which is what `CPM-AD-27` opens it for. The two that drive the Celery task do it
differently for a stated reason: the task builds its own transport, so one reaches
a refusal that fires before any call is made, and the other substitutes the
collector the task constructs -- which is the only seam a task has, and is the
same move `tests/integration/django_apps/test_identity_overrides.py` makes when it
substitutes a model's `save`.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the database as found.
`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field
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
from conda_package_supply_chain_monitor.collectors.models import RELEASE_FACTS_CONSTRAINT
from conda_package_supply_chain_monitor.collectors.models import SourceReleaseSnapshot
from conda_package_supply_chain_monitor.collectors.source_release import ABSENT_CAVEAT
from conda_package_supply_chain_monitor.collectors.source_release import COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.source_release import NO_RELEASES_DETAIL
from conda_package_supply_chain_monitor.collectors.source_release import NO_TAGS_DETAIL
from conda_package_supply_chain_monitor.collectors.source_release import SOURCE_RELEASE_HEADERS
from conda_package_supply_chain_monitor.collectors.source_release import TAGGED_DETAIL
from conda_package_supply_chain_monitor.collectors.source_release import SourceLocatorError
from conda_package_supply_chain_monitor.collectors.source_release import SourceReleaseCollector
from conda_package_supply_chain_monitor.collectors.source_release import SourceReleaseDocumentError
from conda_package_supply_chain_monitor.collectors.source_release import releases_locator
from conda_package_supply_chain_monitor.collectors.source_release import tags_locator
from conda_package_supply_chain_monitor.collectors.tasks import collect_source_release
from conda_package_supply_chain_monitor.core.clock import Clock
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.freshness import UNOBSERVED_STATUS
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.core.transport import Payload
from conda_package_supply_chain_monitor.core.transport import TransportError
from conda_package_supply_chain_monitor.identity.models import Package
from tests.clocks import FIXED_INSTANT
from tests.collectors import FixedLimiter
from tests.collectors import RecordingResponseCache
from tests.collectors import cached_response
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conda_package_supply_chain_monitor.core.collection import CollectionResult
    from conda_package_supply_chain_monitor.core.rate_limit import RateLimiter
    from conda_package_supply_chain_monitor.core.response_cache import ResponseCache
    from conda_package_supply_chain_monitor.core.transport import Transport

#: The repository the packages in this module are resolved to, and the two
#: locators it produces. Derived rather than written out: a case here is about
#: what a *run* does with a locator, and `tests/unit/django_apps/test_source_release.py`
#: is where the locators' own spelling is pinned.
A_REPOSITORY: Final[str] = "https://github.com/conda-forge/numpy-feedstock"
THE_LOCATOR: Final[str] = releases_locator(A_REPOSITORY)
THE_TAGS_LOCATOR: Final[str] = tags_locator(A_REPOSITORY)

#: When the releases in these documents were published, and the same instant to
#: assert against.
PUBLISHED: Final[str] = "2026-04-11T14:00:00Z"
PUBLISHED_INSTANT: Final[datetime] = datetime(2026, 4, 11, 14, 0, tzinfo=UTC)

#: The tag the determinate cases observe, and a second one for the case that
#: observes twice.
A_TAG: Final[str] = "v2.1.0"
A_LATER_TAG: Final[str] = "v3.0.0"

#: The entity tag a source hands back, so a case can show the answer was
#: remembered for the next conditional request and replayed on the one after.
AN_ETAG: Final[str] = '"a1b2c3"'

#: How many rows and how many calls the cases that do a thing twice expect. Named
#: because `PLR2004` is right about a bare number in an assertion.
TWO_ROWS: Final[int] = 2
TWO_CALLS: Final[int] = 2

#: The gap between two observations in the re-observation case. Longer than the
#: declared observation window, so the second collection is not suppressed and the
#: case is about re-observation rather than about the window.
A_DAY: Final[timedelta] = timedelta(days=1)

#: A primary key no row in this module holds. Every case rolls back, so nothing
#: reaches it by accident, and it is large rather than merely unused so that a
#: sequence which happened to reach it would have to have been asked for.
NO_SUCH_PACKAGE: Final[int] = 9_999_999


@dataclass(slots=True)
class ScriptedTransport:
    """A transport that answers each locator from its own script.

    `tests/collectors.py`'s `RecordedTransport` answers every call with one
    payload, which is all the base's own cases ever need: they make one call. This
    collector makes two on the tag-fallback path, and a double that answered both
    with one script could not tell a case that read tags from one that read the
    release list twice.

    Attributes:
        answers: What to return for each locator.
        failures: What to raise for each locator instead.
        calls: Every locator `fetch` was handed, in order.
        sent_headers: The header mapping each call carried, in the same order.

    """

    answers: dict[str, Payload] = field(default_factory=dict)
    failures: dict[str, TransportError] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    sent_headers: list[Mapping[str, str] | None] = field(default_factory=list)

    def fetch(self, source: str, *, headers: Mapping[str, str] | None = None) -> Payload:
        """Record the request and answer from the script for this locator.

        Args:
            source: The locator the collector asked for.
            headers: The headers the base composed for it.

        Returns:
            The scripted payload.

        Raises:
            TransportError: When one was scripted for this locator.
            RuntimeError: When nothing was scripted for it. A raise rather than an
                `assert`, because `assert` vanishes under `python -O` and would
                then return `None` where a `Payload` is annotated -- and a helper
                that invented an empty payload would let a case pass by observing
                nothing.

        """
        self.calls.append(source)
        self.sent_headers.append(headers)
        if source in self.failures:
            raise self.failures[source]
        if source not in self.answers:
            message = f"ScriptedTransport was asked to fetch {source!r}, which nothing scripted"
            raise RuntimeError(message)
        return self.answers[source]


def _document(*entries: dict[str, Any]) -> str:
    """Return the body a source would serve for these entries.

    Args:
        *entries: The releases or tags the document lists.

    Returns:
        The JSON body.

    """
    return json.dumps(list(entries))


def _a_release(tag: str = A_TAG, published_at: str = PUBLISHED) -> dict[str, Any]:
    """Return one ordinary published release.

    Args:
        tag: The tag it carries.
        published_at: When it was published.

    Returns:
        The release object a source would list.

    """
    return {"tag_name": tag, "published_at": published_at, "draft": False, "prerelease": False}


def _a_tag(name: str = A_TAG) -> dict[str, Any]:
    """Return one tag, as the tags endpoint lists it.

    Args:
        name: The tag's name.

    Returns:
        The tag object, carrying the one field this collector reads and the commit
        reference it ignores.

    """
    return {"name": name, "commit": {"sha": "0" * 40}}


def _releases(*entries: dict[str, Any]) -> ScriptedTransport:
    """Return a transport that answers the release locator with these entries.

    Args:
        *entries: The releases the document lists.

    Returns:
        The scripted transport.

    """
    return ScriptedTransport(
        answers={THE_LOCATOR: recorded_payload(source=THE_LOCATOR, body=_document(*entries))},
    )


def _a_package(name: str = "numpy", *, repository: str = A_REPOSITORY) -> Package:
    """Return a saved package resolved to a source repository.

    Created directly rather than through `resolve_package_shell`, because what
    this module is about starts *after* an identity exists: the resolution path
    has its own suite, and reaching for it here would make every case depend on a
    second story's contract.

    Args:
        name: The canonical name, unique per case.
        repository: What the identity established as the source repository, or
            the empty string for a package nothing resolved.

    Returns:
        The saved row.

    """
    return Package.objects.create(
        canonical_name=name,
        resolved_at=FIXED_INSTANT,
        source_repository_url=repository,
    )


def _collect(  # noqa: PLR0913 - one parameter per seam the base takes; a bundle would hide the one under test
    package: Package,
    *,
    transport: ScriptedTransport,
    at: datetime = FIXED_INSTANT,
    force: bool = False,
    permitted: bool = True,
    cache: RecordingResponseCache | None = None,
) -> CollectionResult:
    """Run one collection through a scripted transport.

    Args:
        package: The package to observe.
        transport: The transport substituted at the base's seam (`CPM-AD-27`).
        at: The instant the run's clock is stopped at, so a case that observes
            twice places the two observations apart by a stated interval rather
            than by however long the test took.
        force: Whether to bypass the observation window (`CPM-UJ-1`).
        permitted: What the substituted limiter answers. Substituted in every
            case, so none depends on a counter another case left in the cache.
        cache: The response cache to use, substituted for the same reason.

    Returns:
        What the run did.

    """
    collector = SourceReleaseCollector(
        clock=FixedClock(instant=at),
        transport=transport,
        limiter=FixedLimiter(permitted=permitted),
        response_cache=cache if cache is not None else RecordingResponseCache(),
    )
    try:
        return collector.collect(package_id=package.pk, force=force)
    finally:
        collector.close()


def _rows(package: Package) -> list[SourceReleaseSnapshot]:
    """Return this package's observations, oldest first.

    Args:
        package: The package to read.

    Returns:
        The rows, ordered by primary key so a case reads them in the order they
        were inserted.

    """
    return list(SourceReleaseSnapshot.objects.filter(package=package).order_by("pk"))


def _run(package: Package) -> CollectionRun:
    """Return the most recent ledger row for this collector and package.

    Args:
        package: The package the run was scoped to.

    Returns:
        The row, newest first, so a case that collects twice reads the second.

    """
    return CollectionRun.objects.filter(collector=COLLECTOR_NAME, package=package).order_by("-pk").first()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# AC 1: the observation, and the lookup status recorded explicitly.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_released_repository_is_recorded_with_its_version_date_and_activity() -> None:
    """AC 1: latest release, its date, and a repository activity signal, on one row.

    Also the three things a case about the row alone would not see: the transport
    was asked for the locator this package's repository produces, the request
    carried the headers the collector declared -- which is `CPM-AD-20`'s "headers
    reach the socket only through the base" observed from the outside -- and the
    locator reached the row, which is what lets an append-only history say which
    repository each observation came from.
    """
    package = _a_package()
    transport = _releases(_a_release())

    result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == 1
    assert transport.calls == [THE_LOCATOR]
    assert dict(SOURCE_RELEASE_HEADERS).items() <= dict(transport.sent_headers[0] or {}).items()

    row = _rows(package)[0]
    assert row.source == THE_LOCATOR
    assert row.state == OutcomeState.OK.value
    assert row.latest_version == A_TAG
    assert row.released_at == PUBLISHED_INSTANT
    assert row.last_activity_at == PUBLISHED_INSTANT
    assert row.releases_seen == 1
    assert row.observed_at == FIXED_INSTANT
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_an_unreadable_repository_is_an_observation_and_says_what_it_cannot_prove() -> None:
    """AC 1's `not_found`: the source answered, and the answer was `404`.

    `succeeded` rather than `failed`, and that is the base's rule rather than this
    collector's: `CPM-AD-5` keeps "we looked and it is not there" apart from
    "looking failed" precisely so a reader is never asked to infer which happened.

    What the row adds is the caveat the state cannot carry. GitHub answers `404`
    to an absent repository and to a private, moved or blocked one alike, and this
    collector sends no credential -- so the row records `not_found` because that is
    what the source said, and records in `detail` that it may equally mean
    unreadable. `releases_seen` is NULL because this run read no document at all.
    """
    package = _a_package()
    transport = ScriptedTransport(answers={THE_LOCATOR: recorded_payload(source=THE_LOCATOR, found=False, body="")})

    result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_FOUND.value
    assert row.latest_version == ""
    assert row.releases_seen is None
    assert row.source == THE_LOCATOR
    assert ABSENT_CAVEAT in row.detail
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_an_unreachable_source_is_an_error_row_and_a_failed_run() -> None:
    """AC 1's `error`, and `CPM-NFR-3`'s "never a clean result, never no row".

    The row is what matters here rather than the ledger: a failing call that wrote
    nothing would leave the package looking unobserved, which reads as `unknown`
    now and as stale later -- the degradation `CPM-NFR-3` says must never look
    clean. It carries no absence caveat, because nothing said the repository was
    absent.
    """
    package = _a_package()
    transport = ScriptedTransport(
        failures={THE_LOCATOR: TransportError("the source did not answer", source=THE_LOCATOR)},
    )

    result = _collect(package, transport=transport)

    assert result.state == RunState.FAILED
    assert result.evidence_rows == 1
    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert row.detail != ""
    assert ABSENT_CAVEAT not in row.detail
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_document_that_cannot_be_read_writes_an_error_row_before_it_raises() -> None:
    """A parser that no longer matches its source is an `error`, on the record first.

    The base catches whatever `translate` raised, writes the row, and re-raises
    unchanged -- so the exception reaching the task is the same object, and the
    observation exists either way. Both halves are asserted, because the write is
    the half that would disappear silently.
    """
    package = _a_package()
    transport = ScriptedTransport(
        answers={THE_LOCATOR: recorded_payload(source=THE_LOCATOR, body="not a release document")},
    )

    with pytest.raises(SourceReleaseDocumentError):
        _collect(package, transport=transport)

    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert _run(package).status == RunState.FAILED.value


# ---------------------------------------------------------------------------
# AC 1's "or tag", and AC 2.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_repository_that_only_tags_records_its_newest_tag() -> None:
    """AC 1's "or tag", end to end, and the second call it costs.

    Publishing a GitHub Release is a deliberate act many projects never perform.
    Recording `not_found` for all of them would be a false fact in a log nothing
    may correct, so an empty release list falls back to the repository's tags --
    and the fallback fires *only* then, which is what keeps the second call off
    every repository that does publish releases.

    What the row records is weaker than a release and says so: the version, no
    date at all, `releases_seen` still zero because the release list really was
    empty, and the tags locator in `source` so a reader can tell which endpoint
    answered without a second status vocabulary.
    """
    package = _a_package()
    transport = ScriptedTransport(
        answers={
            THE_LOCATOR: recorded_payload(source=THE_LOCATOR, body="[]"),
            THE_TAGS_LOCATOR: recorded_payload(source=THE_TAGS_LOCATOR, body=_document(_a_tag(), _a_tag("v2.0.0"))),
        },
    )

    result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert transport.calls == [THE_LOCATOR, THE_TAGS_LOCATOR]
    row = _rows(package)[0]
    assert row.state == OutcomeState.OK.value
    assert row.latest_version == A_TAG
    assert row.released_at is None
    assert row.last_activity_at is None
    assert row.releases_seen == 0
    assert row.source == THE_TAGS_LOCATOR
    assert row.detail == TAGGED_DETAIL


@pytest.mark.django_db
def test_a_repository_that_releases_is_never_asked_about_its_tags() -> None:
    """The anti-vacuity half: the fallback is a fallback rather than a second call.

    A collector that asked both endpoints every time would pass the case above and
    would double this collector's spend against an allowance the story already
    records as too small. One call, and only one, for the ordinary case.
    """
    package = _a_package()
    transport = _releases(_a_release())

    _collect(package, transport=transport)

    assert transport.calls == [THE_LOCATOR]


@pytest.mark.django_db
def test_a_repository_with_neither_releases_nor_tags_is_observed_rather_than_left_to_go_stale() -> None:
    """AC 2, asserted where the difference actually shows: the freshness read.

    Once the tag fallback exists, "a repository that publishes no releases at all"
    is the narrower claim it sounds like: nothing released *and* nothing tagged.
    That produces a `not_found` row carrying this run's instant, and the run
    succeeds.

    The half that makes it AC 2 rather than a detail is the last three assertions:
    `core/freshness.py` -- the module every read surface asks -- reports that
    observation as *not stale* and carrying `not_found`, where a package this
    collector had written nothing for would come back with no instant at all and
    would age from there.
    """
    package = _a_package()
    transport = ScriptedTransport(
        answers={
            THE_LOCATOR: recorded_payload(source=THE_LOCATOR, body="[]"),
            THE_TAGS_LOCATOR: recorded_payload(source=THE_TAGS_LOCATOR, body="[]"),
        },
    )

    result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_FOUND.value
    assert row.latest_version == ""
    assert row.released_at is None
    assert row.releases_seen == 0
    assert row.detail == NO_TAGS_DETAIL

    collector = SourceReleaseCollector(clock=FixedClock(instant=FIXED_INSTANT))
    try:
        report = collector.freshness(package_id=package.pk, now=FIXED_INSTANT, status=row.state)
    finally:
        collector.close()

    assert report.observed_at == FIXED_INSTANT
    assert report.stale is False


@pytest.mark.django_db
def test_a_package_this_collector_has_not_observed_reads_as_unobserved() -> None:
    """The anti-vacuity half of AC 2: the freshness read can say the other thing.

    Without this, the case above would pass if `freshness` always answered
    "fresh". What makes the `not_found` row worth writing is that the alternative
    -- no row -- is a different and worse answer, and this is it.
    """
    package = _a_package()

    collector = SourceReleaseCollector(clock=FixedClock(instant=FIXED_INSTANT))
    try:
        report = collector.freshness(package_id=package.pk, now=FIXED_INSTANT)
    finally:
        collector.close()

    assert report.observed_at is None
    assert report.status == UNOBSERVED_STATUS


@pytest.mark.django_db
@pytest.mark.parametrize(
    "tags_answer",
    ["failure", "absent", "not-modified"],
    ids=["unreachable", "absent", "answered-a-question-nobody-asked"],
)
def test_a_fallback_that_cannot_be_read_keeps_the_answer_the_release_list_gave(tags_answer: str) -> None:
    """A failed fallback never costs the fact the first call did establish.

    "This repository publishes no releases" is something this run read and can
    stand behind, so a tags endpoint that is unreachable, absent, or answering
    `304` to an unconditional request leaves that answer in place with the reason
    appended. Failing the whole collection instead would throw away an observation
    to report a second one that could not be made.
    """
    package = _a_package()
    transport = ScriptedTransport(answers={THE_LOCATOR: recorded_payload(source=THE_LOCATOR, body="[]")})
    if tags_answer == "failure":
        transport.failures[THE_TAGS_LOCATOR] = TransportError("no answer", source=THE_TAGS_LOCATOR)
    elif tags_answer == "absent":
        transport.answers[THE_TAGS_LOCATOR] = recorded_payload(source=THE_TAGS_LOCATOR, found=False, body="")
    else:
        transport.answers[THE_TAGS_LOCATOR] = recorded_payload(
            source=THE_TAGS_LOCATOR,
            body="",
            not_modified=True,
        )

    result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_FOUND.value
    assert row.detail.startswith(NO_RELEASES_DETAIL)
    assert row.detail != NO_RELEASES_DETAIL
    assert row.source == THE_LOCATOR


# ---------------------------------------------------------------------------
# The window, the allowance and the cache, as this collector declares them.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_second_collection_inside_the_window_is_skipped_without_a_call() -> None:
    """`CPM-AD-7`'s window, and the only assertion that shows it: no call was made.

    A skipped run writes a `skipped` ledger row and no evidence, which is a
    decision *not* to observe rather than an observation. The transport's empty
    call list is what distinguishes that from a run that observed and wrote
    nothing.
    """
    package = _a_package()
    _collect(package, transport=_releases(_a_release()))

    second = _releases(_a_release())
    result = _collect(package, transport=second)

    assert result.state == RunState.SKIPPED
    assert result.evidence_rows == 0
    assert second.calls == []
    assert len(_rows(package)) == 1
    assert _run(package).status == RunState.SKIPPED.value


@pytest.mark.django_db
def test_a_forced_collection_bypasses_the_window_and_writes_again() -> None:
    """`CPM-UJ-1`: manual recollection "always bypasses the window and always writes".

    Re-observation inserts (`CPM-AD-2`), so the second run is a second row rather
    than an update -- which is what makes freshness advance and what keeps the
    first observation readable at its own cut-off.
    """
    package = _a_package()
    _collect(package, transport=_releases(_a_release()))

    forced = _releases(_a_release())
    result = _collect(package, transport=forced, force=True)

    assert result.state == RunState.SUCCEEDED
    assert forced.calls == [THE_LOCATOR]
    assert len(_rows(package)) == TWO_ROWS


@pytest.mark.django_db
def test_a_spent_allowance_refuses_the_call_and_records_it() -> None:
    """`CPM-AD-20`: never issued unlimited, and never silently not issued either.

    The limiter is substituted rather than exhausted, so the case is about what
    the collector does with a refusal rather than about the counter -- which
    `tests/unit/django_apps/test_rate_limit.py` owns. The row records `error`
    with no absence caveat, and its `detail` is the base's own sentence naming the
    allowance, which is what an operator reads to tell "we never got to look" from
    "the source is failing".
    """
    package = _a_package()
    transport = _releases(_a_release())

    result = _collect(package, transport=transport, permitted=False)

    assert result.state == RunState.FAILED
    assert transport.calls == []
    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert "allowance" in row.detail


@pytest.mark.django_db
def test_an_answer_carrying_a_validator_is_remembered_after_its_evidence_is_written() -> None:
    """This collector declares a cache lifetime, so the base's caching is live for it.

    `CPM-EVIDENCE-S08` owns the mechanism and proves it; what is asserted here is
    that this collector actually reaches it -- a `NO_CACHE` declaration would make
    every one of these lists empty and nothing else in the suite would notice.
    The ordering claim comes with it: the entry exists only because the evidence
    write succeeded first.
    """
    package = _a_package()
    cache = RecordingResponseCache()
    transport = ScriptedTransport(
        answers={
            THE_LOCATOR: recorded_payload(source=THE_LOCATOR, body=_document(_a_release()), etag=AN_ETAG),
        },
    )

    _collect(package, transport=transport, cache=cache)

    assert cache.reads == [(COLLECTOR_NAME, THE_LOCATOR)]
    assert [collector for collector, _, _, _ in cache.writes] == [COLLECTOR_NAME]
    assert cache.entries[(COLLECTOR_NAME, THE_LOCATOR)].etag == AN_ETAG


@pytest.mark.django_db
def test_a_revalidated_answer_writes_the_same_evidence_a_body_would_have() -> None:
    """The `304` replay, which is what a week-long cache lifetime is *for*.

    `CPM-EVIDENCE-S08` built the mechanism against a repository with no collector
    in it; this is the first collector whose declared lifetime makes it reachable,
    and a replay that produced different facts, a different `releases_seen` or the
    wrong `observed_at` would pass everything else in this module. The second run
    is forced, because a revalidation is otherwise suppressed by the window before
    it can happen -- which is itself worth seeing: caching and the window save the
    same call for different reasons.
    """
    package = _a_package()
    cache = RecordingResponseCache(
        entries={
            (COLLECTOR_NAME, THE_LOCATOR): cached_response(body=_document(_a_release()), etag=AN_ETAG),
        },
    )
    transport = ScriptedTransport(
        answers={
            THE_LOCATOR: recorded_payload(source=THE_LOCATOR, body="", not_modified=True, etag=AN_ETAG),
        },
    )

    result = _collect(package, transport=transport, cache=cache, force=True)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.OK.value
    assert row.latest_version == A_TAG
    assert row.released_at == PUBLISHED_INSTANT
    assert row.releases_seen == 1
    assert row.observed_at == FIXED_INSTANT
    # The validator went out and the body did not come back, which is the saving.
    assert transport.sent_headers[0] is not None
    assert AN_ETAG in dict(transport.sent_headers[0]).values()


# ---------------------------------------------------------------------------
# The locator refusals, where they are actually reached.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_with_no_source_repository_fails_the_run_and_writes_nothing() -> None:
    """The decision `SourceLocatorError` records, observed end to end.

    `source_for` is asked before the window, the allowance and the transport, so
    the refusal leaves a ledger row saying why and no evidence: the collector was
    asked to observe a source repository this package does not have. It is not an
    `error` observation, because nothing was observed -- and the base offers no
    `not_applicable` write path to make it one.
    """
    package = _a_package(repository="")
    transport = _releases(_a_release())

    with pytest.raises(SourceLocatorError):
        _collect(package, transport=transport)

    assert _rows(package) == []
    assert transport.calls == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_asking_about_a_package_that_is_not_there_is_refused_rather_than_answered() -> None:
    """`source_for` is public, and a caller reaching it directly is not the base.

    Through `collect()` this is unreachable: `core/ledger.py`'s recorder checks
    the key before it writes the opening row (`CPM-EVIDENCE-S09`), so a run
    against an unknown package never gets this far. That is exactly why the branch
    is worth having and worth a case -- it is the one this method cannot rely on
    somebody else having made, and a `None` falling through it would reach the
    locator builder as a repository URL that is not a string.
    """
    collector = SourceReleaseCollector(clock=FixedClock(instant=FIXED_INSTANT))

    try:
        with pytest.raises(SourceLocatorError, match="identity row"):
            collector.source_for(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()


# ---------------------------------------------------------------------------
# The task.
# ---------------------------------------------------------------------------


class SubstitutedCollector(SourceReleaseCollector):
    """The collector the task builds, with every seam already filled.

    A task takes a package key and nothing else -- it is a message, so it cannot
    be handed a transport -- and it constructs the collector itself. That
    construction is therefore the only seam a case about the *task* has, and
    substituting the name the task reads is the same move
    `tests/integration/django_apps/test_identity_overrides.py` makes when it
    substitutes a model's `save`: a collaborator is replaced, and the code under
    test is untouched.

    Class attributes rather than constructor arguments, because the caller under
    test is the task and it passes only a clock.
    """

    #: What the substituted instance is handed instead of what the task passes.
    #: Set by the case immediately before it drives the task.
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
            clock: What the task passed, replaced by the case's stopped one so the
                observation window is decided by a stated instant rather than by
                how long the test took.
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
def test_the_task_collects_the_package_it_was_handed() -> None:
    """The task wires `package_id` through to the base, and nothing else does.

    Driven to a terminal state that is reachable without a socket: a package with
    no source repository is refused before any call is made, so this asserts the
    wiring -- the task built the collector, opened a run against *this* package,
    and let the refusal out -- without opening a connection in a suite that must
    not.
    """
    package = _a_package(repository="")

    with pytest.raises(SourceLocatorError):
        collect_source_release(package_id=package.pk)

    assert _run(package).status == RunState.FAILED.value
    assert _rows(package) == []


@pytest.mark.django_db
def test_the_task_carries_force_through_to_the_base_and_returns_how_the_run_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CPM-UJ-1`'s manual recollection is this task, and the flag is live here.

    Unlike inventory ingestion -- whose window is `NO_WINDOW`, so its `force` is
    inert and its case says so -- this collector declares a twelve-hour window. A
    task that dropped the flag would silently subject every manual recollection to
    a window nobody asked for, and the run would come back `skipped` with no new
    observation. Both calls are driven through the task, so the difference between
    them is the flag and nothing else.

    The returned value is asserted rather than discarded: it is the ledger row's
    state as a string, it is what a caller inspecting a task result reads, and it
    is observed by nothing else in the suite.
    """
    monkeypatch.setattr(SubstitutedCollector, "fixed_clock", FixedClock(instant=FIXED_INSTANT))
    monkeypatch.setattr(SubstitutedCollector, "fixed_transport", _releases(_a_release()))
    monkeypatch.setattr(collector_tasks, "SourceReleaseCollector", SubstitutedCollector)
    package = _a_package()

    first = collect_source_release(package_id=package.pk)
    suppressed = collect_source_release(package_id=package.pk)
    forced = collect_source_release(package_id=package.pk, force=True)

    assert first == RunState.SUCCEEDED.value
    assert suppressed == RunState.SKIPPED.value
    assert forced == RunState.SUCCEEDED.value
    assert len(_rows(package)) == TWO_ROWS


# ---------------------------------------------------------------------------
# The table's own rules, on a migrated schema.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_determinate_row_without_a_version_is_refused_by_the_database() -> None:
    """The first conjunct, isolated: a determinate row names what it observed.

    A row saying "there is a latest version" while declining to say which is a
    claim nothing can act on and nothing may correct, so the database refuses it
    rather than the collector remembering not to write one.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=RELEASE_FACTS_CONSTRAINT), transaction.atomic():
        SourceReleaseSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.OK.value,
            latest_version="",
            released_at=PUBLISHED_INSTANT,
        )


@pytest.mark.django_db
def test_a_sentinel_row_carrying_a_version_is_refused_by_the_database() -> None:
    """The second conjunct, isolated, and it is the one a well-meaning writer reaches for.

    Keeping the last known version on an `error` row would make "the newest thing
    we know about" and "what the source said this time" the same column, and a
    currency policy reading it could not tell a fresh answer from a stale one
    wearing a fresh timestamp.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=RELEASE_FACTS_CONSTRAINT), transaction.atomic():
        SourceReleaseSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.ERROR.value,
            latest_version=A_TAG,
            released_at=None,
        )


@pytest.mark.django_db
def test_a_sentinel_row_carrying_a_release_date_is_refused_by_the_database() -> None:
    """The third conjunct, isolated, which no other case here reaches on its own.

    A row that is not a determinate observation and still carries a publication
    date is claiming a release date for a release it cannot name. Asserted
    separately from the version, because a row violating both would pass a
    constraint that had lost either one -- which is exactly how a dropped conjunct
    survives a regenerated migration.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=RELEASE_FACTS_CONSTRAINT), transaction.atomic():
        SourceReleaseSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.NOT_FOUND.value,
            latest_version="",
            released_at=PUBLISHED_INSTANT,
        )


@pytest.mark.django_db
def test_a_determinate_row_may_carry_a_version_and_no_date() -> None:
    """The permission the constraint has to grant, which is AC 1's "or tag".

    The tags endpoint supplies no date, so a tagged observation is `ok`, names its
    version, and dates nothing. A constraint that required the date would make the
    honest answer unwritable and would push the collector into inventing one --
    which is why the rule is "a determinate row names a version" rather than "a
    determinate row names a version and a date".
    """
    package = _a_package()

    SourceReleaseSnapshot.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=OutcomeState.OK.value,
        latest_version=A_TAG,
        released_at=None,
    )

    assert _rows(package)[0].latest_version == A_TAG


@pytest.mark.django_db
def test_re_observation_inserts_rather_than_updating() -> None:
    """`CPM-AD-2`, on the real table: two observations of one package are two rows.

    Written through the collector twice at two instants rather than by saving a
    row twice, because what `CPM-AD-2` protects is the *history*, and the history
    is only visible once the second observation disagrees with the first.
    """
    package = _a_package()
    _collect(package, transport=_releases(_a_release()))

    later = FIXED_INSTANT + A_DAY
    _collect(package, transport=_releases(_a_release(tag=A_LATER_TAG)), at=later)

    rows = _rows(package)
    assert [row.latest_version for row in rows] == [A_TAG, A_LATER_TAG]
    assert [row.observed_at for row in rows] == [FIXED_INSTANT, later]
