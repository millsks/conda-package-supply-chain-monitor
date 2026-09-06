"""Published-package collection against real tables: several channels, several platforms, the rows and the ledger.

`CPM-FR-10` asks for facts a row can say -- this channel publishes this version
for this platform, that one publishes nothing, this build string is what a fresh
install would resolve to -- and every one of them is only true or false once a run
exists. Which is why this module sits beside
`tests/unit/django_apps/test_conda_package.py`: the declaration rule, the locator
and the document reader are decided before a run does, and are asserted there.

**AC 1 is proved by counting rows and reading what each one names.** Two channels
that both serve the package produce two rows, each naming its own channel; two
platforms produce two rows, each carrying that platform's own build string. A
collector that merged them would produce one row and fail here rather than
quietly record a plausible answer -- and the scripted transport shows the other
half, that the run made one call per channel and no more.

**AC 1's absence clause is asserted through the read every surface asks.** A
`(channel, platform)` pair with nothing published is an observation with a
timestamp, which is a claim about what a *later* reader sees -- so the absence is
read back through `core/freshness.py`, with the paired never-observed case
showing that read answering the other thing.

**The two constraints are database rules here, not conventions.** Both are
asserted by writing the row the collector may not write and watching PostgreSQL --
or SQLite -- refuse it.

**No socket is opened.** Every case substitutes the transport at the base's seam,
and every case declares its own monitored channels and platforms through
`django.test.override_settings`, because what ships is empty and the refusal that
follows is itself one of the cases.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction.
`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction
from django.test import override_settings

from conda_package_supply_chain_monitor.collectors import conda_package as conda_package_module
from conda_package_supply_chain_monitor.collectors import tasks as collector_tasks
from conda_package_supply_chain_monitor.collectors.conda_package import CHANNELS_SETTING
from conda_package_supply_chain_monitor.collectors.conda_package import COLLECTOR_NAME
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_FRESHNESS_TARGET
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_HEADERS
from conda_package_supply_chain_monitor.collectors.conda_package import CONDA_PACKAGE_RETRIES
from conda_package_supply_chain_monitor.collectors.conda_package import MAX_MONITORED_CHANNELS
from conda_package_supply_chain_monitor.collectors.conda_package import NO_LATEST_VERSION_DETAIL
from conda_package_supply_chain_monitor.collectors.conda_package import NO_PUBLISHED_FILE_DETAIL
from conda_package_supply_chain_monitor.collectors.conda_package import PLATFORMS_SETTING
from conda_package_supply_chain_monitor.collectors.conda_package import UNREAD_CHANNEL_DETAIL
from conda_package_supply_chain_monitor.collectors.conda_package import CondaChannelError
from conda_package_supply_chain_monitor.collectors.conda_package import CondaDocumentError
from conda_package_supply_chain_monitor.collectors.conda_package import CondaPackageCollector
from conda_package_supply_chain_monitor.collectors.conda_package import package_locator
from conda_package_supply_chain_monitor.collectors.models import CHANNEL_AND_PLATFORM_CONSTRAINT
from conda_package_supply_chain_monitor.collectors.models import CONDA_PACKAGE_FACTS_CONSTRAINT
from conda_package_supply_chain_monitor.collectors.models import CondaPackageSnapshot
from conda_package_supply_chain_monitor.collectors.tasks import collect_conda_package
from conda_package_supply_chain_monitor.core.clock import Clock
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.freshness import UNOBSERVED_STATUS
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.runs import RunLedgerError
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.core.transport import Payload
from conda_package_supply_chain_monitor.core.transport import TransportError
from conda_package_supply_chain_monitor.identity.models import Package
from tests.clocks import FIXED_INSTANT
from tests.collectors import FixedLimiter
from tests.collectors import RecordingResponseCache
from tests.collectors import ScriptedTransport
from tests.collectors import cached_response
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from datetime import datetime

    from conda_package_supply_chain_monitor.core.collection import CollectionResult
    from conda_package_supply_chain_monitor.core.rate_limit import RateLimiter
    from conda_package_supply_chain_monitor.core.response_cache import ResponseCache
    from conda_package_supply_chain_monitor.core.transport import Transport

#: The package the cases ask about, the surfaces they monitor, and the locators
#: those produce. Derived rather than written out: a case here is about what a
#: *run* does with a locator, and the unit tier is where their spelling is pinned.
A_NAME: Final[str] = "numpy"
A_CHANNEL: Final[str] = "conda-forge"
ANOTHER_CHANNEL: Final[str] = "bioconda"
A_PLATFORM: Final[str] = "linux-64"
ANOTHER_PLATFORM: Final[str] = "osx-arm64"
THE_LOCATOR: Final[str] = package_locator(A_CHANNEL, A_NAME)
THE_OTHER_LOCATOR: Final[str] = package_locator(ANOTHER_CHANNEL, A_NAME)

#: What the channel documents say.
A_VERSION: Final[str] = "2.1.3"
ANOTHER_VERSION: Final[str] = "1.9.0"
A_LATER_VERSION: Final[str] = "2.2.0"
A_BUILD: Final[str] = "py312h1234567_0"
ANOTHER_BUILD: Final[str] = "py312h7654321_2"
A_THIRD_BUILD: Final[str] = "py312hcafef00d_0"
A_BUILD_NUMBER: Final[int] = 0
ANOTHER_BUILD_NUMBER: Final[int] = 2

#: The entity tag a source hands back, for the caching cases.
AN_ETAG: Final[str] = '"c0ffee"'

#: The counts the cases assert against, one named constant per concept, because
#: `PLR2004` is right about a bare number in an assertion -- and kept apart
#: because they count different things: two evidence rows, two transport calls,
#: the four rows two channels by two platforms owes, and the one allowance ask a
#: collection makes however many calls it issues.
TWO_ROWS: Final[int] = 2
TWO_REQUESTS: Final[int] = 2
FOUR_ROWS: Final[int] = 4

#: The rows the largest declaration the ceiling permits owes: four channels by
#: four platforms. Its own constant rather than `FOUR_ROWS` reused -- that one
#: counts two channels by two platforms, and the two numbers move for different
#: reasons.
THE_CEILINGS_ROWS: Final[int] = MAX_MONITORED_CHANNELS * 4
ONE_ALLOWANCE_ASK: Final[int] = 1

#: The gap between two observations in the re-observation case, longer than the
#: declared window so the second collection is about re-observation.
A_DAY: Final[timedelta] = timedelta(days=1)

#: The document ceiling the size case lowers the real one to, so nothing here
#: allocates thirty-two mebibytes to prove a comparison.
SMALL_DOCUMENT_BOUND: Final[int] = 64

#: A primary key no row in this module holds.
NO_SUCH_PACKAGE: Final[int] = 9_999_999


def _document(
    latest: str | None = A_VERSION,
    *files: tuple[str, str, str, int | None],
) -> str:
    """Return the body a channel would serve for one package.

    Args:
        latest: The version the channel states as latest, or `None` for a channel
            that names none.
        *files: One `(version, subdir, build, build_number)` per published file.
            Defaults to one file of the latest version on the first platform.

    Returns:
        The JSON body.

    """
    described = files or ((A_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER),)
    return json.dumps(
        {
            "name": A_NAME,
            "latest_version": latest,
            "files": [
                {
                    "version": version,
                    "attrs": {"subdir": subdir, "build": build, "build_number": number},
                }
                for version, subdir, build, number in described
            ],
        },
    )


def _answering(**scripted: str | Payload) -> ScriptedTransport:
    """Return a transport answering each named channel with a body or a whole payload.

    Args:
        **scripted: `first` and `second` -- each either the body the channel
            serves or a whole `Payload` for the cases that need one.

    Returns:
        The scripted transport.

    """
    locators = {"first": THE_LOCATOR, "second": THE_OTHER_LOCATOR}
    answers: dict[str, Payload] = {}
    for which, answer in scripted.items():
        locator = locators[which]
        answers[locator] = answer if isinstance(answer, Payload) else recorded_payload(source=locator, body=answer)
    return ScriptedTransport(answers=answers)


def _monitoring(
    channels: tuple[str, ...] = (A_CHANNEL,),
    platforms: tuple[str, ...] = (A_PLATFORM,),
) -> Any:
    """Return the settings override one case's monitored surfaces need.

    Declared per case rather than in a fixture, because what a case monitors is
    part of what it is asserting -- and because what *ships* is empty, which is
    itself one of the cases below.

    Args:
        channels: The channels to declare.
        platforms: The platforms to declare.

    Returns:
        The `override_settings` context manager.

    """
    return override_settings(**{CHANNELS_SETTING: channels, PLATFORMS_SETTING: platforms})


def _a_package(name: str = A_NAME) -> Package:
    """Return a saved package.

    Created directly rather than through `identity`'s resolution service, because
    what this module is about starts *after* a package exists. No mapping row is
    seeded and none is read: nothing a resolution recorded can make a
    published-artifact question inapplicable, which is what
    `tests/unit/django_apps/test_conda_package.py`'s source sweep pins.

    Args:
        name: The canonical name, unique per case.

    Returns:
        The saved row.

    """
    return Package.objects.create(canonical_name=name, resolved_at=FIXED_INSTANT)


def _collect(  # noqa: PLR0913 - one parameter per seam the base takes; a bundle would hide the one under test
    package: Package,
    *,
    transport: ScriptedTransport,
    at: datetime = FIXED_INSTANT,
    force: bool = False,
    permitted: bool = True,
    cache: RecordingResponseCache | None = None,
    limiter: FixedLimiter | None = None,
    document_bound: int | None = None,
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
        document_bound: A smaller `MAX_DOCUMENT_CHARACTERS` for the case about the
            ceiling, so the suite does not build a real one to prove a comparison.

    Returns:
        What the run did.

    """
    if document_bound is not None:
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(conda_package_module, "MAX_DOCUMENT_CHARACTERS", document_bound)
    collector = CondaPackageCollector(
        clock=FixedClock(instant=at),
        transport=transport,
        limiter=limiter if limiter is not None else FixedLimiter(permitted=permitted),
        response_cache=cache if cache is not None else RecordingResponseCache(),
    )
    try:
        return collector.collect(package_id=package.pk, force=force)
    finally:
        collector.close()
        if document_bound is not None:
            monkeypatch.undo()


