"""The remediation pass through a real policy run, against real evidence.

`tests/unit/django_apps/test_remediation_policy.py` holds the rules: the
vocabularies, the comparison, the per-surface reading and every declaration. None
of those needs a database. What does need one is everything the rules are
*wrapped in* -- the cut-off-bound read of five sweeps, staleness measured against
the collectors' real declared targets, the row the pass writes, the constraints
the database keeps, the replay that must reproduce it, and the one claim this
story cannot make anywhere else: that **a `blocked` row naming a surface this run
did not read is refused by PostgreSQL** rather than merely avoided by the pass.

**The pass is never called directly, except by the query-count case and the
constraint cases.** Every other case runs `execute_policy_run`, because what
`CPM-AD-21` promises is a property of the orchestration: the cut-off comes from
the run ledger and the pass runs inside the package's transaction.

**The pass is already registered, and nothing here registers it.**
`policies/apps.py` adopts it during `django.setup()`, which is the arrangement a
deployed process is in. `tests/unit/django_apps/test_policies_app.py` is where the
adoption itself is asserted.

**The reviewed parameter file is *not* substituted, and that is the point.** This
pass reads no policy parameter -- the comparison is `policies/currency.py`'s, the
freshness targets are the collectors' own declarations, and the readiness
vocabulary is fixed by `CPM-AD-5` -- so every case here runs at the version the
suite already records and reads the shipped file end to end. A fixture file would
only prove that the other passes still parse.

**Time comes from stopped clocks, never from the wall.** `tests/clocks.py` owns
the instants and derives the later ones from the earlier, and the staleness cases
derive theirs from the collectors' declared targets, so the boundary the cases
assert is the boundary the product ships.

Every case rolls back: `@pytest.mark.django_db` wraps each in a transaction, which
is what leaves the database as found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import connection
from django.db import transaction
from django.test.utils import CaptureQueriesContext

from conda_sentinel.collectors.conda_package import CONDA_PACKAGE_FRESHNESS_TARGET
from conda_sentinel.collectors.feedstock import FEEDSTOCK_FRESHNESS_TARGET
from conda_sentinel.collectors.models import CondaPackageSnapshot
from conda_sentinel.collectors.models import FeedstockSnapshot
from conda_sentinel.collectors.models import PyPIReleaseSnapshot
from conda_sentinel.collectors.models import SourceReleaseSnapshot
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.collectors.outcomes import VULNERABILITY_ERROR
from conda_sentinel.collectors.outcomes import VULNERABILITY_UNKNOWN
from conda_sentinel.collectors.vulnerability import NO_FIXED_RANGE_DETAIL
from conda_sentinel.collectors.vulnerability import NOTHING_MATCHED_DETAIL
from conda_sentinel.collectors.vulnerability import UNIDENTIFIED_DETAIL
from conda_sentinel.collectors.vulnerability import VULNERABILITY_FRESHNESS_TARGET
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.policy_run import execute_policy_run
from conda_sentinel.core.runs import RunState
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.identity.models import VersionSurface
from conda_sentinel.policies.models import PackageCurrency
from conda_sentinel.policies.models import PackageFeedstockPresence
from conda_sentinel.policies.models import PackageLicense
from conda_sentinel.policies.models import PackageRemediation
from conda_sentinel.policies.models import PackageVulnerability
from conda_sentinel.policies.outcomes import AWAITING_BUILD
from conda_sentinel.policies.outcomes import AWAITING_PACKAGING
from conda_sentinel.policies.outcomes import BLOCKED
from conda_sentinel.policies.outcomes import FIX_NOT_PUBLISHED
from conda_sentinel.policies.outcomes import FIX_PUBLISHED
from conda_sentinel.policies.outcomes import READINESS_NOT_APPLICABLE
from conda_sentinel.policies.outcomes import READINESS_UNKNOWN
from conda_sentinel.policies.outcomes import READY
from conda_sentinel.policies.outcomes import SURFACE_NOT_READ
from conda_sentinel.policies.outcomes import VULNERABILITY_STATUS_UNKNOWN
from conda_sentinel.policies.remediation import POLICY_NAME
from conda_sentinel.policies.remediation import RemediationPass
from conda_sentinel.policies.remediation import RemediationPolicyError
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.clocks import OBSERVATION_GAP
from tests.passes import A_RECORDED_POLICY_VERSION

if TYPE_CHECKING:
    from datetime import datetime

#: The version the fix is published in, and the version every case looks for.
A_FIXED_VERSION: Final[str] = "1.2.3"

#: A version that is not the fix. Later than it on purpose: this product cannot
#: decide that it supersedes the fix, and a surface states its *latest* version
#: rather than the set it carries, so a surface stating it has established nothing
#: -- it reads `not_read`, and the row records the comparison.
A_LATER_VERSION: Final[str] = "1.2.4"

#: A version that is not the fix and is *earlier* than it: the genuinely-behind
#: case. Named separately because every case used a later version while the two
#: were treated identically, so the shape a version-ordering rule would first have
#: to decide was exercised nowhere.
AN_OLDER_VERSION: Final[str] = "1.2.2"

#: An instant one second past the advisory collector's declared freshness target,
#: measured back from the cut-off. `CPM-UJ-1`'s stated edge case is about this one.
A_STALE_ADVISORY_INSTANT: Final = FIXED_INSTANT - VULNERABILITY_FRESHNESS_TARGET - OBSERVATION_GAP

#: An earlier in-window sweep, so a case can put two sweeps at or before the
#: cut-off and require the newer to win. Inside every freshness target here.
AN_EARLIER_INSTANT: Final = FIXED_INSTANT - OBSERVATION_GAP

#: The package name most cases use.
A_NAME: Final[str] = "numpy"

#: The collector name the fixture collection runs carry. Prefixed so it cannot be
#: confused with a real collector's.
A_COLLECTOR: Final[str] = "cpm-fixture-collector"

#: An instant after the run's cut-off, for the case about evidence the cut-off
#: excludes.
AFTER_THE_CUTOFF: Final = FIXED_INSTANT + OBSERVATION_GAP

#: An instant one second past the published-package collector's declared freshness
#: target, measured back from the cut-off. Derived from the collector's own
#: declaration rather than written out, so the boundary these cases assert is the
#: boundary the product ships.
A_STALE_INSTANT: Final = FIXED_INSTANT - CONDA_PACKAGE_FRESHNESS_TARGET - OBSERVATION_GAP

#: The same, for the feedstock collector, whose cadence is weekly where the
#: published-package collector's is daily -- so one instant cannot serve both, and
#: an instant that was stale for the channel and fresh for the recipe is exactly
#: how a staleness case comes to assert nothing.
A_STALE_RECIPE_INSTANT: Final = FIXED_INSTANT - FEEDSTOCK_FRESHNESS_TARGET - OBSERVATION_GAP

#: The channels the multi-row conda sweep is about. `bioconda` sorts before
#: `conda-forge`, which is what makes the second entry the one a single-row read
#: chosen by an alphabetical tie-break would never see.
A_FIRST_CHANNEL: Final[str] = "bioconda"
A_SECOND_CHANNEL: Final[str] = "conda-forge"

#: The platform every published-package row names. Required of every row by that
#: table's own constraint.
A_PLATFORM: Final[str] = "linux-64"

#: What one `evaluate` costs for a package with a matched advisory: two reads of
#: the advisory sweep, two per surface for the four surfaces, and the insert.
QUERIES_PER_MATCHED_PACKAGE: Final[int] = 11

#: What one `evaluate` costs for a package with no advisory evidence at all: the
#: read for the sweep's instant, which finds none and short-circuits, and the
#: insert. `docs/conda-sentinel/operations.md` said three.
QUERIES_PER_PACKAGE_WITH_NO_ADVISORY_EVIDENCE: Final[int] = 2

#: What it costs for a package with no matched advisory: the advisory instant, the
#: sweep's rows, and the insert. No surface is read, because there is nothing to
#: look for.
QUERIES_PER_UNMATCHED_PACKAGE: Final[int] = 3

#: How many rows two runs over one package leave behind.
REPLAYED_RUNS: Final[int] = 2

#: How many derived tables a run writes a row to per package, the rollup included.
DOMAIN_TABLES: Final[int] = 5

#: A state nothing recognises, for the one evidence fault this pass refuses.
#: `choices` is a form rule Django does not enforce on `save()`, so the row is
#: reachable.
A_STATE_FROM_NOWHERE: Final[str] = "probably_fine"


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


def a_package(name: str = A_NAME, *, confidence: str = IdentityConfidence.VERIFIED) -> Package:
    """Create one package with a resolved identity.

    Args:
        name: Its canonical name, which is unique.
        confidence: How certain its identity is.

    Returns:
        The saved `Package`. `resolved_at` comes from `tests.clocks.FIXED_INSTANT`
        rather than from the wall clock, exactly as `CPM-AD-26` requires of every
        writer.

    """
    return Package.objects.create(canonical_name=name, resolved_at=FIXED_INSTANT, confidence=confidence)


def an_advisory(  # noqa: PLR0913 - one keyword per evidence column a case varies; a bundle would hide which
    package: Package,
    *,
    state: str = MATCHED,
    fixed_range: str = A_FIXED_VERSION,
    detail: str = "",
    advisory_id: str = "CPM-FIXTURE-1",
    observed_at: datetime = FIXED_INSTANT,
) -> VulnerabilityFinding:
    """Record one advisory finding.

    Written directly rather than through the collector: what these cases are about
    is the pass reading evidence, and driving a collection would make each of them
    depend on an advisory source none of them is about.

    Args:
        package: The package observed.
        state: What the lookup concluded.
        fixed_range: The versions the source says carry the fix.
        detail: What the collector had to say -- the seam that distinguishes "the
            source states no fix" from "this row records none".
        advisory_id: Which advisory, so two findings on one package are two
            findings.
        observed_at: The instant of this observation.

    Returns:
        The saved row.

    """
    determinate = state == MATCHED
    return VulnerabilityFinding.objects.create(
        package=package,
        observed_at=observed_at,
        state=state,
        source="https://example.invalid/advisories",
        advisory_id=advisory_id if determinate else "",
        affected_range="<1.2.3" if determinate else "",
        fixed_range=fixed_range if determinate else "",
        matched_version="1.2.0" if determinate else "",
        match_confidence="exact-version" if determinate else "",
        detail=detail,
    )


def a_source_release(package: Package, version: str, *, observed_at: datetime = FIXED_INSTANT) -> None:
    """Record what the upstream source surface stated.

    Args:
        package: The package observed.
        version: The latest release it names.
        observed_at: The instant of this observation.

    """
    SourceReleaseSnapshot.objects.create(
        package=package,
        observed_at=observed_at,
        state=OutcomeState.OK,
        source="https://example.invalid/repo",
        latest_version=version,
    )


def a_pypi_release(package: Package, version: str, *, observed_at: datetime = FIXED_INSTANT) -> None:
    """Record what the PyPI surface stated.

    Args:
        package: The package observed.
        version: The latest release it names.
        observed_at: The instant of this observation.

    """
    PyPIReleaseSnapshot.objects.create(
        package=package,
        observed_at=observed_at,
        state=OutcomeState.OK,
        source="https://pypi.org/pypi/numpy/json",
        latest_version=version,
    )


def a_recipe(package: Package, version: str, *, observed_at: datetime = FIXED_INSTANT) -> None:
    """Record what the conda-forge recipe stated.

    Args:
        package: The package observed.
        version: The recipe version.
        observed_at: The instant of this observation.

    """
    FeedstockSnapshot.objects.create(
        package=package,
        observed_at=observed_at,
        state=OutcomeState.OK,
        source="https://example.invalid/feedstock",
        feedstock_name=f"{package.canonical_name}-feedstock",
        recipe_version=version,
    )


def a_published_package(
    package: Package,
    version: str,
    *,
    channel: str = A_SECOND_CHANNEL,
    observed_at: datetime = FIXED_INSTANT,
    state: str = OutcomeState.OK.value,
) -> CondaPackageSnapshot:
    """Record what one monitored channel published.

    **`state` is a keyword because a mixed sweep is ordinary.**
    `conda_package_snapshots` holds one row per `(channel, platform)` pair and each
    row carries its own outcome, so "conda-forge errored and bioconda answered" is
    a shape the collector writes -- and a helper that always wrote `ok` was a
    helper under which the case could not be written.

    Args:
        package: The package observed.
        version: The published version.
        channel: The channel this row is about. Required of every row by that
            table's own constraint.
        observed_at: The instant of this observation.
        state: What this channel's read concluded.

    Returns:
        The saved row.

    """
    return CondaPackageSnapshot.objects.create(
        package=package,
        observed_at=observed_at,
        state=state,
        source=f"https://example.invalid/{channel}",
        channel=channel,
        platform=A_PLATFORM,
        published_version=version,
    )


def every_surface_states(package: Package, version: str, *, observed_at: datetime = FIXED_INSTANT) -> None:
    """Record all four surfaces stating one version.

    The arrangement every "the fix is nowhere" case needs: four determinate
    observations, each naming a version, so each surface reads an *established*
    absence rather than saying nothing.

    Args:
        package: The package observed.
        version: What all four state.
        observed_at: The instant of these observations.

    """
    a_source_release(package, version, observed_at=observed_at)
    a_pypi_release(package, version, observed_at=observed_at)
    a_recipe(package, version, observed_at=observed_at)
    a_published_package(package, version, observed_at=observed_at)


def a_policy_run(*, version: str = A_RECORDED_POLICY_VERSION, at: datetime = LATER_INSTANT) -> None:
    """Execute one policy run over the whole inventory.

    Args:
        version: The policy version the run declares.
        at: The instant the run's clock answers, which becomes every rollup row's
            `computed_at`.

    """
    execute_policy_run(policy_version=version, clock=FixedClock(instant=at))


def a_policy_run_row(*, version: str = A_RECORDED_POLICY_VERSION) -> PolicyRun:
    """Record a policy run directly, for the cases that do not execute one.

    Args:
        version: The policy version the row declares.

    Returns:
        The saved row.

    """
    return PolicyRun.objects.create(
        policy_version=version,
        evidence_cutoff=FIXED_INSTANT,
        started_at=FIXED_INSTANT,
        finished_at=LATER_INSTANT,
        status=RunState.SUCCEEDED,
    )


def the_row(package: Package) -> PackageRemediation:
    """Return the one remediation row the latest run wrote for a package.

    Args:
        package: The package whose row is wanted.

    Returns:
        Its `PackageRemediation` row, newest run first. `get()` on the package
        alone would raise once a case has run twice, and the replay case needs both
        rows.

    """
    return PackageRemediation.objects.filter(package=package).order_by("-policy_run_id")[0]


def a_hand_built_row(**overrides: Any) -> PackageRemediation:
    """Write one remediation row directly, for the cases about what the database refuses.

    Built by `create()` rather than through the pass, for the reason each
    constraint exists: the pass cannot produce a violating row, and a case that
    only drove the pass would pass against a constraint weakened to `1 = 1`. The
    `blocked`-with-an-unread-surface case is the one this whole helper is here for.

    Args:
        **overrides: The columns to differ from a well-formed row in.

    Returns:
        The saved row.

    """
    package = overrides.pop("package", None) or a_package()
    row: dict[str, Any] = {
        "package": package,
        "policy_run": a_policy_run_row(),
        "readiness_status": READINESS_UNKNOWN,
        "source_fix": SURFACE_NOT_READ,
        "pypi_fix": SURFACE_NOT_READ,
        "feedstock_fix": SURFACE_NOT_READ,
        "conda_package_fix": SURFACE_NOT_READ,
        "fixed_version": "",
        "evidence_stale": False,
        "policy_version": A_RECORDED_POLICY_VERSION,
        "evidence_cutoff": FIXED_INSTANT,
        "vulnerability_finding": None,
        "detail": "",
    }
    row.update(overrides)
    return PackageRemediation.objects.create(**row)


def every_surface_voted(package: Package, *, value: str = FIX_NOT_PUBLISHED) -> dict[str, Any]:
    """Return the four surface columns and the four observations they voted from.

    **What isolates a constraint case from every other constraint.** A hand-built
    row that leaves the snapshot references `None` while its surface columns vote
    violates `decided_surface_names_its_observation` as well as whatever it was
    written to exercise, and passes only because PostgreSQL happens to report the
    earlier-created constraint first. A case built on this one violates exactly the
    rule it names.

    Args:
        package: The package the observations are about.
        value: The `FixAvailability` value every surface column carries.

    Returns:
        The eight keyword overrides, ready to be spread into `a_hand_built_row`.

    """
    a_source_release(package, A_FIXED_VERSION)
    a_pypi_release(package, A_FIXED_VERSION)
    a_recipe(package, A_FIXED_VERSION)
    a_published_package(package, A_FIXED_VERSION)
    return {
        "source_fix": value,
        "pypi_fix": value,
        "feedstock_fix": value,
        "conda_package_fix": value,
        "source_snapshot": SourceReleaseSnapshot.objects.get(package=package),
        "pypi_snapshot": PyPIReleaseSnapshot.objects.get(package=package),
        "feedstock_snapshot": FeedstockSnapshot.objects.get(package=package),
        "conda_package_snapshot": CondaPackageSnapshot.objects.get(package=package),
    }


# ---------------------------------------------------------------------------
# AC 1: readiness comes from where the fixed version is available.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_fix_published_to_a_monitored_channel_is_ready_and_names_that_channel() -> None:
    """AC 1's first matrix row: the reviewer can act this morning.

    The row names the exact channel observation the verdict rests on, which is
    what `CPM-FR-16`'s "the evidence supporting it is stored with the result" comes
    to here -- and what `A_READY_ROW_NAMES_THE_CHANNEL_THAT_CARRIES_THE_FIX`
    requires of every `ready` row.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    published = a_published_package(package, A_FIXED_VERSION)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READY
    assert row.conda_package_fix == FIX_PUBLISHED
    assert row.conda_package_snapshot_id == published.pk
    assert row.fixed_version == A_FIXED_VERSION
    # Pinned because nothing else asserted the false direction of this column: a
    # pass that hardcoded `evidence_stale=True` passed the whole suite.
    assert row.evidence_stale is False


