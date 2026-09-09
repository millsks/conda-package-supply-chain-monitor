"""Verified compatibility against real tables: the two verdicts, the three sentinels, and the constraints.

`CPM-PY314-S02` asks for a verification that says where it ran, that is
distinguishable from an inference, and that nothing sweeps. The first and the third
are only true or false once a run exists, which is why this module sits beside
`tests/unit/django_apps/test_py314_verification.py`: the document reader, the
declarations, the queue routing and the seam are decided before a run does, and are
asserted there.

**AC 1 is proved from both sides here.** A determinate run writes the platform, the
architecture and the log reference onto the row -- and the database refuses a
determinate row that names fewer than all three, which is the half a collector's own
discipline cannot demonstrate.

**AC 2 is proved as two rows about one package.** A package carrying a static
`inferred_compatible` assessment *and* a verified result is read back and the two
states are asserted distinct, on the real tables, in the shape a read surface would
join them. Nothing else in this repository puts the two rows side by side.

**AC 3 is proved as a refusal.** A dispatch that names this collector is refused by
name, against the real registry, and nothing is enqueued -- so a beat entry added
later fails at its first tick rather than sweeping the inventory.

**No build runs, and none can.** Every case substitutes the backend at the base's
seam with something that answers a literal, which is what `CPM-AD-29` makes possible
and what `collectors/verification.py` ships nothing for.

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
from conda_sentinel.collectors.models import VERIFICATION_EVIDENCE_CONSTRAINT
from conda_sentinel.collectors.models import VERIFICATION_REASON_CONSTRAINT
from conda_sentinel.collectors.models import VERIFICATION_SERIES_CONSTRAINT
from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.models import PythonVerificationResult
from conda_sentinel.collectors.outcomes import INFERRED_COMPATIBLE
from conda_sentinel.collectors.outcomes import VERIFICATION_ERROR
from conda_sentinel.collectors.outcomes import VERIFICATION_FAILED
from conda_sentinel.collectors.outcomes import VERIFICATION_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import VERIFICATION_NOT_FOUND
from conda_sentinel.collectors.outcomes import VERIFIED_COMPATIBLE
from conda_sentinel.collectors.py314_verification import COLLECTOR_NAME
from conda_sentinel.collectors.py314_verification import NOT_BUILT_DETAIL
from conda_sentinel.collectors.py314_verification import NOT_OBTAINABLE_DETAIL
from conda_sentinel.collectors.py314_verification import PYTHON_SERIES
from conda_sentinel.collectors.py314_verification import Py314VerificationCollector
from conda_sentinel.collectors.py314_verification import Py314VerificationDocumentError
from conda_sentinel.collectors.py314_verification import Py314VerificationIdentityError
from conda_sentinel.collectors.py314_verification import package_locator
from conda_sentinel.collectors.specifiers import DecidingSignal
from conda_sentinel.collectors.specifiers import series_of
from conda_sentinel.collectors.sweep import SweepDispatchError
from conda_sentinel.collectors.sweep import dispatch
from conda_sentinel.collectors.verification import VerificationBackendError
from conda_sentinel.collectors.verification import declare_verification_backend
from conda_sentinel.collectors.verification import withdraw_verification_backend
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.runs import RunState
from conda_sentinel.core.transport import TransportError
from conda_sentinel.identity.models import ESTABLISHED
from conda_sentinel.identity.models import MappingKind
from conda_sentinel.identity.models import Package
from conda_sentinel.identity.models import PackageMapping
from tests.clocks import FIXED_INSTANT
from tests.collectors import FixedLimiter
from tests.collectors import RecordedTransport
from tests.collectors import RecordingResponseCache
from tests.collectors import recorded_payload

if TYPE_CHECKING:
    from conda_sentinel.core.collection import CollectionResult

#: The purl the packages in this module are resolved to, and the locator it
#: produces. Derived rather than written out: a case here is about what a *run* does
#: with a locator, and the unit tier is where its spelling is pinned.
A_PURL: Final[str] = "pkg:pypi/Django"
THE_LOCATOR: Final[str] = package_locator(A_PURL)

#: What a backend reports about where it ran.
A_PLATFORM: Final[str] = "linux"
AN_ARCHITECTURE: Final[str] = "x86_64"
A_LOG_REFERENCE: Final[str] = "https://builds.example.invalid/runs/1234/log"

#: A second runner, for the case about two verifications of one package. A verified
#: result is about one platform, so a second row on another platform is not a
#: correction -- it is a different fact.
ANOTHER_PLATFORM: Final[str] = "osx"
ANOTHER_ARCHITECTURE: Final[str] = "arm64"
ANOTHER_LOG_REFERENCE: Final[str] = "https://builds.example.invalid/runs/1235/log"

#: A specifier the static half would read as admitting the series, for the one case
#: that puts an inferred row and a verified row side by side.
AN_ADMITTING_SPECIFIER: Final[str] = ">=3.9"

#: How many rows the cases that write twice expect. Named because `PLR2004` is right
#: about a bare number in an assertion.
TWO_ROWS: Final[int] = 2

#: A primary key no row in this module holds.
NO_SUCH_PACKAGE: Final[int] = 9_999_999


class _RaisingBackend:
    """A backend that falls over rather than answering, for the `error` path.

    Distinct from a backend that answers `verified: false`, which is the whole point
    of the case that uses it: a failed build is a result and a backend that raised is
    not.
    """

    def __init__(self) -> None:
        """Record that nothing has been asked yet."""
        self.calls: list[str] = []

    def fetch(self, source: str, *, headers: Any = None) -> Any:
        """Raise, as an adapter whose runner is unreachable must.

        Args:
            source: The locator asked about.
            headers: The headers, ignored.

        Raises:
            TransportError: Always.

        """
        self.calls.append(source)
        message = "the build runner is unreachable"
        raise TransportError(message, source=source, status_code=None)


def _result(
    *,
    verified: bool = True,
    platform: str = A_PLATFORM,
    architecture: str = AN_ARCHITECTURE,
    log_reference: str = A_LOG_REFERENCE,
    detail: str | None = None,
) -> str:
    """Return the result document a backend would answer with.

    Args:
        verified: Whether the build and the import came out.
        platform: Where it ran.
        architecture: What it ran on.
        log_reference: Where the log is.
        detail: The backend's own note, or `None` to send none.

    Returns:
        The JSON body.

    """
    document: dict[str, Any] = {
        "verified": verified,
        "platform": platform,
        "architecture": architecture,
        "log_reference": log_reference,
    }
    if detail is not None:
        document["detail"] = detail
    return json.dumps(document)


def _answering(body: str = _result(), **payload: Any) -> RecordedTransport:
    """Return a backend that answers the locator with this body.

    Args:
        body: What the backend answers.
        **payload: Further `Payload` fields -- `found`, most usefully.

    Returns:
        The recorded transport standing in for a declared execution backend.

    """
    return RecordedTransport(payload=recorded_payload(source=THE_LOCATOR, body=body, **payload))


def _a_package(
    name: str = "django",
    *,
    outcome: str | None = ESTABLISHED,
    primary_purl: str = A_PURL,
) -> Package:
    """Return a saved package with a recorded release-ecosystem identity.

    Created directly rather than through `identity`'s resolution service, because
    what this module is about starts *after* an identity exists.

    Args:
        name: The canonical name, unique per case.
        outcome: The `release_ecosystem` mapping's outcome, or `None` to record no
            mapping row at all -- a package no resolver has reached.
        primary_purl: What resolution recorded as the primary purl.

    Returns:
        The saved row.

    """
    package = Package.objects.create(
        canonical_name=name,
        resolved_at=FIXED_INSTANT,
        primary_type="pypi",
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


def _verify(
    package: Package,
    *,
    transport: Any,
    at: datetime = FIXED_INSTANT,
    permitted: bool = True,
    limiter: FixedLimiter | None = None,
) -> CollectionResult:
    """Run one verification through a scripted backend.

    Args:
        package: The package to verify.
        transport: The backend substituted at the base's seam (`CPM-AD-27`,
            `CPM-AD-29`).
        at: The instant the run's clock is stopped at.
        permitted: What the substituted limiter answers, when none is passed.
        limiter: The limiter to use, so a case can read what it was asked.

    Returns:
        What the run did.

    """
    collector = Py314VerificationCollector(
        clock=FixedClock(instant=at),
        transport=transport,
        limiter=limiter if limiter is not None else FixedLimiter(permitted=permitted),
        response_cache=RecordingResponseCache(),
    )
    try:
        return collector.collect(package_id=package.pk)
    finally:
        collector.close()


def _rows(package: Package) -> list[PythonVerificationResult]:
    """Return this package's verification results, oldest first.

    Args:
        package: The package to read.

    Returns:
        The rows, ordered by primary key.

    """
    return list(PythonVerificationResult.objects.filter(package=package).order_by("pk"))


def _run(package: Package) -> CollectionRun:
    """Return the most recent ledger row for this collector and package.

    Args:
        package: The package the run was scoped to.

    Returns:
        The row, newest first.

    """
    return CollectionRun.objects.filter(collector=COLLECTOR_NAME, package=package).order_by("-pk").first()  # type: ignore[return-value]


def _row(**overrides: Any) -> PythonVerificationResult:
    """Return an unsaved result row a constraint case can try to insert.

    Args:
        **overrides: Columns to replace on an otherwise ordinary determinate row.

    Returns:
        The unsaved row.

    """
    fields: dict[str, Any] = {
        "observed_at": FIXED_INSTANT,
        "source": THE_LOCATOR,
        "state": VERIFIED_COMPATIBLE,
        "python_series": series_of(PYTHON_SERIES),
        "platform": A_PLATFORM,
        "architecture": AN_ARCHITECTURE,
        "log_reference": A_LOG_REFERENCE,
        "detail": "",
        "trace_id": "",
    }
    fields.update(overrides)
    return PythonVerificationResult(**fields)


# ---------------------------------------------------------------------------
# AC 1: it records the platform and architecture it ran on, and a log reference.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_successful_verification_records_where_it_ran_and_what_it_can_be_checked_against() -> None:
    """AC 1: the platform, the architecture and a log reference, on the row.

    Asserted as three columns rather than as "the row exists", because the criterion
    is about what a reader can find out afterwards: a verified row nobody can trace to
    a runner and a log is a claim with no evidence attached.
    """
    package = _a_package()

    result = _verify(package, transport=_answering())

    assert result.state is RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == VERIFIED_COMPATIBLE
    assert row.platform == A_PLATFORM
    assert row.architecture == AN_ARCHITECTURE
    assert row.log_reference == A_LOG_REFERENCE
    assert row.python_series == series_of(PYTHON_SERIES)
    assert row.source == THE_LOCATOR


@pytest.mark.django_db
def test_a_failed_build_is_a_determinate_row_carrying_its_log_reference() -> None:
    """The matrix row: a failed build is a result, not an error.

    Both halves asserted -- the state is the determinate one *and* it is not `error`,
    because folding the two together would lose exactly the row an engineer opens, and
    the ledger still says the run succeeded.
    """
    package = _a_package()

    result = _verify(package, transport=_answering(_result(verified=False)))

    assert result.state is RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == VERIFICATION_FAILED
    assert row.state != VERIFICATION_ERROR
    assert row.log_reference == A_LOG_REFERENCE
    assert row.platform == A_PLATFORM
    assert row.detail == NOT_BUILT_DETAIL


@pytest.mark.django_db
def test_a_backend_that_raised_writes_an_error_row_with_nowhere_named() -> None:
    """Distinct from a failed build: nothing was verified, so there is nothing to open.

    The ledger says `failed` where the failed *build* above left it `succeeded`, which
    is the operational difference an alert is written against.
    """
    package = _a_package()
    backend = _RaisingBackend()

    result = _verify(package, transport=backend)

    assert result.state is RunState.FAILED
    row = _rows(package)[0]
    assert row.state == VERIFICATION_ERROR
    assert row.platform == ""
    assert row.architecture == ""
    assert row.log_reference == ""
    assert backend.calls == [THE_LOCATOR]


@pytest.mark.django_db
def test_a_backend_that_cannot_say_where_it_ran_writes_an_error_row_and_never_a_verdict() -> None:
    """AC 1 is not optional, and a document that omits it is refused at the reader.

    The row is `error` rather than absent, which is the amendment `CPM-PY314-S02`'s
    Spec Change Log records: the matrix asked for no row, the base writes one for a
    translation that raised, and `CPM-NFR-3` wants it written. What the criterion
    actually protects -- never a determinate row with nowhere attached -- holds either
    way, and is asserted here as well as by the constraint below.
    """
    package = _a_package()
    body = json.dumps({"verified": True, "platform": "", "architecture": "", "log_reference": ""})

    with pytest.raises(Py314VerificationDocumentError, match=r"CPM-PY314-S02 AC 1"):
        _verify(package, transport=_answering(body))

    row = _rows(package)[0]
    assert row.state == VERIFICATION_ERROR
    assert row.state not in {VERIFIED_COMPATIBLE, VERIFICATION_FAILED}
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_the_database_refuses_a_determinate_row_that_names_fewer_than_all_three() -> None:
    """`VERIFICATION_EVIDENCE_CONSTRAINT` from the side that matters.

    Parametrized by hand over the three columns rather than by decorator, because each
    needs its own `atomic()` block: a failed statement poisons the surrounding
    transaction and the next insert would fail for the wrong reason.
    """
    package = _a_package()

    for blank in ("platform", "architecture", "log_reference"):
        with pytest.raises(IntegrityError, match=VERIFICATION_EVIDENCE_CONSTRAINT), transaction.atomic():
            _row(package=package, **{blank: ""}).save()


@pytest.mark.django_db
def test_the_database_refuses_a_sentinel_row_that_claims_to_know_where_it_ran() -> None:
    """The other half of the biconditional, and the one a collector bug would reach.

    A sentinel row is written for a run that produced no execution, so a platform on
    one would be a fact nobody observed -- carried on a row a reader would reasonably
    take at face value.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=VERIFICATION_EVIDENCE_CONSTRAINT), transaction.atomic():
        _row(package=package, state=VERIFICATION_ERROR, detail="something failed").save()


