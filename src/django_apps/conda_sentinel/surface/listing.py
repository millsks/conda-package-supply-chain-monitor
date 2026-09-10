"""The one health queryset, so the screen and the API cannot become two projections.

`CPM-AD-24` requires that "every read surface projects the same values", and names
the failure it prevents: a new derived status reaching the API but not the governed
view. The obvious way to build `CPM-APP-S07`'s API is to write a second queryset with
the same filters and the same annotations, and the two would agree on the day they
were written and drift on the first day somebody changed one.

So there is one, here, and both surfaces call it. `surface/views.py` re-exports
`ORDERINGS` and `SORT_PARAM` because they were declared there first and tests and
templates name them; the definitions live here now, beside the queryset that uses
them.

**Filtering and ordering are the whole of what a surface may choose.** Which rows,
and in what order. Everything else -- the statuses, the freshness, the evidence -- is
`health_rows()`'s, and a surface that wanted a different value for a package would
have to go through that.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from django.core.exceptions import BadRequest
from django.db.models import Case
from django.db.models import IntegerField
from django.db.models import OuterRef
from django.db.models import Subquery
from django.db.models import Value
from django.db.models import When

from conda_sentinel.core.models import PackageHealth
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.policies.outcomes import PRIORITY_BUCKETS
from conda_sentinel.surface.filters import UnknownFacetValueError
from conda_sentinel.surface.filters import applied_filters
from conda_sentinel.surface.filters import filter_condition

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from django.db.models import QuerySet

__all__ = ["DEFAULT_ORDERING", "ORDERINGS", "SORT_PARAM", "health_queryset", "ordering_key"]

#: The query-string parameter naming an ordering. The same spelling on both surfaces,
#: because a bookmark a reviewer sends an integrator should mean the same thing.
SORT_PARAM: Final[str] = "sort"

#: How the table may be ordered, and the first entry is the default.
#:
#: **By name first, and rank second, which is the opposite of what the mockup
#: shows.** The mockup's screenshot is of a reviewer who arrived from their queue and
#: has already chosen rank; a reader arriving at the URL with no opinion is usually
#: looking *up* a package rather than being handed one, and an unranked default is
#: also the cheap one -- `canonical_name` is uniquely indexed and rank is two
#: annotations. `?sort=rank` is one click and the applied-filters bar says which is
#: in force, so nothing is hidden.
#:
#: `package_id` terminates both orderings. `CPM-NFR-4`'s ten thousand rows are read a
#: page at a time, and a non-deterministic ordering means a row can appear on two
#: pages or on none -- the quietest paging bug there is, and one that only shows up
#: at a size nobody tests by hand.
ORDERINGS: Final[dict[str, tuple[str, ...]]] = {
    "name": ("package__canonical_name", "package_id"),
    "rank": ("bucket_rank", "-priority_score", "package_id"),
}

#: What an unrecognised `?sort=` falls back to. Silently, and unlike a bad facet
#: value: an ordering cannot make a result set wrong, only differently sorted, so
#: refusing a stale bookmark's sort key would cost a reader their page for nothing.
DEFAULT_ORDERING: Final[str] = next(iter(ORDERINGS))


def ordering_key(requested: str) -> str:
    """Return which ordering a request asked for.

    Args:
        requested: The raw `?sort=` value, or the empty string.

    Returns:
        The requested key when it names one, otherwise `DEFAULT_ORDERING`.

    """
    return requested if requested in ORDERINGS else DEFAULT_ORDERING


def health_queryset(params: Mapping[str, Sequence[str]], *, sort: str = "") -> QuerySet[PackageHealth]:
    """Return the rollup rows a filtered, ordered read of current health asks for.

    Args:
        params: The query string as a multi-value mapping -- `request.GET.lists()` on
            either surface. A mapping rather than a `QueryDict` so this module needs
            nothing from Django's request layer and both a Django view and a DRF one
            can call it with what they already hold.
        sort: The requested ordering key. Unrecognised values fall back rather than
            refusing; see `DEFAULT_ORDERING`.

    Returns:
        The filtered, ordered queryset. `select_related("package")` is the one join a
        list query needs -- the canonical name is on every row -- and everything else
        is deferred to `health_rows()`'s bounded reads against the settled page.

    Raises:
        BadRequest: When a filter value is outside its vocabulary. Rendered as a 400
            rather than silently returning the whole inventory under a URL that
            claims to be filtered -- on both surfaces, because an integrator reading
            an unfiltered ten thousand rows as a filtered result is the worse half of
            that failure.

    """
    try:
        condition = filter_condition(applied_filters(dict(params)))
    except UnknownFacetValueError as refusal:
        raise BadRequest(str(refusal)) from refusal

    return (
        PackageHealth.objects.select_related("package")
        .filter(condition)
        .annotate(
            # The priority pass's own order, reproduced rather than re-derived.
            # `PRIORITY_BUCKETS` is worst-first, so its index *is* the rank and a
            # bucket outside it -- the four sentinels, `unknown` among them -- sorts
            # after every real bucket rather than among them.
            bucket_rank=Case(
                *(When(priority_status=bucket, then=Value(rank)) for rank, bucket in enumerate(PRIORITY_BUCKETS)),
                default=Value(len(PRIORITY_BUCKETS)),
                output_field=IntegerField(),
            ),
            # The score lives on `package_priority` and not on the rollup, by
            # `CPM-PRIORITY-S01`'s argument that a contribution carries statuses and
            # not numbers. A correlated subquery is what reads it without a join that
            # would multiply rows and break the page count.
            priority_score=Subquery(
                PackagePriority.objects.filter(
                    package_id=OuterRef("package_id"),
                    policy_run_id=OuterRef("policy_run_id"),
                ).values("score")[:1],
                output_field=IntegerField(),
            ),
        )
        .order_by(*ORDERINGS[ordering_key(sort)])
    )