@pytest.mark.django_db
def test_a_fix_upstream_only_is_released_but_not_yet_packaged() -> None:
    """The matrix's second row: not `ready`, because there is nothing to install.

    The row records upstream as the only surface carrying it, so a reviewer reading
    `awaiting_packaging` can see immediately that the recipe is the outstanding
    work.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_source_release(package, A_FIXED_VERSION)
    a_pypi_release(package, A_LATER_VERSION)
    a_recipe(package, A_LATER_VERSION)
    a_published_package(package, A_LATER_VERSION)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == AWAITING_PACKAGING
    assert row.source_fix == FIX_PUBLISHED
    # The other three state a version that is not the fix, which establishes
    # nothing: a surface states its latest, not the set it carries. They read
    # `not_read` and still name the row they looked at.
    assert [row.pypi_fix, row.feedstock_fix, row.conda_package_fix] == [SURFACE_NOT_READ] * 3
    assert row.source_snapshot_id is not None
    assert row.pypi_snapshot_id is not None
    assert row.evidence_stale is False


@pytest.mark.django_db
def test_a_fix_in_the_recipe_but_not_built_is_awaiting_a_build() -> None:
    """The matrix's third row, and it is distinct from both of its neighbours.

    The packaging work is done and only the build is outstanding, which is a
    different next action from "update the recipe" and from "install it".
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_source_release(package, A_FIXED_VERSION)
    a_pypi_release(package, A_FIXED_VERSION)
    a_recipe(package, A_FIXED_VERSION)
    a_published_package(package, A_LATER_VERSION)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == AWAITING_BUILD
    assert row.feedstock_fix == FIX_PUBLISHED
    assert row.conda_package_fix == SURFACE_NOT_READ