def _rows(package: Package) -> list[CondaPackageSnapshot]:
    """Return this package's observations, oldest first.

    Args:
        package: The package to read.

    Returns:
        The rows, ordered by primary key.

    """
    return list(CondaPackageSnapshot.objects.filter(package=package).order_by("pk"))


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
    collector = CondaPackageCollector(clock=FixedClock(instant=FIXED_INSTANT))
    try:
        if status is None:
            return collector.freshness(package_id=package.pk, now=now)
        return collector.freshness(package_id=package.pk, now=now, status=status)
    finally:
        collector.close()


# ---------------------------------------------------------------------------
# AC 1: one row per channel, and channels are never merged.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_one_channel_and_one_platform_record_the_published_version_and_its_build() -> None:
    """The simplest whole run: `CPM-FR-10`'s three facts on one row, with the locator it came from.

    Also the things a case about the row alone would not see: the declared headers
    reached the request, and exactly one call was made.
    """
    package = _a_package()
    transport = _answering(first=_document())

    with _monitoring():
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == 1
    assert transport.calls == [THE_LOCATOR]
    assert dict(CONDA_PACKAGE_HEADERS).items() <= dict(transport.sent_headers[0] or {}).items()

    row = _rows(package)[0]
    assert row.source == THE_LOCATOR
    assert row.state == OutcomeState.OK.value
    assert row.channel == A_CHANNEL
    assert row.platform == A_PLATFORM
    assert row.published_version == A_VERSION
    assert row.build_string == A_BUILD
    assert row.build_number == A_BUILD_NUMBER
    assert row.detail == ""
    assert row.observed_at == FIXED_INSTANT
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_two_channels_produce_two_rows_and_no_row_names_two_channels() -> None:
    """AC 1, end to end: each channel produces its own observation and channels are never merged.

    The two channels are given *different* versions and builds deliberately: a
    collector that merged them could still produce two rows from one answer, and
    only rows that disagree can show that each was read from its own channel. The
    call list is asserted too -- one call per channel, in declared order -- because
    a run that read one channel twice would satisfy the row assertions.
    """
    package = _a_package()
    transport = _answering(
        first=_document(),
        second=_document(ANOTHER_VERSION, (ANOTHER_VERSION, A_PLATFORM, ANOTHER_BUILD, ANOTHER_BUILD_NUMBER)),
    )

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == TWO_ROWS
    assert transport.calls == [THE_LOCATOR, THE_OTHER_LOCATOR]
    # The declared headers reach the *second* request too. The one-channel case
    # above reads `sent_headers[0]`, which is the base's own call -- so dropping
    # them from the call this module makes would leave that case green and send
    # unidentified requests asking for no particular representation.
    assert dict(CONDA_PACKAGE_HEADERS).items() <= dict(transport.sent_headers[1] or {}).items()

    first, second = _rows(package)
    assert (first.channel, first.published_version, first.build_string) == (A_CHANNEL, A_VERSION, A_BUILD)
    assert (second.channel, second.published_version, second.build_string) == (
        ANOTHER_CHANNEL,
        ANOTHER_VERSION,
        ANOTHER_BUILD,
    )
    assert first.source == THE_LOCATOR
    assert second.source == THE_OTHER_LOCATOR
    assert {row.state for row in (first, second)} == {OutcomeState.OK.value}