@pytest.mark.django_db
def test_the_database_refuses_a_not_applicable_row_that_does_not_say_why() -> None:
    """`VERIFICATION_REASON_CONSTRAINT`: the only honest reason is one identity established."""
    package = _a_package()

    with pytest.raises(IntegrityError, match=VERIFICATION_REASON_CONSTRAINT), transaction.atomic():
        _row(
            package=package,
            state=VERIFICATION_NOT_APPLICABLE,
            platform="",
            architecture="",
            log_reference="",
            detail="",
        ).save()


@pytest.mark.django_db
def test_the_database_refuses_a_row_that_cannot_say_which_python_it_verified() -> None:
    """`VERIFICATION_SERIES_CONSTRAINT`, on a row that would otherwise look ordinary.

    `CPM-PY314-S03` reduces this table and the static one together, so a row with no
    series would make a 3.14 build indistinguishable from a build of whatever comes
    next.
    """
    package = _a_package()

    with pytest.raises(IntegrityError, match=VERIFICATION_SERIES_CONSTRAINT), transaction.atomic():
        _row(package=package, python_series="").save()


# ---------------------------------------------------------------------------
# AC 2: inferred and verified are distinct recorded states, on real rows.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_one_package_can_carry_an_inferred_row_and_a_verified_row_that_read_differently() -> None:
    """AC 2, proved as the two rows a read surface would join.

    This is the only place in the repository the two tables are put side by side, and
    it is where the epic's title is either true or not: a reader holding both states
    can say which came from a claim and which from an execution, without knowing which
    table each came from.
    """
    package = _a_package()
    PythonReadinessAssessment.objects.create(
        observed_at=FIXED_INSTANT,
        package=package,
        source="https://pypi.org/pypi/django/json",
        state=INFERRED_COMPATIBLE,
        python_series=series_of(PYTHON_SERIES),
        requires_python=AN_ADMITTING_SPECIFIER,
        matching_classifier="",
        deciding_signal=DecidingSignal.REQUIRES_PYTHON.value,
        detail="",
        trace_id="",
    )

    _verify(package, transport=_answering())

    inferred = PythonReadinessAssessment.objects.get(package=package)
    verified = PythonVerificationResult.objects.get(package=package)
    assert inferred.state != verified.state
    assert inferred.python_series == verified.python_series
    assert {inferred.state, verified.state} == {INFERRED_COMPATIBLE, VERIFIED_COMPATIBLE}