@pytest.mark.django_db
def test_a_fix_on_a_second_sorting_channel_still_makes_the_package_ready() -> None:
    """`CPM-SECURITY-S05`'s review lesson, applied before the fact and end to end.

    `conda_package_snapshots` holds one row per `(channel, platform)` pair, and
    `policies/currency.py` picks one of them by an alphabetical tie-break. A pass
    that copied that here would read `not_published` for a package whose fix
    `conda-forge` publishes because `bioconda` sorts first and does not -- and four
    such readings are `blocked`, which is a channel list telling a reviewer to give
    up on work they could do now.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_published_package(package, A_LATER_VERSION, channel=A_FIRST_CHANNEL)
    carrying = a_published_package(package, A_FIXED_VERSION, channel=A_SECOND_CHANNEL)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READY
    assert row.conda_package_snapshot_id == carrying.pk


# ---------------------------------------------------------------------------
# AC 2: `blocked` is an established absence, and never anything else.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("stated", [A_LATER_VERSION, AN_OLDER_VERSION], ids=["ahead-of-the-fix", "behind-the-fix"])
def test_four_surfaces_stating_another_version_is_unknown_and_never_blocked(stated: str) -> None:
    """**AC 2 inverted, and the defect this review turned on, end to end.**

    Four determinate observations, each stating a version, none of them the fix.
    This case previously asserted `blocked` -- and asserting it was asserting the
    defect. A surface stores the version it states as its **latest**, not the set
    of versions it carries, so `latest != fix` establishes nothing in either
    direction. Recording it as `not_published`, the one reading permitted to vote
    towards `blocked`, made `blocked` the *steady state*: advisories name a fix,
    surfaces move past it, and every package with an older advisory decayed into
    the verdict that tells a security reviewer to stop looking.

    Both directions are driven. The behind-the-fix case is the one a
    version-ordering rule would decide differently, and it was exercised nowhere.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    every_surface_states(package, stated)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert [row.source_fix, row.pypi_fix, row.feedstock_fix, row.conda_package_fix] == [SURFACE_NOT_READ] * 4
    assert row.fixed_version == A_FIXED_VERSION
    assert all(
        getattr(row, f"{surface}_snapshot_id") is not None
        for surface in ("source", "pypi", "feedstock", "conda_package")
    )
    assert stated in row.detail
    assert "reads not_read rather than not_published" in row.detail


