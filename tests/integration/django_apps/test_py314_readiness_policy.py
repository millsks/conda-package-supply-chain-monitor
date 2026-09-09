"""Python readiness against real tables: the four verdicts, the absences, and the constraints.

`CPM-PY314-S03` asks for a readiness verdict that states which kind of evidence
produced it. The reduction itself is a pure function and is decided in
`tests/unit/django_apps/test_py314_readiness_policy.py`; what is only true or false
once a run exists is here — the row a real policy run writes, the two evidence
tables read at the run's own cut-off, and the three check constraints that hold
`CPM-FR-19` at the database rather than at the pass's discretion.

**AC 2 is proved on real rows, in the shape a read surface would meet them.** One
package carrying a static assessment *and* a verification produces one derived row
that cites both and rests on the verification. Nothing else in this repository puts
the epic's two evidence tables and its derived table together.

**The constraints are asserted against a real backend rather than against the
pass's discipline.** A hand-written row whose evidence type contradicts its
verdict is refused — from all three sides, because a rule that held for two of them
would let exactly the third through. SQLite enforces `CHECK` constraints; `pixi run
gate-postgres` runs the same cases against `postgres:17`.

Every test here rolls back: `@pytest.mark.django_db` wraps each in a transaction.
`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction

from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.models import PythonVerificationResult
from conda_sentinel.collectors.outcomes import INFERRED_COMPATIBLE
from conda_sentinel.collectors.outcomes import INFERRED_INCOMPATIBLE
from conda_sentinel.collectors.outcomes import READINESS_NOT_APPLICABLE
from conda_sentinel.collectors.outcomes import READINESS_UNKNOWN
from conda_sentinel.collectors.outcomes import VERIFICATION_FAILED
from conda_sentinel.collectors.outcomes import VERIFIED_COMPATIBLE
from conda_sentinel.collectors.specifiers import DecidingSignal
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.policy_run import execute_policy_run
from conda_sentinel.core.runs import RunState
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.policies.models import A_VERIFIED_VERDICT_RESTS_ON_A_VERIFICATION
from conda_sentinel.policies.models import AN_INFERRED_VERDICT_RESTS_ON_AN_ASSESSMENT
from conda_sentinel.policies.models import AN_UNDECIDED_VERDICT_CLAIMS_NO_EVIDENCE_TYPE
from conda_sentinel.policies.models import ONE_PYTHON_READINESS_ROW_PER_PACKAGE_PER_RUN
from conda_sentinel.policies.models import PYTHON_READINESS_ROW_NAMES_ITS_POLICY_VERSION
from conda_sentinel.policies.models import PYTHON_READINESS_ROW_NAMES_THE_SERIES_IT_JUDGED
from conda_sentinel.policies.models import PackagePythonReadiness
from conda_sentinel.policies.outcomes import EVIDENCE_INFERRED
from conda_sentinel.policies.outcomes import EVIDENCE_NONE
from conda_sentinel.policies.outcomes import EVIDENCE_VERIFIED
from conda_sentinel.policies.outcomes import INFERRED_NOT_READY
from conda_sentinel.policies.outcomes import INFERRED_READY
from conda_sentinel.policies.outcomes import PY314_READINESS_NOT_APPLICABLE
from conda_sentinel.policies.outcomes import PY314_READINESS_UNKNOWN
from conda_sentinel.policies.outcomes import VERIFIED_NOT_READY
from conda_sentinel.policies.outcomes import VERIFIED_READY
from conda_sentinel.policies.py314_readiness import AGREEMENT_DETAIL
from conda_sentinel.policies.py314_readiness import ASSESSED_SERIES
from conda_sentinel.policies.py314_readiness import DISAGREEMENT_DETAIL
from conda_sentinel.policies.py314_readiness import NOTHING_OBSERVED_DETAIL
from conda_sentinel.policies.py314_readiness import POLICY_NAME
from conda_sentinel.policies.py314_readiness import current_assessment
from conda_sentinel.policies.py314_readiness import current_verification
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.clocks import OBSERVATION_GAP
from tests.passes import A_RECORDED_POLICY_VERSION

if TYPE_CHECKING:
    from datetime import datetime

#: The collector name the fixture collection run is recorded under. Any name: what
#: the run supplies is a `finished_at`, which is the cut-off.
A_COLLECTOR: Final[str] = "python_readiness"

#: A series this product does not assess, for the cases that prove the readers
#: filter rather than compare.
ANOTHER_SERIES: Final[str] = "3.15"

#: What a verification reports about where it ran. The table refuses a determinate
#: row that names none of the three, so every fixture verification carries them.
A_PLATFORM: Final[str] = "linux"
AN_ARCHITECTURE: Final[str] = "x86_64"
A_LOG_REFERENCE: Final[str] = "https://builds.example.invalid/runs/1/log"

#: How many rows the replay case expects. Named because `PLR2004` is right about a
#: bare number in an assertion.
TWO_ROWS: Final[int] = 2


def an_ended_collection_run(finished_at: datetime = FIXED_INSTANT) -> CollectionRun:
    """Record a collection run that has ended, which is what supplies the cut-off.

    Written directly rather than through `core/ledger.py`'s recorder, because what
    these cases need is a row with a *chosen* `finished_at`: the recorder reads its
    own clock.

    Args:
        finished_at: When the run ended, and therefore the cut-off every pass in
            the policy run reads evidence as of.

    Returns:
        The saved row.

    """
    return CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=FIXED_INSTANT,
        finished_at=finished_at,
        status=RunState.SUCCEEDED,
    )


def a_package(name: str = "numpy") -> Package:
    """Create one package with a resolved identity.

    Args:
        name: Its canonical name, which is unique.

    Returns:
        The saved `Package`.

    """
    return Package.objects.create(
        canonical_name=name,
        resolved_at=FIXED_INSTANT,
        confidence=IdentityConfidence.VERIFIED,
    )


def an_assessment(
    package: Package,
    *,
    state: str = INFERRED_COMPATIBLE,
    series: str = ASSESSED_SERIES,
    observed_at: datetime = FIXED_INSTANT,
) -> PythonReadinessAssessment:
    """Write one static assessment for a package.

    Args:
        package: The package it is about.
        state: The collector verdict.
        series: The Python series it assessed.
        observed_at: When it was observed.

    Returns:
        The saved row.

    """
    determinate = state in {INFERRED_COMPATIBLE, INFERRED_INCOMPATIBLE}
    return PythonReadinessAssessment.objects.create(
        observed_at=observed_at,
        package=package,
        source="https://pypi.org/pypi/numpy/json",
        state=state,
        python_series=series,
        requires_python=">=3.9" if determinate else "",
        deciding_signal=DecidingSignal.REQUIRES_PYTHON.value if determinate else "",
        detail="because the test said so" if not determinate else "",
    )


def a_verification(
    package: Package,
    *,
    state: str = VERIFIED_COMPATIBLE,
    series: str = ASSESSED_SERIES,
    observed_at: datetime = FIXED_INSTANT,
) -> PythonVerificationResult:
    """Write one verification result for a package.

    The three where-it-ran columns are present exactly on the determinate states,
    which is what `python_verification_results` requires of every row.

    Args:
        package: The package it is about.
        state: The collector verdict.
        series: The Python series it verified.
        observed_at: When it was observed.

    Returns:
        The saved row.

    """
    determinate = state in {VERIFIED_COMPATIBLE, VERIFICATION_FAILED}
    return PythonVerificationResult.objects.create(
        observed_at=observed_at,
        package=package,
        source="py314-verify://declared-backend/pkg:pypi/numpy",
        state=state,
        python_series=series,
        platform=A_PLATFORM if determinate else "",
        architecture=AN_ARCHITECTURE if determinate else "",
        log_reference=A_LOG_REFERENCE if determinate else "",
        detail="because the test said so" if not determinate else "",
    )


def a_policy_run(*, at: datetime = LATER_INSTANT) -> None:
    """Execute one policy run over the whole inventory.

    Args:
        at: The instant the run's clock answers.

    """
    execute_policy_run(policy_version=A_RECORDED_POLICY_VERSION, clock=FixedClock(instant=at))


def a_policy_run_row() -> PolicyRun:
    """Record a policy run directly, for the cases that do not execute one.

    Returns:
        The saved row.

    """
    return PolicyRun.objects.create(
        policy_version=A_RECORDED_POLICY_VERSION,
        evidence_cutoff=FIXED_INSTANT,
        started_at=FIXED_INSTANT,
        finished_at=LATER_INSTANT,
        status=RunState.SUCCEEDED,
    )


def the_finding(package: Package) -> PackagePythonReadiness:
    """Return the readiness row the latest run wrote for a package.

    Args:
        package: The package whose row is wanted.

    Returns:
        Its row, newest run first.

    """
    return PackagePythonReadiness.objects.filter(package=package).order_by("-policy_run_id")[0]


def a_hand_built_row(**overrides: Any) -> PackagePythonReadiness:
    """Write one readiness row directly, for the cases about what the database refuses.

    Built by `create()` rather than through the pass, for the reason each constraint
    exists: the pass cannot produce a violating row, and a case that went through it
    would be asserting about the pass rather than about the schema.

    Args:
        **overrides: Columns to replace on an otherwise ordinary inferred row.

    Returns:
        The saved row, where the database accepts it.

    """
    package = overrides.pop("package", None) or a_package("hand-built")
    fields: dict[str, Any] = {
        "package": package,
        "policy_run": a_policy_run_row(),
        "readiness": INFERRED_READY,
        "evidence_type": EVIDENCE_INFERRED,
        "python_series": ASSESSED_SERIES,
        "assessment": an_assessment(package),
        "verification": None,
        "evidence_stale": False,
        "policy_version": A_RECORDED_POLICY_VERSION,
        "evidence_cutoff": FIXED_INSTANT,
        "detail": "",
    }
    fields.update(overrides)
    return PackagePythonReadiness.objects.create(**fields)


# ---------------------------------------------------------------------------
# AC 1: a verdict, and the evidence type that produced it.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("state", "verdict"),
    [(VERIFIED_COMPATIBLE, VERIFIED_READY), (VERIFICATION_FAILED, VERIFIED_NOT_READY)],
    ids=["built", "did-not-build"],
)
def test_a_verification_produces_a_verified_verdict_that_cites_the_build(state: str, verdict: str) -> None:
    """AC 1 end to end: the row names the verdict, the evidence type and the build.

    Args:
        state: The collector verdict on the verification.
        verdict: The derived verdict expected.

    """
    an_ended_collection_run()
    package = a_package()
    verification = a_verification(package, state=state)

    a_policy_run()

    row = the_finding(package)
    assert row.readiness == verdict
    assert row.evidence_type == EVIDENCE_VERIFIED
    assert row.verification_id == verification.pk
    assert row.assessment_id is None
    assert row.python_series == ASSESSED_SERIES
    assert row.policy_version == A_RECORDED_POLICY_VERSION
    assert row.evidence_cutoff == FIXED_INSTANT


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("state", "verdict"),
    [(INFERRED_COMPATIBLE, INFERRED_READY), (INFERRED_INCOMPATIBLE, INFERRED_NOT_READY)],
    ids=["admits", "excludes"],
)
def test_an_assessment_produces_an_inferred_verdict_that_cites_the_claim(state: str, verdict: str) -> None:
    """The other half of AC 1, and the value says `inferred` without reading the column.

    Args:
        state: The collector verdict on the assessment.
        verdict: The derived verdict expected.

    """
    an_ended_collection_run()
    package = a_package()
    assessment = an_assessment(package, state=state)

    a_policy_run()

    row = the_finding(package)
    assert row.readiness == verdict
    assert row.evidence_type == EVIDENCE_INFERRED
    assert row.assessment_id == assessment.pk
    assert row.verification_id is None


# ---------------------------------------------------------------------------
# AC 2: the distinction survives into the derived result.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_with_both_kinds_of_evidence_rests_on_the_build_and_cites_both() -> None:
    """AC 2, on real rows: proof decides, and the inference is still on the row.

    This is the only case in the repository that puts the epic's two evidence tables
    and its derived table together, which is where "kept apart" is either true or
    not.
    """
    an_ended_collection_run()
    package = a_package()
    assessment = an_assessment(package, state=INFERRED_COMPATIBLE)
    verification = a_verification(package, state=VERIFIED_COMPATIBLE)

    a_policy_run()

    row = the_finding(package)
    assert row.readiness == VERIFIED_READY
    assert row.evidence_type == EVIDENCE_VERIFIED
    assert row.assessment_id == assessment.pk
    assert row.verification_id == verification.pk
    assert row.detail == AGREEMENT_DETAIL


@pytest.mark.django_db
def test_a_build_that_contradicts_the_metadata_wins_and_the_row_says_so() -> None:
    """The disagreement, recorded rather than averaged.

    Emphatically not `unknown`: a package we know fails to build must not read the
    same as one nobody has looked at.
    """
    an_ended_collection_run()
    package = a_package()
    assessment = an_assessment(package, state=INFERRED_COMPATIBLE)
    a_verification(package, state=VERIFICATION_FAILED)

    a_policy_run()

    row = the_finding(package)
    assert row.readiness == VERIFIED_NOT_READY
    assert row.readiness != PY314_READINESS_UNKNOWN
    assert row.assessment_id == assessment.pk
    assert row.detail == DISAGREEMENT_DETAIL


# ---------------------------------------------------------------------------
# The absences.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_with_no_readiness_evidence_still_gets_a_row() -> None:
    """The ordinary state of most of an inventory, and an absent row would read as never-evaluated."""
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    row = the_finding(package)
    assert row.readiness == PY314_READINESS_UNKNOWN
    assert row.evidence_type == EVIDENCE_NONE
    assert row.assessment_id is None
    assert row.verification_id is None
    assert row.detail == NOTHING_OBSERVED_DETAIL


@pytest.mark.django_db
def test_evidence_that_established_nothing_never_reaches_a_negative_verdict() -> None:
    """An `unknown` assessment is not a claim that the package will not run."""
    an_ended_collection_run()
    package = a_package()
    an_assessment(package, state=READINESS_UNKNOWN)

    a_policy_run()

    row = the_finding(package)
    assert row.readiness == PY314_READINESS_UNKNOWN
    assert row.readiness not in {INFERRED_NOT_READY, VERIFIED_NOT_READY}
    assert row.evidence_type == EVIDENCE_NONE


@pytest.mark.django_db
def test_identity_that_established_no_ecosystem_reaches_not_applicable() -> None:
    """The one path to the state, inherited whole from `CPM-PY314-S01`."""
    an_ended_collection_run()
    package = a_package()
    an_assessment(package, state=READINESS_NOT_APPLICABLE)

    a_policy_run()

    row = the_finding(package)
    assert row.readiness == PY314_READINESS_NOT_APPLICABLE
    assert row.evidence_type == EVIDENCE_NONE


# ---------------------------------------------------------------------------
# The readers: the cut-off and the series.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evidence_written_after_the_cutoff_is_not_read() -> None:
    """`CPM-AD-21`: a pass reads no evidence written after the run's cut-off.

    Without it, a replay of one version at one cut-off would produce a different
    answer every time the collectors ran again — which is `CPM-FR-22` lost.
    """
    package = a_package()
    a_verification(package, state=VERIFIED_COMPATIBLE, observed_at=FIXED_INSTANT + OBSERVATION_GAP)

    assert current_verification(package_id=package.pk, cutoff=FIXED_INSTANT) is None


@pytest.mark.django_db
@pytest.mark.parametrize("reader", [current_assessment, current_verification], ids=["assessment", "verification"])
def test_evidence_about_another_python_series_is_not_read_at_all(reader: Any) -> None:
    """A row about another series is not evidence that disagrees — it is a different question.

    Asserted at the reader rather than at the verdict, because the filter being in
    the query is the claim: a row fetched and then ignored would produce the same
    verdict and a different number of rows in memory.

    Args:
        reader: The cut-off-bound reader under test.

    """
    package = a_package()
    an_assessment(package, state=INFERRED_COMPATIBLE, series=ANOTHER_SERIES)
    a_verification(package, state=VERIFIED_COMPATIBLE, series=ANOTHER_SERIES)

    assert reader(package_id=package.pk, cutoff=FIXED_INSTANT) is None


@pytest.mark.django_db
def test_the_latest_verification_as_of_the_cutoff_is_the_reading() -> None:
    """Two platforms, and the newest is the one the verdict rests on.

    The "latest observation" convention every pass in this application takes. The
    row cites the verification, which is what names the platform it ran on.
    """
    an_ended_collection_run(finished_at=FIXED_INSTANT + OBSERVATION_GAP)
    package = a_package()
    a_verification(package, state=VERIFIED_COMPATIBLE)
    newer = a_verification(package, state=VERIFICATION_FAILED, observed_at=FIXED_INSTANT + OBSERVATION_GAP)

    a_policy_run()

    row = the_finding(package)
    assert row.verification_id == newer.pk
    assert row.readiness == VERIFIED_NOT_READY


# ---------------------------------------------------------------------------
# What the database refuses.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_database_refuses_a_verified_verdict_that_cites_no_verification() -> None:
    """`CPM-FR-19` held at the schema: a claim of proof names the build it rests on."""
    with pytest.raises(IntegrityError, match=A_VERIFIED_VERDICT_RESTS_ON_A_VERIFICATION), transaction.atomic():
        a_hand_built_row(readiness=VERIFIED_READY, evidence_type=EVIDENCE_VERIFIED, verification=None)


@pytest.mark.django_db
def test_the_database_refuses_a_verified_verdict_that_claims_the_wrong_evidence_type() -> None:
    """The half a constraint over the FK alone would miss.

    A row saying `verified_ready` while declaring `inferred` would make the two
    columns disagree about the one fact `CPM-FR-19` is about, and a reader filtering
    on evidence type would count it as an inference.
    """
    package = a_package("mismatched")
    with pytest.raises(IntegrityError, match=A_VERIFIED_VERDICT_RESTS_ON_A_VERIFICATION), transaction.atomic():
        a_hand_built_row(
            package=package,
            readiness=VERIFIED_READY,
            evidence_type=EVIDENCE_INFERRED,
            verification=a_verification(package),
        )


@pytest.mark.django_db
def test_the_database_refuses_an_inferred_verdict_that_cites_no_assessment() -> None:
    """The same rule for the inferred half."""
    with pytest.raises(IntegrityError, match=AN_INFERRED_VERDICT_RESTS_ON_AN_ASSESSMENT), transaction.atomic():
        a_hand_built_row(readiness=INFERRED_READY, evidence_type=EVIDENCE_INFERRED, assessment=None)


@pytest.mark.django_db
def test_the_database_refuses_a_row_that_decided_nothing_but_claims_an_evidence_type() -> None:
    """The third side, and the one that stops the column drifting into decoration.

    Without it an `unknown` row could carry `inferred`, and a reader asking "how
    many packages have we assessed" would count packages nobody had.
    """
    with pytest.raises(IntegrityError, match=AN_UNDECIDED_VERDICT_CLAIMS_NO_EVIDENCE_TYPE), transaction.atomic():
        a_hand_built_row(readiness=PY314_READINESS_UNKNOWN, evidence_type=EVIDENCE_INFERRED, assessment=None)


@pytest.mark.django_db
def test_the_database_refuses_a_second_row_for_one_package_in_one_run() -> None:
    """`CPM-AD-21`'s key, as the database's rule.

    Matched on the columns rather than on the constraint's name, unlike the check
    constraints above: SQLite reports a unique violation by the columns it was
    declared over and never by the name, so a case matching the name would pass
    against PostgreSQL and fail here for a reason that has nothing to do with the
    rule. The name is still asserted to be the one the model declares, so a rename
    is caught without the message depending on the backend.
    """
    package = a_package("twice")
    run = a_policy_run_row()
    a_hand_built_row(package=package, policy_run=run)

    with pytest.raises(IntegrityError, match="package_id"), transaction.atomic():
        a_hand_built_row(package=package, policy_run=run)

    declared = {
        constraint.name
        for constraint in PackagePythonReadiness._meta.constraints  # noqa: SLF001 - Django's API
    }
    assert ONE_PYTHON_READINESS_ROW_PER_PACKAGE_PER_RUN in declared


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("policy_version", PYTHON_READINESS_ROW_NAMES_ITS_POLICY_VERSION),
        ("python_series", PYTHON_READINESS_ROW_NAMES_THE_SERIES_IT_JUDGED),
    ],
    ids=["policy-version", "python-series"],
)
def test_the_database_refuses_a_row_that_cannot_say_what_produced_it(column: str, constraint: str) -> None:
    """Both stamps, and the series matters most on this table: it is what a surface projects.

    Args:
        column: The column left blank.
        constraint: The constraint expected to refuse it.

    """
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        a_hand_built_row(**{column: ""})


# ---------------------------------------------------------------------------
# The pass inside a run.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_pass_is_registered_and_writes_one_row_per_package_per_run() -> None:
    """Adoption, and `CPM-AD-21`'s key over a real run of the whole inventory."""
    an_ended_collection_run()
    packages = [a_package("numpy"), a_package("scipy")]

    a_policy_run()

    assert PackagePythonReadiness.objects.count() == len(packages)
    for package in packages:
        assert PackagePythonReadiness.objects.filter(package=package).count() == 1


