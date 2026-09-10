"""`CPM-FR-23`'s screen: the whole estate, narrowed to what matters.

The most-read surface in the product, and the one `CPM-NFR-4` sizes at ten thousand
packages. It renders `package_health` -- `CPM-AD-11`'s one row per package -- joined
by `core/health.py` to the evidence behind every status, filtered by
`core/filters.py`, and paginated by the global bound `CPM-APP-S01` installed.

**It writes nothing, and the shape says so.** `CPM-AD-10` gives the application layer
no write path to a derived status, so this is a `ListView` over a queryset that is
never saved through, handing the template frozen dataclasses rather than model
instances.

**Freshness is on the page, not implied by it.** `CPM-AD-11` requires every view to
display `computed_at`, the run's cut-off and the per-domain version map, and
`CPM-APP-S02`'s AC 1 says the view "states when the underlying rollup was last
recomputed". A screen that showed statuses without them would be a screen a reader
could not date -- and after a replay (`CPM-PRIORITY-S03`) current health can
legitimately be a quarter old.

**A bad filter value is a 400, not a silent full inventory.** See
`core/filters.py` for the argument; the view's part is turning the refusal into a
status code rather than a traceback.

**Two orderings and no more.** By name, which is how a reader finds a package they
already have in mind, and by rank, which is how a reader finds the package they
should be looking at. Rank is the priority pass's own order -- bucket, then score
descending -- reproduced here as an annotation rather than re-derived, because a
second ranking rule is exactly what `CPM-PRIORITY-S01` put `RANKING_ORDER` in one
place to prevent.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar
from typing import Final

from django.conf import settings
from django.core.exceptions import BadRequest
from django.db.models import Case
from django.db.models import IntegerField
from django.db.models import OuterRef
from django.db.models import Subquery
from django.db.models import Value
from django.db.models import When
from django.http import Http404
from django.http import HttpResponse
from django.views import View
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import TemplateView

from conda_sentinel.core.clock import SystemClock
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.pagination import DEFAULT_PAGE_SIZE
from conda_sentinel.core.permissions import PRODUCT_ROLES
from conda_sentinel.core.permissions import RoleRequiredMixin
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.policies.outcomes import PRIORITY_BUCKETS
from conda_sentinel.surface.coverage import collector_health
from conda_sentinel.surface.coverage import coverage_of
from conda_sentinel.surface.detail import identity_of
from conda_sentinel.surface.detail import recent_runs
from conda_sentinel.surface.detail import traces_for
from conda_sentinel.surface.detail import work_on
from conda_sentinel.surface.filters import FACETS
from conda_sentinel.surface.filters import UnknownFacetValueError
from conda_sentinel.surface.filters import applied_filters
from conda_sentinel.surface.filters import filter_condition
from conda_sentinel.surface.health import COLUMNS
from conda_sentinel.surface.health import health_rows
from conda_sentinel.surface.queues import queue_items
from conda_sentinel.surface.queues import queue_rows
from conda_sentinel.surface.reports import REPORTS
from conda_sentinel.surface.reports import REPORTS_BY_SLUG
from conda_sentinel.surface.reports import report_page
from conda_sentinel.workflow.states import QUEUE_OWNERS

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from conda_sentinel.workflow.models import WorkflowItem

__all__ = ["ORDERINGS", "SORT_PARAM", "PackageHealthView"]

#: The query-string parameter naming an ordering.
SORT_PARAM: Final[str] = "sort"

#: What a URL naming no declared queue is told.
#:
#: A 404 rather than a refusal: a queue that does not exist is not one somebody lacks
#: a role for, and answering 403 would tell a reader a queue exists that does not.
UNKNOWN_QUEUE: Final[str] = "no queue is called {queue!r}. The queues are {known}."

#: What a URL naming no declared report is told, on the same terms.
UNKNOWN_REPORT: Final[str] = "no report is called {slug!r}. The reports are {known}."

#: How many rows a report *page* shows. The export is bounded separately, by
#: `CPM_SYNC_EXPORT_MAX_ROWS` -- a page is what somebody reads on a screen and an
#: export is what they take away, and one number for both would make one of them
#: wrong.
REPORT_PAGE_ROWS: Final[int] = 200

#: Where an export carries its own provenance.
#:
#: A header rather than a row in the file, because a row would be data a spreadsheet
#: sorts into the middle of the report. `CPM-APP-S06`'s AC 2 asks that a report state
#: its cut-off and version; for the artifact that *leaves*, that has to travel with
#: the file rather than live on the page it came from.
PROVENANCE_HEADER: Final[str] = "X-Conda-Sentinel-Provenance"
TRUNCATION_HEADER: Final[str] = "X-Conda-Sentinel-Truncated"
TRUNCATED: Final[str] = (
    "this export reached the {cap}-row cap and is incomplete; CPM-APP-S08 moves an export beyond the cap out "
    "of the request"
)

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


# `ListView` is generic to django-stubs and a plain class at runtime, so the
# parameter mypy wants is a `TypeError` when Python evaluates the base list. The
# annotation on `get_queryset` below is what actually carries the model.
class PackageHealthView(RoleRequiredMixin, ListView):  # type: ignore[type-arg]
    """Browse, filter and sort current package health across the inventory.

    Readable by all three roles: `CPM-AD-13` grants read access to evidence to each
    of them, and the UX contract puts role scoping below the navigation rather than
    on a shared read surface.
    """

    required_roles: ClassVar[frozenset[str]] = frozenset(PRODUCT_ROLES)
    model = PackageHealth
    template_name = "conda_sentinel/package_health.html"
    context_object_name = "rollup_rows"

    #: The same size the global DRF bound uses, imported rather than repeated.
    #:
    #: Django's paginator and DRF's are separate mechanisms reading separate
    #: settings, which is exactly how a product ends up with a bounded API and an
    #: unbounded screen. One number, one import, and
    #: `tests/unit/django_apps/test_pagination_audit.py` sweeps for a view that
    #: chose its own.
    paginate_by = DEFAULT_PAGE_SIZE

    def get_queryset(self) -> QuerySet[PackageHealth]:
        """Return the rollup rows this request asked for.

        Returns:
            The filtered, ordered queryset. `select_related("package")` is the one
            join the list query needs -- the canonical name is on every row -- and
            everything else is deferred to `core/health.py`'s bounded reads against
            the settled page.

        Raises:
            BadRequest: When a filter value is outside its vocabulary. Rendered as a
                400 rather than silently returning the whole inventory under a URL
                that claims to be filtered.

        """
        try:
            condition = filter_condition(applied_filters(dict(self.request.GET.lists())))
        except UnknownFacetValueError as refusal:
            raise BadRequest(str(refusal)) from refusal

        return (
            PackageHealth.objects.select_related("package")
            .filter(condition)
            .annotate(
                # The priority pass's own order, reproduced rather than re-derived.
                # `PRIORITY_BUCKETS` is worst-first, so its index *is* the rank and
                # a bucket outside it -- the four sentinels, `unknown` among them --
                # sorts after every real bucket rather than among them.
                bucket_rank=Case(
                    *(When(priority_status=bucket, then=Value(rank)) for rank, bucket in enumerate(PRIORITY_BUCKETS)),
                    default=Value(len(PRIORITY_BUCKETS)),
                    output_field=IntegerField(),
                ),
                # The score lives on `package_priority` and not on the rollup, by
                # `CPM-PRIORITY-S01`'s argument that a contribution carries statuses
                # and not numbers. A correlated subquery is what reads it without a
                # join that would multiply rows and break the page count.
                priority_score=Subquery(
                    PackagePriority.objects.filter(
                        package_id=OuterRef("package_id"),
                        policy_run_id=OuterRef("policy_run_id"),
                    ).values("score")[:1],
                    output_field=IntegerField(),
                ),
            )
            .order_by(*ORDERINGS[self.ordering_key()])
        )

    def ordering_key(self) -> str:
        """Return which ordering this request asked for.

        Returns:
            The requested key when it names one, otherwise `DEFAULT_ORDERING`.

        """
        requested = self.request.GET.get(SORT_PARAM, "")
        return requested if requested in ORDERINGS else DEFAULT_ORDERING

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Return what the template renders.

        Args:
            **kwargs: Django's context, carrying the page and the paginator.

        Returns:
            The context, with the projected rows, the facet roster with the current
            selection marked, and the freshness stamps `CPM-AD-11` requires on every
            view.

        """
        context = super().get_context_data(**kwargs)
        selected = applied_filters(dict(self.request.GET.lists()))
        rows = health_rows(list(context["page_obj"].object_list))
        context.update(
            columns=COLUMNS,
            rows=rows,
            facets=[
                {
                    "facet": facet,
                    "selected": frozenset(selected.get(facet.param, ())),
                }
                for facet in FACETS
            ],
            applied=selected,
            ordering=self.ordering_key(),
            orderings=tuple(ORDERINGS),
            # The freshest row's stamps, which is what "when was the rollup last
            # recomputed" means when a replay has left rows from more than one run.
            # Every row carries its own as well, so a mixed table is visible rather
            # than averaged away.
            freshest=max(rows, key=lambda row: row.computed_at, default=None),
        )
        return context