@pytest.mark.django_db
def test_no_row_this_pass_writes_reaches_blocked() -> None:
    """**The honest shipping state of this story, driven through the orchestration.**

    Every shape the matrix names, over one run: the fix on a channel, on the recipe,
    upstream only, on no surface, on no surface with one unread, on no surface at
    all, with no fixed range, with an uncomparable fixed range, and with nothing
    matched. Not one of them is `blocked`, because nothing this product records can
    establish that a surface does not carry a version.

    Recorded here rather than left to be inferred from a suite of green cases. The
    verdict stays in the vocabulary and both check constraints still guard it --
    the epic's AC 2 requires the value to exist and be distinct -- and the two
    changes that would make it reachable are on the story's deferred list.
    """
    an_ended_collection_run()
    ready = a_package("ready")
    an_advisory(ready)
    a_published_package(ready, A_FIXED_VERSION)
    recipe = a_package("recipe")
    an_advisory(recipe)
    a_recipe(recipe, A_FIXED_VERSION)
    upstream = a_package("upstream")
    an_advisory(upstream)
    a_source_release(upstream, A_FIXED_VERSION)
    nowhere = a_package("nowhere")
    an_advisory(nowhere)
    every_surface_states(nowhere, A_LATER_VERSION)
    behind = a_package("behind")
    an_advisory(behind)
    every_surface_states(behind, AN_OLDER_VERSION)
    partial = a_package("partial")
    an_advisory(partial)
    a_source_release(partial, A_LATER_VERSION)
    silent = a_package("silent")
    an_advisory(silent)
    no_fix = a_package("no-fix")
    an_advisory(no_fix, fixed_range="", detail=NO_FIXED_RANGE_DETAIL)
    uncomparable = a_package("uncomparable")
    an_advisory(uncomparable, fixed_range=">=1.2.3")
    unmatched = a_package("unmatched")
    an_advisory(unmatched, state=VULNERABILITY_UNKNOWN, detail=NOTHING_MATCHED_DETAIL)

    a_policy_run()

    assert BLOCKED not in set(PackageRemediation.objects.values_list("readiness_status", flat=True))
    assert FIX_NOT_PUBLISHED not in {
        value
        for row in PackageRemediation.objects.all()
        for value in (row.source_fix, row.pypi_fix, row.feedstock_fix, row.conda_package_fix)
    }
    assert the_row(ready).readiness_status == READY
    assert the_row(recipe).readiness_status == AWAITING_BUILD
    assert the_row(upstream).readiness_status == AWAITING_PACKAGING


@pytest.mark.django_db
def test_one_unread_surface_is_never_blocked_and_the_row_says_which() -> None:
    """**The property this whole story turns on, driven through the orchestration.**

    Three surfaces read and the fourth with no evidence at the cut-off. An
    implementation that read "no observation" as "the fix is absent here" would
    report `blocked` and tell a reviewer to give up on a package whose fix may well
    be on the channel nobody checked. The row is `unknown` and names the surface.

    This is a comparison an implementation could actually fail, where a case
    computing the same expression twice could not: the *only* difference from the
    case above is one missing evidence row.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_source_release(package, A_LATER_VERSION)
    a_pypi_release(package, A_LATER_VERSION)
    a_recipe(package, A_LATER_VERSION)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.conda_package_fix == SURFACE_NOT_READ
    assert row.conda_package_snapshot_id is None
    assert VersionSurface.CONDA_PACKAGE.value in row.detail
    assert "a surface that was not read is not a surface where the fix is absent" in row.detail


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [OutcomeState.ERROR.value, OutcomeState.NOT_FOUND.value],
    ids=["errored", "not-found"],
)
def test_a_surface_that_errored_or_did_not_carry_the_package_is_unknown_and_not_absent(state: str) -> None:
    """The matrix's "only an `error` or `not_found` row on a surface".

    A read that failed is not a statement that the fix is absent, and a channel
    that simply does not carry the package has not said anything about the fix
    either. Folding either into `not_published` is the same defect as folding a
    missing surface, arriving by a different route.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_source_release(package, A_LATER_VERSION)
    a_pypi_release(package, A_LATER_VERSION)
    a_recipe(package, A_LATER_VERSION)
    CondaPackageSnapshot.objects.create(
        package=package,
        observed_at=FIXED_INSTANT,
        state=state,
        source="https://example.invalid/channel",
        channel=A_SECOND_CHANNEL,
        platform=A_PLATFORM,
        published_version="",
    )

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.conda_package_fix == SURFACE_NOT_READ


@pytest.mark.django_db
def test_a_package_with_no_currency_evidence_at_all_is_unknown() -> None:
    """The matrix's "no surface was read": never `blocked`, never `ready`.

    The four `not_read` columns and the missing references are what say the run
    looked and found nothing to read, and the readiness claims nothing.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert [row.source_fix, row.pypi_fix, row.feedstock_fix, row.conda_package_fix] == [SURFACE_NOT_READ] * 4


# ---------------------------------------------------------------------------
# AC 3: staleness, read from `core/freshness.py` and never re-derived.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_fix_only_on_stale_evidence_does_not_assert_that_it_is_available() -> None:
    """AC 3: readiness reports stale rather than claiming a fix can be installed.

    The channel published the fix, and its evidence is past the target
    `CondaPackageCollector` declares -- so the surface reads `not_read`, the row is
    not `ready`, `evidence_stale` says it happened and the `detail` says which
    surface was not relied on.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_published_package(package, A_FIXED_VERSION, observed_at=A_STALE_INSTANT)

    a_policy_run()

    row = the_row(package)
    # An equality, not `!= READY`: this row is deterministically `unknown` -- the
    # stale channel is the only surface with evidence and it reads `not_read` -- so
    # an inequality asserted almost nothing.
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.conda_package_fix == SURFACE_NOT_READ
    assert row.evidence_stale is True
    assert "past the freshness target" in row.detail


