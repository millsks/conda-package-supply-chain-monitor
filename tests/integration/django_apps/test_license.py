"""Licence collection against real tables: the two columns side by side, the channels kept apart, and the constraints.

`CPM-FR-13` asks for facts a row can say -- this channel states this licence, this
is the SPDX expression this product normalized it to, this one it would not
normalize -- and every one of them is only true or false once a run exists. Which
is why this module sits beside `tests/unit/django_apps/test_license.py`: the
declaration rule, the locator, the document reader and the normalizer are decided
before a run does, and are asserted there.

**AC 1 is proved by reading both columns off one row.** A reviewer's question is
"what did normalization do before I trust its result", so a case that read only the
normalized column would pass for a collector that had thrown the source's own words
away. Every determinate case here asserts the raw string too, and the case that
matters most is AC 2's: an `unknown` row still carrying the raw value is a review
item somebody can act on, while one carrying nothing is an absence of information.

**AC 2 is proved by the state and by what it is not.** `unknown`, never a
permissive value and never `not_found` -- which on a licence table would read as
*unrestricted*.

**The three constraints are database rules here, not conventions.** Each is
asserted by writing the row the collector may not write and watching PostgreSQL --
or SQLite -- refuse it, including the asymmetric half: the raw string is permitted
on every row there is, which is the permission AC 1 depends on.

**No socket is opened.** Every case substitutes the transport at the base's seam,
and every case declares its own monitored channels through
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
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction
from django.test import override_settings

from conda_sentinel.collectors.license import CHANNELS_SETTING
from conda_sentinel.collectors.license import COLLECTOR_NAME
from conda_sentinel.collectors.license import LICENSE_FIELD
from conda_sentinel.collectors.license import LICENSE_FRESHNESS_TARGET
from conda_sentinel.collectors.license import LICENSE_HEADERS
from conda_sentinel.collectors.license import NO_LICENSE_FIELD_DETAIL
from conda_sentinel.collectors.license import NO_LICENSE_STATED_DETAIL
from conda_sentinel.collectors.license import UNNORMALIZABLE_LICENSE_DETAIL
from conda_sentinel.collectors.license import UNREAD_CHANNEL_DETAIL
from conda_sentinel.collectors.license import UNRECOGNISED_LICENSE_DETAIL
from conda_sentinel.collectors.license import LicenseChannelError
from conda_sentinel.collectors.license import LicenseCollector
from conda_sentinel.collectors.license import LicenseDocumentError
from conda_sentinel.collectors.license import package_locator
from conda_sentinel.collectors.models import LICENSE_APPLICABILITY_CONSTRAINT
from conda_sentinel.collectors.models import LICENSE_CHANNEL_CONSTRAINT
from conda_sentinel.collectors.models import LICENSE_FACTS_CONSTRAINT
from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.outcomes import LICENSE_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import LICENSE_UNKNOWN
from conda_sentinel.collectors.outcomes import NORMALIZED
from conda_sentinel.collectors.spdx import DetectionMethod
from conda_sentinel.collectors.sweep import dispatch
from conda_sentinel.collectors.tasks import COLLECT_LICENSE_TASK_NAME
from conda_sentinel.collectors.tasks import collect_license
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.freshness import UNOBSERVED_STATUS
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.runs import RunLedgerError
from conda_sentinel.core.runs import RunState
from conda_sentinel.core.transport import Payload
from conda_sentinel.core.transport import TransportError
from conda_sentinel.identity.models import Package
from config.celery_app import app
from tests.clocks import FIXED_INSTANT
from tests.collectors import FixedLimiter
from tests.collectors import RecordingResponseCache
from tests.collectors import ScriptedTransport
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from datetime import datetime

    from conda_sentinel.core.collection import CollectionResult

#: The package the cases ask about, the channels they monitor, and the locators
#: those produce. Derived rather than written out: a case here is about what a
#: *run* does with a locator, and the unit tier is where their spelling is pinned.
A_NAME: Final[str] = "numpy"
A_CHANNEL: Final[str] = "conda-forge"
ANOTHER_CHANNEL: Final[str] = "bioconda"
THE_LOCATOR: Final[str] = package_locator(A_CHANNEL, A_NAME)
THE_OTHER_LOCATOR: Final[str] = package_locator(ANOTHER_CHANNEL, A_NAME)

#: What the channels state, and what this product records.
A_LICENSE: Final[str] = "MIT"
A_SPELLING: Final[str] = "Apache 2.0"
ITS_IDENTIFIER: Final[str] = "Apache-2.0"
AN_EXPRESSION: Final[str] = "BSD-3 OR mit"
ITS_NORMALIZED_FORM: Final[str] = "BSD-3-Clause OR MIT"
AN_UNRECOGNISED_LICENSE: Final[str] = "BSD"
ANOTHER_LICENSE: Final[str] = "GPL-3.0-only"

#: The entity tag a source hands back, for the caching case.
AN_ETAG: Final[str] = '"c0ffee"'

#: The counts the cases assert against, one named constant per concept, because
#: `PLR2004` is right about a bare number in an assertion.
TWO_ROWS: Final[int] = 2

#: The gap between two observations in the re-observation case, longer than the
#: declared window so the second collection is about re-observation.
A_DAY: Final[timedelta] = timedelta(days=1)

#: A primary key no row in this module holds.
NO_SUCH_PACKAGE: Final[int] = 9_999_999


def _document(license_value: object = A_LICENSE) -> str:
    """Return the body a channel would serve for one package.

    Args:
        license_value: What the channel states for `license`, or `None` for a
            channel that states it as JSON `null`.

    Returns:
        The JSON body.

    """
    return json.dumps({"name": A_NAME, "latest_version": "2.1.3", LICENSE_FIELD: license_value})


def _document_without_the_field() -> str:
    """Return the body a channel would serve if it had renamed or moved the licence field.

    Built from a literal rather than from `_document`, because what it is about is the
    key being *absent* -- which is a different fact from the key being present and
    null, and is the one the two record different reasons for.

    Returns:
        The JSON body, carrying every other field a real document carries.

    """
    return json.dumps({"name": A_NAME, "latest_version": "2.1.3", "license_family": "MIT"})


def _answering(**scripted: str | Payload) -> ScriptedTransport:
    """Return a transport answering each named channel with a body or a whole payload.

    Args:
        **scripted: `first` and `second` -- each either the body the channel serves
            or a whole `Payload` for the cases that need one.

    Returns:
        The scripted transport.

    """
    locators = {"first": THE_LOCATOR, "second": THE_OTHER_LOCATOR}
    answers: dict[str, Payload] = {}
    for which, answer in scripted.items():
        locator = locators[which]
        answers[locator] = answer if isinstance(answer, Payload) else recorded_payload(source=locator, body=answer)
    return ScriptedTransport(answers=answers)


def _monitoring(*channels: str) -> Any:
    """Return the settings override one case's monitored channels need.

    Declared per case rather than in a fixture, because what a case monitors is part
    of what it is asserting -- and because what *ships* is empty, which is itself one
    of the cases below.

    Args:
        *channels: The channels to declare, in order. Defaults to the first one.

    Returns:
        The `override_settings` context manager.

    """
    return override_settings(**{CHANNELS_SETTING: channels or (A_CHANNEL,)})


def _a_package(name: str = A_NAME) -> Package:
    """Return a saved package.

    Created directly rather than through `identity`'s resolution service, because
    what this module is about starts *after* a package exists. No mapping row is
    seeded and none is read: nothing a resolution recorded can make a licence
    question inapplicable.

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
) -> CollectionResult:
    """Run one collection through a scripted transport.

    Args:
        package: The package to observe.
        transport: The transport substituted at the base's seam (`CPM-AD-27`).
        at: The instant the run's clock is stopped at.
        force: Whether to bypass the observation window (`CPM-UJ-1`).
        permitted: What the substituted limiter answers.
        cache: The response cache to use, or a fresh recording one.

    Returns:
        What the run did.

    """
    collector = LicenseCollector(
        clock=FixedClock(instant=at),
        transport=transport,
        limiter=FixedLimiter(permitted=permitted),
        response_cache=cache if cache is not None else RecordingResponseCache(),
    )
    try:
        return collector.collect(package_id=package.pk, force=force)
    finally:
        collector.close()