@pytest.mark.django_db
def test_verifying_a_package_twice_writes_two_rows_and_the_first_one_stands() -> None:
    """`CPM-AD-2`, and the matrix row about two triggers for one package.

    The second run is on another platform, which is what makes the case about more
    than append-only storage: a verified result is about one runner, so a second row
    is a different fact rather than a correction of the first -- and a window would
    have made the row unreachable.
    """
    package = _a_package()

    _verify(package, transport=_answering())
    _verify(
        package,
        transport=_answering(
            _result(platform=ANOTHER_PLATFORM, architecture=ANOTHER_ARCHITECTURE, log_reference=ANOTHER_LOG_REFERENCE),
        ),
        at=FIXED_INSTANT + timedelta(minutes=5),
    )

    rows = _rows(package)
    assert len(rows) == TWO_ROWS
    assert [row.platform for row in rows] == [A_PLATFORM, ANOTHER_PLATFORM]
    assert rows[0].log_reference == A_LOG_REFERENCE


# ---------------------------------------------------------------------------
# AC 3: not run across the inventory.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_dispatch_naming_this_collector_is_refused_and_enqueues_nothing() -> None:
    """AC 3 against the real registry and the real dispatch.

    The refusal names the collector, so an operator who added a beat entry learns
    which one rather than being told a dispatch failed -- and the ledger row for the
    attempt is finalized `failed`, which is what an alert reads.
    """
    with pytest.raises(SweepDispatchError, match=COLLECTOR_NAME):
        dispatch(collector=COLLECTOR_NAME, clock=FixedClock(instant=FIXED_INSTANT))

    assert PythonVerificationResult.objects.count() == 0


