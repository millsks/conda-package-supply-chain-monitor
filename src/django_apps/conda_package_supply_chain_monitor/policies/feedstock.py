"""`CPM-FR-40`: does a feedstock exist, and is anybody maintaining it.

The second policy pass. It reads the feedstock evidence `CPM-CURRENCY-S03`'s
collector writes, as of the run's stated cut-off; looks up an inactivity
threshold **by the run's policy version** from reviewed data; records one verdict
per package in its own derived row; and returns one rollup column. It writes no
evidence, makes no outbound call, and never writes the rollup.

**Four determinate outcomes, and the two questions behind them.** `CPM-UJ-2` asks
which packages have no feedstock worth filling and which have one nobody is
maintaining, and those are two different questions with two different pieces of
work behind them. So *does it exist* answers `absent` or `staged_recipe_pending`
-- a gap to fill, or a review somebody has already started and not finished --
and *is anybody maintaining it* answers `present_and_maintained` or
`present_and_inactive`.

**What counts as recipe activity is not this module's to decide.** PRD Open
Question 10 has two halves, and `CPM-CURRENCY-S03` answered the second: recipe
activity is a push to the feedstock repository, and `FeedstockSnapshot`
records the instant. This pass applies a threshold to that instant and invents no
second definition -- no commit counting, no release cadence, no issue activity.
`FeedstockSnapshot.last_recipe_activity_at` is the only signal read.

**The threshold is data keyed by the run's policy version, never a constant.**
That is AC 3, and `policies/parameters.py` is the whole of it: a reviewed file
shipped in the wheel, changed by pull request, with a version that records no
parameters refused rather than defaulted. What makes the parameter *observably*
versioned rather than merely stored somewhere else is that two runs at two
versions over one cut-off reach different verdicts, which no constant could do.

**A verdict this pass cannot support is a sentinel, never a guess.** No
observation is `unknown`; an errored observation is `error`; an inapplicable one
is `not_applicable`; and a feedstock that exists whose activity the collector
could not date is `unknown` rather than inactive. That last one is the case worth
naming: the collector records an absent or unusable push instant honestly rather
than inventing one, and a threshold cannot be applied to nothing. Calling it
inactive would be the guess the whole evidence chain is built to refuse, and
calling it maintained would be worse.

**Nothing here gates on confidence, and that is `CPM-AD-4` rather than an
oversight.** The gate is one function in `core`, applied once by
`core/rollup.py` on the way into `package_health`; a pass never sees a confidence
and never applies one, which is what makes the rule hold for the passes nobody
has written. So the rollup column for an `unmapped` package reads `unknown`
whatever this pass computed, and the derived row *records* the confidence beside
its own ungated verdict so a reader of this pass's table can see what the gate
would have done with it. `core/confidence.py` is read by `core/rollup.py` and by
nothing here.

**Nothing here reads the current time.** Every instant is the run's: the cut-off
arrives as an argument (`CPM-AD-21`) and the age is measured against it, never
against the wall clock. That is what makes `CPM-FR-22`'s replay reproduce
identical rows -- and it is more load-bearing here than it was for currency,
because an age measured from *now* would change every verdict every day while the
evidence and the rules stood still.

**A pass that cannot compute refuses rather than guessing.** A policy version
with no recorded parameters, and an evidence row carrying a state outside the
vocabulary, both raise. `core/policy_run.py` contains that per package
(`CPM-AD-23`): this package's derived rows roll back, every other package
commits, the run finalizes `partial` -- or `failed`, where the fault is the
version and therefore every package's -- and the failure is logged with the
package and the traceback.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

from conda_package_supply_chain_monitor.collectors.models import FeedstockSnapshot
from conda_package_supply_chain_monitor.core.clock import is_aware
from conda_package_supply_chain_monitor.core.outcomes import SENTINEL_MEMBERS
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.policy import PolicyPass
from conda_package_supply_chain_monitor.policies.models import PackageFeedstockPresence
from conda_package_supply_chain_monitor.policies.outcomes import ABSENT
from conda_package_supply_chain_monitor.policies.outcomes import FEEDSTOCK_UNKNOWN
from conda_package_supply_chain_monitor.policies.outcomes import PRESENT_AND_INACTIVE
from conda_package_supply_chain_monitor.policies.outcomes import PRESENT_AND_MAINTAINED
from conda_package_supply_chain_monitor.policies.outcomes import STAGED_RECIPE_PENDING
from conda_package_supply_chain_monitor.policies.parameters import parameters_for

if TYPE_CHECKING:
    from conda_package_supply_chain_monitor.policies.parameters import PolicyParameters

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from django.db import models

    from conda_package_supply_chain_monitor.core.models import PolicyRun
    from conda_package_supply_chain_monitor.identity.models import Package

__all__ = [
    "CARRIED_SENTINELS",
    "FUTURE_ACTIVITY_DETAIL",
    "POLICY_NAME",
    "READ_ORDERING",
    "REFINED_SENTINEL",
    "ROLLUP_COLUMN",
    "STAGED_RECIPE_DETAIL",
    "STALE_OBSERVATION_DETAIL",
    "UNDATABLE_ACTIVITY_DETAIL",
    "UNESTABLISHED_ABSENCE_DETAIL",
    "FeedstockPolicyError",
    "FeedstockPresencePass",
    "activity_age",
    "observation_age",
    "observed_feedstock",
    "presence_detail",
    "presence_verdict",
]

#: What this pass is called. It keys `core/policy.py`'s registry, keys the
#: rollup's per-domain `policy_versions` map (`CPM-AD-11`) and appears in every
#: refusal about this pass, so it is spelled once and imported.
#:
#: `feedstock-presence` rather than `feedstock`, because `CPM-EP-PY314` has a
#: feedstock pass of its own coming -- whether a recipe *builds* on 3.14 -- and
#: two passes cannot share a name.
POLICY_NAME: Final[str] = "feedstock-presence"

#: The rollup column this pass owns and the only one it contributes.
#: `core/policy.py` refuses a contribution to a column `core/rollup.py` does not
#: offer, so a misspelling here is a refusal at registration rather than a column
#: contributed nowhere for as long as the pass ran.
ROLLUP_COLUMN: Final[str] = "feedstock_presence_status"

#: The one **sentinel** this domain refines into verdicts of its own.
#:
#: Named for the sentinel rather than for the refinement, because
#: `FeedstockOutcome` refines two of `core`'s values and only one of them is a
#: sentinel: `ok` becomes `present_and_maintained` or `present_and_inactive` on
#: the determinate branch below, and `not_found` -- conda-forge answering that
#: there is no feedstock -- becomes `absent` or `staged_recipe_pending`. This
#: constant is about the second, which is the one the branching here is over;
#: `policies/outcomes.py` argues both.
REFINED_SENTINEL: Final[str] = OutcomeState.NOT_FOUND.value

#: The sentinel states this pass carries through unchanged, as strings.
#:
#: Derived by *excluding* `REFINED_SENTINEL` from `core.outcomes.SENTINEL_MEMBERS`
#: rather than listed, and both halves of that are deliberate. Listing them would
#: be a second spelling of three values whose spelling `outcome_type` has already
#: fixed once -- and a module-scope literal holding several `OutcomeState` members
#: is indistinguishable from a precedence order to
#: `tests/unit/django_apps/test_single_ordering_audit.py`, which is a false
#: positive that module's docstring records and would rightly refuse. A
#: comprehension is neither.
CARRIED_SENTINELS: Final[frozenset[str]] = frozenset(
    value for _, value in SENTINEL_MEMBERS if value != REFINED_SENTINEL
)

#: Zero, for the one comparison that asks whether an interval is negative. Named
#: rather than spelled `timedelta()` at the branch, because what the branch means
#: is "the push is later than the cut-off" and a bare constructor there reads as
#: an empty value rather than as an instant ordering.
_NO_TIME: Final = timedelta()

#: The ordering that decides which observation a cut-off-bound read returns.
#:
#: Declared rather than spelled inside the query, so the fourth hand-written copy
#: of `collectors/models.py`'s `snapshot_as_of` rule in this repository is
#: reconciled against the third by a case rather than by four docstrings agreeing
#: with each other. `policies/currency.py` builds the same key with a per-surface
#: tie-break in the middle; this table needs none, and
#: `tests/unit/django_apps/test_feedstock_policy.py` asserts the two agree where
#: that tie-break is empty.
READ_ORDERING: Final[tuple[str, ...]] = ("-observed_at", "-pk")

#: What the row says about a feedstock that exists whose activity could not be
#: dated. The three measurement columns are all empty on such a row, and without
#: this line a reader cannot tell that case from "nobody looked" -- which is the
#: one distinction the `unknown` verdict is carrying.
UNDATABLE_ACTIVITY_DETAIL: Final[str] = (
    "the feedstock exists but observation {observation} records no usable last-activity instant, so no age "
    "could be measured against the {threshold} threshold; unknown rather than inactive, because a threshold "
    "cannot be applied to nothing"
)

#: What the row says about a package whose feedstock is pending a staged recipe.
#: The locator lives on the evidence row rather than here, and the whole point of
#: the verdict is that somebody should go and look at it.
STAGED_RECIPE_DETAIL: Final[str] = (
    "no feedstock exists, and observation {observation} records an open staged recipe at {url} that would "
    "create one; staged_recipe_pending rather than absent, because the work is a review to finish rather "
    "than a recipe to write"
)

#: What the row says when the collector recorded that it did not *establish* the
#: absence it wrote down. Four shapes reach that row -- the feedstock repository
#: could not be read, the staged-recipes queue could not be read, the queue held
#: more than one candidate so none was recorded, and the search overflowed its
#: page -- and the collector's own `detail` says which. This line says only that
#: it was one of them, and sends the reader there.
UNESTABLISHED_ABSENCE_DETAIL: Final[str] = (
    "observation {observation} records that no feedstock was found and that the absence was not established "
    "-- see its own detail for which of the four ways -- so this is unknown rather than absent: reporting a "
    "gap to fill on evidence nobody confirmed sends somebody to write a recipe that may already exist or "
    "already be queued"
)

#: What the row says when the feedstock's own observation is older than the
#: threshold being applied to it. See `presence_verdict` for why staleness stops
#: a maintenance verdict and nothing else.
STALE_OBSERVATION_DETAIL: Final[str] = (
    "observation {observation} is itself {observed} old at this run's cut-off, which is longer than the "
    "{threshold} threshold, so whether anybody has pushed to this feedstock since is not something this "
    "evidence can say; unknown rather than inactive, because a collector that stopped running is not a "
    "feedstock that stopped moving"
)

#: What the row says when the recorded push is *later* than the run's cut-off.
#: The verdict is `present_and_maintained` and stays so -- a feedstock pushed to
#: after the evidence boundary is certainly not one nobody has touched -- but the
#: negative age is a fact about somebody's clock rather than about the recipe,
#: and a reader who never thinks to sort by the age column would otherwise never
#: see it.
FUTURE_ACTIVITY_DETAIL: Final[str] = (
    "observation {observation} records a last-activity instant {ahead} after this run's cut-off, so the age "
    "measured against the {threshold} threshold is negative; the verdict is maintained, which is what a push "
    "later than the evidence boundary means, but the instant is a claim about a clock somewhere rather than "
    "about the recipe"
)


class FeedstockPolicyError(ValueError):
    """The feedstock presence pass met evidence or an argument it cannot compute from.

    A `ValueError` subclass, matching `policies/currency.py`'s
    `CurrencyPolicyError`, `core/policy.py`'s `PolicyPassError` and
    `core/outcomes.py`'s `OutcomeVocabularyError`: every "this is unusable" in
    this product is a `ValueError`, so a caller catching one catches them all.

    **`policies/parameters.py` deliberately does not raise this.** A refusal
    about the reviewed parameter file is an `ImproperlyConfigured`, because it
    sends an operator to a file they can edit rather than to evidence they
    cannot; `collectors/watchlist.py` draws the same boundary for the same
    reason. Both are contained per package by `core/policy_run.py`, which catches
    whatever a pass raises.
    """


def observed_feedstock(*, package_id: int, cutoff: datetime) -> FeedstockSnapshot | None:
    """Return what the feedstock surface said about one package at or before a cut-off.

    The cut-off-bound read `collectors/models.py`'s `snapshot_as_of` establishes:
    newest `observed_at` first, then descending primary key. The primary-key
    tie-break is what makes a replay a replay -- one sweep writes every row it
    produces with the run's one instant (`CPM-AD-7`), so an unordered tie would
    let the database's arbitrary row order decide the verdict.

    No per-surface tie-break column, unlike `policies/currency.py`'s conda
    reader: `feedstock_snapshots` holds at most one row per package per sweep, so
    two rows can only tie on `observed_at` if two sweeps ran at one instant, and
    the primary key settles that. `conda_package_snapshots` is the table where a
    stated key is genuinely needed, and it is not this one.

    **This is the fourth hand-written copy of that rule in the repository, and
    the copy is deliberate.** `policies/currency.py`'s `observed_surface` reads
    the same key and could have been called with a tie-break of `()` -- but it
    takes a `SurfaceReader` carrying a `version_field` this question has no
    analogue for, returns a `SurfaceReading` whose `version` would be
    meaningless here, and refuses a naive cut-off with `CurrencyPolicyError`. A
    feedstock presence pass raising a *currency* error is a worse coupling than a
    second query, and hoisting the read into `core` is a machinery change no
    story has claimed. What the copies are not left to do is drift: the ordering
    is `READ_ORDERING` above rather than a literal inside the query, and
    `tests/unit/django_apps/test_feedstock_policy.py` reconciles it against the
    sibling pass's directly rather than trusting either docstring.

    Args:
        package_id: The package being asked about, by the integer primary key
            `CPM-AD-3` fixes.
        cutoff: The instant to read as of, aware. `CPM-AD-21` makes it the
            `finished_at` of a completed collection run, so a pass never reads
            evidence written by a run that is still `running`.

    Returns:
        The newest observation at or before the cut-off, or `None` where the
        surface had none by then. `None` is not an error -- a cut-off earlier
        than a package's first observation is an ordinary question with an
        ordinary answer.

    Raises:
        FeedstockPolicyError: When `cutoff` is naive. Refused rather than
            converted, on the same terms `snapshot_as_of` refuses one: there is
            no offset to convert from, `USE_TZ` is on so Django would read it as
            if it were UTC, and a cut-off silently shifted by the reader's offset
            selects a different evidence set on every replay -- which is the
            opposite of what `CPM-FR-22` promises.

    """
    if not is_aware(cutoff):
        message = (
            f"the feedstock surface cannot be read as of the naive cutoff {cutoff!r}. Every instant comes "
            f"from a Clock, which always answers in UTC (CPM-AD-26); a naive value has no offset to "
            f"interpret, so the read would be silently shifted by whichever offset the reader happened to "
            f"be in and the replay CPM-FR-22 promises would return a different set each time."
        )
        raise FeedstockPolicyError(message)
    return (
        FeedstockSnapshot.objects.filter(package_id=package_id, observed_at__lte=cutoff)
        .order_by(*READ_ORDERING)
        .first()
    )


def activity_age(observation: FeedstockSnapshot | None, *, cutoff: datetime) -> timedelta | None:
    """Return how old the recorded recipe activity was at the run's cut-off.

    Measured against the cut-off and never against the current time. An age
    measured from *now* would change every verdict every day while the evidence
    and the rules stood still, which is the property `CPM-AD-8`'s replay
    guarantee is made of.

    **The result may be non-positive, and that is not an error.** A source that
    reports a push instant after the run's cut-off -- clock skew, a repository
    stating a future date -- gives a negative age, and the honest reading is that
    the feedstock has been pushed to more recently than the evidence boundary. It
    reads `present_and_maintained` below, which is what a negative age means, and
    nothing refuses it: turning somebody else's clock skew into a failed package
    would cost a real verdict to defend an arithmetic tidiness nobody asked for.

    Args:
        observation: The observation this verdict rests on, or `None`.
        cutoff: The instant the run reads evidence as of, aware.

    Returns:
        The interval between the recorded activity and the cut-off, or `None`
        where there is no observation or the observation records no instant. The
        second is a real, ordinary row rather than a defensive branch:
        `FeedstockSnapshot` records a feedstock that exists whose last push the
        collector could not read, with `last_recipe_activity_at` NULL and
        `detail` saying why.

    Raises:
        FeedstockPolicyError: When the recorded instant is naive. Refused rather
            than subtracted, on the terms every instant guard in this product
            refuses one: `USE_TZ` is on so Django reads a naive value back as if
            it were UTC, and the subtraction against an aware cut-off raises a
            bare `TypeError` about offset-naive and offset-aware datetimes --
            which fails the package with a message about Python's arithmetic and
            nothing in it naming the row a reader has to go and look at.

    """
    if observation is None or observation.last_recipe_activity_at is None:
        return None
    activity_at = observation.last_recipe_activity_at
    if not is_aware(activity_at):
        message = (
            f"the feedstock observation {observation.pk} records the naive last-activity instant "
            f"{activity_at!r}, which cannot be measured against this run's cut-off. Every instant in this "
            f"product comes from a Clock and is aware (CPM-AD-26); a naive one has no offset to interpret, "
            f"so an age computed from it would be wrong by whichever offset wrote it."
        )
        raise FeedstockPolicyError(message)
    return cutoff - activity_at


def observation_age(observation: FeedstockSnapshot | None, *, cutoff: datetime) -> timedelta | None:
    """Return how old the *observation itself* was at the run's cut-off.

    The second age this pass measures, and the one that says whether the first is
    worth trusting. `activity_age` above is how long ago somebody pushed to the
    feedstock; this is how long ago anybody looked.

    **Two ages rather than one, because `CPM-AD-28` puts them on different
    axes.** `core/freshness.py` is this product's one statement that staleness is
    a property *beside* a status rather than a status of its own, and it is the
    machinery a read surface uses. This is not a second copy of it: it reports no
    verdict and reads no per-collector target -- it answers one arithmetic
    question that `presence_verdict` needs, and the threshold it is compared
    against is the policy's own, not a collector's freshness target.

    Args:
        observation: The observation the verdict rests on, or `None`.
        cutoff: The instant the run reads evidence as of, aware.

    Returns:
        The interval between the observation and the cut-off, or `None` where
        there is no observation. Never negative in practice -- the read excludes
        anything after the cut-off -- and not asserted to be, because a row is
        not the place to defend a query's own filter.

    Raises:
        FeedstockPolicyError: When the observation's own instant is naive.
            `AppendOnlyModel` takes it from an injected `Clock`, so this is the
            same unreachable-by-the-writer shape `activity_age` refuses, refused
            for the same reason.

    """
    if observation is None:
        return None
    observed_at = observation.observed_at
    if not is_aware(observed_at):
        message = (
            f"the feedstock observation {observation.pk} carries the naive observed_at {observed_at!r}, so "
            f"its own age at this run's cut-off cannot be measured. Every evidence instant comes from an "
            f"injected Clock and is aware (CPM-AD-26, CPM-AD-7)."
        )
        raise FeedstockPolicyError(message)
    return cutoff - observed_at


def presence_verdict(
    observation: FeedstockSnapshot | None,
    *,
    age: timedelta | None,
    observed: timedelta | None,
    threshold: timedelta,
) -> str:
    """Return one package's feedstock presence and maintenance verdict.

    `CPM-FR-6`'s states stay un-folded: no two of them arrive at one verdict here.
    Three of the four sentinels an observation can carry become the same sentinel;
    the fourth, `not_found`, is the one this domain *refines* -- into `absent` or
    `staged_recipe_pending` -- which is a split rather than a fold, and is what
    `CPM-FR-40` asks for.

    **An absence is only reported when the collector established one.**
    `feedstock_snapshots.absence_established` is what says so, and it is the
    reason that column exists: `not_found` is reachable four ways and three of
    them are the run failing to find out. Reporting `absent` from one of those
    would send somebody to write a recipe that may already exist or already be
    queued for review, which is the outcome `staged_recipe_pending` was invented
    to prevent. So an unestablished absence reads `unknown` -- both when nothing
    is queued and when something is, because a queued recipe is only *pending*
    if there is no feedstock, and that is the half nobody confirmed.

    **A stale observation cannot support a maintenance verdict.** The age of the
    last push is measured against the cut-off, and it is only a statement about
    whether anybody is maintaining the recipe if somebody looked recently enough
    to know. An observation older than the threshold itself would otherwise make
    a feedstock nobody has *re-observed* indistinguishable from one nobody has
    *pushed to* -- a collector that stopped running, reported as an abandoned
    recipe, for the whole inventory. So it reads `unknown` and the row says why.

    The staleness rule stops at the maintenance verdict and does not reach
    `absent` or `staged_recipe_pending`, which is a boundary rather than an
    oversight. A maintenance verdict is a claim about the interval between the
    last push and the cut-off, and it is exactly the claim an old observation
    cannot support; `absent` is a claim about what conda-forge held when somebody
    looked, which age makes older but does not falsify. `core/freshness.py` is
    where "how old is this" belongs beside every verdict, for a read surface to
    report; this is only the one place staleness changes what may be *claimed*.

    **The boundary is stated rather than discovered.** A feedstock last pushed to
    *exactly* the threshold ago at the cut-off reads `present_and_maintained`:
    the threshold is how long a feedstock may go without a push, so inactivity
    begins strictly after it. An observation exactly the threshold old is on the
    same side, for the same reason and by the same comparison. The choice is
    arbitrary in the way every closed boundary is; what matters is that it is
    written down here, in `policies/data/README.md`, in `docs/deployment.md` and
    in a case, so a reviewer choosing a value knows which side of it their number
    sits on.

    Args:
        observation: The newest observation at the cut-off, or `None`.
        age: How old the recorded activity was at the cut-off, from
            `activity_age`, or `None` where no instant could be measured.
        observed: How old the observation itself was, from `observation_age`, or
            `None` where there was none.
        threshold: The inactivity threshold this run's policy version records.

    Returns:
        A `FeedstockOutcome` value. `unknown` where nothing was observed, where
        the observation itself records `unknown`, where a feedstock exists whose
        activity could not be dated, where the observation is older than the
        threshold, and where an absence was recorded but not established.

    Raises:
        FeedstockPolicyError: When the observation carries a state outside
            `OutcomeState`. `choices` is a form rule Django does not enforce on
            `save()`, so such a row is reachable; reading it as an absence would
            let a value nobody recognises become a clean-looking answer.

    """
    if observation is None:
        return FEEDSTOCK_UNKNOWN
    state = observation.state
    if state in CARRIED_SENTINELS:
        return state
    if state == REFINED_SENTINEL:
        if not observation.absence_established:
            return FEEDSTOCK_UNKNOWN
        return STAGED_RECIPE_PENDING if observation.staged_recipe_url.strip() else ABSENT
    if state != OutcomeState.OK:
        message = (
            f"the feedstock observation {observation.pk} carries state {state!r}, which is not one of "
            f"{sorted(OutcomeState.values)}. CPM-AD-5 fixes the vocabulary an evidence state is drawn from; "
            f"a maintenance verdict derived from a value outside it would be a claim about the package "
            f"resting on a value nothing in this product recognises."
        )
        raise FeedstockPolicyError(message)
    if age is None or observed is None or observed > threshold:
        return FEEDSTOCK_UNKNOWN
    return PRESENT_AND_MAINTAINED if age <= threshold else PRESENT_AND_INACTIVE


def presence_detail(  # noqa: PLR0911 - one return per thing the row cannot say for itself; a shared exit would hide which
    observation: FeedstockSnapshot | None,
    verdict: str,
    *,
    age: timedelta | None,
    observed: timedelta | None,
    threshold: timedelta,
) -> str:
    """Return the row's account of its verdict, or `""` where the columns already say it.

    Populated on exactly the shapes whose reason is not readable off the row's own
    columns, and empty everywhere else -- the rule every evidence table in this
    product applies to its own `detail`: an explanation of an unremarkable row is
    noise.

    Four shapes need a line:

    * an absence the collector did not establish, which is `unknown` on a row
      that looks exactly like a row for a package nobody observed;
    * an observation too old to support a maintenance verdict, likewise;
    * a feedstock that exists whose activity could not be dated, whose three
      measurement columns are all empty;
    * a staged recipe, whose locator lives on the evidence row.

    And one shape needs a line while keeping its verdict: a push instant *later*
    than the cut-off. The verdict is `present_and_maintained`, which is what that
    means, but the negative age is a fact about somebody's clock and a reader who
    never sorts by the age column would otherwise never meet it.

    Args:
        observation: The observation the verdict rests on, or `None`.
        verdict: The verdict reached.
        age: The activity age, or `None`.
        observed: The observation's own age, or `None`.
        threshold: The threshold applied, named in each line so a reader can see
            what was or could not be measured against it.

    Returns:
        One line, or `""`.

    """
    if observation is None:
        return ""
    if verdict == STAGED_RECIPE_PENDING:
        return STAGED_RECIPE_DETAIL.format(observation=observation.pk, url=observation.staged_recipe_url.strip())
    if verdict == FEEDSTOCK_UNKNOWN and observation.state == REFINED_SENTINEL:
        return UNESTABLISHED_ABSENCE_DETAIL.format(observation=observation.pk)
    if verdict == FEEDSTOCK_UNKNOWN and observation.state == OutcomeState.OK:
        if observed is not None and observed > threshold:
            return STALE_OBSERVATION_DETAIL.format(
                observation=observation.pk,
                observed=observed,
                threshold=threshold,
            )
        return UNDATABLE_ACTIVITY_DETAIL.format(observation=observation.pk, threshold=threshold)
    if verdict == PRESENT_AND_MAINTAINED and age is not None and age < _NO_TIME:
        return FUTURE_ACTIVITY_DETAIL.format(observation=observation.pk, ahead=-age, threshold=threshold)
    return ""


class FeedstockPresencePass(PolicyPass):
    """`CPM-FR-40` as a `PolicyPass`: read one surface, apply a versioned threshold, write one row.

    Four declarations and two methods. The derived table is
    `PackageFeedstockPresence` and the one rollup column is
    `feedstock_presence_status`; this class never writes the rollup and never
    gates, because `CPM-AD-4`'s gate is applied by the one rollup writer on the
    way in and a pass is not asked (`CPM-AD-21`).

    **It is the first pass to override `prepare`**, and the reason is the shape
    of its one run-wide fault: a policy version the reviewed parameter file does
    not record is every package's failure, not one package's. See that method.
    """

    name: ClassVar[str] = POLICY_NAME
    derived_model: ClassVar[type[models.Model] | None] = PackageFeedstockPresence
    contributes: ClassVar[tuple[str, ...]] = (ROLLUP_COLUMN,)

    #: The parameter set this run applies, established once by `prepare`.
    #:
    #: An instance attribute rather than a lookup per package, and the difference
    #: is what `prepare` exists for. `core/policy_run.py` builds one instance per
    #: run, so the value cannot leak between runs -- and a pass instance that had
    #: somehow reached `evaluate` without a run is the one thing this default
    #: makes visible rather than silent.
    parameters: PolicyParameters | None = None

    def prepare(self, *, policy_run: PolicyRun, evidence_cutoff: datetime) -> None:
        """Establish the parameter set this run applies, once, before any package.

        **The version is a run-wide fact and its failure is a run-wide failure.**
        A policy version `policies/data/policy-parameters.toml` does not record
        has no threshold for any package, so looking it up per package would
        discover one condition ten thousand times: ten thousand tracebacks, ten
        thousand failed rows, a failed count the size of the inventory, and a
        file read per package. Established here, the refusal costs one read and
        one ledger row -- the run finalizes `failed`, nothing is written, and the
        message names the file and the version.

        `CPM-AD-23`'s per-package containment is unaffected and is not being
        argued around: what it contains is a fault that *can* differ between
        packages, and this one cannot.

        Args:
            policy_run: The run about to execute. Its `policy_version` is what
                the parameter set is looked up by, which is what makes the
                threshold versioned rather than merely external.
            evidence_cutoff: Accepted and unused. The parameter set is chosen by
                version alone; the cut-off is what evidence is read as of, and
                `evaluate` is where that matters.

        Raises:
            PolicyParameterError: When the run's policy version records no
                parameters, or the reviewed file cannot be read.

        """
        self.parameters = parameters_for(policy_run.policy_version)

    def evaluate(
        self,
        package: Package,
        *,
        policy_run: PolicyRun,
        evidence_cutoff: datetime,
    ) -> Mapping[str, str]:
        """Judge one package's feedstock and write its derived row.

        Called once per package, inside that package's transaction
        (`CPM-AD-23`), so a refusal here rolls this package's row back and leaves
        every other package's committed.

        **The threshold is read off `prepare`'s answer rather than looked up.**
        Every row this run writes was therefore written under one rule set, which
        is what `CPM-AD-8`'s "one version means one rule set" asks for, and what
        lets `inactivity_threshold` be NOT NULL: a run whose version records no
        parameters never reaches this method at all.

        **The activity instant and its age are copied only from a determinate
        observation.** `collectors/models.py` already forbids a feedstock fact on
        a row that is not `ok`, so copying unconditionally would be correct today
        -- and would be correct because of a constraint in another application
        that this module would then silently depend on. Guarding here means the
        row this pass writes is well-formed on its own terms, and the two
        constraints agree rather than one standing in for the other.

        Args:
            package: The package to judge. Its `confidence` is read off the
                instance the run is holding and recorded on the row -- recorded,
                never applied: `CPM-AD-4`'s gate is `core/rollup.py`'s.
            policy_run: The run this evaluation belongs to, written onto the row
                where together with the package it is `CPM-AD-21`'s key.
            evidence_cutoff: The instant to read evidence as of, and the instant
                both ages are measured against. Nothing here reads the current
                time.

        Returns:
            The one rollup column this pass declared, carrying the verdict.
            Ungated: `core/rollup.py` applies `CPM-AD-4` to it, and an `unmapped`
            package's rollup column reads `unknown` however this pass judged it.

        Raises:
            FeedstockPolicyError: When the evidence row carries a state outside
                the outcome vocabulary, when either instant it carries is naive,
                or when the cut-off is naive -- and when this pass was never
                prepared, which is a caller that bypassed the orchestration.

        """
        threshold = self._threshold()
        observation = observed_feedstock(package_id=package.pk, cutoff=evidence_cutoff)
        # `is not None` on its own line rather than folded into `determinate`,
        # so the guarded copies below narrow the type as well as the branch --
        # the two say the same thing and only one of them is checkable.
        determinate = observation if observation is not None and observation.state == OutcomeState.OK else None
        age = activity_age(determinate, cutoff=evidence_cutoff)
        observed = observation_age(observation, cutoff=evidence_cutoff)
        verdict = presence_verdict(observation, age=age, observed=observed, threshold=threshold)
        # Written with one keyword per column rather than through a `defaults`
        # mapping, on exactly the terms `policies/currency.py` states:
        # `tests/unit/django_apps/test_derived_status_writability_audit.py` reads
        # keyword names, so the mapping form would take this write out of that
        # audit's view -- which is the `**kwargs` dodge that module names. The
        # visible form plus a recorded exemption is the honest shape.
        PackageFeedstockPresence.objects.create(
            package=package,
            policy_run=policy_run,
            presence_status=verdict,
            inactivity_threshold=threshold,
            last_recipe_activity_at=None if determinate is None else determinate.last_recipe_activity_at,
            activity_age=age,
            confidence=package.confidence,
            feedstock_snapshot=observation,
            detail=presence_detail(observation, verdict, age=age, observed=observed, threshold=threshold),
        )
        return {ROLLUP_COLUMN: verdict}

    def _threshold(self) -> timedelta:
        """Return the inactivity threshold `prepare` established for this run.

        Returns:
            The interval this run's policy version records.

        Raises:
            FeedstockPolicyError: When `prepare` was never called. Unreachable
                through `core/policy_run.py`, which prepares every pass before
                the package loop -- and stated rather than assumed, because the
                alternative is an `AttributeError` on `None` deep inside a
                comparison, in a caller that constructed the pass by hand and
                would learn nothing from it.

        """
        if self.parameters is None:
            message = (
                f"policy pass {POLICY_NAME!r} was asked to evaluate a package before its parameter set was "
                f"established. core/policy_run.py calls prepare() once per run, before the package loop; a "
                f"caller driving this pass directly has to do the same."
            )
            raise FeedstockPolicyError(message)
        return self.parameters.feedstock_inactivity