def _rows(package: Package) -> list[LicenseFinding]:
    """Return this package's licence observations, oldest first.

    Args:
        package: The package to read.

    Returns:
        The rows, ordered by primary key.

    """
    return list(LicenseFinding.objects.filter(package=package).order_by("pk"))


def _run(package: Package) -> CollectionRun:
    """Return the most recent ledger row for this collector and package.

    Args:
        package: The package the run was scoped to.

    Returns:
        The row, newest first.

    """
    return CollectionRun.objects.filter(collector=COLLECTOR_NAME, package=package).order_by("-pk").first()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# AC 1: the raw string and the expression, side by side.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_recognised_licence_records_the_raw_string_the_expression_and_the_method() -> None:
    """AC 1 end to end: one row, both columns, the method named, the channel and the source on it.

    The raw column is asserted as well as the normalized one, which is the whole
    point of the story: a reviewer compares them to judge what normalization did, and
    a case that read only the expression would pass for a collector that had thrown
    the channel's own words away.
    """
    package = _a_package()

    with _monitoring():
        result = _collect(package, transport=_answering(first=_document(A_SPELLING)))

    (row,) = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert row.state == NORMALIZED
    assert row.raw_license == A_SPELLING
    assert row.normalized_license == ITS_IDENTIFIER
    assert row.detection_method == DetectionMethod.RECOGNISED_SPELLING.value
    assert row.channel == A_CHANNEL
    assert row.source == THE_LOCATOR
    assert row.observed_at == FIXED_INSTANT
    assert _run(package).status == RunState.SUCCEEDED.value