class PackageDetailView(RoleRequiredMixin, DetailView):  # type: ignore[type-arg]
    """`CPM-FR-24`: every status on one package, traced to the evidence behind it.

    The question a reviewer asks after the health view has told them *what*. So this
    is not a narrower table -- it is the reasoning: each status with the observations
    that produced it, the identity those observations were gathered under, and the
    collection runs that gathered them.

    **Keyed on the canonical name rather than the primary key**, because a URL a
    reviewer pastes into a ticket should say which package it is about. `CPM-FR-42`
    makes `canonical_name` unique and correctable, and the key stays the surrogate
    integer for exactly that reason -- so a corrected name changes this URL and
    breaks no foreign key, which is the right trade for a link.

    **Read at the rollup row's own run.** The package's health row names the
    `policy_run` every derived row is read at; reading at the latest run instead
    would pair a verdict with freshness stamps that are not its own, and the two
    screens would disagree about the same package.

    Readable by all three roles, on `CPM-AD-13`'s terms: read access to evidence is
    granted to each of them, and this screen is the evidence.
    """

    required_roles: ClassVar[frozenset[str]] = frozenset(PRODUCT_ROLES)
    model = PackageHealth
    template_name = "conda_sentinel/package_detail.html"
    context_object_name = "health"
    slug_field = "package__canonical_name"
    slug_url_kwarg = "canonical_name"

    def get_queryset(self) -> QuerySet[PackageHealth]:
        """Return the rollup rows a detail URL may name.

        Returns:
            Every rollup row, with its package joined. `CPM-AD-11` gives every
            inventory package a row *including unmapped ones*, so there is no package
            in the inventory this view cannot open -- which matters, because the
            unmapped ones are exactly what a reviewer working the identity queue
            arrives here to look at.

        """
        return PackageHealth.objects.select_related("package")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Return the statuses, the identity and the runs.

        Args:
            **kwargs: Django's context, carrying the rollup row.

        Returns:
            The context.

        """
        context = super().get_context_data(**kwargs)
        row: PackageHealth = context["health"]
        context.update(
            package=row.package,
            traces=traces_for(row),
            identity=identity_of(row.package),
            runs=recent_runs(row.package),
            work=work_on(row.package),
        )
        return context


class CoverageView(RoleRequiredMixin, TemplateView):
    """What the monitor cannot see, which is the question a coverage screen is for.

    **`CPM-APP-S09`, whose acceptance criteria were drafted by the implementing
    agent** rather than derived from the PRD -- the story was added to the epic after
    it was written, to close design gap `G-8`. See `surface/coverage.py`.

    The screen it deliberately is not is the one that reports a percentage healthy.
    `CPM-FR-5` forbids presenting a package as clean without evidence, and this is
    where the aggregate of that is visible: how many packages have no established
    identity, how many statuses are sentinels rather than verdicts, and which
    collector has not completed a run inside the window it declared.
    """

    required_roles: ClassVar[frozenset[str]] = frozenset(PRODUCT_ROLES)
    template_name = "conda_sentinel/coverage.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Return the coverage counts and the collector roster.

        Args:
            **kwargs: Django's context.

        Returns:
            The context.

        """
        context = super().get_context_data(**kwargs)
        # `CPM-AD-26`: the clock is injected, never read by the module that needs it.
        context.update(
            coverage=coverage_of(),
            collectors=collector_health(now=SystemClock().now()),
        )
        return context