@pytest.mark.django_db
def test_no_verification_row_exists_for_a_package_nobody_triggered() -> None:
    """The ordinary state of most of an inventory, asserted rather than assumed.

    An absence here is not a gap: verification is triggered, so a package with no row
    is one nobody has asked about, and every read surface reports it `unknown` for want
    of an observation.
    """
    package = _a_package()

    assert _rows(package) == []


# ---------------------------------------------------------------------------
# Identity: the one path to `not_applicable`, and the refusal beside it.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_identity_that_established_no_ecosystem_records_not_applicable_with_no_build_attempted() -> None:
    """The one path to the state, and it costs no run on anybody's builder.

    The recording transport is the only way to show the negative: no call was made, so
    the row is written from what identity said rather than from an execution that
    produced nothing.
    """
    package = _a_package(outcome=OutcomeState.NOT_APPLICABLE.value)
    backend = _answering()

    result = _verify(package, transport=backend)

    assert result.state is RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == VERIFICATION_NOT_APPLICABLE
    assert "identity established" in row.detail
    assert row.platform == ""
    assert row.source == ""
    assert backend.calls == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "outcome",
    [OutcomeState.UNKNOWN.value, OutcomeState.ERROR.value, OutcomeState.NOT_FOUND.value, None],
    ids=["unknown", "error", "not_found", "no-mapping-row"],
)
def test_identity_that_established_nothing_writes_no_row_at_all(outcome: str | None) -> None:
    """The absence trap, from the end that matters: no claim of any kind is recorded.

    Emphatically not a `not_applicable` row, which would be this product recording
    that it need never build a package nobody has resolved. The refusal happens in
    `source_for`, before any evidence is written, and the ledger carries the reason.

    Args:
        outcome: The mapping outcome recorded, or `None` for no mapping row.

    """
    package = _a_package(outcome=outcome)

    with pytest.raises(Py314VerificationIdentityError, match="unanswered rather than inapplicable"):
        _verify(package, transport=_answering())

    assert _rows(package) == []
    assert _run(package).status == RunState.FAILED.value