@pytest.mark.django_db
def test_a_compound_expression_is_one_row_and_the_method_says_it_was_an_expression() -> None:
    """The matrix's compound row: normalized whole, never split into one row per operand."""
    package = _a_package()

    with _monitoring():
        _collect(package, transport=_answering(first=_document(AN_EXPRESSION)))

    (row,) = _rows(package)

    assert row.raw_license == AN_EXPRESSION
    assert row.normalized_license == ITS_NORMALIZED_FORM
    assert row.detection_method == DetectionMethod.SPDX_EXPRESSION.value


@pytest.mark.django_db
def test_an_unrecognised_licence_is_unknown_with_the_raw_value_preserved_and_a_reason() -> None:
    """AC 2 end to end, and every clause of it.

    `unknown` rather than anything permissive; the normalized column blank; the raw
    value preserved *exactly*; and a detail saying it needs review. The last is what
    makes the row a review item a queue can select, which is how this story reads
    "routes to manual review" -- the queue itself belongs to `CPM-EP-APP`.
    """
    package = _a_package()

    with _monitoring():
        result = _collect(package, transport=_answering(first=_document(AN_UNRECOGNISED_LICENSE)))

    (row,) = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert row.state == LICENSE_UNKNOWN
    assert row.raw_license == AN_UNRECOGNISED_LICENSE
    assert row.normalized_license == ""
    assert row.detection_method == ""
    assert UNRECOGNISED_LICENSE_DETAIL in row.detail
    assert row.state != OutcomeState.NOT_FOUND.value
    assert row.state != OutcomeState.OK.value


@pytest.mark.django_db
def test_a_channel_that_states_no_licence_is_unknown_with_a_blank_raw_column_and_its_own_reason() -> None:
    """The matrix's "source states no licence" row: same state, distinct detail, blank raw column.

    Asserted *against* the unrecognised row's reason as well as for its own, because
    the two `unknown` rows are different pieces of work for a reviewer and `CPM-FR-6`
    is why they may not be folded into one sentence.
    """
    package = _a_package()

    with _monitoring():
        _collect(package, transport=_answering(first=_document(None)))

    (row,) = _rows(package)

    assert row.state == LICENSE_UNKNOWN
    assert row.raw_license == ""
    assert row.detail == NO_LICENSE_STATED_DETAIL
    assert UNRECOGNISED_LICENSE_DETAIL not in row.detail


@pytest.mark.django_db
def test_a_document_with_no_licence_field_at_all_records_that_rather_than_an_affirmative_none() -> None:
    """The field being absent is a different fact from the field being `null`, against a real row.

    If anaconda.org renames the field or wraps the body in an envelope, reading the
    two as one records "this channel states no license" -- an affirmative claim -- for
    every package on every channel, permanently, with the run `succeeded` and nothing
    failing anywhere. Both stay `unknown`, because a reader that could not find its
    field is not a reason to fail a package's run; the reason is what makes the
    rename visible in a sweep of `detail`.
    """
    package = _a_package()

    with _monitoring():
        result = _collect(package, transport=_answering(first=_document_without_the_field()))

    (row,) = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert row.state == LICENSE_UNKNOWN
    assert row.raw_license == ""
    assert row.detail == NO_LICENSE_FIELD_DETAIL
    assert row.detail != NO_LICENSE_STATED_DETAIL


@pytest.mark.django_db
def test_a_multi_line_licence_is_stored_verbatim_as_a_review_item_and_costs_no_other_channel_its_answer() -> None:
    """The refusal that used to fail the whole run over a value PostgreSQL stores perfectly well.

    `"BSD 3-Clause\\nSee LICENSE file"` is ordinary conda metadata. Refused, it raised
    out of `translate`, so the run went `failed`, the *other* channel got an `error`
    row without ever being asked, and both rows carried `raw_license=""` -- losing the
    string that caused it precisely where a reviewer needs it. It then repeated every
    day, because the observation window only suppresses after a success.

    Recorded, it is one `unknown` row carrying the newline verbatim beside the other
    channel's determinate row, and the run succeeds. The raw column is asserted
    character for character, which is the whole of AC 1 on the row it matters most on.
    """
    package = _a_package()
    stated = "BSD 3-Clause\nSee LICENSE file"

    with _monitoring(A_CHANNEL, ANOTHER_CHANNEL):
        result = _collect(package, transport=_answering(first=_document(stated), second=_document(A_LICENSE)))

    reviewable, licensed = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert reviewable.state == LICENSE_UNKNOWN
    assert reviewable.raw_license == stated
    assert reviewable.normalized_license == ""
    assert reviewable.detail == UNNORMALIZABLE_LICENSE_DETAIL
    assert licensed.state == NORMALIZED
    assert licensed.normalized_license == A_LICENSE