@pytest.mark.django_db
def test_two_platforms_produce_two_rows_each_carrying_its_own_build_string() -> None:
    """A build is per platform, so a row that named one channel and one build would have merged them."""
    package = _a_package()
    transport = _answering(
        first=_document(
            A_VERSION,
            (A_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER),
            (A_VERSION, ANOTHER_PLATFORM, ANOTHER_BUILD, ANOTHER_BUILD_NUMBER),
        ),
    )

    with _monitoring(platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        result = _collect(package, transport=transport)

    assert result.evidence_rows == TWO_ROWS
    # One call, two rows: platforms cost rows rather than calls.
    assert transport.calls == [THE_LOCATOR]

    first, second = _rows(package)
    assert (first.platform, first.build_string) == (A_PLATFORM, A_BUILD)
    assert (second.platform, second.build_string) == (ANOTHER_PLATFORM, ANOTHER_BUILD)
    assert {row.published_version for row in (first, second)} == {A_VERSION}


@pytest.mark.django_db
def test_two_channels_by_two_platforms_are_four_rows_and_every_pair_appears_once() -> None:
    """The whole shape of the table in one run: no row stands for two of anything."""
    package = _a_package()
    transport = _answering(
        first=_document(
            A_VERSION,
            (A_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER),
            (A_VERSION, ANOTHER_PLATFORM, ANOTHER_BUILD, ANOTHER_BUILD_NUMBER),
        ),
        second=_document(
            ANOTHER_VERSION,
            (ANOTHER_VERSION, A_PLATFORM, A_THIRD_BUILD, A_BUILD_NUMBER),
            (ANOTHER_VERSION, ANOTHER_PLATFORM, A_THIRD_BUILD, A_BUILD_NUMBER),
        ),
    )

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL), platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        result = _collect(package, transport=transport)

    assert result.evidence_rows == FOUR_ROWS
    assert transport.calls == [THE_LOCATOR, THE_OTHER_LOCATOR]

    rows = _rows(package)
    assert len({(row.channel, row.platform) for row in rows}) == FOUR_ROWS
    assert {row.observed_at for row in rows} == {FIXED_INSTANT}