class HomeView(RoleRequiredMixin, TemplateView):
    """Where a reader starts: how fresh the picture is, and what is missing from it.

    **`CPM-APP-S10`, on the same terms**, and what it can show is bounded by what
    exists: the mockups' `S2` leads with "top of my queue", and there is no queue --
    `CPM-AD-22`'s workflow application arrives with `CPM-APP-S04`. Building a
    placeholder queue would be inventing the product's central abstraction on a
    screen nobody asked for, so this shows the two things that *are* real: how
    current the rollup is, and the size of what the monitor cannot see.

    Everything on it is a link into a filtered health view rather than a number in a
    box. A dashboard whose counters do not lead anywhere is a dashboard people read
    once.
    """

    required_roles: ClassVar[frozenset[str]] = frozenset(PRODUCT_ROLES)
    template_name = "conda_sentinel/home.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Return the freshness stamps and the coverage counts.

        Args:
            **kwargs: Django's context.

        Returns:
            The context.

        """
        context = super().get_context_data(**kwargs)
        context.update(
            coverage=coverage_of(),
            collectors=collector_health(now=SystemClock().now()),
        )
        return context


class QueueView(RoleRequiredMixin, ListView):  # type: ignore[type-arg]
    """One of `CPM-AD-22`'s three queues, scoped to the role that owns it.

    **The role is read from the URL, not declared on the class**, and this is the one
    surface in the product where that is true. Every other names its roles as a class
    attribute because every other wants the same roles whoever opens it; a queue does
    not, because which role may read it is a property of the *queue*.
    `workflow/states.py`'s `QUEUE_OWNERS` is where that is declared, and
    `roles_required()` is the seam `RoleRequiredMixin` offers for it -- a method
    rather than a per-request assignment to a class attribute, which two requests
    could race on.

    It stays narrow: the answer comes from a closed table keyed on a URL segment, and
    a segment naming no queue yields *no* roles, so the refusal happens before
    anything else.

    **A queue that is not yours is refused, never rendered empty.** The UX contract
    is explicit -- "a queue that is not yours is refused, never rendered empty" -- and
    the difference matters: an empty queue says there is no work, and a reviewer who
    reads that goes away satisfied. `RoleRequiredMixin` logs the refusal with the
    acting user identity, which is `CPM-APP-S05`'s AC 3.
    """

    template_name = "conda_sentinel/queue.html"
    context_object_name = "items"
    paginate_by = DEFAULT_PAGE_SIZE

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        """Refuse a URL naming no queue before anything asks about roles.

        **Order matters and an earlier version had it backwards.** Checking the role
        first made the 404 below unreachable: an unknown queue owns no role, so
        everybody was refused -- including a reader who owns a real queue and
        mistyped its URL, who was then told a queue exists that does not.

        There is nothing for that ordering to protect. The nav lists all three queue
        names to every role (`CPM-AD-13`: scoping happens below the nav), so which
        queues exist is not a secret and 404 leaks nothing.

        Args:
            request: The request.
            *args: Django's positional URL arguments.
            **kwargs: Django's keyword URL arguments, carrying the queue.

        Returns:
            Whatever the view returns.

        Raises:
            Http404: When the URL names no declared queue.

        """
        queue = str(kwargs.get("queue", ""))
        if queue not in QUEUE_OWNERS:
            raise Http404(UNKNOWN_QUEUE.format(queue=queue, known=sorted(QUEUE_OWNERS)))
        return super().dispatch(request, *args, **kwargs)

    def roles_required(self) -> frozenset[str]:
        """Return the role that owns the queue this URL names.

        Returns:
            The owner's slot. `dispatch` has already refused a URL naming no queue,
            so the lookup below always finds one.

        """
        return frozenset({QUEUE_OWNERS[str(self.kwargs["queue"])]})

    def get_queryset(self) -> QuerySet[WorkflowItem]:
        """Return the queue named in the URL.

        Returns:
            The ranked, open items. `dispatch` has already refused an unknown queue.

        """
        return queue_items(str(self.kwargs["queue"]))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Return the rows and what the heading says.

        Args:
            **kwargs: Django's context, carrying the page.

        Returns:
            The context.

        """
        context = super().get_context_data(**kwargs)
        queue = str(self.kwargs["queue"])
        context.update(
            queue=queue,
            owner=QUEUE_OWNERS[queue],
            rows=queue_rows(queue, context["page_obj"].object_list),
        )
        return context