@pytest.mark.django_db
def test_a_lone_surrogate_is_refused_where_it_enters_rather_than_inside_the_driver() -> None:
    """The one value that reached `_write_evidence` outside every guard and wrote no row at all.

    `json.loads('{"license": "\\\\ud800"}')` succeeds; the value is one character wide,
    is not a control character and is not a recognised spelling, so it became an
    `unknown` row carrying it -- and psycopg raised `UnicodeEncodeError: surrogates not
    allowed` from inside the driver, past the `try` wrapping `translate`. No evidence
    row of any kind, and the same again the next day.

    Refused where the value enters it is the ordinary unreadable-value path: this
    module's own error, the base's `error` row written first, and a `failed` ledger
    row a reader can act on.
    """
    package = _a_package()
    body = json.dumps({"name": A_NAME, LICENSE_FIELD: "\ud800"})

    with _monitoring(), pytest.raises(LicenseDocumentError, match="not encodable as UTF-8"):
        _collect(package, transport=_answering(first=body))

    (row,) = _rows(package)

    assert row.state == OutcomeState.ERROR.value
    assert row.raw_license == ""
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_second_channels_failure_message_that_cannot_be_stored_still_writes_every_row() -> None:
    """`_channel_instead`'s reasons carry a third party's words, and this write has no handler over it.

    The rows a collection produces go in one `bulk_create` with no `DatabaseError`
    around it, so an uncleaned NUL byte in one transport failure's message discarded
    **every** channel's row -- including the determinate one the first channel had
    already earned -- from inside the driver. Asserted against a real table so the
    driver is the one being satisfied rather than a guard's own opinion of it.
    """
    package = _a_package()
    transport = _answering(first=_document(A_LICENSE))
    transport.failures[THE_OTHER_LOCATOR] = TransportError(
        "the host refused\x00 the \x07connection \ud800",
        source=THE_OTHER_LOCATOR,
    )

    with _monitoring(A_CHANNEL, ANOTHER_CHANNEL):
        result = _collect(package, transport=transport)

    answered, failed = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert answered.state == NORMALIZED
    assert failed.state == OutcomeState.ERROR.value
    assert "\x00" not in failed.detail
    assert "\ud800" not in failed.detail


# ---------------------------------------------------------------------------
# The channels, kept apart.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_two_channels_stating_different_licences_are_two_rows_and_neither_merges_them() -> None:
    """The matrix's disagreement row: disagreement is a fact to record rather than a verdict to resolve.

    One row per channel, each naming its own channel and its own source, and nothing
    anywhere deciding which of the two is right -- that judgement is not this
    collector's and is not this table's.
    """
    package = _a_package()

    with _monitoring(A_CHANNEL, ANOTHER_CHANNEL):
        _collect(
            package,
            transport=_answering(first=_document(A_LICENSE), second=_document(ANOTHER_LICENSE)),
        )

    first, second = _rows(package)

    assert len(_rows(package)) == TWO_ROWS
    assert (first.channel, first.raw_license, first.normalized_license) == (A_CHANNEL, A_LICENSE, A_LICENSE)
    assert (second.channel, second.raw_license, second.normalized_license) == (
        ANOTHER_CHANNEL,
        ANOTHER_LICENSE,
        ANOTHER_LICENSE,
    )
    assert first.source == THE_LOCATOR
    assert second.source == THE_OTHER_LOCATOR


@pytest.mark.django_db
def test_a_failing_second_channel_leaves_the_first_channels_row_and_carries_error_on_its_own() -> None:
    """`CPM-FR-15` on the per-package path: one channel's failure never discards another's answer."""
    package = _a_package()
    transport = _answering(first=_document(A_LICENSE))
    transport.failures[THE_OTHER_LOCATOR] = TransportError("the host refused", source=THE_OTHER_LOCATOR)

    with _monitoring(A_CHANNEL, ANOTHER_CHANNEL):
        result = _collect(package, transport=transport)

    answered, failed = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert answered.state == NORMALIZED
    assert failed.state == OutcomeState.ERROR.value
    assert failed.channel == ANOTHER_CHANNEL
    assert failed.raw_license == ""
    assert UNREAD_CHANNEL_DETAIL in failed.detail


@pytest.mark.django_db
def test_a_first_channel_that_does_not_serve_the_package_never_stops_a_second_being_asked() -> None:
    """The defect `CPM-CURRENCY-S04` was patched for, asserted in a second table so it is not repeated.

    The base's `not_found` branch writes its rows without reaching `translate`, so a
    collector that owed one row per channel and did not override
    `sentinel_evidence_rows` would record nothing whatever about the second channel --
    which is exactly the case "one row per monitored channel" exists for.
    """
    package = _a_package()

    with _monitoring(A_CHANNEL, ANOTHER_CHANNEL):
        result = _collect(
            package,
            transport=_answering(
                first=recorded_payload(source=THE_LOCATOR, body="", found=False),
                second=_document(A_LICENSE),
            ),
        )

    absent, licensed = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert absent.channel == A_CHANNEL
    assert absent.state == OutcomeState.NOT_FOUND.value
    assert licensed.channel == ANOTHER_CHANNEL
    assert licensed.state == NORMALIZED
    assert licensed.normalized_license == A_LICENSE