@pytest.mark.django_db
def test_an_established_mapping_naming_no_purl_is_refused_rather_than_called_inapplicable() -> None:
    """Identity permits an `established` mapping with a blank purl, and it establishes nothing.

    There is no artifact to name to a backend, so there is nothing to build -- and
    saying the question does not apply would be a determinate claim from an absence.
    """
    package = _a_package(primary_purl="")

    with pytest.raises(Py314VerificationIdentityError, match="unanswered rather than inapplicable"):
        _verify(package, transport=_answering())

    assert _rows(package) == []


@pytest.mark.django_db
def test_an_artifact_the_backend_cannot_obtain_records_not_found_with_the_caveat() -> None:
    """An absence from wherever the backend fetches from, not a package that fails to build.

    The two rows a reader could most plausibly confuse, and the caveat is what keeps
    them apart on the row itself.
    """
    package = _a_package()

    result = _verify(package, transport=_answering(found=False, body=""))

    assert result.state is RunState.SUCCEEDED
    row = _rows(package)[0]
    assert row.state == VERIFICATION_NOT_FOUND
    assert NOT_OBTAINABLE_DETAIL in row.detail
    assert row.log_reference == ""


@pytest.mark.django_db
def test_a_spent_allowance_writes_an_error_row_without_asking_the_backend() -> None:
    """The allowance is what bounds a trigger loop, and a refusal is still a run on the record."""
    package = _a_package()
    backend = _answering()

    result = _verify(package, transport=backend, permitted=False)

    assert result.state is RunState.FAILED
    assert _rows(package)[0].state == VERIFICATION_ERROR
    assert backend.calls == []