@pytest.mark.django_db
def test_a_fresh_surface_beside_a_stale_one_still_decides_the_row() -> None:
    """The matrix's "some surfaces fresh, one stale": freshness is per surface.

    The fix is on a fresh channel and also on a stale recipe. The row is `ready` on
    the fresh surface's evidence, and it still says the stale one was not relied
    on -- so a reader is never left to wonder why a surface that carries the fix
    reads `not_read`.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_published_package(package, A_FIXED_VERSION)
    a_recipe(package, A_FIXED_VERSION, observed_at=A_STALE_RECIPE_INSTANT)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READY
    assert row.conda_package_fix == FIX_PUBLISHED
    assert row.feedstock_fix == SURFACE_NOT_READ
    assert row.evidence_stale is True
    assert VersionSurface.FEEDSTOCK.value in row.detail


# ---------------------------------------------------------------------------
# What the advisory itself established.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_with_no_matched_advisory_has_nothing_to_be_ready_for() -> None:
    """The matrix's "no open finding": distinct from `ready` and from `blocked`.

    And it is not a claim that the package is clean -- whether this run established
    that is `package_vulnerability`'s verdict at the same cut-off, which this row
    neither reads nor restates. The `detail` says so in as many words.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package, state=VULNERABILITY_UNKNOWN, detail=NOTHING_MATCHED_DETAIL)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_NOT_APPLICABLE
    assert row.vulnerability_finding_id is None
    assert "package_vulnerability" in row.detail


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("state", "detail"),
    [
        (VULNERABILITY_ERROR, ""),
        (VULNERABILITY_UNKNOWN, UNIDENTIFIED_DETAIL),
        (VULNERABILITY_UNKNOWN, ""),
    ],
    ids=["the-read-failed", "the-source-cannot-identify-the-package", "an-unknown-with-no-reason"],
)
def test_a_sweep_that_established_nothing_is_unknown_rather_than_nothing_to_do(state: str, detail: str) -> None:
    """A look that failed must not read as a package with nothing to remediate.

    `CPM-NFR-3` forbids degrading to a clean-looking result, and "the advisory
    source could not be read" is precisely the shape that would.

    **The second case is the one this pass got wrong**, and it is the sentinel a
    real source produces most often. The advisory collector writes "the source
    cannot identify this package" as `unknown`, not as `not_found`; an earlier
    draft treated every `unknown` as established, so such a package read
    `not_applicable` here -- "there is nothing to be ready for" -- while
    `package_vulnerability` read `unknown` for the same package, same run, same
    rows.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package, state=state, detail=detail)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.readiness_status != READINESS_NOT_APPLICABLE
    # The two passes read the same sweep in the same run: neither may call it
    # established while the other calls it unknown.
    assert PackageVulnerability.objects.get(package=package).vulnerability_status == VULNERABILITY_STATUS_UNKNOWN


@pytest.mark.django_db
def test_a_matched_advisory_with_no_fixed_range_is_unknown_however_the_collector_wrote_it() -> None:
    """**The matrix row this pass got wrong**, driven through the orchestration.

    Both packages carry a matched advisory with a blank `fixed_range`, one with the
    advisory collector's own "the source states no fixed range" clause and one
    without. The clause used to select `blocked` -- four unread surfaces, blank
    fixed version, a reviewer told to stop looking -- on the claim that it meant
    "the source was asked and answered". It does not:
    `collectors/vulnerability.py` writes one clause per field the source left
    *blank*, so the two rows below are the same row wearing two `detail`s, and this
    was the steady state for every feed that simply omits a fixed range.

    Both are `unknown`. The distinction the matrix asks for needs a collector that
    records it, which is on this story's deferred list.
    """
    an_ended_collection_run()
    with_the_clause = a_package("with-the-clause")
    without_it = a_package("without-it")
    an_advisory(with_the_clause, fixed_range="", detail=NO_FIXED_RANGE_DETAIL)
    an_advisory(without_it, fixed_range="")

    a_policy_run()

    for package in (with_the_clause, without_it):
        row = the_row(package)
        assert row.readiness_status == READINESS_UNKNOWN
        assert row.fixed_version == ""
        assert "blank means missing and is never inferred" in row.detail


@pytest.mark.django_db
def test_a_fixed_range_that_cannot_be_ordered_is_unknown_and_the_run_does_not_fail() -> None:
    """The story's `Block If`, and the Never list beside it.

    `>=1.2.3` names a set of versions, and deciding whether a surface's single
    stated version falls inside it needs a version-ordering rule no architecture
    decision owns. The finding reads `unknown` with the reason on the row -- and
    every other domain still writes its row, because `CPM-AD-23` puts one *package*
    in a transaction and a refusal here would have taken four other verdicts down
    with it.

    The row used to name `CPM-AD-6` as whose decision would settle it. That is
    *version authority is explicit per package* -- which surface is authoritative,
    not how two version strings compare -- so the row was sending a reviewer to a
    decision that does not answer the question. The story's own Block If said the
    same thing and was the source of it.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package, fixed_range=">=1.2.3")
    every_surface_states(package, A_LATER_VERSION)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.fixed_version == ""
    assert ">=1.2.3" in row.detail
    assert "no architecture decision owns version ordering yet" in row.detail
    assert "CPM-AD-6" not in row.detail
    assert PolicyRun.objects.get(policy_version=A_RECORDED_POLICY_VERSION).status == RunState.SUCCEEDED


@pytest.mark.django_db
def test_a_package_is_only_as_actionable_as_its_worst_finding() -> None:
    """The matrix's "several open findings": one row per package, taking the least ready.

    One advisory is fixed everywhere and one nowhere. The row is `blocked`, names
    the blocked finding, and its four surface columns are about *that* finding's
    fix -- which is why the `detail` says how many findings there were and which
    one the columns describe.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package, advisory_id="CPM-FIXTURE-READY", fixed_range=A_LATER_VERSION)
    unresolved = an_advisory(package, advisory_id="CPM-FIXTURE-UNRESOLVED", fixed_range=A_FIXED_VERSION)
    every_surface_states(package, A_LATER_VERSION)

    a_policy_run()

    row = the_row(package)
    # The first advisory's fix is on every surface (`ready`); the second's is on
    # none this run relies on (`unknown`). `unknown` outranks `ready` in
    # `READINESS_PRECEDENCE`, so the package carries it and the columns describe
    # the finding it came from.
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.vulnerability_finding_id == unresolved.pk
    assert row.fixed_version == A_FIXED_VERSION
    assert "least ready" in row.detail


# ---------------------------------------------------------------------------
# The cut-off, and the replay.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evidence_newer_than_the_cutoff_is_ignored() -> None:
    """`CPM-AD-21`: a pass reads as of the run's cut-off, never as of now.

    The fix is published *after* the collection run ended, so the run that reads as
    of that instant cannot see it -- and a run that did see it would be `ready`,
    which is what makes this a comparison an implementation can fail rather than a
    restatement.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    every_surface_states(package, A_LATER_VERSION)
    a_published_package(package, A_FIXED_VERSION, channel="later-channel", observed_at=AFTER_THE_CUTOFF)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.conda_package_fix == SURFACE_NOT_READ
    assert row.conda_package_snapshot.observed_at == FIXED_INSTANT