@pytest.mark.django_db
def test_a_package_absent_from_every_channel_is_one_row_per_channel_naming_what_was_asked() -> None:
    """The matrix's absence row: the base's answer, on the record, for each channel it was about.

    With one monitored channel that is literally one row. With two it is one per
    channel, because the alternative -- a single row standing for both -- is the merge
    this table refuses, and because the run really did ask each of them.
    """
    package = _a_package()

    with _monitoring(A_CHANNEL, ANOTHER_CHANNEL):
        result = _collect(
            package,
            transport=_answering(
                first=recorded_payload(source=THE_LOCATOR, body="", found=False),
                second=recorded_payload(source=THE_OTHER_LOCATOR, body="", found=False),
            ),
        )

    rows = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert [row.state for row in rows] == [OutcomeState.NOT_FOUND.value] * TWO_ROWS
    assert [row.channel for row in rows] == [A_CHANNEL, ANOTHER_CHANNEL]
    assert [row.source for row in rows] == [THE_LOCATOR, THE_OTHER_LOCATOR]
    assert all(row.raw_license == "" for row in rows)


@pytest.mark.django_db
def test_one_monitored_channel_that_does_not_serve_the_package_is_exactly_one_row() -> None:
    """The matrix's absence row at its simplest, and a `succeeded` run: the channel answered."""
    package = _a_package()

    with _monitoring():
        result = _collect(package, transport=_answering(first=recorded_payload(source=THE_LOCATOR, found=False)))

    (row,) = _rows(package)

    assert result.state is RunState.SUCCEEDED
    assert row.state == OutcomeState.NOT_FOUND.value
    assert row.channel == A_CHANNEL
    assert THE_LOCATOR in row.detail


# ---------------------------------------------------------------------------
# The failing paths: the base's rows, and the ledger.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_only_channel_failing_is_an_error_row_naming_its_channel_and_a_failed_run() -> None:
    """The matrix's transport-failure row: `error` on the row, `failed` on the ledger."""
    package = _a_package()
    transport = ScriptedTransport(failures={THE_LOCATOR: TransportError("the host refused", source=THE_LOCATOR)})

    with _monitoring():
        result = _collect(package, transport=transport)

    (row,) = _rows(package)

    assert result.state is RunState.FAILED
    assert row.state == OutcomeState.ERROR.value
    assert row.channel == A_CHANNEL
    assert row.raw_license == ""
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_spent_allowance_writes_an_error_row_per_channel_and_issues_no_call() -> None:
    """The matrix's refused-allowance row: nothing is asked, and every channel still gets a row.

    Calls issued on this path would spend the remote budget the limiter has just
    refused (`CPM-AD-20`) and would write determinate rows underneath a ledger row
    that says the run failed.
    """
    package = _a_package()
    transport = _answering(first=_document(A_LICENSE), second=_document(A_LICENSE))

    with _monitoring(A_CHANNEL, ANOTHER_CHANNEL):
        result = _collect(package, transport=transport, permitted=False)

    rows = _rows(package)

    assert result.state is RunState.FAILED
    assert [row.channel for row in rows] == [A_CHANNEL, ANOTHER_CHANNEL]
    assert {row.state for row in rows} == {OutcomeState.ERROR.value}
    assert transport.calls == []


@pytest.mark.django_db
def test_an_unreadable_first_document_writes_an_error_row_before_it_raises() -> None:
    """The matrix's unreadable-document row: a document error from `translate`, an `error` row, and a re-raise.

    `CPM-NFR-3` holds on this path too -- never a clean result and never no row -- and
    the refusal is what stops a source whose shape has changed being recorded as a
    channel that states no licence.
    """
    package = _a_package()

    with _monitoring(), pytest.raises(LicenseDocumentError, match=THE_LOCATOR):
        _collect(package, transport=_answering(first="not a document at all"))

    (row,) = _rows(package)

    assert row.state == OutcomeState.ERROR.value
    assert row.channel == A_CHANNEL
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_a_licence_wider_than_its_column_fails_the_run_rather_than_storing_a_different_licence() -> None:
    """The matrix's width row, end to end: refused where the value enters, never truncated.

    On SQLite an over-long value would simply be stored, so the guard is what makes
    the two backends agree -- and a truncated licence is a different licence,
    permanently, in a row nothing may correct.
    """
    package = _a_package()
    width = LicenseFinding._meta.get_field("raw_license").max_length  # noqa: SLF001 - Django's own public API
    assert width is not None

    with _monitoring(), pytest.raises(LicenseDocumentError, match="truncated"):
        _collect(package, transport=_answering(first=_document("M" * (width + 1))))

    (row,) = _rows(package)

    assert row.state == OutcomeState.ERROR.value
    assert row.raw_license == ""


