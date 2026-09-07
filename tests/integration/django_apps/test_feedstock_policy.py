"""The feedstock presence pass through a real policy run, against real evidence.

`tests/unit/django_apps/test_feedstock_policy.py` holds the rules: the verdict,
the age, the boundary, the parameter contract and every declaration. None of
those needs a database. What does need one is everything the rules are *wrapped
in* -- the cut-off-bound read, the row the pass writes, the constraints the
database keeps, the replay that must reproduce it, and the two claims this story
cannot make anywhere else: that a threshold is genuinely versioned, and that
`CPM-AD-4`'s gate reaches the rollup column without this pass gating anything.

**The pass is never called directly, except by the query-count case.** Every
other case runs `execute_policy_run`, because what `CPM-AD-21` promises is a
property of the orchestration: the cut-off comes from the run ledger, the pass
runs inside the package's transaction, and `core/rollup.py` writes the column
after the gate. AC 2 in particular is a claim about the **rollup column**, and
proving it means driving one -- a case that called
`FeedstockPresencePass().evaluate(...)` and inspected its return value would be
asserting that this pass does not gate, which is not the same thing as asserting
that the product does.

**The pass is already registered, and nothing here registers it.**
`policies/apps.py` adopts it during `django.setup()`, which is the arrangement a
deployed process is in. `tests/unit/django_apps/test_policies_app.py` is where
the adoption itself is asserted.

**The reviewed parameter file is substituted for every case here, and the shipped
one is still exercised.** These cases need a threshold they chose -- one that
does not move when review changes the shipped value -- and the two-version case
needs two thresholds where the `Block If` on this story permits shipping one. So
`_recorded_thresholds` points the reader at a file this module writes. What still
reads the shipped file end to end is every policy run in
`tests/integration/django_apps/test_currency_policy.py` and
`tests/integration/django_apps/test_policy_run.py`, each of which now names the
version it records; and
`test_the_shipped_file_records_the_version_the_suite_names` below reconciles that
version against the file directly.

**Time comes from stopped clocks, never from the wall.** `tests/clocks.py` owns
the instants and derives the later ones from the earlier, so the ordering the
cut-off cases assert cannot drift.

Every case rolls back: `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the database as found.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction

from conda_package_supply_chain_monitor.collectors.models import FeedstockSnapshot
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.confidence import GATED_VALUE
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.policy_run import choose_evidence_cutoff
from conda_package_supply_chain_monitor.core.policy_run import execute_policy_run
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.policies import parameters as parameters_module
from conda_package_supply_chain_monitor.policies.feedstock import POLICY_NAME
from conda_package_supply_chain_monitor.policies.feedstock import FeedstockPresencePass
from conda_package_supply_chain_monitor.policies.models import AN_AGE_EXACTLY_WHEN_THERE_IS_AN_INSTANT
from conda_package_supply_chain_monitor.policies.models import DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION
from conda_package_supply_chain_monitor.policies.models import DETERMINATE_VERDICTS
from conda_package_supply_chain_monitor.policies.models import MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT
from conda_package_supply_chain_monitor.policies.models import MEASURED_VERDICTS
from conda_package_supply_chain_monitor.policies.models import THRESHOLD_IS_A_POSITIVE_INTERVAL
from conda_package_supply_chain_monitor.policies.models import PackageCurrency
from conda_package_supply_chain_monitor.policies.models import PackageFeedstockPresence
from conda_package_supply_chain_monitor.policies.outcomes import ABSENT
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_ERROR
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_NOT_APPLICABLE
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_UNKNOWN
from conda_package_supply_chain_monitor.policies.outcomes import PRESENT_AND_INACTIVE
from conda_package_supply_chain_monitor.policies.outcomes import PRESENT_AND_MAINTAINED
from conda_package_supply_chain_monitor.policies.outcomes import STAGED_RECIPE_PENDING
from conda_package_supply_chain_monitor.policies.parameters import PolicyParameterError
from conda_package_supply_chain_monitor.policies.parameters import forget_recorded_parameters
from conda_package_supply_chain_monitor.policies.parameters import parameters_at
from conda_package_supply_chain_monitor.policies.parameters import parameters_file
from conda_package_supply_chain_monitor.policies.parameters import recorded_parameters
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.clocks import OBSERVATION_GAP
from tests.passes import A_RECORDED_POLICY_VERSION
from tests.policy_parameters import parameter_document
from tests.policy_parameters import recorded_policy_parameters

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path

#: The shipped parameter file, resolved at import so the cases about it still
#: name the real path while `_recorded_thresholds` has the reader pointed
#: elsewhere.
THE_SHIPPED_FILE: Final = parameters_file()

#: The two policy versions this module records, and the threshold each one
#: applies. They differ by a factor of four so that one observation can sit
#: comfortably inside one and outside the other -- the whole of AC 3's claim.
A_POLICY_VERSION: Final[str] = "cpm-fixture-policy-1"
A_LENIENT_POLICY_VERSION: Final[str] = "cpm-fixture-policy-lenient"
A_THRESHOLD_IN_DAYS: Final[int] = 90
A_LENIENT_THRESHOLD_IN_DAYS: Final[int] = 360
A_THRESHOLD: Final = timedelta(days=A_THRESHOLD_IN_DAYS)

#: A policy version neither the shipped file nor the substituted one records, for
#: the refusal AC 3 is about.
AN_UNRECORDED_POLICY_VERSION: Final[str] = "cpm-fixture-policy-nobody-reviewed"

#: The collector name the fixture collection runs carry. Prefixed so it cannot be
#: confused with a real collector's.
A_COLLECTOR: Final[str] = "cpm-fixture-collector"

#: A feedstock name, because `feedstock_snapshots` requires one of every
#: determinate row -- "a feedstock exists" and "this is which one" are one fact.
A_FEEDSTOCK_NAME: Final[str] = "numpy-feedstock"

#: The staged recipe a `not_found` observation may carry. Only a `not_found` row
#: may carry one, which is that table's own constraint.
A_STAGED_RECIPE_URL: Final[str] = "https://github.com/conda-forge/staged-recipes/pull/26000"

#: A day either side of the boundary, so the maintained and inactive fixtures are
#: never accidentally *on* it -- the boundary has a case of its own.
A_DAY: Final = timedelta(days=1)

#: An instant after the run's cut-off, for the case about evidence the cut-off
#: excludes. Derived from `OBSERVATION_GAP` rather than written out, so the two
#: instants cannot drift into an ordering nobody intended.
AFTER_THE_CUTOFF: Final = FIXED_INSTANT + OBSERVATION_GAP

#: What one `evaluate` costs: the one evidence read plus the one insert of the
#: derived row. The parameter lookup costs no query at all -- it is a memoized
#: file read -- and that is part of what this pins.
QUERIES_PER_PACKAGE: Final[int] = 2

#: How many rows two runs over one package leave behind, and how many packages the
#: multi-package case is over. Named separately because the two cases mean
#: different things by it: one counts runs and the other counts packages, and a
#: shared literal would hide that they are two facts that happen to agree.
REPLAYED_RUNS: Final[int] = 2
PACKAGES_IN_THE_INVENTORY: Final[int] = 2


@pytest.fixture(autouse=True)
def _recorded_thresholds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Record this module's two policy versions and their two thresholds.

    Autouse because every case here needs a threshold it chose. See the module
    docstring for why the shipped file is substituted rather than extended, and
    for where the shipped file is still read end to end.

    Args:
        monkeypatch: pytest's patcher, which restores the shipped path.
        tmp_path: Where the substituted file is written.

    Yields:
        Nothing; the substitution is the effect.

    """
    thresholds = {
        A_POLICY_VERSION: A_THRESHOLD_IN_DAYS,
        A_LENIENT_POLICY_VERSION: A_LENIENT_THRESHOLD_IN_DAYS,
    }
    with recorded_policy_parameters(monkeypatch, tmp_path, thresholds):
        yield