@pytest.mark.django_db
def test_two_runs_over_one_cutoff_produce_identical_verdicts() -> None:
    """`CPM-FR-22`: re-running a version against a cut-off reproduces the answer.

    Two rows rather than one overwritten, which is what makes the comparison
    possible at all (`CPM-AD-21`).
    """
    an_ended_collection_run()
    package = a_package()
    an_assessment(package, state=INFERRED_COMPATIBLE)

    a_policy_run()
    a_policy_run(at=LATER_INSTANT + OBSERVATION_GAP)

    rows = list(PackagePythonReadiness.objects.filter(package=package).order_by("policy_run_id"))
    assert len(rows) == TWO_ROWS
    assert rows[0].readiness == rows[1].readiness
    assert rows[0].evidence_type == rows[1].evidence_type
    assert rows[0].assessment_id == rows[1].assessment_id


@pytest.mark.django_db
def test_the_run_records_this_domains_policy_version_under_its_own_name() -> None:
    """The rollup's per-domain version map, which is what the pass name keys.

    Asserted against the shipped rollup rather than the pass, because the name being
    distinct from the remediation pass's `readiness` only matters where the two
    would otherwise collide.
    """
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    from conda_sentinel.core.models import PackageHealth  # noqa: PLC0415 - read after the run wrote it

    assert PackageHealth.objects.get(package=package).policy_versions[POLICY_NAME] == A_RECORDED_POLICY_VERSION