# ---------------------------------------------------------------------------
# The declaration, the selection and the dispatch.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_run_that_finds_nothing_declared_fails_naming_the_setting_and_writes_no_row() -> None:
    """The shipped state: `CPM_MONITORED_CHANNELS` is empty and PRD Open Question 4 owns the choice.

    No evidence row at all, because there is nothing honest to write: every row names
    the channel it is about, and not knowing which channel is not a channel.
    """
    package = _a_package()

    with override_settings(**{CHANNELS_SETTING: ()}), pytest.raises(LicenseChannelError, match=CHANNELS_SETTING):
        _collect(package, transport=ScriptedTransport())

    assert _rows(package) == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_an_undeclared_component_selects_nothing_so_a_scheduled_run_records_an_empty_selection() -> None:
    """The matrix's "nothing declared" row, and the lesson `CPM-CURRENCY-S04` was patched for.

    A selection that offered the inventory anyway would have a scheduled sweep write
    one `failed` collection per package per day, for ever, out of the box -- reached
    from the shipped settings rather than from any mistake an operator made.
    """
    _a_package()

    with override_settings(**{CHANNELS_SETTING: ()}):
        assert list(LicenseCollector.selectable_packages()) == []

    with override_settings(**{CHANNELS_SETTING: "conda-forge"}):
        assert list(LicenseCollector.selectable_packages()) == []


@pytest.mark.django_db
def test_a_declared_component_offers_every_package_including_ones_no_channel_serves() -> None:
    """ "It is not there" is the observation `CPM-FR-13` asks for rather than a reason not to look.

    Narrowing the selection to packages some channel is known to serve would be the
    selection defect `CPM-SECURITY-S01` was patched for, in a third table.
    """
    first = _a_package()
    second = _a_package("nothing-published")

    with _monitoring():
        assert sorted(LicenseCollector.selectable_packages()) == sorted([first.pk, second.pk])