@contextmanager
def monkeypatched(module: object, name: str, value: object) -> Iterator[None]:
    """Substitute one module attribute for the body of a `with`, and put it back.

    A context manager rather than the `monkeypatch` fixture, because the one case
    that needs it already takes `tmp_path` through the autouse parameter fixture
    and a second patcher in the signature would read as though the case were
    about patching rather than about counting.

    Args:
        module: The module to patch.
        name: The attribute to replace.
        value: What to replace it with.

    Yields:
        Nothing; the substitution is the effect.

    """
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


def an_ended_collection_run(finished_at: datetime = FIXED_INSTANT) -> CollectionRun:
    """Record a collection run that has ended, which is what supplies the cut-off.

    `CPM-AD-21` makes the cut-off the `finished_at` of a completed collection run
    and forbids the current time, so a run with nothing completed behind it
    refuses outright. Written directly rather than through `core/ledger.py`'s
    recorder, because what these cases need is a row with a *chosen*
    `finished_at`: the recorder reads its own clock.

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


def a_package(name: str = "numpy", *, confidence: str = IdentityConfidence.VERIFIED) -> Package:
    """Create one package with a resolved identity.

    Args:
        name: Its canonical name, which is unique.
        confidence: How certain its identity is. `verified` unless a case is about
            `CPM-AD-4`'s gate.

    Returns:
        The saved `Package`. `resolved_at` comes from `tests.clocks.FIXED_INSTANT`
        rather than from the wall clock, exactly as `CPM-AD-26` requires of every
        writer.

    """
    return Package.objects.create(canonical_name=name, resolved_at=FIXED_INSTANT, confidence=confidence)


def a_feedstock_observation(  # noqa: PLR0913 - one keyword per fact a feedstock row can carry; a bundle would hide them
    package: Package,
    *,
    state: str = OutcomeState.OK,
    activity_at: datetime | None = None,
    staged_recipe_url: str = "",
    established: bool | None = None,
    observed_at: datetime = FIXED_INSTANT,
) -> FeedstockSnapshot:
    """Record one feedstock observation.

    Written directly rather than through the collector: what these cases are about
    is the pass reading evidence, and driving a collection would make each of them
    depend on a transport none of them is about.

    Args:
        package: The package observed.
        state: What the lookup concluded.
        activity_at: When the feedstock was last pushed to. Only a determinate row
            may carry one, which is that table's own constraint.
        staged_recipe_url: The open staged recipe. Only a `not_found` row may
            carry one, likewise.
        established: Whether the collector established the absence it recorded.
            Only a `not_found` row may claim it, which is that table's own
            constraint. `None` -- the default -- means "whatever an ordinary
            absence carries", which is True.
        observed_at: The instant of this observation.

    Returns:
        The saved row.

    """
    return FeedstockSnapshot.objects.create(
        package=package,
        observed_at=observed_at,
        state=state,
        feedstock_name=A_FEEDSTOCK_NAME if state == OutcomeState.OK else "",
        last_recipe_activity_at=activity_at,
        staged_recipe_url=staged_recipe_url,
        absence_established=(state == OutcomeState.NOT_FOUND) if established is None else established,
    )


def a_maintained_feedstock(package: Package, **kwargs: Any) -> FeedstockSnapshot:
    """Record a feedstock pushed to a day inside the strict threshold.

    Args:
        package: The package observed.
        **kwargs: Passed through to `a_feedstock_observation`.

    Returns:
        The saved row.

    """
    return a_feedstock_observation(package, activity_at=FIXED_INSTANT - (A_THRESHOLD - A_DAY), **kwargs)


def an_inactive_feedstock(package: Package, **kwargs: Any) -> FeedstockSnapshot:
    """Record a feedstock last pushed to a day outside the strict threshold.

    Args:
        package: The package observed.
        **kwargs: Passed through to `a_feedstock_observation`.

    Returns:
        The saved row.

    """
    return a_feedstock_observation(package, activity_at=FIXED_INSTANT - (A_THRESHOLD + A_DAY), **kwargs)


def a_policy_run(*, version: str = A_POLICY_VERSION, at: datetime = LATER_INSTANT) -> None:
    """Execute one policy run over the whole inventory.

    Args:
        version: The policy version the run declares, and therefore the parameter
            set it applies.
        at: The instant the run's clock answers, which becomes every rollup row's
            `computed_at`. Separate from the evidence cut-off, which is a property
            of the evidence rather than of when the run happens.

    """
    execute_policy_run(policy_version=version, clock=FixedClock(instant=at))


def a_policy_run_row() -> PolicyRun:
    """Record a policy run directly, for the cases that do not execute one.

    The constraint cases need a `policy_run` to key a hand-built row to, and the
    query-count case needs one to hand a pass without measuring the
    orchestration's own queries around it. Written directly rather than through
    `core/ledger.py`'s recorder for the reason `an_ended_collection_run` is: the
    recorder reads its own clock, and none of these cases is about when the run
    happened.

    Returns:
        The saved row.

    """
    return PolicyRun.objects.create(
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=FIXED_INSTANT,
        started_at=FIXED_INSTANT,
        finished_at=LATER_INSTANT,
        status=RunState.SUCCEEDED,
    )


def the_finding(package: Package) -> PackageFeedstockPresence:
    """Return the one presence row the latest run wrote for a package.

    Args:
        package: The package whose finding is wanted.

    Returns:
        Its `PackageFeedstockPresence` row, newest run first. `get()` on the
        package alone would raise once a case has run twice, and the replay case
        needs both rows -- so this names the newest explicitly rather than relying
        on the table holding one.

    """
    return PackageFeedstockPresence.objects.filter(package=package).order_by("-policy_run_id")[0]


def a_hand_built_row(**overrides: Any) -> PackageFeedstockPresence:
    """Write one presence row directly, for the cases about what the database refuses.

    Built by `create()` rather than through the pass, for the reason each
    constraint exists: the pass cannot produce a violating row, and a case that
    only drove the pass would pass against a constraint weakened to `1 = 1`.

    Args:
        **overrides: The columns to differ from a well-formed row in.

    Returns:
        The saved row.

    """
    package = a_package()
    row: dict[str, Any] = {
        "package": package,
        "policy_run": a_policy_run_row(),
        "presence_status": ABSENT,
        "inactivity_threshold": A_THRESHOLD,
        "last_recipe_activity_at": None,
        "activity_age": None,
        "confidence": IdentityConfidence.VERIFIED,
        # A determinate verdict must name the observation it rests on, which is
        # `feedstock_verdict_names_its_observation`. Supplied by default so the
        # cases about the *other* constraints are refused by the one they name
        # rather than by this one, and overridden by the case that is about it.
        "feedstock_snapshot": a_feedstock_observation(package, state=OutcomeState.NOT_FOUND),
        "detail": "",
    }
    row.update(overrides)
    return PackageFeedstockPresence.objects.create(**row)


# ---------------------------------------------------------------------------
# AC 1: the four determinate outcomes, end to end.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_feedstock_pushed_to_inside_the_threshold_is_maintained_and_the_row_says_how() -> None:
    """AC 1's first outcome, with the three facts the matrix asks the row to record.

    The threshold applied, the activity instant and the age it computed -- as
    columns rather than as prose, so a reader can see the comparison that produced
    the verdict without re-deriving it from the run's cut-off. The evidence row is
    referenced too, which is what makes the instant checkable against the
    observation it was copied from.
    """
    an_ended_collection_run()
    package = a_package()
    observation = a_maintained_feedstock(package)

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == PRESENT_AND_MAINTAINED
    assert finding.inactivity_threshold == A_THRESHOLD
    assert finding.last_recipe_activity_at == observation.last_recipe_activity_at
    assert finding.activity_age == A_THRESHOLD - A_DAY
    assert finding.feedstock_snapshot_id == observation.pk
    assert finding.detail == "", "a verdict its own columns explain needs no line"


@pytest.mark.django_db
def test_a_feedstock_not_pushed_to_inside_the_threshold_is_inactive_and_records_the_same_three_facts() -> None:
    """AC 1's second outcome, and the answer `CPM-UJ-2` asks for.

    The same three facts, because the operator reading an `inactive` verdict is
    the one who most needs to see the arithmetic: the age is what they will argue
    with, and the threshold is what they will change.
    """
    an_ended_collection_run()
    package = a_package()
    observation = an_inactive_feedstock(package)

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == PRESENT_AND_INACTIVE
    assert finding.inactivity_threshold == A_THRESHOLD
    assert finding.last_recipe_activity_at == observation.last_recipe_activity_at
    assert finding.activity_age == A_THRESHOLD + A_DAY
    assert finding.activity_age > finding.inactivity_threshold


@pytest.mark.django_db
def test_no_feedstock_and_no_staged_recipe_is_absent() -> None:
    """AC 1's third outcome: the gap `CPM-UJ-2` asks which packages have.

    The measurement columns are empty because there was nothing to measure, and
    the row still references the observation -- so `absent` is readable as a claim
    somebody's collector made rather than as a row nobody filled in.
    """
    an_ended_collection_run()
    package = a_package()
    observation = a_feedstock_observation(package, state=OutcomeState.NOT_FOUND)

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == ABSENT
    assert finding.last_recipe_activity_at is None
    assert finding.activity_age is None
    assert finding.feedstock_snapshot_id == observation.pk


@pytest.mark.django_db
def test_no_feedstock_but_a_staged_recipe_is_pending_and_never_absent() -> None:
    """AC 1's fourth outcome, and the matrix's "the two are distinct outcomes".

    The two rows differ in exactly one column of the *evidence* -- the staged
    recipe locator -- and reach two different verdicts, which is what says the
    pass reads it rather than answering `absent` for every `not_found`. Reporting
    a package with an open staged recipe as a gap to fill would send a second
    person to redo the first person's work.

    The `detail` names the pull request, because the locator lives on the evidence
    row and the whole point of the verdict is that somebody should go and look at
    it.
    """
    an_ended_collection_run()
    pending = a_package("pending")
    absent = a_package("absent")
    a_feedstock_observation(pending, state=OutcomeState.NOT_FOUND, staged_recipe_url=A_STAGED_RECIPE_URL)
    a_feedstock_observation(absent, state=OutcomeState.NOT_FOUND)

    a_policy_run()

    assert the_finding(pending).presence_status == STAGED_RECIPE_PENDING
    assert the_finding(absent).presence_status == ABSENT
    assert A_STAGED_RECIPE_URL in the_finding(pending).detail
    # Both on the rollup column too, which the operator documentation calls the
    # read surface. These are the two verdicts that dispatch work -- one sends
    # somebody to write a recipe and the other to finish a review -- so a column
    # that carried neither, or carried them the wrong way round, would be wrong
    # in the place a report actually reads.
    assert PackageHealth.objects.get(package=pending).feedstock_presence_status == STAGED_RECIPE_PENDING
    assert PackageHealth.objects.get(package=absent).feedstock_presence_status == ABSENT


@pytest.mark.django_db
@pytest.mark.parametrize("staged", ["", A_STAGED_RECIPE_URL], ids=["nothing-queued", "something-queued"])
def test_an_absence_the_collector_did_not_establish_reads_unknown_on_the_rollup(staged: str) -> None:
    """The row `not_found` is reachable four ways, and only one is evidence of an absence.

    `collectors/feedstock.py` writes `not_found` when conda-forge answered that
    the conventional repository is not there, when that repository could not be
    read, when the staged-recipes queue could not be read, and when the queue
    held more than one candidate or overflowed its page. Each already wrote a
    distinct `detail`, and `absence_established` is the structural half added by
    this story so a policy can read it.

    Without it, a GitHub outage and a two-candidate queue both produced `absent`
    -- and `absent` is documented as "the gap to fill: a recipe has to be
    written", which dispatches somebody to write a recipe that may already exist
    or already be queued. That is precisely the outcome `staged_recipe_pending`
    was invented to prevent.

    Asserted on the **rollup column** as well as on the finding, because that is
    where a report reads it.
    """
    an_ended_collection_run()
    package = a_package()
    a_feedstock_observation(
        package,
        state=OutcomeState.NOT_FOUND,
        staged_recipe_url=staged,
        established=False,
    )

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == FEEDSTOCK_UNKNOWN
    assert finding.presence_status != ABSENT
    assert "not established" in finding.detail
    assert PackageHealth.objects.get(package=package).feedstock_presence_status == FEEDSTOCK_UNKNOWN


@pytest.mark.django_db
def test_a_feedstock_nobody_re_observed_is_unknown_rather_than_inactive() -> None:
    """A collector that stopped running is not a feedstock that stopped moving.

    The observation is older than the threshold and the push older still, so the
    arithmetic alone reaches `present_and_inactive` -- indistinguishable on the
    row from a genuinely abandoned recipe, and reported as work somebody should
    go and do. What separates them is how old the *observation* is, which this
    product already treats as a first-class question (`CPM-AD-28`).

    The paired case below is what keeps the rule narrow: an old push seen
    *recently* is exactly the finding `CPM-UJ-2` asks for, and a staleness rule
    that swallowed it would turn the pass's whole purpose into `unknown`.
    """
    an_ended_collection_run()
    package = a_package()
    a_feedstock_observation(
        package,
        observed_at=FIXED_INSTANT - (A_THRESHOLD + A_DAY),
        activity_at=FIXED_INSTANT - (A_THRESHOLD * 3),
    )

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == FEEDSTOCK_UNKNOWN
    assert finding.presence_status != PRESENT_AND_INACTIVE
    assert "unknown rather than inactive" in finding.detail
    assert PackageHealth.objects.get(package=package).feedstock_presence_status == FEEDSTOCK_UNKNOWN


@pytest.mark.django_db
def test_a_fresh_observation_of_an_old_push_is_still_inactive() -> None:
    """The finding the staleness rule must not swallow.

    Observed at the cut-off, pushed to long before it: this is a recipe nobody is
    maintaining, seen by a collector that is running. It is the answer `CPM-UJ-2`
    asks for, and it is the one a staleness rule applied too widely would take
    away.
    """
    an_ended_collection_run()
    package = a_package()
    a_feedstock_observation(package, observed_at=FIXED_INSTANT, activity_at=FIXED_INSTANT - (A_THRESHOLD * 3))

    a_policy_run()

    assert the_finding(package).presence_status == PRESENT_AND_INACTIVE


@pytest.mark.django_db
def test_a_future_dated_push_keeps_its_verdict_and_the_row_says_so() -> None:
    """Clock skew, recorded rather than left to somebody who sorts by the age column.

    A push instant later than the run's cut-off gives a negative age, and the
    verdict stays `present_and_maintained` -- refusing it would turn a remote
    clock into a failed package. What was missing is that the row said nothing:
    an ordinary maintained row and one resting on an impossible instant were
    identical apart from a sign, permanently and silently.
    """
    an_ended_collection_run()
    package = a_package()
    a_feedstock_observation(package, activity_at=FIXED_INSTANT + A_DAY)

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == PRESENT_AND_MAINTAINED
    assert finding.activity_age is not None
    assert finding.activity_age < timedelta()
    assert "after this run's cut-off" in finding.detail


@pytest.mark.django_db
def test_a_feedstock_pushed_to_exactly_the_threshold_ago_is_maintained() -> None:
    """The boundary, asserted through the pass and not only through the arithmetic.

    A closed boundary falls on one side; which side is written down in
    `policies/feedstock.py`, in `policies/data/README.md` and in
    `docs/deployment.md`, and this is the executable half of it. The age is
    asserted equal to the threshold as well, or the case would be about a fixture
    that merely happened to be near it.
    """
    an_ended_collection_run()
    package = a_package()
    a_feedstock_observation(package, activity_at=FIXED_INSTANT - A_THRESHOLD)

    a_policy_run()

    finding = the_finding(package)
    assert finding.activity_age == finding.inactivity_threshold
    assert finding.presence_status == PRESENT_AND_MAINTAINED


@pytest.mark.django_db
def test_a_feedstock_that_exists_but_cannot_be_dated_is_unknown_and_the_row_says_so() -> None:
    """The matrix's "present but undatable": never inactive by default.

    The three measurement columns are all empty on this row, exactly as they are
    on a row for a package nobody observed -- so the `detail` is what tells the two
    apart, and the referenced observation is what a reader follows to find the
    collector's own account of why it could not read a push instant.
    """
    an_ended_collection_run()
    package = a_package()
    observation = a_feedstock_observation(package, activity_at=None)

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == FEEDSTOCK_UNKNOWN
    assert finding.activity_age is None
    assert finding.feedstock_snapshot_id == observation.pk
    assert "unknown rather than inactive" in finding.detail


@pytest.mark.django_db
def test_a_package_nothing_observed_is_unknown_and_still_gets_a_row() -> None:
    """The matrix's "no observation": never `absent` from an absence of looking.

    A missing row would be ambiguous between "not computed" and "nothing to say",
    and no read surface can tell those apart. So the row exists, references no
    observation, and says `unknown` -- and it is asserted *not* `absent`, because
    that is the wrong answer that would send somebody to write a recipe for a
    package that may well have one.
    """
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == FEEDSTOCK_UNKNOWN
    assert finding.presence_status != ABSENT
    assert finding.feedstock_snapshot_id is None
    assert finding.detail == "", "there is no observation to explain"
    assert PackageHealth.objects.get(package=package).feedstock_presence_status == FEEDSTOCK_UNKNOWN


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (OutcomeState.ERROR.value, FEEDSTOCK_ERROR),
        (OutcomeState.NOT_APPLICABLE.value, FEEDSTOCK_NOT_APPLICABLE),
    ],
    ids=["an-error-is-not-an-absence", "inapplicable-is-carried-through"],
)
def test_a_sentinel_observation_becomes_the_same_sentinel_verdict(state: str, expected: str) -> None:
    """The matrix's errored and inapplicable rows, against real evidence.

    `CPM-FR-6`'s states stay un-collapsed. Neither is `absent`, and that is the
    assertion that matters operationally: a lookup that failed and a package the
    feedstock question was never about would each otherwise be reported as a gap
    somebody should go and fill.
    """
    an_ended_collection_run()
    package = a_package()
    a_feedstock_observation(package, state=state)

    a_policy_run()

    finding = the_finding(package)
    assert finding.presence_status == expected
    assert finding.presence_status != ABSENT
    assert PackageHealth.objects.get(package=package).feedstock_presence_status == expected


# ---------------------------------------------------------------------------
# AC 2: the gate is the rollup writer's, and it is not this pass's.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_unmapped_packages_rollup_column_is_unknown_while_an_inventory_derived_ones_is_not() -> None:
    """AC 2, proved through the rollup column, with the pair that keeps it honest.

    **This is the case AC 2 is actually about.** `CPM-AD-4` says the gate is one
    function in `core`, applied by the orchestrating run and never re-implemented
    per pass -- so "an unmapped package reports `unknown` and never `absent`" is a
    claim about `package_health.feedstock_presence_status`, not about anything
    this pass computes. Proving it by driving the orchestration is the honest way;
    adding a second gate inside the pass would satisfy an assertion about the
    pass's return value and would break the architecture.

    **The `inventory-derived` half is what stops the gate being a downgrade.**
    `CPM-AD-4` makes that confidence a *label*, not a reduction: its verdict
    travels undegraded with the provenance recorded beside it. A gate that
    replaced anything short of `verified` would satisfy the `unmapped` assertion
    alone, and would throw away every determinate answer this product can give
    about the majority of its inventory.

    **Both derived rows still record what the evidence supported**, which is the
    other half of what makes the run auditable: the gate is applied on the way
    into the rollup and the pass's own table is untouched by it, so a reader can
    see the verdict *and* the confidence that replaced it.

    Both packages carry identical evidence, so the only thing that differs between
    the three columns asserted is the confidence.
    """
    an_ended_collection_run()
    unmapped = a_package("unresolved", confidence=IdentityConfidence.UNMAPPED)
    derived = a_package("numpy", confidence=IdentityConfidence.INVENTORY_DERIVED)
    for package in (unmapped, derived):
        an_inactive_feedstock(package)

    a_policy_run()

    assert GATED_VALUE != PRESENT_AND_INACTIVE, "the gate must change the value, or this case asserts nothing"
    assert PackageHealth.objects.get(package=unmapped).feedstock_presence_status == GATED_VALUE
    assert PackageHealth.objects.get(package=derived).feedstock_presence_status == PRESENT_AND_INACTIVE
    assert PackageHealth.objects.get(package=derived).confidence == IdentityConfidence.INVENTORY_DERIVED
    assert the_finding(unmapped).presence_status == PRESENT_AND_INACTIVE
    assert the_finding(unmapped).confidence == IdentityConfidence.UNMAPPED
    assert the_finding(derived).confidence == IdentityConfidence.INVENTORY_DERIVED


@pytest.mark.django_db
def test_an_unmapped_package_never_reports_absent_however_the_evidence_reads() -> None:
    """AC 2 in the words the story uses: `unknown`, and never `absent`.

    The case above shows the gate replacing a *maintenance* verdict; this shows it
    replacing the one verdict that would actually send somebody to do work.
    `absent` is a claim that conda-forge has no feedstock and that a recipe should
    be written, and making it about a package whose identity was never established
    is precisely what `CPM-FR-5` forbids -- the mapping the claim would be about is
    not known to be this package's.
    """
    an_ended_collection_run()
    package = a_package("unresolved", confidence=IdentityConfidence.UNMAPPED)
    a_feedstock_observation(package, state=OutcomeState.NOT_FOUND)

    a_policy_run()

    assert the_finding(package).presence_status == ABSENT
    assert PackageHealth.objects.get(package=package).feedstock_presence_status == FEEDSTOCK_UNKNOWN
    assert PackageHealth.objects.get(package=package).feedstock_presence_status != ABSENT


@pytest.mark.django_db
def test_the_rollup_column_arrives_through_the_orchestration_rather_than_from_the_pass() -> None:
    """`CPM-AD-21`: a pass returns its columns and never writes the rollup.

    The verdict on the rollup row and the verdict on the pass's own table agree,
    and the pass wrote only one of them -- `core/rollup.py` wrote the other, after
    the gate, from the mapping the pass returned. The run's per-domain version map
    naming this pass is what says the contribution travelled that route rather
    than some other one.

    The currency column is asserted beside it, because both passes contribute to
    the same row and a writer that replaced the whole row per pass would leave
    whichever ran last.
    """
    an_ended_collection_run()
    package = a_package()
    an_inactive_feedstock(package)

    a_policy_run()

    health = PackageHealth.objects.get(package=package)
    assert health.feedstock_presence_status == PRESENT_AND_INACTIVE
    assert health.feedstock_presence_status == the_finding(package).presence_status
    assert health.policy_versions[POLICY_NAME] == A_POLICY_VERSION
    assert health.evidence_cutoff == FIXED_INSTANT
    assert PackageCurrency.objects.filter(package=package).count() == 1, (
        "both adopted passes must have run, or this case says nothing about two contributions on one row"
    )


# ---------------------------------------------------------------------------
# AC 3: the threshold is versioned data.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_two_runs_at_two_versions_over_one_cutoff_reach_two_verdicts() -> None:
    """AC 3, and the only arrangement that can show a parameter is *versioned*.

    One package, one observation, one evidence cut-off, two policy versions whose
    recorded thresholds differ -- and two different verdicts. No constant could do
    this, and neither could a setting: a setting is per-deployment, so both runs in
    one process would read the same value and the two rows would agree.

    Each row records the threshold it applied, which is what makes the difference
    explicable rather than merely observable: a reader diffing the two runs sees
    *why* they disagree without going to the parameter file, and would see it even
    if the file had since changed again.

    The second run passes the first run's cut-off explicitly, so the two are
    genuinely over the same evidence and the only difference between them is the
    rule.
    """
    an_ended_collection_run()
    package = a_package()
    an_inactive_feedstock(package)

    strict = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))
    lenient = execute_policy_run(
        policy_version=A_LENIENT_POLICY_VERSION,
        clock=FixedClock(instant=LATER_INSTANT + OBSERVATION_GAP),
        evidence_cutoff=strict.evidence_cutoff,
    )

    rows = {
        row.policy_run_id: row
        for row in PackageFeedstockPresence.objects.filter(package=package).select_related("policy_run")
    }
    assert strict.evidence_cutoff == lenient.evidence_cutoff, "the two runs must read one evidence set"
    assert rows[strict.policy_run.pk].presence_status == PRESENT_AND_INACTIVE
    assert rows[lenient.policy_run.pk].presence_status == PRESENT_AND_MAINTAINED
    assert rows[strict.policy_run.pk].inactivity_threshold == timedelta(days=A_THRESHOLD_IN_DAYS)
    assert rows[lenient.policy_run.pk].inactivity_threshold == timedelta(days=A_LENIENT_THRESHOLD_IN_DAYS)
    assert rows[strict.policy_run.pk].last_recipe_activity_at == rows[lenient.policy_run.pk].last_recipe_activity_at


@pytest.mark.django_db
def test_a_run_at_a_version_nothing_records_fails_the_run_rather_than_each_package() -> None:
    """The matrix's "unknown policy version": refused, never defaulted -- and refused once.

    **The fault is the run's, not any package's, and the run is what fails.**
    `FeedstockPresencePass.prepare` establishes the parameter set once, before
    the package loop, so a version `policies/data/policy-parameters.toml` does
    not record is met one time: one refusal, one ledger row, and a message naming
    the file and the version. Looking it up per package would have produced a
    traceback and a failed row per package, a failed count the size of the
    inventory, and a file read per package -- for a condition that was knowable
    before the first one.

    Nothing is written: no derived row of either pass, no rollup row, and the
    ledger row says `failed`. The refusal reaches the caller, which is what makes
    an operator's mistyped version legible rather than something to reconstruct
    from ten thousand log lines.
    """
    an_ended_collection_run()
    package = a_package()
    an_inactive_feedstock(package)

    with pytest.raises(PolicyParameterError) as refused:
        execute_policy_run(
            policy_version=AN_UNRECORDED_POLICY_VERSION,
            clock=FixedClock(instant=LATER_INSTANT),
        )

    assert AN_UNRECORDED_POLICY_VERSION in str(refused.value)
    assert PackageFeedstockPresence.objects.count() == 0
    assert PackageCurrency.objects.count() == 0
    assert PackageHealth.objects.count() == 0
    assert PolicyRun.objects.get().status == RunState.FAILED


@pytest.mark.django_db
def test_a_run_at_an_unrecorded_version_does_not_take_the_previous_rows_away() -> None:
    """`CPM-NFR-3`: degrade to stale, never to a clean result.

    A failed run leaves every package's previous rollup row where it was rather
    than overwriting it with a health computed from a pass that never ran. So a
    component whose operator enqueues a run at a mistyped version loses the day's
    update and keeps yesterday's answer, which is the outcome the whole
    partial-run machinery exists to produce -- and which failing in `prepare`
    preserves more completely than failing per package did, because nothing is
    written at all.
    """
    an_ended_collection_run()
    package = a_package()
    an_inactive_feedstock(package)

    clean = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))
    with pytest.raises(PolicyParameterError):
        execute_policy_run(
            policy_version=AN_UNRECORDED_POLICY_VERSION,
            clock=FixedClock(instant=LATER_INSTANT + OBSERVATION_GAP),
        )

    health = PackageHealth.objects.get(package=package)
    assert health.policy_run_id == clean.policy_run.pk
    assert health.feedstock_presence_status == PRESENT_AND_INACTIVE


@pytest.mark.django_db
def test_the_parameter_set_is_established_once_however_large_the_inventory() -> None:
    """The other half of `prepare`: the cost of the lookup does not scale.

    A version is one fact about a run, and reading the reviewed file per package
    would have made an inventory-sized run read it an inventory-sized number of
    times -- cheap per read and absurd in aggregate, for an answer that cannot
    differ. Asserted by counting the reads rather than by inspecting the pass,
    because "it is established once" is a property of the orchestration calling
    `prepare` once and not of any declaration.
    """
    an_ended_collection_run()
    reads: list[Path] = []
    original = parameters_module.parameters_at

    def counted(path: Path) -> dict[str, Any]:
        reads.append(path)
        return original(path)

    for index in range(PACKAGES_IN_THE_INVENTORY):
        an_inactive_feedstock(a_package(f"package-{index}"))
    forget_recorded_parameters()
    with monkeypatched(parameters_module, "parameters_at", counted):
        a_policy_run()

    assert len(reads) == 1, f"the reviewed file was read {len(reads)} times for one run"
    assert PackageFeedstockPresence.objects.count() == PACKAGES_IN_THE_INVENTORY


def test_the_shipped_file_records_the_version_the_suite_names() -> None:
    """The reviewed file parses, and the constant the rest of the suite runs at is in it.

    Read at the *shipped* path rather than through `parameters_for`, because
    `_recorded_thresholds` has the reader pointed at this module's own file -- and
    read directly rather than through the memoized entry point, so this case
    cannot be satisfied by a parse some earlier case happened to cache.

    Both directions matter. If the file stopped recording
    `A_RECORDED_POLICY_VERSION`, every policy run in
    `tests/integration/django_apps/test_currency_policy.py` and
    `tests/integration/django_apps/test_policy_run.py` would fail every package,
    and those modules would report faults that have nothing to do with what they
    are about. And if the file stopped parsing at all, nothing else in the unit
    tier would notice: every parameter case there is measured against a document a
    case wrote.

    No database, and no substitution: this reads one file this repository ships.
    """
    recorded = parameters_at(THE_SHIPPED_FILE)

    assert A_RECORDED_POLICY_VERSION in recorded, sorted(recorded)
    assert recorded[A_RECORDED_POLICY_VERSION].feedstock_inactivity > timedelta()
    assert recorded[A_RECORDED_POLICY_VERSION].version == A_RECORDED_POLICY_VERSION


@pytest.mark.parametrize(
    ("write", "expected"),
    [
        (None, "could not be read"),
        (b"[versions]\n\xff\xfe = 1\n", "not utf-8"),
    ],
    ids=["a-file-that-is-not-there", "a-file-that-is-not-text"],
)
def test_a_file_that_cannot_be_read_refuses_and_names_itself(
    tmp_path: Path,
    write: bytes | None,
    expected: str,
) -> None:
    """The two refusals only a *file* can earn, which is why they need a filesystem.

    `parameters_from` owns every refusal about what a parameter file says, and
    every one of those is measured against a string in
    `tests/unit/django_apps/test_feedstock_policy.py`. These two are about the
    file itself -- one that is not there, and one that is not text this component
    can decode -- and neither can be reached without opening one.

    An installation that shipped the modules and dropped the data tree is the
    first; a file saved in some other encoding is the second, and TOML is UTF-8 by
    specification so there is nothing to be tolerant of. Both name the path,
    because these are `CPM-AD-14` governed data and an operator sent to the file
    is being sent to the right place.

    `tmp_path`, not the shipped tree: nothing here may touch the file the product
    actually reads.
    """
    path = tmp_path / "unreadable.toml"
    if write is not None:
        path.write_bytes(write)

    with pytest.raises(PolicyParameterError) as refused:
        parameters_at(path)

    assert expected in str(refused.value).lower()
    assert str(path) in str(refused.value)


def test_the_shipped_file_is_read_once_per_process() -> None:
    """The memoization, asserted as identity, and against the file this case names.

    `CPM-AD-8` makes one policy version mean one rule set, and a file re-read per
    package would let an edit part-way through a run judge half the inventory
    under one threshold and half under another. Equality would hold for a reader
    that parsed afresh every time; identity is what says it did not.

    **The shipped path is passed explicitly**, which is the correction this case
    needed: it runs under `_recorded_thresholds`, which has the reader pointed at
    this module's own file, so an argument-free call memoized the *substituted*
    parse while the name and the docstring described the shipped one.

    The consequence -- a change to the shipped file takes effect at the next
    process start -- is stated in `policies/parameters.py` and in
    `policies/data/README.md`, because it is the one way this differs from the
    watchlist an operator edits between sweeps.
    """
    assert recorded_parameters(THE_SHIPPED_FILE) is recorded_parameters(THE_SHIPPED_FILE)
    assert parameters_module.parameters_file() != THE_SHIPPED_FILE, (
        "this case must name the shipped file explicitly, or it is asserting about the substituted one"
    )


def test_a_refused_read_is_remembered_rather_than_retried(tmp_path: Path) -> None:
    """A file repaired mid-run must not start answering part of the way through.

    `functools.cache` stores returns and re-runs on every exception, so a refusal
    is not remembered by default -- and a reviewed file corrected while a failing
    run was still going would begin succeeding mid-inventory, judging half the
    packages under a rule set the other half never saw. That is the exact hazard
    the memoization exists to prevent, reached from the other side.

    The file is repaired between the two reads and the second still refuses,
    which is what says the refusal was cached rather than merely raised twice --
    and the cleared cache reads it again, which is what says the memory is the
    process's rather than for ever.
    """
    broken = tmp_path / "broken.toml"
    broken.write_text("this is not toml = = =", encoding="utf-8")

    with pytest.raises(PolicyParameterError):
        recorded_parameters(broken)

    broken.write_text(parameter_document({A_POLICY_VERSION: A_THRESHOLD_IN_DAYS}), encoding="utf-8")

    with pytest.raises(PolicyParameterError):
        recorded_parameters(broken)

    forget_recorded_parameters()

    assert A_POLICY_VERSION in recorded_parameters(broken)


def test_the_memo_answers_about_the_file_it_was_asked_about(tmp_path: Path) -> None:
    """Keyed on the path, not on nothing.

    An argument-free memo over a module global answers about whatever file the
    *first* caller happened to name, so a later caller reading a different one
    silently gets the earlier parse. In the suite that is a substituted file that
    stops taking effect; in the product it is a parameter tree that moved and
    nobody noticed.
    """
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    first.write_text(parameter_document({A_POLICY_VERSION: A_THRESHOLD_IN_DAYS}), encoding="utf-8")
    second.write_text(parameter_document({A_POLICY_VERSION: A_LENIENT_THRESHOLD_IN_DAYS}), encoding="utf-8")

    assert recorded_parameters(first)[A_POLICY_VERSION].feedstock_inactivity == timedelta(days=A_THRESHOLD_IN_DAYS)
    assert recorded_parameters(second)[A_POLICY_VERSION].feedstock_inactivity == timedelta(
        days=A_LENIENT_THRESHOLD_IN_DAYS,
    )


def test_the_parse_the_memo_hands_out_cannot_be_edited(tmp_path: Path) -> None:
    """One process, one parse, shared by every caller -- so no caller may change it.

    `PolicyParameters` is frozen so a parameter set cannot be edited after it was
    read; a mutable mapping around it would leave the same hole one level up,
    where a single assignment changes the rule set for every later caller in the
    process. The mapping is read-only for the same reason the object is.
    """
    path = tmp_path / "recorded.toml"
    path.write_text(parameter_document({A_POLICY_VERSION: A_THRESHOLD_IN_DAYS}), encoding="utf-8")

    recorded = recorded_parameters(path)

    with pytest.raises(TypeError):
        recorded[A_POLICY_VERSION] = recorded[A_POLICY_VERSION]  # type: ignore[index]


# ---------------------------------------------------------------------------
# The cut-off, the replay, and the cost.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evidence_written_after_the_cutoff_is_not_read() -> None:
    """`CPM-AD-21`: a pass reads evidence as of the run's stated instant and no later.

    The two observations disagree, and only the earlier one is at or before the
    cut-off -- so the verdict is what the cut-off's evidence supports, and the
    referenced row is the earlier one. Without this the later observation would
    make the feedstock read `present_and_maintained`, which is the difference
    between a replay that reproduces and one that answers differently every time
    it runs.
    """
    an_ended_collection_run()
    package = a_package()
    at_the_cutoff = an_inactive_feedstock(package)
    later = a_feedstock_observation(package, activity_at=AFTER_THE_CUTOFF, observed_at=AFTER_THE_CUTOFF)

    a_policy_run()

    finding = the_finding(package)
    assert finding.feedstock_snapshot_id == at_the_cutoff.pk
    assert finding.feedstock_snapshot_id != later.pk
    assert finding.presence_status == PRESENT_AND_INACTIVE


@pytest.mark.django_db
def test_the_newest_observation_at_the_cutoff_is_the_one_read() -> None:
    """The other half of the read: newer evidence at or before the cut-off wins.

    Together with the case above this pins the boundary from both sides. A read
    that took the *oldest* row would satisfy the exclusion case for the wrong
    reason -- it would also ignore the later row -- and would keep reporting a
    feedstock as abandoned long after somebody had started pushing to it again.
    """
    an_ended_collection_run(finished_at=AFTER_THE_CUTOFF)
    package = a_package()
    an_inactive_feedstock(package)
    newest = a_feedstock_observation(
        package,
        activity_at=AFTER_THE_CUTOFF - A_DAY,
        observed_at=AFTER_THE_CUTOFF,
    )

    a_policy_run()

    finding = the_finding(package)
    assert finding.feedstock_snapshot_id == newest.pk
    assert finding.presence_status == PRESENT_AND_MAINTAINED


@pytest.mark.django_db
def test_replaying_a_version_at_a_cutoff_reproduces_the_row_and_leaves_the_first_alone() -> None:
    """`CPM-AD-8` and `CPM-FR-22`: same version, same cut-off, identical output.

    **The second run is a real replay, not a repetition.** A collection run
    finishes between the two, which moves the boundary `choose_evidence_cutoff`
    would pick -- so a second run that chose its own cut-off would read a
    different evidence set and this case would be asserting determinism, which is
    a weaker property than the one `CPM-FR-22` promises. New evidence lands after
    the original cut-off too, and it must not be read.

    Every column that is not the key is compared, rather than a chosen few: the
    guarantee is about the whole row, and a case naming three columns would pass
    while a fourth drifted. The threshold in particular is part of that -- a
    replay that re-read a parameter file which had since changed would produce a
    row that differed in exactly one column.
    """
    an_ended_collection_run()
    package = a_package()
    an_inactive_feedstock(package)

    first = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    an_ended_collection_run(finished_at=AFTER_THE_CUTOFF)
    a_feedstock_observation(package, activity_at=AFTER_THE_CUTOFF, observed_at=AFTER_THE_CUTOFF)

    assert choose_evidence_cutoff() != first.evidence_cutoff, (
        "the cut-off must have moved between the two runs, or this case is a repetition rather than a replay"
    )

    execute_policy_run(
        policy_version=A_POLICY_VERSION,
        clock=FixedClock(instant=LATER_INSTANT + OBSERVATION_GAP),
        evidence_cutoff=first.evidence_cutoff,
    )

    rows = list(PackageFeedstockPresence.objects.filter(package=package).order_by("policy_run_id"))
    compared = [
        field.name
        for field in PackageFeedstockPresence._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if field.name not in {"id", "policy_run"}
    ]

    assert len(rows) == REPLAYED_RUNS
    assert rows[0].policy_run_id != rows[1].policy_run_id
    for column in compared:
        assert getattr(rows[0], column) == getattr(rows[1], column), column


@pytest.mark.django_db
@pytest.mark.parametrize("packages", [1, 2, 4], ids=str)
def test_the_query_count_per_package_does_not_grow_with_the_inventory(
    django_assert_num_queries: Any,
    packages: int,
) -> None:
    """Two queries per package, and the parameter lookup costs none of them.

    The count is *linear* in the inventory and the per-package constant is two --
    one evidence read and one insert of the derived row. A read that started
    issuing a query per surface, or a parameter lookup that had become a database
    table rather than a reviewed file, would change the constant and show up here
    at three cardinalities rather than at none.

    That the reviewed file costs no query at all is the half worth pinning: it is
    a memoized read of a file established once per run, and a later story moving
    the parameters into a table would take that away silently -- one more query
    per package, or one per run that nothing here would notice.

    Only the pass phase is measured. `execute_policy_run` also opens a ledger row,
    reads the package set and composes the rollup, and those are the
    orchestration's queries rather than this pass's.
    """
    an_ended_collection_run()
    inventory = [a_package(f"package-{index}") for index in range(packages)]
    for package in inventory:
        an_inactive_feedstock(package)
    cutoff = choose_evidence_cutoff()
    run = a_policy_run_row()
    # Prepared outside the measurement, exactly as the orchestration prepares it
    # outside the package loop: the parameter set is established once per run and
    # the point of this case is what each *package* costs after that.
    policy_pass = FeedstockPresencePass()
    policy_pass.prepare(policy_run=run, evidence_cutoff=cutoff)

    with django_assert_num_queries(QUERIES_PER_PACKAGE * packages):
        for package in inventory:
            policy_pass.evaluate(package, policy_run=run, evidence_cutoff=cutoff)


@pytest.mark.django_db
def test_one_row_per_package_per_run_over_more_than_one_package() -> None:
    """`CPM-AD-21`'s key and `CPM-AD-23`'s atomic unit, over an inventory.

    Two packages with different evidence, one run: two findings, each about its
    own package, neither carrying the other's verdict. A pass that had computed
    once and written the same row twice would satisfy every single-package case in
    this module.
    """
    an_ended_collection_run()
    maintained = a_package("numpy")
    inactive = a_package("scipy")
    a_maintained_feedstock(maintained)
    an_inactive_feedstock(inactive)

    a_policy_run()

    assert PackageFeedstockPresence.objects.count() == PACKAGES_IN_THE_INVENTORY
    assert the_finding(maintained).presence_status == PRESENT_AND_MAINTAINED
    assert the_finding(inactive).presence_status == PRESENT_AND_INACTIVE


# ---------------------------------------------------------------------------
# What the database refuses.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_derived_table_refuses_a_second_row_for_one_package_and_run() -> None:
    """`CPM-AD-21`'s key as a database rule, proven by the database refusing.

    A unique constraint is only genuinely proven by the second write failing. The
    row is built by copying the one the run wrote, so it differs from it in
    nothing but the primary key -- which is exactly the duplicate a pass that ran
    twice would produce.
    """
    an_ended_collection_run()
    package = a_package()
    a_maintained_feedstock(package)

    a_policy_run()

    duplicate = the_finding(package)
    duplicate.pk = None
    duplicate._state.adding = True  # noqa: SLF001 - Django's own way to make a copied instance an insert

    # Contained in its own atomic block: an IntegrityError marks the surrounding
    # transaction broken, and `@pytest.mark.django_db` wraps the whole case in
    # one -- so a raise outside a savepoint would make the rollback at teardown
    # the error a reader sees instead of this one.
    with pytest.raises(IntegrityError), transaction.atomic():
        duplicate.save()


@pytest.mark.django_db
@pytest.mark.parametrize("threshold", [timedelta(), -timedelta(days=1)], ids=["zero", "negative"])
def test_a_threshold_that_is_not_a_positive_interval_is_refused_by_the_database(threshold: timedelta) -> None:
    """`feedstock_threshold_is_a_positive_interval`, refused by the database rather than named.

    `policies/parameters.py` refuses a non-positive threshold at the *read*, so
    the pass cannot produce this row -- which is exactly why the constraint exists
    and why a case asserting it by name would pass against one weakened to
    `1 = 1`. What it holds is the hand-written `INSERT` that read no file: a row
    claiming a verdict measured against zero would say every observed feedstock
    was inactive at the instant it was pushed to.

    Both sides of zero, because a check written as `>= 0` would refuse the
    negative and admit the zero, and one written as `<> 0` the reverse.
    """
    with pytest.raises(IntegrityError, match=THRESHOLD_IS_A_POSITIVE_INTERVAL), transaction.atomic():
        a_hand_built_row(inactivity_threshold=threshold)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("instant", "age"),
    [(FIXED_INSTANT, None), (None, A_THRESHOLD)],
    ids=["an-instant-with-no-age", "an-age-with-no-instant"],
)
def test_a_measurement_without_what_it_was_measured_from_is_refused_by_the_database(
    instant: datetime | None,
    age: timedelta | None,
) -> None:
    """`feedstock_age_exactly_when_there_is_an_instant`, in both directions.

    An age with no instant is a number nothing supports; an instant with no age is
    a measurement the run declined to make while still reaching a verdict. Both
    are asserted because either half alone permits the other's row -- a check
    written as one implication would admit exactly the case it did not name.

    The verdict on these rows is `absent`, which needs no instant, so the
    maintenance constraint below cannot be what refuses them.
    """
    with pytest.raises(IntegrityError, match=AN_AGE_EXACTLY_WHEN_THERE_IS_AN_INSTANT), transaction.atomic():
        a_hand_built_row(last_recipe_activity_at=instant, activity_age=age)


@pytest.mark.django_db
@pytest.mark.parametrize("verdict", list(MEASURED_VERDICTS), ids=str)
def test_a_maintenance_verdict_with_no_activity_instant_is_refused_by_the_database(verdict: str) -> None:
    """`feedstock_maintenance_verdict_names_its_instant`, per verdict.

    `present_and_maintained` and `present_and_inactive` are verdicts *about an
    age*: each is reached by comparing one against the threshold, so a row
    carrying either while recording no instant is a comparison against nothing --
    and it is precisely the row a reader would take as proof that somebody is, or
    is not, maintaining the recipe.

    Parametrised over both because each is a separate disjunct of the condition: a
    constraint that had lost one would still refuse the other, and a single-verdict
    case would not notice.
    """
    with pytest.raises(IntegrityError, match=MAINTENANCE_VERDICT_NEEDS_AN_ACTIVITY_INSTANT), transaction.atomic():
        a_hand_built_row(presence_status=verdict, last_recipe_activity_at=None, activity_age=None)


@pytest.mark.django_db
@pytest.mark.parametrize("verdict", list(DETERMINATE_VERDICTS), ids=str)
def test_a_determinate_verdict_with_no_observation_is_refused_by_the_database(verdict: str) -> None:
    """`feedstock_verdict_names_its_observation`, refused by the database rather than named.

    All four of `CPM-FR-40`'s verdicts are statements about what conda-forge
    holds, and every one is read off a feedstock observation -- so a row carrying
    one while referencing none is a claim about a package resting on nothing. The
    pass cannot build such a row, which is why the constraint exists and why a
    case asserting it by name would pass against one weakened to `1 = 1`; it is
    also the assumption every integration case here leans on when it follows a
    finding's reference back to the evidence.

    Parametrised over all four because each is a separate member of the
    condition's `IN` list: a constraint that had lost one would still refuse the
    other three.

    The two measured verdicts carry an instant and an age, or the maintenance
    constraint would be what refuses them and this case would be about the wrong
    rule.
    """
    measured = verdict in MEASURED_VERDICTS

    with pytest.raises(IntegrityError, match=DETERMINATE_PRESENCE_NEEDS_AN_OBSERVATION), transaction.atomic():
        a_hand_built_row(
            presence_status=verdict,
            feedstock_snapshot=None,
            last_recipe_activity_at=FIXED_INSTANT if measured else None,
            activity_age=A_THRESHOLD if measured else None,
        )


@pytest.mark.django_db
def test_a_sentinel_verdict_needs_no_observation() -> None:
    """The other side, and the row this table exists to write.

    `unknown` for a package nobody observed is precisely the row that has no
    observation to name, and a constraint that had reached it would make the
    commonest row on a fresh inventory unwritable.
    """
    written = a_hand_built_row(presence_status=FEEDSTOCK_UNKNOWN, feedstock_snapshot=None)

    assert written.pk is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, ABSENT),
        (
            {
                "presence_status": PRESENT_AND_MAINTAINED,
                "last_recipe_activity_at": FIXED_INSTANT,
                "activity_age": A_THRESHOLD,
            },
            PRESENT_AND_MAINTAINED,
        ),
    ],
    ids=["a-verdict-that-needs-no-measurement", "a-verdict-that-has-one"],
)
def test_a_well_formed_row_is_permitted_by_every_constraint(overrides: dict[str, Any], expected: str) -> None:
    """The other side, so the four constraints are not simply ones that refuse every row.

    A check written as "refuse everything" would satisfy all six refusal cases
    above and would make the table unwritable, which the pass's own cases would
    then report as a failure somewhere else entirely. Two shapes, because the
    measurement columns are populated on one kind of row and empty on the other,
    and a constraint could legitimately refuse only one of them.
    """
    written = a_hand_built_row(**overrides)

    assert written.pk is not None
    assert written.presence_status == expected
