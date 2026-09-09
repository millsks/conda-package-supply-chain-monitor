"""What the monitor cannot see, counted rather than implied.

**This module has no story and no requirement behind it.** It was built because the
UX mockups carry a coverage screen (`S8`) and a reviewer home (`S2`) that the epic's
eight stories never commission, and because those two screens answer the question
`CPM-FR-5` makes load-bearing: *what is this product not in a position to tell you?*
Every acceptance criterion it satisfies was written for it rather than derived from
the PRD, and
`_bmad-output/implementation-artifacts/stories/cpm-app-x01-coverage-and-home.md`
records which. Treat the numbers here as a proposal.

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

from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.registry import registered_collectors
from conda_sentinel.core.runs import RunState
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.surface.health import COLUMNS

if TYPE_CHECKING:
    from datetime import datetime
    from datetime import timedelta

__all__ = [
    "INCONCLUSIVE",
    "ROLLUP_STATUS_COLUMNS",
    "CollectorHealth",
    "Coverage",
    "LedgerSummary",
    "StatusGap",
    "collector_health",
    "coverage_of",
]

#: The statuses that are not verdicts.
#:
#: `CPM-FR-5`'s four unhappy answers. Counting them together is deliberate -- an
#: operator reading this screen wants one number for "how much of the estate has the
#: product formed no opinion about", and the per-package screen is where the four are
#: told apart. `OutcomeState.OK` is absent because it is a verdict, and so is every
#: adverse verdict: `behind` and `advisories_matched` are things the product *knows*.
INCONCLUSIVE: Final[frozenset[str]] = frozenset(
    {
        OutcomeState.UNKNOWN.value,
        OutcomeState.NOT_FOUND.value,
        OutcomeState.NOT_APPLICABLE.value,
        OutcomeState.ERROR.value,
    },
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

    #: How many packages carry a sentinel in it.
    inconclusive: int

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
        return 0.0 if not self.total else round(100 * self.inconclusive / self.total, 1)


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
        **{column: Count("pk", filter=Q(**{f"{column}__in": INCONCLUSIVE})) for column in ROLLUP_STATUS_COLUMNS},
    )
    return Coverage(
        inventory=inventory,
        identity=identity,
        gaps=tuple(
            StatusGap(label=label, inconclusive=counted[column] or 0, total=inventory)
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
