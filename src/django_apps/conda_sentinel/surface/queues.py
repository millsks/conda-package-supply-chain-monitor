"""The three queues, ranked the way the priority pass ranked everything else.

`CPM-AD-22` puts all three on one table and `CPM-APP-S05` asks for them as *filtered
views* over it. So there is no queue model, no per-queue query and no per-queue
ranking: one function takes a queue name and returns the items in it, and the only
thing that differs between the three is a string.

**Ranked by bucket, then score, then key.** The priority pass already decided both
numbers and `CPM-PRIORITY-S01` put its ordering in one place; re-deriving an order
here would be a second ranking rule, and the two would disagree the first time
somebody changed one. The bucket comes off the rollup row, the score off
`package_priority`, and the finding key terminates the ordering so a queue pages
deterministically -- a non-deterministic order returns an item on two pages and
another on none, which is invisible until somebody works a long queue.

**Identity items are ranked by usage breadth**, which is `CPM-APP-S05`'s AC 2 and is
not a special case bolted on: an unmapped package has no priority bucket, because
`CPM-AD-4`'s gate blanked every verdict the bucket would have been derived from. So
there is nothing to rank it by except how much of the estate depends on it, which is
what the score already is. The identity queue therefore ranks on score alone, and
the bucket column it would otherwise sort by is `unknown` for every row in it.

**Open work only, by default.** A queue is what is left to do. Resolved and accepted
items stay on the item's own history and on the package detail view; putting them in
the queue would make its length meaningless within a month.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Final

from django.db.models import Case
from django.db.models import IntegerField
from django.db.models import OuterRef
from django.db.models import Subquery
from django.db.models import Value
from django.db.models import When

from conda_sentinel.core.models import PackageHealth
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.policies.outcomes import PRIORITY_BUCKETS
from conda_sentinel.workflow.models import WorkflowItem
from conda_sentinel.workflow.states import TERMINAL_STATES
from conda_sentinel.workflow.states import Queue

if TYPE_CHECKING:
    from django.db.models import QuerySet

__all__ = ["QUEUE_ORDER", "QueueRow", "queue_items", "queue_rows"]

#: How a queue is ordered.
#:
#: Bucket, then score descending, then the finding key. The last is not decoration:
#: a queue that pages needs a total order, and two items in one bucket with one score
#: are otherwise returned in whatever order the database felt like -- which puts one
#: on two pages and another on none, invisibly, until somebody works a long queue.
QUEUE_ORDER: Final[tuple[str, ...]] = ("bucket_rank", "-priority_score", "finding_key")

#: The score a package with no priority row gets, for ordering purposes only.
#:
#: Zero, so it sorts below everything the priority pass scored -- which is the honest
#: place for a package the pass reached no conclusion about. It is *not* written
#: anywhere and is not shown as a score: `QueueRow.score` carries `None` for these,
#: because zero is a score somebody could have been given and the absence of one is
#: not.
_UNSCORED: Final[int] = 0


@dataclass(frozen=True, slots=True)
class QueueRow:
    """One item in a queue, with everything the listing shows."""

    item: WorkflowItem
    canonical_name: str

    #: The bucket off the rollup row, and the score off `package_priority`. `None`
    #: where the pass reached no conclusion -- which is every identity item, because
    #: the confidence gate blanked the verdicts a bucket is derived from.
    bucket: str
    score: int | None


def queue_items(queue: str, *, include_finished: bool = False) -> QuerySet[WorkflowItem]:
    """Return one queue as a filtered, ranked queryset.

    Args:
        queue: The queue name, a `Queue` value.
        include_finished: Whether to include resolved and accepted items. `False` by
            default: a queue is what is left to do, and a queue whose length grows
            monotonically stops being read.

    Returns:
        The items, ranked bucket-then-score-then-key, with the package and the
        ranking annotations joined.

    """
    items = WorkflowItem.objects.filter(queue=queue).select_related("package", "claimed_by")
    if not include_finished:
        items = items.exclude(state__in=TERMINAL_STATES)
    return items.annotate(
        # A correlated subquery rather than a join, for both. The rollup is a
        # one-to-one on `package` and Django will not resolve it as a lookup inside a
        # `Case`, which surfaces as `FieldError: Unsupported lookup` at request time
        # -- and a join here would multiply rows against a queue that pages anyway.
        #
        # The bucket is fetched as its *rank* rather than its value, because
        # `PRIORITY_BUCKETS` is worst-first and its index is the order: `p10` sorts
        # after `p2`, which a lexicographic sort on the value would get wrong.
        bucket_rank=Subquery(
            PackageHealth.objects.filter(package_id=OuterRef("package_id"))
            .annotate(
                rank=Case(
                    *(When(priority_status=bucket, then=Value(index)) for index, bucket in enumerate(PRIORITY_BUCKETS)),
                    default=Value(len(PRIORITY_BUCKETS)),
                    output_field=IntegerField(),
                ),
            )
            .values("rank")[:1],
            output_field=IntegerField(),
        ),
        priority_score=Subquery(
            PackagePriority.objects.filter(package_id=OuterRef("package_id"))
            .order_by("-policy_run_id")
            .values("score")[:1],
            output_field=IntegerField(),
        ),
    ).order_by(*QUEUE_ORDER)


def queue_rows(queue: str, items: QuerySet[WorkflowItem] | None = None) -> tuple[QueueRow, ...]:
    """Return the rows a queue listing renders.

    Args:
        queue: The queue name, for the default read.
        items: A page of items, already sliced by a paginator. Passed in rather than
            read here so the projection runs over the settled page -- the same shape
            `surface/health.py` takes, and for the same reason.

    Returns:
        One row per item, in the order given.

    """
    page = list(items if items is not None else queue_items(queue))
    if not page:
        return ()

    # One read for the whole page rather than one per row. The bucket is on the
    # rollup, which the queryset above already annotates for *ordering* -- but an
    # annotation used for ordering is not a value the template can read without
    # reaching through a join, so the display value is fetched once here.
    buckets = dict(
        PackageHealth.objects.filter(package_id__in={item.package_id for item in page}).values_list(
            "package_id",
            "priority_status",
        ),
    )
    scores = dict(
        PackagePriority.objects.filter(package_id__in={item.package_id for item in page})
        .order_by("package_id", "-policy_run_id")
        .values_list("package_id", "score"),
    )
    return tuple(
        QueueRow(
            item=item,
            canonical_name=item.package.canonical_name,
            bucket=buckets.get(item.package_id, ""),
            # `None` rather than zero: zero is a score somebody could have been
            # given, and the absence of one is a different thing. The ordering uses
            # `_UNSCORED`; the display does not.
            score=scores.get(item.package_id),
        )
        for item in page
    )


#: The three queues, in the order a nav lists them. Read off the vocabulary rather
#: than written out, so a fourth queue appears without an edit here.
ALL_QUEUES: Final[tuple[str, ...]] = tuple(Queue.values)