class ReportView(RoleRequiredMixin, TemplateView):
    """One of `CPM-FR-26`'s recurring reports.

    One view for six reports, because they are six *questions* over one rollup and
    six views would be six places to forget `CPM-APP-S06`'s AC 2. The provenance
    comes from `surface/reports.py`'s projection rather than from the report, so a
    seventh report states its cut-off and policy version because it cannot do
    otherwise.

    Readable by all three roles: a report is evidence, and `CPM-AD-13` grants read
    access to evidence to each of them.
    """

    required_roles: ClassVar[frozenset[str]] = frozenset(PRODUCT_ROLES)
    template_name = "conda_sentinel/report.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Return the report, its rows and its provenance.

        Args:
            **kwargs: Django's context, carrying the slug.

        Returns:
            The context.

        Raises:
            Http404: When the URL names no declared report. Checked here rather than
                in the URL pattern so the message can name the reports that exist.

        """
        context = super().get_context_data(**kwargs)
        report = REPORTS_BY_SLUG.get(str(kwargs.get("slug", "")))
        if report is None:
            raise Http404(UNKNOWN_REPORT.format(slug=kwargs.get("slug"), known=sorted(REPORTS_BY_SLUG)))
        context.update(page=report_page(report, limit=REPORT_PAGE_ROWS), reports=REPORTS)
        return context


class ReportExportView(RoleRequiredMixin, View):
    """The same report, as the artifact that leaves the system.

    **The same rows as the page**, from the same projection with a different bound --
    not a second query with its own filters, which is how an export comes to disagree
    with the screen somebody exported it from. That disagreement is the one nobody
    notices until it is in a board pack.

    **A status is written verbatim and blank is reserved.** `CPM-AD-24` names this
    exact artifact when it says what the rule prevents: "the export rendering
    `unknown` as a blank cell -- destroying the five states in the one artifact that
    leaves the system".

    **The row cap is `CPM-APP-S08`'s**, and this view honours the constant rather
    than choosing one. Beyond it the work leaves the request (`CPM-AD-9`); until that
    story lands, an export at the cap is truncated and the response says so in a
    header rather than silently handing somebody a partial file.
    """

    required_roles: ClassVar[frozenset[str]] = frozenset(PRODUCT_ROLES)

    def get(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Return the report as CSV.

        Args:
            request: The request.
            *args: Django's positional URL arguments.
            **kwargs: Django's keyword URL arguments, carrying the slug.

        Returns:
            The CSV.

        Raises:
            Http404: When the URL names no declared report.

        """
        report = REPORTS_BY_SLUG.get(str(kwargs.get("slug", "")))
        if report is None:
            raise Http404(UNKNOWN_REPORT.format(slug=kwargs.get("slug"), known=sorted(REPORTS_BY_SLUG)))

        page = report_page(report, limit=settings.CPM_SYNC_EXPORT_MAX_ROWS)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{report.slug}.csv"'
        # The provenance travels with the file, not only on the page it came from:
        # a CSV in somebody's downloads folder next week has to be datable, and a
        # spreadsheet is where a number outlives the context it was true in.
        response[PROVENANCE_HEADER] = (
            f"evidence_cutoff={page.evidence_cutoff or 'none'}; policy_versions={' '.join(page.policy_versions)}"
        )
        if len(page.rows) == settings.CPM_SYNC_EXPORT_MAX_ROWS:
            response[TRUNCATION_HEADER] = TRUNCATED.format(cap=settings.CPM_SYNC_EXPORT_MAX_ROWS)

        writer = csv.writer(response)
        writer.writerow([column.heading for column in page.columns])
        writer.writerows(page.rows)
        return response
