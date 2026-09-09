"""The join `CPM-APP-S02`'s AC 1 asks for: every status, dated by the evidence behind it.

`tests/integration/django_apps/test_package_health_view.py` drives real policy runs,
which is the honest way to test the view and the reason almost every status there is
a sentinel: no collector has run, so no pass has anything to conclude from. What that
cannot show is the half of AC 1 that says "with the observation timestamp behind
each" -- a cell dated by nothing is indistinguishable from a cell dated wrongly.

So this module builds derived rows and their evidence directly. That is a deliberate
step down in fidelity and it buys the one thing the other module cannot reach: a
`Cell` whose `observed_at` can be checked against a *known* instant, and can be seen
to come from the right relation when there are two to choose between.

**The readiness cell is why this module exists at all.** `CPM-PY314-S03` made the
kind of evidence part of the verdict -- a `verified_` readiness rests on a build that
ran, an `inferred_` one on static metadata -- and the row cites both relations. A
projection that always read `assessment` would date a proof by the metadata it
superseded, and every assertion about "there is a timestamp" would still pass.

**And the confidence gate is checked here rather than only through the view.** The
four statuses this module reads out of derived tables are what the pass wrote,
ungated, because a pass computes its verdict without knowing anything about identity.
`CPM-AD-4` has to be applied on the way to the screen or an unmapped package shows a
confident claim beside five columns correctly saying `unknown`.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_sentinel.collectors.match_confidence import MatchConfidence
from conda_sentinel.collectors.models import KevFinding
from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.models import PythonVerificationResult
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import LISTED
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.collectors.outcomes import VERIFIED_COMPATIBLE
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.identity.models import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.policies.models import PackageLicense
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.policies.models import PackagePythonReadiness
from conda_sentinel.policies.models import PackageVulnerability
from conda_sentinel.policies.outcomes import PRIORITY_STATUS_UNKNOWN
from conda_sentinel.policies.outcomes import ReadinessEvidence
from conda_sentinel.surface.health import COLUMNS
from conda_sentinel.surface.health import NO_ROW_NOTE
from conda_sentinel.surface.health import health_rows

if TYPE_CHECKING:
    from conda_sentinel.surface.health import HealthRow

pytestmark = pytest.mark.integration

#: Distinct instants, far enough apart that a cell dated by the wrong one is
#: unmistakable rather than plausible. A projection reading `assessment` where it
#: should read `verification` would be a day out, not a second.
RUN_AT: Final[datetime] = datetime(2026, 9, 4, 6, 12, tzinfo=UTC)
CUTOFF: Final[datetime] = RUN_AT - timedelta(minutes=32)
ADVISORY_OBSERVED: Final[datetime] = CUTOFF - timedelta(hours=1)
LICENCE_OBSERVED: Final[datetime] = CUTOFF - timedelta(hours=2)
ASSESSED_AT: Final[datetime] = CUTOFF - timedelta(days=3)
VERIFIED_AT: Final[datetime] = CUTOFF - timedelta(days=1)

A_POLICY_VERSION: Final[str] = "cpm-app-s02-projection-fixture"

#: The score the priority fixture records, so the assertion names the same number
#: the row was given rather than a literal that happens to match.
A_PRIORITY_SCORE: Final[int] = 96
THE_SERIES: Final[str] = "3.14"

#: Where each column sits in a row's `cells`, by key. Built from the roster rather
#: than written out, so a column inserted between two others does not silently move
#: every assertion below onto its neighbour.
INDEX: Final[dict[str, int]] = {column.key: position for position, column in enumerate(COLUMNS)}


def a_run() -> PolicyRun:
    """Return one finished policy run for the fixtures to hang off.

    Returns:
        The saved run.

    """
    return PolicyRun.objects.create(
        policy_version=A_POLICY_VERSION,
        started_at=RUN_AT,
        finished_at=RUN_AT,
        evidence_cutoff=CUTOFF,
    )


def a_package(name: str, *, confidence: str = IdentityConfidence.VERIFIED) -> Package:
    """Return one package at a stated identity confidence.

    Args:
        name: Its canonical name.
        confidence: How certain its identity is (`CPM-AD-4`).

    Returns:
        The saved package.

    """
    return Package.objects.create(canonical_name=name, resolved_at=CUTOFF, confidence=confidence)


def a_matched_advisory(package: Package) -> VulnerabilityFinding:
    """Return one advisory finding that matched, with every fact its table requires.

    `vulnerability_findings` enforces the facts biconditionally: a `matched` row
    states the advisory, the affected range, the matched version and the match
    confidence, and a row in any other state states none of them. A fixture that
    set only the advisory id is refused by the database -- correctly, and it is
    worth building the whole row rather than reaching for a state that needs less.

    Args:
        package: The package the advisory is about.

    Returns:
        The saved finding.

    """
    return VulnerabilityFinding.objects.create(
        package=package,
        observed_at=ADVISORY_OBSERVED,
        state=MATCHED,
        advisory_id="CVE-2024-23334",
        severity="critical",
        affected_range="<3.9.2",
        matched_version="3.9.1",
        match_confidence=MatchConfidence.EXACT_VERSION,
    )


def a_kev_cross_reference(package: Package, advisory: VulnerabilityFinding, *, state: str) -> KevFinding:
    """Return one KEV catalogue cross-reference for an advisory.

    `kev_findings` requires the advisory behind any `listed` or `not_listed` row:
    both are things the *catalogue* said about a specific advisory, and only
    `not_established` -- the row saying nothing was said -- may stand alone.

    Args:
        package: The package.
        advisory: The advisory the catalogue was asked about.
        state: `listed` or `not_listed`.

    Returns:
        The saved cross-reference.

    """
    return KevFinding.objects.create(
        package=package,
        vulnerability_finding=advisory,
        observed_at=ADVISORY_OBSERVED,
        state=state,
        catalog_date_added=ADVISORY_OBSERVED if state == LISTED else None,
    )


def a_licence_finding(package: Package) -> LicenseFinding:
    """Return one licence observation for a package.

    Args:
        package: The package whose licence was read.

    Returns:
        The saved finding.

    """
    return LicenseFinding.objects.create(
        package=package,
        observed_at=LICENCE_OBSERVED,
        state=OutcomeState.OK.value,
        channel="conda-forge",
        raw_license="Apache-2.0",
    )


def a_rollup_row(package: Package, run: PolicyRun, **columns: str) -> PackageHealth:
    """Return one rollup row, defaulting every contributed column to `unknown`.

    Args:
        package: The package it is about.
        run: The run that computed it.
        **columns: Contributed columns to override.

    Returns:
        The saved row.

    """
    return PackageHealth.objects.create(
        package=package,
        policy_run=run,
        computed_at=RUN_AT,
        evidence_cutoff=CUTOFF,
        confidence=package.confidence,
        policy_versions={"fixture": A_POLICY_VERSION},
        **columns,
    )


def projected(row: PackageHealth) -> HealthRow:
    """Return the projection of one rollup row.

    Args:
        row: The row to project.

    Returns:
        Its `HealthRow`.

    """
    (projection,) = health_rows([PackageHealth.objects.select_related("package").get(pk=row.pk)])
    return projection


def cell(row: HealthRow, key: str) -> object:
    """Return one cell of a projected row by column key.

    Args:
        row: The projected row.
        key: The column's key.

    Returns:
        The `Cell`.

    """
    return row.cells[INDEX[key]]


# ---------------------------------------------------------------------------
# The evidence behind a status, and when it was observed.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_vulnerability_cell_is_dated_by_the_advisory_behind_it() -> None:
    """AC 1: the status, and the observation timestamp behind it.

    The instant is asserted exactly rather than as "not None", which is the
    assertion that can tell a cell dated by the right evidence from one dated by
    whatever the projection reached first.
    """
    run, package = a_run(), a_package("aiohttp")
    a_rollup_row(package, run)
    finding = a_matched_advisory(package)
    PackageVulnerability.objects.create(
        package=package,
        policy_run=run,
        vulnerability_status="advisories_matched",
        kev_membership=LISTED,
        risk_level="critical",
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
        vulnerability_finding=finding,
        kev_finding=a_kev_cross_reference(package, finding, state=LISTED),
    )

    vulnerability = cell(projected(PackageHealth.objects.get(package=package)), "vulnerability")

    assert vulnerability.status == "advisories_matched"  # type: ignore[attr-defined]
    assert vulnerability.note == "critical"  # type: ignore[attr-defined]
    assert vulnerability.observed_at == ADVISORY_OBSERVED  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_the_kev_cell_is_dated_by_the_catalogue_rather_than_the_advisory() -> None:
    """Two statuses on one derived row, and each dated by its own evidence.

    The advisory and the KEV catalogue are separate observations at separate
    instants, and the row cites both. A projection that dated both cells by
    `vulnerability_finding` would be right about one and quietly wrong about the
    other -- and the wrong one is the column that says whether something is being
    exploited.
    """
    run, package = a_run(), a_package("aiohttp")
    a_rollup_row(package, run)
    advisory = a_matched_advisory(package)
    PackageVulnerability.objects.create(
        package=package,
        policy_run=run,
        vulnerability_status="advisories_matched",
        kev_membership="not_established",
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
        vulnerability_finding=advisory,
    )

    row = projected(PackageHealth.objects.get(package=package))

    assert cell(row, "kev").status == "not_established"  # type: ignore[attr-defined]
    assert cell(row, "kev").observed_at is None  # type: ignore[attr-defined]
    assert cell(row, "vulnerability").observed_at == ADVISORY_OBSERVED  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_a_licence_cell_names_the_rule_that_matched() -> None:
    """What makes an `allowed` verdict checkable rather than merely reassuring."""
    run, package = a_run(), a_package("cryptography")
    a_rollup_row(package, run)
    finding = a_licence_finding(package)
    PackageLicense.objects.create(
        package=package,
        policy_run=run,
        license_outcome="allowed",
        matched_rule="permissive",
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
        license_finding=finding,
    )

    licence = cell(projected(PackageHealth.objects.get(package=package)), "licence")

    assert licence.status == "allowed"  # type: ignore[attr-defined]
    assert licence.note == "permissive"  # type: ignore[attr-defined]
    assert licence.observed_at == LICENCE_OBSERVED  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The readiness cell, which cites one of two relations.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_verified_readiness_is_dated_by_the_build_that_ran() -> None:
    """`CPM-PY314-S03`: the kind of evidence is part of the verdict, and dates it.

    The row cites *both* relations and the assessment is deliberately the older of
    the two, so a projection that read `assessment` regardless would date a proof by
    the metadata it superseded -- and would still produce a timestamp, which is why
    "not None" would not catch it.
    """
    run, package = a_run(), a_package("cryptography")
    a_rollup_row(package, run)
    assessment = PythonReadinessAssessment.objects.create(
        package=package,
        observed_at=ASSESSED_AT,
        state=OutcomeState.OK.value,
        python_series=THE_SERIES,
    )
    verification = PythonVerificationResult.objects.create(
        package=package,
        observed_at=VERIFIED_AT,
        # A build that ran says where it ran: `python_verification_results`
        # requires the platform, the architecture and the log reference on any
        # determinate verdict, and forbids all three on any other -- so a fixture
        # cannot record a proof without recording what would let somebody check it.
        state=VERIFIED_COMPATIBLE,
        python_series=THE_SERIES,
        platform="linux-64",
        architecture="x86_64",
        log_reference="builds/aiohttp/3.14/linux-64",
    )
    PackagePythonReadiness.objects.create(
        package=package,
        policy_run=run,
        readiness="verified_ready",
        evidence_type=ReadinessEvidence.VERIFIED,
        python_series=THE_SERIES,
        assessment=assessment,
        verification=verification,
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
    )

    readiness = cell(projected(PackageHealth.objects.get(package=package)), "python_readiness")

    assert readiness.status == "verified_ready"  # type: ignore[attr-defined]
    assert readiness.note == ReadinessEvidence.VERIFIED.value  # type: ignore[attr-defined]
    assert readiness.observed_at == VERIFIED_AT  # type: ignore[attr-defined]
    assert readiness.observed_at != ASSESSED_AT  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_an_inferred_readiness_is_dated_by_the_metadata_it_rests_on() -> None:
    """The other branch, and it is the one that would pass by accident.

    A projection hard-coded to `assessment` passes this and fails the case above;
    one hard-coded to `verification` fails this. Both are needed or the branch is
    untested in one direction.
    """
    run, package = a_run(), a_package("aiohttp")
    a_rollup_row(package, run)
    assessment = PythonReadinessAssessment.objects.create(
        package=package,
        observed_at=ASSESSED_AT,
        state=OutcomeState.OK.value,
        python_series=THE_SERIES,
    )
    PackagePythonReadiness.objects.create(
        package=package,
        policy_run=run,
        readiness="inferred_ready",
        evidence_type=ReadinessEvidence.INFERRED,
        python_series=THE_SERIES,
        assessment=assessment,
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
    )

    readiness = cell(projected(PackageHealth.objects.get(package=package)), "python_readiness")

    assert readiness.status == "inferred_ready"  # type: ignore[attr-defined]
    assert readiness.observed_at == ASSESSED_AT  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_an_undecided_readiness_claims_no_evidence_and_no_instant() -> None:
    """`CPM-AD-24`: blank is for a field with no value, and a status always has one.

    The status is `unknown` and is printed; the timestamp is genuinely absent and is
    the field that may be blank. Both halves, because the failure worth catching is
    the two being swapped.
    """
    run, package = a_run(), a_package("orjson")
    a_rollup_row(package, run)
    PackagePythonReadiness.objects.create(
        package=package,
        policy_run=run,
        readiness=OutcomeState.UNKNOWN.value,
        evidence_type=ReadinessEvidence.NONE,
        python_series=THE_SERIES,
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
    )

    readiness = cell(projected(PackageHealth.objects.get(package=package)), "python_readiness")

    assert readiness.status == OutcomeState.UNKNOWN.value  # type: ignore[attr-defined]
    assert readiness.note != ""  # type: ignore[attr-defined]
    assert readiness.observed_at is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# `CPM-AD-4` on the way to the screen.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_unmapped_packages_derived_verdicts_are_gated_on_the_way_out() -> None:
    """The defect this module's fixtures were what found.

    A pass computes its verdict without knowing anything about identity, so
    `package_vulnerability` holds a confident `advisories_matched` for a package
    nobody has identified. The rollup's own columns went through `gated_status` on
    the way in; these did not, and reading them straight onto the row would have put
    that claim beside five columns correctly saying `unknown` -- with every other
    cell looking right.
    """
    run, package = a_run(), a_package("internal-telemetry-sdk", confidence=IdentityConfidence.UNMAPPED)
    a_rollup_row(package, run)
    finding = a_matched_advisory(package)
    PackageVulnerability.objects.create(
        package=package,
        policy_run=run,
        vulnerability_status="advisories_matched",
        kev_membership=LISTED,
        risk_level="critical",
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
        vulnerability_finding=finding,
        kev_finding=a_kev_cross_reference(package, finding, state=LISTED),
    )

    row = projected(PackageHealth.objects.get(package=package))

    assert cell(row, "vulnerability").status == OutcomeState.UNKNOWN.value  # type: ignore[attr-defined]
    assert cell(row, "kev").status == OutcomeState.UNKNOWN.value  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_the_evidence_is_still_dated_even_where_the_verdict_is_gated() -> None:
    """The gate suppresses a *claim*, not the record that a lookup happened.

    `CPM-AD-4` is about what may be asserted, and "we looked at this advisory at
    05:38" is not an assertion about the package's identity. Keeping the timestamp is
    what lets a reviewer working the identity queue see there is something waiting
    behind the gate.
    """
    run, package = a_run(), a_package("internal-telemetry-sdk", confidence=IdentityConfidence.UNMAPPED)
    a_rollup_row(package, run)
    finding = a_matched_advisory(package)
    PackageVulnerability.objects.create(
        package=package,
        policy_run=run,
        vulnerability_status="advisories_matched",
        kev_membership=LISTED,
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
        vulnerability_finding=finding,
        kev_finding=a_kev_cross_reference(package, finding, state=LISTED),
    )

    assert cell(projected(PackageHealth.objects.get(package=package)), "vulnerability").observed_at == (  # type: ignore[attr-defined]
        ADVISORY_OBSERVED
    )


@pytest.mark.django_db
def test_an_inventory_derived_identity_is_not_degraded() -> None:
    """`CPM-AD-4` gates `unmapped` and nothing else.

    An `inventory-derived` identity is a real identity: its verdicts stand and the
    label is recorded beside them. Asserted because "gate the uncertain ones" is the
    obvious over-reading, and it would blank a third of the table.
    """
    run, package = a_run(), a_package("pandas", confidence=IdentityConfidence.INVENTORY_DERIVED)
    a_rollup_row(package, run)
    PackageLicense.objects.create(
        package=package,
        policy_run=run,
        license_outcome="allowed",
        matched_rule="permissive",
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
        license_finding=a_licence_finding(package),
    )

    row = projected(PackageHealth.objects.get(package=package))

    assert row.confidence == IdentityConfidence.INVENTORY_DERIVED
    assert cell(row, "licence").status == "allowed"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# What a missing derived row means.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_no_pass_evaluated_says_so_rather_than_going_blank() -> None:
    """`CPM-AD-24`: never blank, and the note says which of the reasons it is.

    A real state: a pass registered after a run began has no row for any package in
    it, and the confidence gate stops an unmapped package's evidence being evaluated
    at all.
    """
    run, package = a_run(), a_package("a-package-nothing-evaluated")
    a_rollup_row(package, run)

    row = projected(PackageHealth.objects.get(package=package))

    assert [c.status for c in row.cells if not c.status] == []
    assert cell(row, "vulnerability").status == OutcomeState.UNKNOWN.value  # type: ignore[attr-defined]
    assert cell(row, "vulnerability").note == NO_ROW_NOTE  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_a_derived_row_from_another_run_is_not_read() -> None:
    """`CPM-AD-21` keys a derived row on `(package, policy_run)`, and so does the lookup.

    The failure this prevents is subtle and would look like the projection working:
    a status from last week's run rendered beside this morning's freshness stamps,
    on a row that says nothing is stale.
    """
    package = a_package("aiohttp")
    older, current = a_run(), a_run()
    a_rollup_row(package, current)
    PackageLicense.objects.create(
        package=package,
        policy_run=older,
        license_outcome="allowed",
        matched_rule="permissive",
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
        license_finding=a_licence_finding(package),
    )

    licence = cell(projected(PackageHealth.objects.get(package=package)), "licence")

    assert licence.status == OutcomeState.UNKNOWN.value  # type: ignore[attr-defined]
    assert licence.note == NO_ROW_NOTE  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_the_score_comes_off_the_priority_table_and_the_bucket_off_the_rollup() -> None:
    """`CPM-PRIORITY-S01`: a contribution carries statuses, so the score is not a column.

    Both halves on one row, because the pair is what a reader ranks by and reading
    one of them from the wrong place would put a P1 next to a score of nothing.
    """
    run, package = a_run(), a_package("aiohttp")
    a_rollup_row(package, run, priority_status="p1")
    PackagePriority.objects.create(
        package=package,
        policy_run=run,
        bucket="p1",
        bucket_description="urgent",
        matched_rule="kev-listed",
        reason="listed in the KEV catalogue",
        score=A_PRIORITY_SCORE,
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=CUTOFF,
    )

    row = projected(PackageHealth.objects.get(package=package))

    assert row.priority == "p1"
    assert row.score == A_PRIORITY_SCORE


@pytest.mark.django_db
def test_a_package_with_no_priority_row_has_no_score_rather_than_a_zero() -> None:
    """Zero is a score somebody could have been given; `None` is the absence of one.

    Rendering the two the same would tell a reader that the priority pass ranked this
    package bottom, when in fact it never ran on it.
    """
    run, package = a_run(), a_package("orjson")
    a_rollup_row(package, run)

    row = projected(PackageHealth.objects.get(package=package))

    assert row.score is None
    assert row.priority == PRIORITY_STATUS_UNKNOWN


# ---------------------------------------------------------------------------
# The shape the template relies on.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_rows_cells_are_in_column_order() -> None:
    """The alignment the template renders headers and cells from separately.

    `COLUMNS` fills the `<th>`s and `row.cells` fills the `<td>`s, so a projection
    that emitted them in a different order would put every status under the wrong
    heading -- and the page would still render, which is what makes this worth
    asserting rather than assuming.
    """
    run, package = a_run(), a_package("aiohttp")
    a_rollup_row(package, run, currency_status="behind", feedstock_presence_status="present_and_maintained")

    row = projected(PackageHealth.objects.get(package=package))

    assert len(row.cells) == len(COLUMNS)
    assert cell(row, "currency").status == "behind"  # type: ignore[attr-defined]
    assert cell(row, "feedstock").status == "present_and_maintained"  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_an_empty_page_costs_nothing() -> None:
    """The paginator hands an empty page for a filter that matched nothing.

    Six queries for no rows would be six queries wasted on every empty result, which
    is the most common result a filtered screen produces.
    """
    assert health_rows([]) == ()