@pytest.mark.django_db
def test_a_platform_the_latest_version_has_no_file_on_is_a_written_absence_beside_a_published_row() -> None:
    """The matrix's "latest version absent from a platform": one `ok` row and one `not_found`, never one row."""
    package = _a_package()
    transport = _answering(first=_document())

    with _monitoring(platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        _collect(package, transport=transport)

    published, absent = _rows(package)
    assert published.state == OutcomeState.OK.value
    assert absent.state == OutcomeState.NOT_FOUND.value
    assert absent.platform == ANOTHER_PLATFORM
    assert absent.published_version == ""
    assert absent.build_string == ""
    assert absent.build_number is None
    assert NO_PUBLISHED_FILE_DETAIL in absent.detail
    assert A_VERSION in absent.detail
    assert absent.observed_at == FIXED_INSTANT


@pytest.mark.django_db
def test_a_channel_that_names_no_latest_version_records_an_absence_per_platform() -> None:
    """The matrix's "no latest version stated": absence with a reason, and still one row per platform."""
    package = _a_package()
    transport = _answering(first=_document(None))

    with _monitoring(platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    rows = _rows(package)
    assert len(rows) == TWO_ROWS
    assert {row.state for row in rows} == {OutcomeState.NOT_FOUND.value}
    assert {row.detail for row in rows} == {NO_LATEST_VERSION_DETAIL}


# ---------------------------------------------------------------------------
# One channel failing never discards another channel's answer (`CPM-FR-15`).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_failing_second_channel_leaves_the_answering_channels_rows_and_carries_error_on_its_own() -> None:
    """`CPM-FR-15`'s partial success on the per-package path, and the story's central claim.

    The run is `succeeded`, not `failed`: one channel answered, and a ledger row
    saying the whole collection failed would make an answer this product does hold
    look like one it does not.
    """
    package = _a_package()
    transport = _answering(first=_document())
    transport.failures[THE_OTHER_LOCATOR] = TransportError("the channel is unreachable", source=THE_OTHER_LOCATOR)

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == TWO_ROWS

    answered, failed = _rows(package)
    assert answered.state == OutcomeState.OK.value
    assert answered.published_version == A_VERSION
    assert failed.state == OutcomeState.ERROR.value
    assert failed.channel == ANOTHER_CHANNEL
    assert failed.source == THE_OTHER_LOCATOR
    assert failed.published_version == ""
    assert UNREAD_CHANNEL_DETAIL in failed.detail
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_a_failing_second_channel_carries_error_on_every_platform_it_was_going_to_be_asked_about() -> None:
    """A channel that could not be read still owes a row per monitored platform, not one for the channel."""
    package = _a_package()
    transport = _answering(
        first=_document(
            A_VERSION,
            (A_VERSION, A_PLATFORM, A_BUILD, A_BUILD_NUMBER),
            (A_VERSION, ANOTHER_PLATFORM, ANOTHER_BUILD, ANOTHER_BUILD_NUMBER),
        ),
    )
    transport.failures[THE_OTHER_LOCATOR] = TransportError("the channel is unreachable", source=THE_OTHER_LOCATOR)

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL), platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        result = _collect(package, transport=transport)

    assert result.evidence_rows == FOUR_ROWS
    failed = [row for row in _rows(package) if row.state == OutcomeState.ERROR.value]
    assert {row.platform for row in failed} == {A_PLATFORM, ANOTHER_PLATFORM}


@pytest.mark.django_db
def test_a_second_channel_that_does_not_serve_the_package_is_an_absence_read_from_its_own_answer() -> None:
    """The matrix's "package absent from a channel": `not_found` per declared platform, from the channel's `404`.

    Read from the channel's own answer rather than left to the base's sentinel,
    which is what makes the *other* channels' rows survive it -- and what makes
    this `not_found` rather than `error`: the channel said the package is not
    there, which is the observation `CPM-FR-10` asks for and not a failure to look.
    """
    package = _a_package()
    transport = _answering(
        first=_document(),
        second=recorded_payload(source=THE_OTHER_LOCATOR, body="", found=False),
    )

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL), platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == FOUR_ROWS

    absent = [row for row in _rows(package) if row.channel == ANOTHER_CHANNEL]
    assert {row.state for row in absent} == {OutcomeState.NOT_FOUND.value}
    assert {row.platform for row in absent} == {A_PLATFORM, ANOTHER_PLATFORM}
    assert {row.observed_at for row in absent} == {FIXED_INSTANT}
    assert all("does not serve the package" in row.detail for row in absent)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "answer",
    [
        recorded_payload(source=THE_OTHER_LOCATOR, body="not a document"),
        recorded_payload(source=THE_OTHER_LOCATOR, body="", not_modified=True),
    ],
    ids=["unreadable-document", "unconditional-304"],
)
def test_a_second_channel_this_run_could_not_read_is_not_recorded_as_an_absence(answer: Payload) -> None:
    """ "Could not read" and "publishes nothing" are opposite claims, and only one of them is evidence.

    A row recording the first as the second would put an absence this run never
    established into a log nothing may correct -- which is the failure the sibling
    collector's review round was mostly about, and the one this collector is shaped
    not to repeat. An unreadable document from a *later* channel never fails the
    run either: the channels that answered keep their rows.
    """
    package = _a_package()
    transport = _answering(first=_document(), second=answer)

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    answered, unread = _rows(package)
    assert answered.state == OutcomeState.OK.value
    assert unread.state == OutcomeState.ERROR.value
    assert UNREAD_CHANNEL_DETAIL in unread.detail


@pytest.mark.django_db
def test_the_three_ways_of_not_reading_a_channel_say_three_different_things() -> None:
    """A blank published version means several things, and only `detail` can say which.

    Asserted as distinctness rather than against three literals: what matters is
    that a reader can tell an unreachable channel from an unreadable document from
    one that answered "no such package", not what any one sentence says.
    """
    package = _a_package()
    answers: list[TransportError | Payload] = [
        TransportError("unreachable", source=THE_OTHER_LOCATOR),
        recorded_payload(source=THE_OTHER_LOCATOR, body="not a document"),
        recorded_payload(source=THE_OTHER_LOCATOR, body="", found=False),
    ]

    for answer in answers:
        transport = _answering(first=_document())
        if isinstance(answer, TransportError):
            transport.failures[THE_OTHER_LOCATOR] = answer
        else:
            transport.answers[THE_OTHER_LOCATOR] = answer
        # `force`, so the observation window does not suppress the second and
        # third collections of one package: what is under test is the *reason*
        # each answer produces, not the window.
        with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL)):
            _collect(package, transport=transport, force=True)

    reasons = {row.detail for row in _rows(package) if row.channel == ANOTHER_CHANNEL}

    assert len(reasons) == len(answers)


# ---------------------------------------------------------------------------
# The refusals: an undeclared or unusable declaration.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("channels", "platforms"),
    [((), (A_PLATFORM,)), ((A_CHANNEL,), ()), ((), ())],
    ids=["no-channels", "no-platforms", "neither"],
)
def test_a_run_that_finds_nothing_declared_fails_naming_the_setting_and_writes_no_row(
    channels: tuple[str, ...],
    platforms: tuple[str, ...],
) -> None:
    """The shipped state, end to end: a loud failure rather than a silent observation of nothing.

    No evidence row is written, and that is the honest answer rather than a gap:
    every row must name the channel and platform it is about, and an empty
    declaration names neither. The message has to carry the setting, because a
    `failed` ledger row is all an operator has to go on.
    """
    package = _a_package()
    transport = _answering(first=_document())

    with _monitoring(channels=channels, platforms=platforms), pytest.raises(CondaChannelError) as refused:
        _collect(package, transport=transport)

    assert CHANNELS_SETTING in str(refused.value) or PLATFORMS_SETTING in str(refused.value)
    assert _rows(package) == []
    assert transport.calls == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_an_unusable_declaration_fails_the_run_and_writes_nothing() -> None:
    """Refused rather than narrowed to the entries that happened to parse."""
    package = _a_package()
    transport = _answering(first=_document())

    with _monitoring(channels=(A_CHANNEL, "not a channel")), pytest.raises(CondaChannelError):
        _collect(package, transport=transport)

    assert _rows(package) == []
    assert transport.calls == []


@pytest.mark.django_db
def test_a_package_whose_canonical_name_is_not_a_segment_fails_the_run_and_writes_nothing() -> None:
    """A canonical name is data a resolution wrote, so it is refused rather than encoded."""
    package = _a_package(name="not a package name")
    transport = _answering(first=_document())

    with _monitoring(), pytest.raises(CondaChannelError, match="canonical_name"):
        _collect(package, transport=transport)

    assert _rows(package) == []