@pytest.mark.django_db
def test_the_dispatch_enqueues_one_collection_per_package_under_the_derived_task_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep end to end, which is the only place the selection and the task name meet.

    `collectors/sweep.py` derives `cpm.collect.<name>` from the registry key, so a
    task declared under any other name would be enqueued into a queue nothing
    consumes -- silent non-delivery rather than an error. The task's `apply_async` is
    intercepted rather than left to the eager suite, which would otherwise run a real
    collection per package.
    """
    first = _a_package()
    second = _a_package("another-package")
    accepted: list[int] = []

    def _apply_async(*, kwargs: dict[str, Any], **_options: Any) -> None:
        accepted.append(int(kwargs["package_id"]))

    monkeypatch.setattr(app.tasks[COLLECT_LICENSE_TASK_NAME], "apply_async", _apply_async)

    with _monitoring():
        outcome = dispatch(collector=COLLECTOR_NAME, clock=FixedClock(instant=FIXED_INSTANT))

    assert outcome.state is RunState.SUCCEEDED
    assert sorted(accepted) == sorted([first.pk, second.pk])


# ---------------------------------------------------------------------------
# The task, the window and the read back.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_task_records_a_run_and_returns_how_it_ended() -> None:
    """The task is the collection the dispatch enqueues, run against a real table.

    The transport is the base's own here rather than a substituted one, which is why
    the case declares no channel: what it asserts is that an unconfigured component
    fails loudly naming the setting rather than reaching a socket.
    """
    package = _a_package()

    with override_settings(**{CHANNELS_SETTING: ()}), pytest.raises(LicenseChannelError, match=CHANNELS_SETTING):
        collect_license(package_id=package.pk)

    assert _rows(package) == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_collecting_a_package_that_is_not_there_leaves_nothing_behind_at_all() -> None:
    """`CPM-EVIDENCE-S09`: the recorder checks the key before it opens a row."""
    with _monitoring(), pytest.raises(RunLedgerError):
        collect_license(package_id=NO_SUCH_PACKAGE)

    assert LicenseFinding.objects.count() == 0
    assert CollectionRun.objects.filter(collector=COLLECTOR_NAME).count() == 0


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
    collector = LicenseCollector(clock=FixedClock(instant=FIXED_INSTANT), transport=ScriptedTransport())
    try:
        with _monitoring(), pytest.raises(LicenseChannelError, match=str(NO_SUCH_PACKAGE)):
            collector.source_for(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()


@pytest.mark.django_db
def test_re_observation_inserts_rather_than_updating() -> None:
    """`CPM-AD-2`: evidence always inserts, and a licence that changed is two rows rather than one corrected.

    Which is the whole reason there is no unique constraint on this table: the tuple
    that looks unique -- package, channel, licence -- is exactly the tuple a
    re-observation repeats.
    """
    package = _a_package()

    with _monitoring():
        _collect(package, transport=_answering(first=_document(A_LICENSE)))
        _collect(package, transport=_answering(first=_document(A_SPELLING)), at=FIXED_INSTANT + A_DAY)

    first, second = _rows(package)

    assert len(_rows(package)) == TWO_ROWS
    assert (first.raw_license, first.observed_at) == (A_LICENSE, FIXED_INSTANT)
    assert (second.raw_license, second.observed_at) == (A_SPELLING, FIXED_INSTANT + A_DAY)


@pytest.mark.django_db
def test_a_second_collection_inside_the_window_is_skipped_without_a_call_and_force_writes_again() -> None:
    """`CPM-AD-7`'s observation window, and `CPM-UJ-1`'s manual recollection past it."""
    package = _a_package()
    transport = _answering(first=_document(A_LICENSE))

    with _monitoring():
        _collect(package, transport=transport)
        skipped = _collect(package, transport=transport)
        forced = _collect(package, transport=transport, force=True)

    assert skipped.state is RunState.SKIPPED
    assert forced.state is RunState.SUCCEEDED
    assert transport.calls == [THE_LOCATOR, THE_LOCATOR]
    assert len(_rows(package)) == TWO_ROWS


@pytest.mark.django_db
def test_a_revalidated_answer_writes_the_same_row_a_body_would_have() -> None:
    """The declared cache covers the base's one call, and a `304` replays the remembered body.

    A licence is a statement in the metadata of a build that has already been
    published, so a revalidated answer is the channel itself saying the document has
    not changed -- which is a different thing from replaying a security answer blind.
    """
    package = _a_package()
    cache = RecordingResponseCache()

    with _monitoring():
        _collect(
            package,
            transport=_answering(
                first=recorded_payload(source=THE_LOCATOR, body=_document(A_LICENSE), etag=AN_ETAG),
            ),
            cache=cache,
        )
        _collect(
            package,
            transport=_answering(
                first=recorded_payload(source=THE_LOCATOR, body="", not_modified=True, etag=AN_ETAG),
            ),
            cache=cache,
            at=FIXED_INSTANT + A_DAY,
        )

    first, second = _rows(package)

    assert first.normalized_license == A_LICENSE
    assert second.normalized_license == A_LICENSE
    assert second.raw_license == A_LICENSE


@pytest.mark.django_db
def test_the_declared_headers_reach_the_call_the_base_makes() -> None:
    """Headers are declared and the base sends them (`CPM-AD-20`, `CPM-AD-27`)."""
    package = _a_package()
    transport = _answering(first=_document(A_LICENSE))

    with _monitoring():
        _collect(package, transport=transport)

    (sent,) = transport.sent_headers

    assert sent is not None
    assert sent["User-Agent"] == LICENSE_HEADERS["User-Agent"]
    assert sent["Accept"] == LICENSE_HEADERS["Accept"]


@pytest.mark.django_db
def test_the_declared_headers_reach_the_call_this_collector_makes_for_the_second_channel() -> None:
    """The base sends the first channel's headers; `_channel_instead` has to send the rest itself.

    The case above runs one channel and reads `sent_headers[0]`, which is the base's
    own call -- so dropping `request_headers(...)` from `_channel_instead` left it
    green while every channel after the first asked `api.anaconda.org` for no
    particular representation, from an unidentified client. The published-package
    collector closed exactly this gap on its own copy of this method
    (`tests/integration/django_apps/test_conda_package.py`); this is the same guard.
    """
    package = _a_package()
    transport = _answering(first=_document(A_LICENSE), second=_document(ANOTHER_LICENSE))

    with _monitoring(A_CHANNEL, ANOTHER_CHANNEL):
        _collect(package, transport=transport)

    assert transport.calls == [THE_LOCATOR, THE_OTHER_LOCATOR]
    assert dict(LICENSE_HEADERS).items() <= dict(transport.sent_headers[1] or {}).items()


@pytest.mark.django_db
def test_an_unknown_row_is_read_back_as_an_observation_with_its_instant_rather_than_as_staleness() -> None:
    """The row AC 2 guarantees is only worth writing if a later reader sees it as an observation.

    A package with no row reads as *unobserved*, which is a different answer -- and
    the paired case below is what shows this read answering that other thing.
    """
    package = _a_package()

    with _monitoring():
        _collect(package, transport=_answering(first=_document(AN_UNRECOGNISED_LICENSE)))

    collector = LicenseCollector(clock=FixedClock(instant=FIXED_INSTANT))
    try:
        report = collector.freshness(package_id=package.pk, now=FIXED_INSTANT, status=LICENSE_UNKNOWN)
        stale = collector.freshness(
            package_id=package.pk,
            now=FIXED_INSTANT + LICENSE_FRESHNESS_TARGET + A_DAY,
            status=LICENSE_UNKNOWN,
        )
        never = collector.freshness(package_id=_a_package("never-observed").pk, now=FIXED_INSTANT)
    finally:
        collector.close()

    assert report.observed_at == FIXED_INSTANT
    assert not report.stale
    assert stale.stale
    assert never.status == UNOBSERVED_STATUS


# ---------------------------------------------------------------------------
# The three constraints, as the database enforces them.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "facts",
    [
        {},
        {"normalized_license": A_LICENSE},
        {"detection_method": DetectionMethod.SPDX_IDENTIFIER.value},
    ],
    ids=["neither", "no-method", "no-expression"],
)
def test_a_determinate_row_missing_either_normalized_fact_is_refused_by_the_database(facts: dict[str, str]) -> None:
    """A normalized licence nobody can say how this product arrived at is not a finding.

    `CPM-SM-2`'s "carries source" is the half a convention would have lost: the
    expression alone is a value a reader has to take on trust.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=LICENSE_FACTS_CONSTRAINT), transaction.atomic():
        LicenseFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=NORMALIZED,
            channel=A_CHANNEL,
            raw_license=A_LICENSE,
            **facts,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [LICENSE_UNKNOWN, OutcomeState.ERROR.value, OutcomeState.NOT_FOUND.value],
    ids=["unknown", "error", "not-found"],
)
@pytest.mark.parametrize(
    "facts",
    [
        {"normalized_license": A_LICENSE},
        {"detection_method": DetectionMethod.SPDX_IDENTIFIER.value},
        {"normalized_license": A_LICENSE, "detection_method": DetectionMethod.SPDX_IDENTIFIER.value},
    ],
    ids=["expression", "method", "both"],
)
def test_a_row_that_is_not_determinate_carrying_a_normalized_fact_is_refused_by_the_database(
    state: str,
    facts: dict[str, str],
) -> None:
    """The story's own acceptance criterion, as a database rule.

    A normalized expression under any other state claims a normalization the run
    never performed -- on an `unknown` row that is an SPDX expression underneath a
    statement that the licence was not recognised.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=LICENSE_FACTS_CONSTRAINT), transaction.atomic():
        LicenseFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=state,
            channel=A_CHANNEL,
            **facts,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [NORMALIZED, LICENSE_UNKNOWN, OutcomeState.ERROR.value, OutcomeState.NOT_FOUND.value],
    ids=["normalized", "unknown", "error", "not-found"],
)
def test_a_row_that_cannot_name_its_channel_is_refused_by_the_database(state: str) -> None:
    """Over every state rather than only the determinate one, which is the half a convention would miss.

    A sentinel row that could not say which channel it was about would be an
    observation of nowhere, in a table whose whole purpose is keeping the channels
    apart.
    """
    package = _a_package()
    determinate = state == NORMALIZED

    with pytest.raises(IntegrityError, match=LICENSE_CHANNEL_CONSTRAINT), transaction.atomic():
        LicenseFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=state,
            channel="",
            normalized_license=A_LICENSE if determinate else "",
            detection_method=DetectionMethod.SPDX_IDENTIFIER.value if determinate else "",
        )


@pytest.mark.django_db
def test_the_one_value_this_vocabulary_carries_and_this_table_may_never_hold_is_refused() -> None:
    """`not_applicable` arrives in `LicenseOutcome` by construction and every package is licensed under something.

    `LicenseCollector` refuses it at `sentinel_evidence` and `inapplicability` never
    answers a reason, but both of those are one writer's rules; this is the table's,
    and it holds against every writer this product ever grows.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=LICENSE_APPLICABILITY_CONSTRAINT), transaction.atomic():
        LicenseFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=LICENSE_NOT_APPLICABLE,
            channel=A_CHANNEL,
        )