@pytest.mark.django_db
def test_a_package_with_no_advisory_evidence_at_all_is_unknown_and_costs_two_queries(
    django_assert_num_queries: Any,
) -> None:
    """The matrix's "no advisory evidence": `unknown`, never `not_applicable`, never `blocked`.

    Also the query floor, which `docs/conda-sentinel/operations.md` had wrong at three:
    `current_findings` short-circuits after the first query when there is no sweep,
    so the whole evaluation is that query plus the insert.
    """
    an_ended_collection_run()
    package = a_package()
    every_surface_states(package, A_FIXED_VERSION)
    run = a_policy_run_row()

    with django_assert_num_queries(QUERIES_PER_PACKAGE_WITH_NO_ADVISORY_EVIDENCE):
        RemediationPass().evaluate(package, policy_run=run, evidence_cutoff=FIXED_INSTANT)

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.vulnerability_finding_id is None
    assert [row.source_fix, row.pypi_fix, row.feedstock_fix, row.conda_package_fix] == [SURFACE_NOT_READ] * 4
    assert "there is no advisory evidence for this package" in row.detail


@pytest.mark.django_db
def test_the_newest_advisory_sweep_at_or_before_the_cutoff_is_the_one_read() -> None:
    """`current_findings`' cut-off and its ordering, which nothing exercised.

    Two advisory sweeps, **both at or before the cut-off**, disagreeing: the older
    names a fix the channel publishes, the newer names one it does not. No case
    wrote an advisory row at a non-default `observed_at`, so dropping
    `observed_at__lte=cutoff` and reversing the order both survived the suite --
    and reversing it means the oldest sweep decides every package for ever.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package, fixed_range=A_FIXED_VERSION, observed_at=AN_EARLIER_INSTANT)
    newest = an_advisory(package, fixed_range=A_LATER_VERSION, observed_at=FIXED_INSTANT)
    an_advisory(package, fixed_range=AN_OLDER_VERSION, observed_at=AFTER_THE_CUTOFF)
    a_published_package(package, A_FIXED_VERSION)

    a_policy_run()

    row = the_row(package)
    assert row.vulnerability_finding_id == newest.pk
    assert row.fixed_version == A_LATER_VERSION
    assert row.readiness_status == READINESS_UNKNOWN


@pytest.mark.django_db
def test_the_newest_in_window_sweep_of_a_surface_is_the_one_read() -> None:
    """The same rule one table over, with both sweeps inside the cut-off.

    The surface cases put their second sweep *outside* the cut-off, so ascending
    order still picked the same row and the ordering itself was never exercised.
    Here the older sweep carries the fix and the newer does not: a read that took
    the oldest would report `ready` for a channel that has since moved.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_published_package(package, A_FIXED_VERSION, observed_at=AN_EARLIER_INSTANT)
    current = a_published_package(package, A_LATER_VERSION, observed_at=FIXED_INSTANT)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.conda_package_snapshot_id == current.pk


@pytest.mark.django_db
def test_an_advisory_sweep_past_its_own_freshness_target_is_stale_rather_than_actionable() -> None:
    """**`CPM-UJ-1`'s stated edge case, which had no implementation.**

    "If the vulnerability evidence is older than its freshness target, the finding
    shows as stale rather than actionable." `VULNERABILITY_FRESHNESS_TARGET` was
    declared and never consulted: freshness was measured over the four surfaces
    alone, so this arrangement -- a month-old advisory sweep beside a channel
    refreshed this morning that publishes the fix -- read `ready` with
    `evidence_stale` false.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package, observed_at=A_STALE_ADVISORY_INSTANT)
    a_published_package(package, A_FIXED_VERSION)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READINESS_UNKNOWN
    assert row.evidence_stale is True
    assert row.conda_package_fix == SURFACE_NOT_READ
    assert row.fixed_version == ""
    assert "the advisory evidence current at this run's cut-off is past the freshness target" in row.detail


@pytest.mark.django_db
def test_a_fresh_advisory_sweep_is_not_reported_stale() -> None:
    """The false direction of the same column, so a hardcoded `True` fails a case."""
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    a_published_package(package, A_FIXED_VERSION)

    a_policy_run()

    row = the_row(package)
    assert row.readiness_status == READY
    assert row.evidence_stale is False


@pytest.mark.django_db
def test_the_pass_issues_no_query_against_another_passs_derived_table() -> None:
    """The Never list as behaviour rather than as a source scan.

    `tests/unit/django_apps/test_remediation_policy.py` reads the module's syntax
    tree; this watches the SQL. A reverse accessor, an `apps.get_model` lookup or a
    `select_related` into a derived table would all show up here as a table name in
    a query, whatever the imports say.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    every_surface_states(package, A_LATER_VERSION)
    run = a_policy_run_row()

    with CaptureQueriesContext(connection) as captured:
        RemediationPass().evaluate(package, policy_run=run, evidence_cutoff=FIXED_INSTANT)

    issued = " ".join(query["sql"] for query in captured.captured_queries)
    for table in ("package_currency", "package_feedstock_presence", "package_vulnerability", "package_license"):
        assert table not in issued
    assert "package_health" not in issued


@pytest.mark.django_db
def test_a_replay_at_the_same_version_and_cutoff_writes_identical_values() -> None:
    """`CPM-FR-22`: re-running one version against one cut-off reproduces the row.

    Two runs, two rows, one comparison -- which is what the `(package, policy_run)`
    key is for: the second run does not overwrite the first, so the two can be
    diffed.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    every_surface_states(package, A_LATER_VERSION)

    a_policy_run()
    a_policy_run()

    rows = list(PackageRemediation.objects.filter(package=package).order_by("policy_run_id"))
    assert len(rows) == REPLAYED_RUNS
    assert {
        (row.readiness_status, row.source_fix, row.pypi_fix, row.feedstock_fix, row.conda_package_fix, row.detail)
        for row in rows
    } == {
        (
            rows[0].readiness_status,
            rows[0].source_fix,
            rows[0].pypi_fix,
            rows[0].feedstock_fix,
            rows[0].conda_package_fix,
            rows[0].detail,
        ),
    }


@pytest.mark.django_db
def test_a_run_at_another_version_writes_the_same_verdict_and_records_its_own_version() -> None:
    """The matrix's "re-run at a different version", answered for a pass with no parameter.

    The matrix expects "different values, each recording its version" because the
    three parameterised passes read reviewed data keyed by the version. This one
    reads none, so the only thing that differs *is* the recorded version -- and
    that is the honest reading of `CPM-FR-22` here rather than a gap: a row can
    still never be read at a version it was not computed under.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    every_surface_states(package, A_LATER_VERSION)

    a_policy_run(version="2026.09.2")
    a_policy_run(version=A_RECORDED_POLICY_VERSION)

    rows = list(PackageRemediation.objects.filter(package=package).order_by("policy_run_id"))
    assert [row.policy_version for row in rows] == ["2026.09.2", A_RECORDED_POLICY_VERSION]
    assert {row.readiness_status for row in rows} == {READINESS_UNKNOWN}