@pytest.mark.django_db
def test_a_package_that_went_between_the_ledgers_check_and_the_name_read_is_refused_by_name() -> None:
    """A narrow race, and not one this collector may answer with a bare `DoesNotExist`.

    `core/ledger.py` checks the key before it opens a row (`CPM-EVIDENCE-S09`), so
    the package exists by the time a hook runs -- unless it went in between. Left
    unhandled that leaves `collect()` as a Django exception naming a queryset;
    re-raised, it is this module's own refusal naming the package, which is what a
    reader of a `failed` ledger row gets.

    Reached through `source_for` directly, because the race itself is not
    arrangeable from a test.
    """
    collector = CondaPackageCollector(clock=FixedClock(instant=FIXED_INSTANT), transport=_answering())
    try:
        with _monitoring(), pytest.raises(CondaChannelError, match=str(NO_SUCH_PACKAGE)):
            collector.source_for(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()


@pytest.mark.django_db
def test_collecting_a_package_that_is_not_there_leaves_nothing_behind_at_all() -> None:
    """`CPM-EVIDENCE-S09`: the recorder checks the key before it writes the opening row."""
    collector = CondaPackageCollector(clock=FixedClock(instant=FIXED_INSTANT), transport=_answering())
    try:
        with _monitoring(), pytest.raises(RunLedgerError):
            collector.collect(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()

    assert CollectionRun.objects.filter(collector=COLLECTOR_NAME).count() == 0
    assert CondaPackageSnapshot.objects.count() == 0


# ---------------------------------------------------------------------------
# The base's own paths: the first channel's failure, the window, the allowance,
# the cache.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_only_channel_failing_is_an_error_row_naming_its_pair_and_a_failed_run() -> None:
    """`CPM-FR-15`'s partial success has nothing to be partial about when one channel is declared.

    The row still names a channel and a platform, because the table refuses one
    that does not.
    """
    package = _a_package()
    transport = _answering()
    transport.failures[THE_LOCATOR] = TransportError("the channel is unreachable", source=THE_LOCATOR)

    with _monitoring():
        result = _collect(package, transport=transport)

    assert result.state == RunState.FAILED
    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert row.channel == A_CHANNEL
    assert row.platform == A_PLATFORM
    assert row.published_version == ""
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_the_first_channel_failing_writes_an_error_row_for_every_pair_and_asks_no_channel() -> None:
    """Every pair gets exactly one row, and nothing is called -- which is the limiter's rule, not an omission.

    `error` is reachable from a *refused allowance* as well as from a failed call,
    and by the time the hook runs the base has already declared the run `failed`.
    Issuing calls here would spend the remote budget the limiter may just have
    refused (`CPM-AD-20`) and would write `ok` rows underneath a ledger row saying
    the run failed. So every pair records `error` carrying the base's own reason,
    and the only call this run made is the one the base made.
    """
    package = _a_package()
    transport = _answering()
    transport.failures[THE_LOCATOR] = TransportError("the channel is unreachable", source=THE_LOCATOR)

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL), platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.FAILED
    assert result.evidence_rows == FOUR_ROWS
    rows = _rows(package)
    assert len({(row.channel, row.platform) for row in rows}) == FOUR_ROWS
    assert {row.state for row in rows} == {OutcomeState.ERROR.value}
    assert {row.observed_at for row in rows} == {FIXED_INSTANT}
    assert transport.calls == [THE_LOCATOR]


@pytest.mark.django_db
def test_a_spent_allowance_writes_an_error_row_per_pair_and_issues_no_call() -> None:
    """The case the `error` branch is shaped around: the limiter said no, so nothing may be asked.

    A hook that asked the remaining channels here would defeat the allowance
    outright -- the base refused *one* call and three would go out anyway.
    """
    package = _a_package()
    transport = _answering(first=_document())

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL), platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        result = _collect(package, transport=transport, permitted=False)

    assert result.state == RunState.FAILED
    assert transport.calls == []
    assert result.evidence_rows == FOUR_ROWS
    assert {row.state for row in _rows(package)} == {OutcomeState.ERROR.value}


@pytest.mark.django_db
def test_the_first_channel_answering_404_is_an_absence_row_and_a_succeeded_run() -> None:
    """The base's `not_found` branch: the channel answered, and the answer was "no such package"."""
    package = _a_package()
    transport = _answering(first=recorded_payload(source=THE_LOCATOR, body="", found=False))

    with _monitoring():
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == OutcomeState.NOT_FOUND.value
    assert row.channel == A_CHANNEL
    assert row.platform == A_PLATFORM
    assert row.observed_at == FIXED_INSTANT


@pytest.mark.django_db
def test_a_first_channel_that_does_not_serve_the_package_never_stops_a_second_channel_being_asked() -> None:
    """AC 1, on the path that used to lose it: absent from channel one, published on channel two.

    The base's `not_found` branch writes its rows without reaching `translate`, so
    before `CPM-CURRENCY-S04` gave the base `sentinel_evidence_rows` this run
    recorded one row and nothing whatever about the second channel -- "each
    monitored channel produces its own observation" failing on exactly the case it
    exists for. The second channel is asked here, its `ok` row is written, and the
    run is `succeeded`, which is what makes the absence and the publication one
    observation rather than two runs.
    """
    package = _a_package()
    transport = _answering(
        first=recorded_payload(source=THE_LOCATOR, body="", found=False),
        second=_document(ANOTHER_VERSION, (ANOTHER_VERSION, A_PLATFORM, ANOTHER_BUILD, ANOTHER_BUILD_NUMBER)),
    )

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == TWO_ROWS
    assert transport.calls == [THE_LOCATOR, THE_OTHER_LOCATOR]
    # And the call the *sentinel* hook makes carries them too: it is a third
    # place a request is issued, and the only one no other case reaches.
    assert dict(CONDA_PACKAGE_HEADERS).items() <= dict(transport.sent_headers[1] or {}).items()

    absent, published = _rows(package)
    assert (absent.channel, absent.state) == (A_CHANNEL, OutcomeState.NOT_FOUND.value)
    assert (published.channel, published.state) == (ANOTHER_CHANNEL, OutcomeState.OK.value)
    assert published.published_version == ANOTHER_VERSION
    assert published.build_string == ANOTHER_BUILD
    assert published.source == THE_OTHER_LOCATOR
    assert {row.observed_at for row in (absent, published)} == {FIXED_INSTANT}