@pytest.mark.django_db
def test_one_instance_verifying_two_packages_reads_identity_afresh_for_the_second() -> None:
    """The remembered identity is keyed by package, so a second verification is about the second one.

    Written as one collector over two packages rather than as two collectors, because
    the cached-identity bug this guards against is invisible to any case that builds a
    fresh instance per package.
    """
    first = _a_package("first")
    second = _a_package("second", outcome=OutcomeState.NOT_APPLICABLE.value)
    collector = Py314VerificationCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=_answering(),
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )

    try:
        collector.collect(package_id=first.pk)
        collector.collect(package_id=second.pk)
    finally:
        collector.close()

    assert _rows(first)[0].state == VERIFIED_COMPATIBLE
    assert _rows(second)[0].state == VERIFICATION_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# The task, and what an unconfigured component does.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_task_refuses_before_the_recorder_opens_when_no_backend_is_declared() -> None:
    """The shipped state: nothing is declared, so nothing claims to have verified anything.

    Asserted as *no ledger row* rather than as the exception alone, because the whole
    point of refusing before the collector is constructed is that an unconfigured
    component leaves no trace of a run it could not have performed.
    """
    package = _a_package()

    with pytest.raises(VerificationBackendError, match=r"no Python 3\.14 execution backend"):
        collector_tasks.verify_py314_build(package_id=package.pk)

    assert _rows(package) == []
    assert CollectionRun.objects.filter(collector=COLLECTOR_NAME).count() == 0


@pytest.mark.django_db
def test_the_task_runs_a_verification_through_whatever_backend_is_declared() -> None:
    """The task end to end, with a backend declared for the length of the case.

    Declared and withdrawn inside the case rather than through a fixture, because the
    slot is process-global and a case that left one declared would change what the
    case above reads -- which is the one asserting the shipped state.
    """
    package = _a_package()
    declare_verification_backend(_answering())
    try:
        assert collector_tasks.verify_py314_build(package_id=package.pk) == RunState.SUCCEEDED.value
    finally:
        withdraw_verification_backend()

    assert _rows(package)[0].state == VERIFIED_COMPATIBLE


@pytest.mark.django_db
def test_the_task_names_no_package_it_cannot_find() -> None:
    """The recorder checks the key before it writes the opening row, so this leaves nothing behind.

    Reached through the collector rather than the task, because the task's own refusal
    is the undeclared backend and this case is about the one after it.
    """
    collector = Py314VerificationCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=_answering(),
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )

    try:
        with pytest.raises(Exception, match="package"):
            collector.collect(package_id=NO_SUCH_PACKAGE)
    finally:
        collector.close()

    assert PythonVerificationResult.objects.count() == 0


# ---------------------------------------------------------------------------
# Freshness: a target measured from the request.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_verification_is_current_for_as_long_as_its_declared_target_and_not_longer() -> None:
    """PRD Open Question 7c's first reading, measured on a real row.

    The target is provisional and the number is expected to move; what this case pins
    is that a target exists at all and that `core/freshness.py` applies it -- the
    second candidate reading, a verification that never goes stale, would need
    `CPM-AD-28` amending and is deliberately not what ships.
    """
    package = _a_package()
    _verify(package, transport=_answering())
    collector = Py314VerificationCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=_answering(),
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )
    target = Py314VerificationCollector.freshness_target
    assert target is not None

    try:
        inside = collector.freshness(package_id=package.pk, now=FIXED_INSTANT + target - timedelta(seconds=1))
        outside = collector.freshness(package_id=package.pk, now=FIXED_INSTANT + target + timedelta(seconds=1))
    finally:
        collector.close()

    assert inside.stale is False
    assert outside.stale is True