# ---------------------------------------------------------------------------
# What the database refuses.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "unread",
    ["source_fix", "pypi_fix", "feedstock_fix", "conda_package_fix"],
    ids=["source", "pypi", "feedstock", "conda-package"],
)
def test_a_blocked_row_naming_a_surface_this_run_did_not_read_is_refused(unread: str) -> None:
    """**The constraint this story exists to put in the schema.**

    `blocked` is an established absence. A row claiming it while one of its four
    surfaces reads `not_read` is an abandonment reached by a silence, and the pass
    never produces one -- which is exactly why the rule is held here as well: a
    hand-written `INSERT` that went round the pass is refused by the database.

    **Every surface position, and the row is otherwise well-formed.** The earlier
    spelling put the unread surface on `conda_package` alone, so the constraint
    could have been weakened to one column and stayed green; and it left every
    snapshot reference `None`, so it violated
    `decided_surface_names_its_observation` three times over and passed only
    because PostgreSQL reports the earlier-created constraint first. Here the four
    surfaces name real observations, so this case fails on the rule it names and on
    no other.
    """
    package = a_package()
    finding = an_advisory(package)
    voting = every_surface_voted(package)
    voting[unread] = SURFACE_NOT_READ

    with pytest.raises(IntegrityError, match="blocked_needs_every_surface_read"), transaction.atomic():
        a_hand_built_row(
            package=package,
            readiness_status=BLOCKED,
            fixed_version=A_FIXED_VERSION,
            vulnerability_finding=finding,
            **voting,
        )


@pytest.mark.django_db
def test_a_blocked_row_that_looked_for_nothing_is_refused_like_any_other() -> None:
    """The exemption that was here, removed, and its removal held at the database.

    The constraint carried a `Q(fixed_version="")` disjunct so that "the advisory
    established there is no fix" could be `blocked` with four unread surfaces. No
    evidence this product records distinguishes that from a feed leaving the field
    blank, so the exemption admitted exactly the row the property forbids -- and
    the claim in two documents that a hand-written `INSERT` is refused by
    PostgreSQL was, for the one row that mattered, false.
    """
    package = a_package()
    finding = an_advisory(package, fixed_range="", detail=NO_FIXED_RANGE_DETAIL)

    with pytest.raises(IntegrityError, match="blocked_needs_every_surface_read"), transaction.atomic():
        a_hand_built_row(package=package, readiness_status=BLOCKED, vulnerability_finding=finding)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "voted",
    ["source_fix", "pypi_fix", "feedstock_fix", "conda_package_fix"],
    ids=["source", "pypi", "feedstock", "conda-package"],
)
def test_a_surface_that_voted_and_names_no_observation_is_refused(voted: str) -> None:
    """The other half of the same property, and the one that makes the first mean something.

    Four `not_published` columns written by a caller that read nothing would put
    `blocked` back within reach of silence. A surface that voted names the row it
    voted from.

    Every position, for the reason the case above gives: the earlier spelling
    exercised `source_fix` alone, so the conjunction could have been weakened to
    one column and stayed green.
    """
    package = a_package()
    finding = an_advisory(package)

    with pytest.raises(IntegrityError, match="decided_surface_names_its_observation"), transaction.atomic():
        a_hand_built_row(
            package=package,
            readiness_status=READINESS_UNKNOWN,
            vulnerability_finding=finding,
            **{voted: FIX_NOT_PUBLISHED},
        )


@pytest.mark.django_db
def test_a_ready_row_naming_no_channel_is_refused() -> None:
    """AC 1's half, as a database rule.

    `ready` is the one verdict in this table that sends a reviewer to install
    something, and a `ready` row naming no surface would be that instruction
    resting on nothing.
    """
    package = a_package()
    finding = an_advisory(package)

    with pytest.raises(IntegrityError, match="ready_names_the_channel_that_carries_the_fix"), transaction.atomic():
        a_hand_built_row(
            package=package,
            readiness_status=READY,
            fixed_version=A_FIXED_VERSION,
            vulnerability_finding=finding,
        )


@pytest.mark.django_db
def test_an_awaiting_build_row_naming_no_recipe_is_refused() -> None:
    """The recipe verdict's half, which had no case at all.

    `awaiting_build` says the feedstock carries the fix and the channel has not
    built it. A row claiming it while `feedstock_fix` names nothing is that
    instruction resting on nothing, exactly as a `ready` row naming no channel is.
    """
    package = a_package()
    finding = an_advisory(package)

    with pytest.raises(IntegrityError, match="awaiting_build_names_the_recipe"), transaction.atomic():
        a_hand_built_row(
            package=package,
            readiness_status=AWAITING_BUILD,
            fixed_version=A_FIXED_VERSION,
            vulnerability_finding=finding,
        )


@pytest.mark.django_db
def test_an_awaiting_packaging_row_naming_no_release_is_refused() -> None:
    """The release verdict's half, which had no case either.

    The one constraint in this table whose antecedent is satisfied by either of two
    columns: upstream and PyPI mean the same next action and share one verdict. A
    row naming neither claims a release nothing observed.
    """
    package = a_package()
    finding = an_advisory(package)

    with pytest.raises(IntegrityError, match="awaiting_packaging_names_the_release"), transaction.atomic():
        a_hand_built_row(
            package=package,
            readiness_status=AWAITING_PACKAGING,
            fixed_version=A_FIXED_VERSION,
            vulnerability_finding=finding,
        )


@pytest.mark.django_db
def test_a_determinate_readiness_naming_no_finding_is_refused() -> None:
    """All four determinate verdicts are statements about a fix a finding named.

    Built on a `ready` row whose channel carries the fix, so the only rule this row
    breaks is the one it names -- `blocked` with four unread surfaces would break
    `blocked_needs_every_surface_read` as well, and which of the two PostgreSQL
    reported first would be the whole of what the case asserted.
    """
    package = a_package()
    a_published_package(package, A_FIXED_VERSION)

    with pytest.raises(IntegrityError, match="readiness_names_its_finding"), transaction.atomic():
        a_hand_built_row(
            package=package,
            readiness_status=READY,
            fixed_version=A_FIXED_VERSION,
            conda_package_fix=FIX_PUBLISHED,
            conda_package_snapshot=CondaPackageSnapshot.objects.get(package=package),
        )