@pytest.mark.django_db
def test_every_channel_absent_writes_one_row_per_pair_and_the_run_succeeds() -> None:
    """The matrix's "every channel absent": a `not_found` row per pair, and no row missing.

    The base's sentinel path covers the first channel's platforms and the bounded
    calls cover the rest, so the count is the whole declaration rather than the
    part the base happened to reach. `succeeded`, because every channel answered
    and every answer was recorded.
    """
    package = _a_package()
    transport = _answering(
        first=recorded_payload(source=THE_LOCATOR, body="", found=False),
        second=recorded_payload(source=THE_OTHER_LOCATOR, body="", found=False),
    )

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL), platforms=(A_PLATFORM, ANOTHER_PLATFORM)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == FOUR_ROWS
    rows = _rows(package)
    assert len({(row.channel, row.platform) for row in rows}) == FOUR_ROWS
    assert {row.state for row in rows} == {OutcomeState.NOT_FOUND.value}
    assert {row.observed_at for row in rows} == {FIXED_INSTANT}
    assert transport.calls == [THE_LOCATOR, THE_OTHER_LOCATOR]
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_the_largest_declaration_the_ceiling_permits_runs_end_to_end() -> None:
    """`MAX_MONITORED_CHANNELS` channels and four platforms, with the sentinel branch asking the rest.

    The ceiling is asserted as arithmetic in the unit tier; this is the case that
    runs it. The first channel answers `404`, so every remaining channel is asked
    from the sentinel hook rather than from `translate` -- the deepest path in this
    collector, and the one no smaller declaration reaches.
    """
    package = _a_package()
    channels = tuple(f"channel-{index}" for index in range(MAX_MONITORED_CHANNELS))
    platforms = (A_PLATFORM, ANOTHER_PLATFORM, "win-64", "noarch")
    answers = {
        package_locator(channels[0], A_NAME): recorded_payload(
            source=package_locator(channels[0], A_NAME),
            body="",
            found=False,
        ),
    }
    for channel in channels[1:]:
        locator = package_locator(channel, A_NAME)
        answers[locator] = recorded_payload(
            source=locator,
            body=_document(A_VERSION, *[(A_VERSION, subdir, A_BUILD, A_BUILD_NUMBER) for subdir in platforms]),
        )
    transport = ScriptedTransport(answers=answers)

    with _monitoring(channels=channels, platforms=platforms):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    assert result.evidence_rows == THE_CEILINGS_ROWS
    assert len(transport.calls) == MAX_MONITORED_CHANNELS
    rows = _rows(package)
    assert len({(row.channel, row.platform) for row in rows}) == THE_CEILINGS_ROWS
    assert {row.observed_at for row in rows} == {FIXED_INSTANT}
    absent = [row for row in rows if row.channel == channels[0]]
    assert {row.state for row in absent} == {OutcomeState.NOT_FOUND.value}
    assert len(absent) == len(platforms)
    published = [row for row in rows if row.channel != channels[0]]
    assert {row.state for row in published} == {OutcomeState.OK.value}


@pytest.mark.django_db
def test_a_second_channel_that_fails_beside_an_absent_first_one_is_not_recorded_as_an_absence() -> None:
    """The sentinel path inherits the distinction the translation path already draws.

    "This channel publishes nothing" and "this run could not find out" are
    opposite claims, and the hook must not collapse them just because the row it
    sits beside is a sentinel the base decided.
    """
    package = _a_package()
    transport = _answering(first=recorded_payload(source=THE_LOCATOR, body="", found=False))
    transport.failures[THE_OTHER_LOCATOR] = TransportError("unreachable", source=THE_OTHER_LOCATOR)

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL)):
        result = _collect(package, transport=transport)

    assert result.state == RunState.SUCCEEDED
    absent, unread = _rows(package)
    assert absent.state == OutcomeState.NOT_FOUND.value
    assert unread.state == OutcomeState.ERROR.value
    assert UNREAD_CHANNEL_DETAIL in unread.detail


@pytest.mark.django_db
def test_an_unreadable_first_document_writes_an_error_row_before_it_raises() -> None:
    """`CPM-NFR-3`: never a clean result, and never no row -- on the path where the parser broke."""
    package = _a_package()
    transport = _answering(first="not a document")

    with _monitoring(), pytest.raises(CondaDocumentError):
        _collect(package, transport=transport)

    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert row.channel == A_CHANNEL
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_first_document_over_the_ceiling_writes_an_error_row_before_it_raises() -> None:
    """The parse bound, reached through a whole run rather than only through the pure function."""
    package = _a_package()
    transport = _answering(first=_document())

    with _monitoring(), pytest.raises(CondaDocumentError, match=str(SMALL_DOCUMENT_BOUND)):
        _collect(package, transport=transport, document_bound=SMALL_DOCUMENT_BOUND)

    assert _rows(package)[0].state == OutcomeState.ERROR.value


@pytest.mark.django_db
def test_one_collection_asks_the_allowance_once_however_many_channels_it_calls() -> None:
    """The property every rate-limit claim rests on, and the gap this story records as deferred.

    The base charges `1 + retries` once, before the first call; the calls the
    translation makes for the remaining channels are not charged. Asserted rather
    than only documented, because "the counter believes something different from
    what the network sees" is not a sentence anybody should have to take on trust.
    """
    package = _a_package()
    limiter = FixedLimiter(permitted=True)
    transport = _answering(first=_document(), second=_document())

    with _monitoring(channels=(A_CHANNEL, ANOTHER_CHANNEL)):
        _collect(package, transport=transport, limiter=limiter)

    assert len(limiter.asks) == ONE_ALLOWANCE_ASK
    assert limiter.asks[0][3] == 1 + CONDA_PACKAGE_RETRIES
    assert len(transport.calls) == TWO_REQUESTS