@pytest.mark.django_db
def test_the_raw_value_is_permitted_on_every_row_including_the_ones_that_failed() -> None:
    """The anti-vacuity half, and the permission AC 1 actually depends on.

    The constraint is deliberately asymmetric: it says nothing whatever about
    `raw_license`, because an `unknown` row carrying the string a channel stated is a
    review item somebody can act on and one carrying nothing is an absence of
    information. A constraint that tidied it away would delete the evidence this
    story exists to record.
    """
    package = _a_package()

    for state in (LICENSE_UNKNOWN, OutcomeState.ERROR.value, OutcomeState.NOT_FOUND.value):
        LicenseFinding.objects.create(
            observed_at=FIXED_INSTANT,
            package=package,
            state=state,
            channel=A_CHANNEL,
            raw_license=AN_UNRECOGNISED_LICENSE,
        )
    LicenseFinding.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        state=NORMALIZED,
        channel=A_CHANNEL,
        raw_license=A_LICENSE,
        normalized_license=A_LICENSE,
        detection_method=DetectionMethod.SPDX_IDENTIFIER.value,
    )

    assert all(row.raw_license for row in _rows(package))


@pytest.mark.django_db
def test_a_row_renders_the_licence_the_channel_and_the_state_it_carries() -> None:
    """`__str__` is read off the key columns rather than the related object, which raises when unsaved."""
    rendered = str(
        LicenseFinding(
            observed_at=FIXED_INSTANT,
            package_id=_a_package().pk,
            state=NORMALIZED,
            channel=A_CHANNEL,
            raw_license=A_SPELLING,
            normalized_license=ITS_IDENTIFIER,
            detection_method=DetectionMethod.RECOGNISED_SPELLING.value,
        ),
    )

    assert A_SPELLING in rendered
    assert A_CHANNEL in rendered
    assert NORMALIZED in rendered
    assert FIXED_INSTANT.isoformat() in rendered