@pytest.mark.django_db
def test_a_row_naming_no_policy_version_is_refused() -> None:
    """`CPM-AD-8` in the column that carries it: a row whose version names nothing cannot replay."""
    with pytest.raises(IntegrityError, match="remediation_row_names_its_policy_version"), transaction.atomic():
        a_hand_built_row(policy_version="")


@pytest.mark.django_db
def test_a_second_row_for_one_package_and_run_is_refused() -> None:
    """`CPM-AD-21`'s key, as a database rule rather than as the writer's promise.

    Matched on the exception type alone, unlike the check-constraint cases beside
    it: PostgreSQL names the constraint in the message and SQLite names the
    columns, so a pattern that held on both would be a pattern asserting neither.
    `tests/unit/django_apps/test_remediation_policy.py` pins the constraint's name
    against the model's own declaration instead.
    """
    package = a_package()
    run = a_policy_run_row()
    a_hand_built_row(package=package, policy_run=run)

    with pytest.raises(IntegrityError), transaction.atomic():
        PackageRemediation.objects.create(
            package=package,
            policy_run=run,
            readiness_status=READINESS_UNKNOWN,
            source_fix=SURFACE_NOT_READ,
            pypi_fix=SURFACE_NOT_READ,
            feedstock_fix=SURFACE_NOT_READ,
            conda_package_fix=SURFACE_NOT_READ,
            fixed_version="",
            evidence_stale=False,
            policy_version=A_RECORDED_POLICY_VERSION,
            evidence_cutoff=FIXED_INSTANT,
            vulnerability_finding=None,
            detail="",
        )


@pytest.mark.django_db
def test_a_blocked_row_whose_four_surfaces_all_answered_is_still_accepted() -> None:
    """The one shape the constraint admits, so the refusals above are not vacuous.

    A constraint that refused every `blocked` row would pass all four positions of
    the case above and mean nothing. This is the row the schema is holding open for
    the day a version-ordering rule makes `not_published` reachable again: four
    established absences, each naming the observation it was read from.
    """
    package = a_package()
    finding = an_advisory(package)

    row = a_hand_built_row(
        package=package,
        readiness_status=BLOCKED,
        fixed_version=A_FIXED_VERSION,
        vulnerability_finding=finding,
        **every_surface_voted(package),
    )

    assert row.pk is not None


# ---------------------------------------------------------------------------
# The pass inside the run, and what it costs.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_domain_writes_its_row_and_the_run_succeeds() -> None:
    """The roster, so a pass that stopped running fails a case rather than going quiet.

    Five per-domain tables and the rollup, over a package every one of them has
    something to say about.
    """
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)
    every_surface_states(package, A_LATER_VERSION)

    a_policy_run()

    counts = [
        PackageCurrency.objects.filter(package=package).count(),
        PackageFeedstockPresence.objects.filter(package=package).count(),
        PackageVulnerability.objects.filter(package=package).count(),
        PackageLicense.objects.filter(package=package).count(),
        PackageRemediation.objects.filter(package=package).count(),
    ]
    assert counts == [1] * DOMAIN_TABLES
    assert PackageHealth.objects.filter(package=package).count() == 1
    assert PolicyRun.objects.get(policy_version=A_RECORDED_POLICY_VERSION).status == RunState.SUCCEEDED


@pytest.mark.django_db
def test_an_unreadable_advisory_state_fails_the_package_and_leaves_the_others() -> None:
    """The one evidence fault this pass refuses, and what `CPM-AD-23` makes it cost.

    A raise here rolls back everything this run did for *this* package -- four
    other domains' rows and its rollup row with them -- and leaves every other
    package's committed. That is why it is the only refusal in the module, and the
    case that shows the price is the case that keeps the list from growing.
    """
    an_ended_collection_run()
    broken = a_package("broken")
    intact = a_package("intact")
    an_advisory(intact)
    # Written directly rather than by amending a good row: `vulnerability_findings`
    # is append-only (`CPM-AD-2`), so `update()` is refused outright. Every advisory
    # fact is blank, which is what that table's own biconditional requires of a row
    # whose state is not `matched` -- and `choices` is a form rule Django does not
    # enforce on `save()`, which is why the row is reachable at all.
    VulnerabilityFinding.objects.create(
        package=broken,
        observed_at=FIXED_INSTANT,
        state=A_STATE_FROM_NOWHERE,
        source="https://example.invalid/advisories",
        detail="a state nothing in this product recognises",
    )

    a_policy_run()

    assert not PackageRemediation.objects.filter(package=broken).exists()
    assert not PackageCurrency.objects.filter(package=broken).exists()
    assert not PackageHealth.objects.filter(package=broken).exists()
    assert PackageRemediation.objects.filter(package=intact).exists()
    assert PolicyRun.objects.get(policy_version=A_RECORDED_POLICY_VERSION).status == RunState.PARTIAL


@pytest.mark.django_db
def test_the_pass_refuses_a_naive_cutoff_before_it_reads_anything() -> None:
    """Unreachable through the orchestration, and stated rather than left to chance.

    `core/policy_run.py` takes the cut-off from a completed collection run, whose
    `finished_at` is aware. A caller driving the pass by hand is the only way here.
    """
    package = a_package()
    run = a_policy_run_row()

    with pytest.raises(RemediationPolicyError, match="naive cutoff"):
        RemediationPass().evaluate(
            package,
            policy_run=run,
            evidence_cutoff=FIXED_INSTANT.replace(tzinfo=None),
        )


@pytest.mark.django_db
def test_what_one_evaluation_costs(django_assert_num_queries: Any) -> None:
    """The query budget, pinned so a read added per finding fails a case.

    Eleven for a package with a matched advisory: the advisory sweep's instant and
    its rows, then the same two per surface for four surfaces, then the insert. The
    four surfaces are read once and reused across every matched finding, because
    what differs between findings is the version being looked for and not the
    evidence being looked at.

    Three for a package with no matched advisory, because there is nothing to look
    for and no surface is read at all.
    """
    matched = a_package("matched")
    unmatched = a_package("unmatched")
    an_advisory(matched)
    every_surface_states(matched, A_LATER_VERSION)
    an_advisory(unmatched, state=VULNERABILITY_UNKNOWN)
    run = a_policy_run_row()

    with django_assert_num_queries(QUERIES_PER_MATCHED_PACKAGE):
        RemediationPass().evaluate(matched, policy_run=run, evidence_cutoff=FIXED_INSTANT)
    with django_assert_num_queries(QUERIES_PER_UNMATCHED_PACKAGE):
        RemediationPass().evaluate(unmatched, policy_run=run, evidence_cutoff=FIXED_INSTANT)


@pytest.mark.django_db
def test_the_pass_is_registered_under_the_name_it_declares() -> None:
    """`policies/apps.py` adopts it at `django.setup()`, which is what a deployed process does."""
    an_ended_collection_run()
    package = a_package()
    an_advisory(package)

    a_policy_run()

    assert POLICY_NAME in PackageHealth.objects.get(package=package).policy_versions