@pytest.mark.django_db
def test_a_spent_allowance_refuses_the_call_and_records_it() -> None:
    """`CPM-AD-20`: refused rather than issued unlimited, and the refusal is a row like any other."""
    package = _a_package()
    transport = _answering(first=_document())

    with _monitoring():
        result = _collect(package, transport=transport, permitted=False)

    assert result.state == RunState.FAILED
    assert transport.calls == []
    row = _rows(package)[0]
    assert row.state == OutcomeState.ERROR.value
    assert row.channel == A_CHANNEL


@pytest.mark.django_db
def test_a_second_collection_inside_the_window_is_skipped_without_a_call_and_force_writes_again() -> None:
    """`CPM-AD-7`'s window, and `CPM-UJ-1`'s bypass of it, on one package."""
    package = _a_package()
    with _monitoring():
        _collect(package, transport=_answering(first=_document()))

        suppressed = ScriptedTransport()
        result = _collect(package, transport=suppressed)
        assert result.state == RunState.SKIPPED
        assert suppressed.calls == []
        assert len(_rows(package)) == 1

        forced = _answering(first=_document())
        assert _collect(package, transport=forced, force=True).state == RunState.SUCCEEDED

    assert len(_rows(package)) == TWO_ROWS
    assert forced.calls == [THE_LOCATOR]


@pytest.mark.django_db
def test_an_answer_carrying_a_validator_is_remembered_after_its_evidence_is_written() -> None:
    """The ordering claim `CPM-EVIDENCE-S08` makes: nothing is remembered until the row exists."""
    package = _a_package()
    cache = RecordingResponseCache()
    transport = _answering(first=recorded_payload(source=THE_LOCATOR, body=_document(), etag=AN_ETAG))

    with _monitoring():
        _collect(package, transport=transport, cache=cache)

    assert [(collector, source) for collector, source, _, _ in cache.writes] == [(COLLECTOR_NAME, THE_LOCATOR)]
    assert cache.writes[0][2].etag == AN_ETAG


@pytest.mark.django_db
def test_a_revalidated_answer_writes_the_same_evidence_a_body_would_have() -> None:
    """The `304` replay: a cached body stands in for one the source did not transfer."""
    package = _a_package()
    cache = RecordingResponseCache()
    cache.entries[(COLLECTOR_NAME, THE_LOCATOR)] = cached_response(body=_document(), etag=AN_ETAG)
    transport = _answering(first=recorded_payload(source=THE_LOCATOR, body="", not_modified=True, etag=AN_ETAG))

    with _monitoring():
        result = _collect(package, transport=transport, cache=cache)

    assert result.state == RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.published_version == A_VERSION
    assert row.build_string == A_BUILD


@pytest.mark.django_db
def test_re_observation_inserts_rather_than_updating() -> None:
    """`CPM-AD-2`: evidence is append-only, so a later answer is a second row and never an overwrite."""
    package = _a_package()
    with _monitoring():
        _collect(package, transport=_answering(first=_document()))
        _collect(
            package,
            transport=_answering(first=_document(A_LATER_VERSION, (A_LATER_VERSION, A_PLATFORM, A_BUILD, 1))),
            at=FIXED_INSTANT + A_DAY,
        )

    first, second = _rows(package)
    assert first.published_version == A_VERSION
    assert second.published_version == A_LATER_VERSION
    assert first.observed_at == FIXED_INSTANT
    assert second.observed_at == FIXED_INSTANT + A_DAY


@pytest.mark.django_db
def test_one_instance_collecting_twice_reads_the_declaration_fresh_on_the_second_run() -> None:
    """A declaration is remembered for a run, not for an instance -- which is what `inapplicability` resets.

    An operator who changes the declaration between two collections through one
    long-lived collector must get the new one, and a collector that remembered the
    first would keep observing a channel nobody monitors any more.
    """
    package = _a_package()
    transport = _answering(first=_document(), second=_document())
    collector = CondaPackageCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=transport,
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )
    try:
        with _monitoring():
            collector.collect(package_id=package.pk)
        with _monitoring(channels=(ANOTHER_CHANNEL,)):
            collector.collect(package_id=package.pk, force=True)
    finally:
        collector.close()

    first, second = _rows(package)
    assert first.channel == A_CHANNEL
    assert second.channel == ANOTHER_CHANNEL
    assert transport.calls == [THE_LOCATOR, THE_OTHER_LOCATOR]


# ---------------------------------------------------------------------------
# AC 1's absence clause, read back the way a reader reads it.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_absence_is_read_back_as_an_observation_with_its_instant_rather_than_as_staleness() -> None:
    """ "Not published here" is a thing this product knows, not a thing it has failed to look at.

    A case that stopped at "a `not_found` row exists" would pass identically if
    the row were never written, because `core/freshness.py` would then report the
    package unobserved -- which is what the paired case below shows.
    """
    package = _a_package()

    with _monitoring():
        _collect(package, transport=_answering(first=_document(None)))

    report = _freshness(package, status=OutcomeState.NOT_FOUND.value)

    assert report.observed_at == FIXED_INSTANT
    assert not report.stale
    assert report.status == OutcomeState.NOT_FOUND.value


@pytest.mark.django_db
def test_a_package_this_collector_has_not_observed_reads_as_unobserved() -> None:
    """The anti-vacuity half of the case above."""
    report = _freshness(_a_package())

    assert report.observed_at is None
    assert report.status == UNOBSERVED_STATUS


@pytest.mark.django_db
def test_an_absence_ages_like_any_other_observation() -> None:
    """A `not_found` row is evidence, so it goes stale on this collector's declared target."""
    package = _a_package()

    with _monitoring():
        _collect(package, transport=_answering(first=_document(None)))

    fresh = _freshness(package, now=FIXED_INSTANT + CONDA_PACKAGE_FRESHNESS_TARGET)
    stale = _freshness(package, now=FIXED_INSTANT + CONDA_PACKAGE_FRESHNESS_TARGET + timedelta(seconds=1))

    assert not fresh.stale
    assert stale.stale


