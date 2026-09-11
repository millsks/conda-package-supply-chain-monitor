"""What the monitor cannot see, counted rather than implied.

**No functional requirement commissions the screens this serves.** `CPM-APP-S09`
and `CPM-APP-S10` were added to the epic after it was written, to close design gaps
`G-8` and `G-9`, and their acceptance criteria were drafted by the implementing agent
rather than derived from the PRD -- each story file leads with that caveat. What they
answer is the question `CPM-FR-5` makes load-bearing at inventory scale: *what is this
product not in a position to tell you?* Whether that deserves an FR of its own is
recorded as an open question under the epic. Treat the metric definitions here as a
proposal.

**The counts are of absence, and that is the whole design.** A coverage screen
built the obvious way -- percentage healthy, percentage current -- reports a product
that is working. What an operator needs is the opposite: how many packages nothing
has looked at, which collector has not completed inside the window it declared, and
how many statuses are sentinels rather than verdicts. `CPM-FR-5` forbids presenting a
package as clean without evidence; this is where the *aggregate* of that is visible,
and where "we are watching ten thousand packages" is separated from "we know
something about ten thousand packages".

**The collector roster is the registry's, never a list written here.** `core/registry.py`
holds every adopted collector and each declares its own `freshness_target`. A screen
with a hand-written roster would report a clean bill of health for a collector
somebody forgot to add to it -- the failure mode of every monitoring dashboard ever
written, and the one this screen exists to be the opposite of.

**The freshness judgement is made against the collector's own declared target and
the run ledger, not against evidence.** `CPM-AD-2` exempts the ledger from
append-only precisely so a run killed mid-call leaves a row saying `running`, and
`CPM-AD-11`'s rollup carries no notion of which collector last succeeded. So "is this
collector keeping up" is a question about runs, and "is this package's evidence
stale" is a different question that the passes already answer per domain.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Final

from django.db.models import Count
from django.db.models import Max
from django.db.models import Q
from django.utils.translation import ngettext

from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.registry import registered_collectors
from conda_sentinel.core.runs import RunState
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.surface.health import COLUMNS
from conda_sentinel.surface.labels import collector_status_label

if TYPE_CHECKING:
    from datetime import datetime
    from datetime import timedelta

__all__ = [
    "ANSWERED_NEGATIVELY",
    "NO_VERDICT",
    "ROLLUP_STATUS_COLUMNS",
    "CollectorHealth",
    "Coverage",
    "LedgerSummary",
    "StatusGap",
    "collector_health",
    "coverage_of",
]

#: The statuses that mean the product could not see.
#:
#: **Two of `CPM-FR-5`'s four sentinels, not all four**, and the distinction is the
#: one this whole screen turns on. `unknown` is nobody looked -- or `CPM-AD-4`'s gate
#: blocked it -- and `error` is the lookup broke. Both are absences of knowledge.
#:
#: `not_found` and `not_applicable` are *not* here, and an earlier version of this
#: module counted them, wrongly. "We looked and there is no feedstock" and "this
#: native library has no Python metadata" are both things the product **does** know,
#: and counting them as gaps inflates the number with answers -- so it would rise as
#: the product learned more, which is the same defect as counting adverse verdicts
#: and is harder to notice. They are counted separately below.
#:
#: `OutcomeState.OK` is absent for the obvious reason, and so is every adverse
#: verdict: `behind` and `advisories_matched` are conclusions.
NO_VERDICT: Final[frozenset[str]] = frozenset({OutcomeState.UNKNOWN.value, OutcomeState.ERROR.value})

#: The statuses that are answers, and negative ones.
#:
#: Shown beside the gap rather than folded into it: an operator reading "1,204
#: packages have no feedstock" is reading a finding, and one reading "217 packages
#: nothing has looked at" is reading a hole in the monitoring. Two different things
#: to do about them, so two numbers.
ANSWERED_NEGATIVELY: Final[frozenset[str]] = frozenset(
    {OutcomeState.NOT_FOUND.value, OutcomeState.NOT_APPLICABLE.value},
)

#: The rollup columns this screen counts gaps in, by the label the health view uses.
#:
#: Only the four the rollup carries: the other statuses live in per-domain derived
#: tables and counting them would mean a query per domain over the whole inventory,
#: on a screen an operator refreshes. `CPM-APP-S06`'s recurring reports are where a
#: full-inventory scan belongs; this is a dashboard.
ROLLUP_STATUS_COLUMNS: Final[dict[str, str]] = {
    "currency_status": "Currency",
    "feedstock_presence_status": "Feedstock",
    "priority_status": "Priority",
    "work_type_status": "Work type",
}


@dataclass(frozen=True, slots=True)
class StatusGap:
    """How much of the estate one status has no verdict for."""

    #: What the column is called on the health view, so the two screens agree.
    label: str

    #: How many packages the product could not see -- `unknown` or `error`.
    no_verdict: int

    #: How many it answered negatively -- `not_found` or `not_applicable`. A finding
    #: rather than a hole, and shown apart from one.
    answered_negatively: int

    #: How many packages there are at all, so the number above has a denominator.
    #: Carried rather than computed by the template: a percentage with no
    #: denominator beside it is the shape a dashboard lies in.
    total: int

    @property
    def share(self) -> float:
        """Return the share of the inventory with no verdict, as a percentage.

        Returns:
            Zero for an empty inventory rather than a division error -- a product
            watching nothing has no gaps, which is true and is the honest answer.

        """
        return 0.0 if not self.total else round(100 * self.no_verdict / self.total, 1)


@dataclass(frozen=True, slots=True)
class CollectorHealth:
    """Whether one collector is keeping up with the cadence it declared."""

    #: The collector's own name, from the registry.
    name: str

    #: What it declared as the age at which its evidence stops being trustworthy.
    #: `None` for a collector that declares none, which is a real state and is shown
    #: as such rather than as "fresh".
    freshness_target: timedelta | None

    #: When it last finished a run, whatever the outcome.
    last_finished_at: datetime | None

    #: How that run ended.
    last_status: str

    #: How many runs it has recorded, and how many of those failed. A collector
    #: succeeding once an hour and failing once an hour is not healthy, and a screen
    #: showing only the last outcome would call it either.
    runs: int
    failures: int

    #: Whether the last completed run is inside the declared target.
    #:
    #: `False` for a collector that has never completed one, which is the state a
    #: dashboard most often renders as blank -- and blank, next to nine green rows,
    #: reads as fine.
    inside_target: bool

    @property
    def freshness_label(self) -> str:
        """Return the freshness target the way somebody would say it.

        A `timedelta` printed by a template is `str(timedelta)`, which is
        `2 days, 0:00:00` -- a repr, in a column whose other rows say `14 days` and
        `30 days` with the same trailing zeros. Every target this product declares is
        a whole number of days, so the hours are noise on every row.

        Returns:
            The number of days, or the raw value where a target is not whole days --
            which no registered collector declares, and which should still render.

        """
        target = self.freshness_target
        if target is None:
            return "—"
        if target.seconds == 0 and target.microseconds == 0:
            return ngettext("%(count)d day", "%(count)d days", target.days) % {"count": target.days}
        return str(target)

    @property
    def status_label(self) -> str:
        """Return what this collector's health is called where somebody reads it.

        Beside `last_status` rather than instead of it, for the reason
        `test_the_navigation_gets_the_value_and_the_label` gives: the template needs
        the *value* to pick a tone and the *label* to print, and a template deriving
        either from the other is what produced the defect this fixes.

        `never_run` was reaching the screen spelled the way this product spells
        values, on a row whose neighbouring column already said `never run` in
        English. Same row, same fact, two spellings.

        Returns:
            The label, or the value itself for a status `surface/labels.py` does not
            declare.

        """
        return collector_status_label(self.last_status)

    @property
    def has_ever_run(self) -> bool:
        """Report whether this collector has completed a run at all.

        Returns:
            True when there is a finished run to judge.

        """
        return self.last_finished_at is not None


@dataclass(frozen=True, slots=True)
class LedgerSummary:
    """What the run ledger holds about one collector.

    A named shape rather than the aggregate's dict, because the three fields are
    read four times between here and the template and a mapping of `object` makes
    every one of those a cast.
    """

    last_finished_at: datetime | None
    runs: int
    failures: int


@dataclass(frozen=True, slots=True)
class Coverage:
    """What the monitor can and cannot see, across the whole inventory."""

    #: How many packages are being watched.
    inventory: int

    #: How many hold each identity confidence, keyed by value. `CPM-AD-4` gates
    #: every verdict on this, so it is the number that bounds every other number on
    #: the screen.
    identity: dict[str, int]

    #: One gap per rollup status column.
    gaps: tuple[StatusGap, ...]

    #: The freshest rollup stamps, so a reader can date everything above.
    computed_at: datetime | None
    evidence_cutoff: datetime | None

    @property
    def unmapped(self) -> int:
        """Return how many packages have no established identity.

        Returns:
            The count, which is also the size of `CPM-APP-S05`'s identity queue and
            the number of packages every other status on this screen is `unknown`
            for.

        """
        return self.identity.get(IdentityConfidence.UNMAPPED.value, 0)


def coverage_of() -> Coverage:
    """Return what the monitor can and cannot see.

    Returns:
        The counts, in a bounded number of queries: one grouping the inventory by
        confidence, one aggregating the rollup's sentinel counts across every status
        column at once, and one for the freshest stamps. Not a query per column --
        this is a screen an operator refreshes, and four scans of a ten-thousand-row
        table to answer four questions about the same rows is how a dashboard becomes
        the slowest page in a product.

    """
    identity = {
        row["confidence"]: row["count"] for row in Package.objects.values("confidence").annotate(count=Count("pk"))
    }
    inventory = sum(identity.values())

    counted = PackageHealth.objects.aggregate(
        computed_at=Max("computed_at"),
        evidence_cutoff=Max("evidence_cutoff"),
        **{
            f"{column}__{suffix}": Count("pk", filter=Q(**{f"{column}__in": values}))
            for column in ROLLUP_STATUS_COLUMNS
            for suffix, values in (("gap", NO_VERDICT), ("negative", ANSWERED_NEGATIVELY))
        },
    )
    return Coverage(
        inventory=inventory,
        identity=identity,
        gaps=tuple(
            StatusGap(
                label=label,
                no_verdict=counted[f"{column}__gap"] or 0,
                answered_negatively=counted[f"{column}__negative"] or 0,
                total=inventory,
            )
            for column, label in ROLLUP_STATUS_COLUMNS.items()
        ),
        computed_at=counted["computed_at"],
        evidence_cutoff=counted["evidence_cutoff"],
    )


def collector_health(*, now: datetime) -> tuple[CollectorHealth, ...]:
    """Return whether each adopted collector is keeping up with its declared cadence.

    Args:
        now: The instant to judge freshness against. Passed in rather than read here:
            `CPM-AD-26` puts every clock read behind the injected clock in `core`, and
            a module that called `timezone.now()` would be the exception that makes
            the rule unenforceable.

    Returns:
        One entry per **registered** collector, in registry order -- including any
        that has never run, which is the row a hand-written roster would omit and the
        one an operator most needs.

    """
    ledger = {
        row["collector"]: LedgerSummary(
            last_finished_at=row["last_finished_at"],
            runs=row["runs"],
            failures=row["failures"],
        )
        for row in CollectionRun.objects.values("collector").annotate(
            last_finished_at=Max("finished_at"),
            runs=Count("pk"),
            failures=Count("pk", filter=Q(status=RunState.FAILED)),
        )
    }
    return tuple(_health(collector, ledger.get(collector.name), now=now) for collector in registered_collectors())


def _health(collector: type, recorded: LedgerSummary | None, *, now: datetime) -> CollectorHealth:
    """Return one collector's health.

    Args:
        collector: The registered collector class, which declares its own target.
        recorded: What the run ledger holds for it, or `None` where it has never run.
        now: The instant to judge freshness against.

    Returns:
        The health row.

    """
    target = getattr(collector, "freshness_target", None)
    last_finished_at = recorded.last_finished_at if recorded else None
    return CollectorHealth(
        name=collector.name,  # type: ignore[attr-defined]
        freshness_target=target,
        last_finished_at=last_finished_at,
        # The status of the *last finished* run is a second query per collector, so
        # the aggregate carries the failure count instead: "9 runs, 2 failed" is what
        # an operator acts on, and a single last-outcome can be green on a collector
        # failing half its runs.
        last_status=_summarised(recorded),
        runs=recorded.runs if recorded else 0,
        failures=recorded.failures if recorded else 0,
        inside_target=(last_finished_at is not None and target is not None and (now - last_finished_at) <= target),
    )


def _summarised(recorded: LedgerSummary | None) -> str:
    """Return one word for how a collector is doing.

    Args:
        recorded: The ledger aggregate, or `None`.

    Returns:
        `never_run` where it has not, `failing` where any run failed, and `ok`
        otherwise. **`never_run` is deliberately not `unknown`**: `unknown` is an
        `OutcomeState` value and means a lookup that concluded nothing, while this is
        a collector that was never asked -- and `tests/unit/django_apps/test_tone.py`
        would have no tone for it either way, which is the second reason it is spelled
        apart.

    """
    if recorded is None:
        return "never_run"
    return "failing" if recorded.failures else "ok"


#: The health view's own column labels, so the coverage screen names statuses the
#: way the table does. Read rather than restated: a column renamed on one screen and
#: not the other is how an operator comes to think they are different things.
HEALTH_VIEW_LABELS: Final[frozenset[str]] = frozenset(column.label for column in COLUMNS)