# ---------------------------------------------------------------------------
# The task.
# ---------------------------------------------------------------------------


class SubstitutedCollector(CondaPackageCollector):
    """A collector whose transport, limiter, cache and clock are the case's.

    The task constructs its own collector, so the only way to see what it did with
    `force` -- and to see it without a socket -- is to substitute the class the
    task names.

    Attributes:
        transport_for_case: What every instance fetches through.
        collected: Every `(package_id, force)` pair `collect` was called with.

    """

    transport_for_case: ClassVar[Transport | None] = None
    collected: ClassVar[list[tuple[int, bool]]] = []

    def __init__(
        self,
        *,
        clock: Clock,
        transport: Transport | None = None,
        limiter: RateLimiter | None = None,
        response_cache: ResponseCache | None = None,
    ) -> None:
        """Build a collector whose seams are the case's rather than the base's defaults.

        Args:
            clock: The clock the task injects, replaced with a stopped one.
            transport: Ignored: the case's is used.
            limiter: Ignored: a permitting one is used.
            response_cache: Ignored: a recording one is used.

        """
        del clock, transport, limiter, response_cache
        super().__init__(
            clock=FixedClock(instant=FIXED_INSTANT),
            transport=type(self).transport_for_case,
            limiter=FixedLimiter(permitted=True),
            response_cache=RecordingResponseCache(),
        )

    def collect(self, *, package_id: int, force: bool = False) -> CollectionResult:
        """Record what the task asked for and collect it.

        Args:
            package_id: The package the task named.
            force: Whether the task asked for the window to be bypassed.

        Returns:
            What the run did.

        """
        type(self).collected.append((package_id, force))
        return super().collect(package_id=package_id, force=force)


@pytest.mark.django_db
def test_the_task_lets_an_undeclared_monitoring_out_as_a_failed_run() -> None:
    """The shipped state through the task itself: no socket, no row, a `failed` ledger row.

    Reached without substituting anything, because the refusal happens before the
    transport is touched -- which is itself the claim.
    """
    package = _a_package()

    with override_settings(**{CHANNELS_SETTING: (), PLATFORMS_SETTING: ()}), pytest.raises(CondaChannelError):
        collect_conda_package(package_id=package.pk)

    assert _rows(package) == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_the_task_carries_force_through_to_the_base_and_returns_how_the_run_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The task is a thin wrapper, and the two things it must not drop are the package and `force`."""
    package = _a_package()
    SubstitutedCollector.collected = []
    SubstitutedCollector.transport_for_case = _answering(first=_document())
    monkeypatch.setattr(collector_tasks, "CondaPackageCollector", SubstitutedCollector)

    with _monitoring():
        first = collect_conda_package(package_id=package.pk)
        second = collect_conda_package(package_id=package.pk, force=True)

    assert first == RunState.SUCCEEDED.value
    assert second == RunState.SUCCEEDED.value
    assert SubstitutedCollector.collected == [(package.pk, False), (package.pk, True)]
    assert len(_rows(package)) == TWO_ROWS


# ---------------------------------------------------------------------------
# The two constraints, as the database enforces them.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_determinate_row_without_a_published_version_is_refused_by_the_database() -> None:
    """A row saying "this channel publishes it" while declining to say what is not an observation."""
    package = _a_package()

    with pytest.raises(IntegrityError, match=CONDA_PACKAGE_FACTS_CONSTRAINT), transaction.atomic():
        CondaPackageSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.OK.value,
            channel=A_CHANNEL,
            platform=A_PLATFORM,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fact",
    [
        {"published_version": A_VERSION},
        {"build_string": A_BUILD},
        {"build_number": A_BUILD_NUMBER},
    ],
    ids=["version", "build-string", "build-number"],
)
def test_a_sentinel_row_carrying_any_published_fact_is_refused_by_the_database(fact: dict[str, Any]) -> None:
    """Every conjunct is load bearing: a row that is not determinate observed no published artifact."""
    package = _a_package()

    with pytest.raises(IntegrityError, match=CONDA_PACKAGE_FACTS_CONSTRAINT), transaction.atomic():
        CondaPackageSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=OutcomeState.NOT_FOUND.value,
            channel=A_CHANNEL,
            platform=A_PLATFORM,
            **fact,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("channel", "platform"),
    [("", A_PLATFORM), (A_CHANNEL, ""), ("", "")],
    ids=["no-channel", "no-platform", "neither"],
)
@pytest.mark.parametrize(
    "state",
    [OutcomeState.OK.value, OutcomeState.NOT_FOUND.value, OutcomeState.ERROR.value],
    ids=["ok", "not-found", "error"],
)
def test_a_row_that_cannot_name_its_channel_and_platform_is_refused_by_the_database(
    channel: str,
    platform: str,
    state: str,
) -> None:
    """AC 1 as a database rule: a row that names no pair has merged every monitored surface into one.

    Over every state rather than only the determinate one, which is the half a
    convention would have missed: a sentinel row that could not say which pair it
    was about would be an observation of nowhere.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=CHANNEL_AND_PLATFORM_CONSTRAINT), transaction.atomic():
        CondaPackageSnapshot.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=state,
            channel=channel,
            platform=platform,
            published_version=A_VERSION if state == OutcomeState.OK.value else "",
        )


@pytest.mark.django_db
def test_a_determinate_row_may_carry_no_build_string_and_an_absence_may_carry_none_of_it() -> None:
    """The anti-vacuity half: the constraints permit the honest rows as well as refusing the dishonest ones.

    A channel that states a version while stating the build poorly is an answer
    rather than a defect, so a build string is deliberately not required of a
    determinate row -- and requiring it would have pushed the collector into
    inventing one.
    """
    package = _a_package()

    CondaPackageSnapshot.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=OutcomeState.OK.value,
        channel=A_CHANNEL,
        platform=A_PLATFORM,
        published_version=A_VERSION,
    )
    CondaPackageSnapshot.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=OutcomeState.NOT_FOUND.value,
        channel=A_CHANNEL,
        platform=ANOTHER_PLATFORM,
    )

    assert len(_rows(package)) == TWO_ROWS
