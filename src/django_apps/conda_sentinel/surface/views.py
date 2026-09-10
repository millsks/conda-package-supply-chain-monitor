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

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar
from typing import Final
from typing import cast

from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import TemplateView

from conda_sentinel.core.clock import SystemClock
from conda_sentinel.core.jobs import JobState
from conda_sentinel.core.jobs import request_job
from conda_sentinel.core.models import BackgroundJob
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.pagination import DEFAULT_PAGE_SIZE
from conda_sentinel.core.permissions import PRODUCT_ROLES
from conda_sentinel.core.permissions import RoleRequiredMixin
from conda_sentinel.surface.coverage import collector_health
from conda_sentinel.surface.coverage import coverage_of
from conda_sentinel.surface.detail import identity_of
from conda_sentinel.surface.detail import recent_runs
from conda_sentinel.surface.detail import traces_for
from conda_sentinel.surface.detail import work_on
from conda_sentinel.surface.exports import EXPORT_JOB_KIND
from conda_sentinel.surface.exports import REPORT_SLUG_PARAMETER
from conda_sentinel.surface.exports import export_csv
from conda_sentinel.surface.exports import over_the_cap
from conda_sentinel.surface.filters import FACETS
from conda_sentinel.surface.filters import applied_filters
from conda_sentinel.surface.health import COLUMNS
from conda_sentinel.surface.health import health_rows
from conda_sentinel.surface.listing import DEFAULT_ORDERING
from conda_sentinel.surface.listing import ORDERINGS
from conda_sentinel.surface.listing import SORT_PARAM
from conda_sentinel.surface.listing import health_queryset
from conda_sentinel.surface.listing import ordering_key
from conda_sentinel.surface.queues import queue_items
from conda_sentinel.surface.queues import queue_rows
from conda_sentinel.surface.reports import REPORTS
from conda_sentinel.surface.reports import REPORTS_BY_SLUG
from conda_sentinel.surface.reports import report_page
from conda_sentinel.surface.theming import THEME_COOKIE
from conda_sentinel.surface.theming import THEME_COOKIE_MAX_AGE
from conda_sentinel.surface.theming import THEME_PARAMETER
from conda_sentinel.surface.theming import THEMES
from conda_sentinel.workflow.states import QUEUE_OWNERS

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from conda_sentinel.workflow.models import WorkflowItem
    from django_service.users.models import User

#: Re-exported: both names were declared here before `surface/listing.py` existed,
#: and templates and tests reach for them at this path. The definitions live beside
#: the queryset that uses them, which is what stops the API growing a second one.
__all__ = ["DEFAULT_ORDERING", "EXPORT_TOO_LARGE", "ORDERINGS", "SORT_PARAM", "PackageHealthView"]

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
#: What a synchronous export of a too-large report is told.
#:
#: **A refusal rather than a truncated file**, which is what `CPM-APP-S06` shipped
#: and `CPM-APP-S08` replaces. Handing somebody a partial CSV silently is the worst
#: of the three available behaviours; saying so in a header was better and still left
#: a file in a downloads folder that reads as complete the moment the header is
#: forgotten. So this path refuses over the cap and names the one that does not.
EXPORT_TOO_LARGE: Final[str] = (
    "this report has more rows than the {cap} an export will produce inside a request (CPM-AD-9). Ask for it "
    "from the report page instead: the work leaves the request and the page says when the file is ready."
)

#: How long a status page waits before asking again.
#:
#: Long enough that a page left open is not a request every second, short enough that
#: somebody watching a small export does not conclude it is stuck. It stops entirely
#: once the job is terminal, which is the part that matters.
JOB_REFRESH_SECONDS: Final[int] = 5

#: What a download of a job with no file is told.
NO_ARTIFACT: Final[str] = "no finished export of yours has the id {pk!r}."

#: Where a prepared export's provenance travels, since a job has no response headers.
#:
#: The job row carries it, and the download view puts it back on the response -- so
#: a file produced in the background is as datable as one produced in a request,
#: which is `CPM-APP-S06`'s AC 2 surviving the trip through a queue.
PROVENANCE_PARAMETER: Final[str] = "provenance"


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
            Whatever `surface/listing.py` builds. Not built here: `CPM-APP-S07` adds
            an API over the same rows, and a queryset written twice is `CPM-AD-24`'s
            named failure -- the two surfaces agree on the day they are written and
            disagree on the first day somebody changes one.

        """
        return health_queryset(dict(self.request.GET.lists()), sort=self.request.GET.get(SORT_PARAM, ""))

    def ordering_key(self) -> str:
        """Return which ordering this request asked for.

        Returns:
            The requested key when it names one, otherwise `DEFAULT_ORDERING`.

        """
        return ordering_key(self.request.GET.get(SORT_PARAM, ""))

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
        context.update(
            page=report_page(report, limit=REPORT_PAGE_ROWS),
            reports=REPORTS,
            # Which export control the page offers. Asked here rather than left to
            # the template to infer from a row count, because the page shows at most
            # `REPORT_PAGE_ROWS` and a template counting what it can see would offer
            # the synchronous download for a report of four thousand rows.
            too_large_to_export_here=over_the_cap(report),
            export_cap=settings.CPM_SYNC_EXPORT_MAX_ROWS,
        )
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

    **The row cap is the boundary of a request, not a limit on the product.**
    `CPM-AD-9` sends work beyond it out of the request, so this view does two things
    and only two: under the cap it streams the file, and over the cap it refuses and
    names the path that does not. It never truncates -- `CPM-APP-S06` shipped a
    truncated file with a header saying so, and `CPM-APP-S08` replaces it, because a
    CSV in somebody's downloads folder outlives the response header that qualified
    it.

    **`POST` is the asynchronous path**, and the split of methods is the point: a
    `GET` that enqueued work would make a bookmark, a prefetch or a link checker
    create jobs. Nothing here decides the cap for itself; `surface/exports.py` owns
    the one comparison, which is AC 2.
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

        if over_the_cap(report):
            # Refused rather than truncated, and 409 rather than 400: the request is
            # well-formed and the report is simply larger than a request will
            # produce. The message names the path that will.
            return HttpResponse(
                EXPORT_TOO_LARGE.format(cap=settings.CPM_SYNC_EXPORT_MAX_ROWS),
                content_type="text/plain",
                status=HTTPStatus.CONFLICT,
            )

        content, _rows, provenance = export_csv(report, limit=settings.CPM_SYNC_EXPORT_MAX_ROWS)
        response = HttpResponse(content, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{report.slug}.csv"'
        # The provenance travels with the file, not only on the page it came from:
        # a CSV in somebody's downloads folder next week has to be datable, and a
        # spreadsheet is where a number outlives the context it was true in.
        response[PROVENANCE_HEADER] = provenance
        return response

    def post(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Hand the export off and point at it.

        `CPM-AD-9`'s AC 1: the work is enqueued and the request returns an
        in-progress state. The in-progress state here is a redirect to the job's own
        page, which is what makes the boundary something a person can cross and then
        look back across -- a 202 with a body would leave a reader on a page that
        never changes.

        Args:
            request: The request.
            *args: Django's positional URL arguments.
            **kwargs: Django's keyword URL arguments, carrying the slug.

        Returns:
            A redirect to the job page.

        Raises:
            Http404: When the URL names no declared report.

        """
        report = REPORTS_BY_SLUG.get(str(kwargs.get("slug", "")))
        if report is None:
            raise Http404(UNKNOWN_REPORT.format(slug=kwargs.get("slug"), known=sorted(REPORTS_BY_SLUG)))

        job = request_job(
            kind=EXPORT_JOB_KIND,
            parameters={REPORT_SLUG_PARAMETER: report.slug},
            requested_by=cast("User", request.user),
            clock=SystemClock(),
        )
        # 303, so a refresh of the job page does not re-post the form and enqueue a
        # second export -- the ordinary post/redirect/get, and the ordinary reason.
        return redirect("conda_sentinel:export-job", pk=job.pk)


class ExportJobView(RoleRequiredMixin, DetailView):  # type: ignore[type-arg]
    """Where a request points after handing an export off.

    `CPM-AD-9`'s AC 1 says the request returns an in-progress state; this is the
    state, as a page somebody can keep open. It is the half of the boundary that is
    easy to leave out and the half that makes it usable -- work that left a request
    and cannot be looked at again has not been handed off, it has been dropped.

    **Scoped to the person who asked.** A job is somebody's request, and a shared
    list of everybody's downloads is not something anybody asked for. Scoping is by
    queryset rather than by a check in the view, so a job that is not yours is a 404
    and not a 403 -- which is the honest answer: you cannot be refused something
    whose existence is not yours to know.

    **It refreshes itself while the job is running and stops when it is not.** A page
    that polls for ever is a page somebody leaves open on a second monitor and a
    request every few seconds for a week.
    """

    required_roles: ClassVar[frozenset[str]] = frozenset(PRODUCT_ROLES)
    model = BackgroundJob
    template_name = "conda_sentinel/export_job.html"
    context_object_name = "job"

    def get_queryset(self) -> QuerySet[BackgroundJob]:
        """Return the jobs this reader may look at.

        Returns:
            Their own. See the class docstring for why this is a queryset rather
            than a check.

        """
        # Narrowed rather than checked: `RoleRequiredMixin` has already sent an
        # anonymous visitor to the sign-in page, so by here there is a user.
        return BackgroundJob.objects.filter(requested_by=cast("User", self.request.user))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Return the job and how long the page should wait before asking again.

        Args:
            **kwargs: Django's context, carrying the job.

        Returns:
            The context.

        """
        context = super().get_context_data(**kwargs)
        job: BackgroundJob = context["job"]
        context.update(refresh_seconds=JOB_REFRESH_SECONDS if job.in_progress() else None)
        return context


class ExportJobDownloadView(RoleRequiredMixin, View):
    """The file a finished export produced.

    Separate from the job page rather than a mode of it, because a download and a
    status page want different responses to the same question -- and because a
    `Content-Disposition` on a page somebody is refreshing would download the file
    on every poll.

    **The provenance goes back on the response.** A job has no response headers to
    carry it, so the row does, and this puts it back -- which is what keeps a file
    produced in the background exactly as datable as one produced in a request.
    """

    required_roles: ClassVar[frozenset[str]] = frozenset(PRODUCT_ROLES)

    def get(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Return the artifact.

        Args:
            request: The request.
            *args: Django's positional URL arguments.
            **kwargs: Django's keyword URL arguments, carrying the job's id.

        Returns:
            The CSV.

        Raises:
            Http404: When the job is not this reader's, or has not finished. A 404
                for an unfinished job rather than a redirect: there is no file, and
                answering with the page would let a script that follows redirects
                save an HTML document as a `.csv`.

        """
        job = BackgroundJob.objects.filter(
            pk=int(kwargs["pk"]),
            requested_by=cast("User", request.user),
        ).first()
        if job is None or job.state != JobState.SUCCEEDED.value:
            raise Http404(NO_ARTIFACT.format(pk=kwargs["pk"]))

        response = HttpResponse(job.artifact, content_type="text/csv")
        slug = job.parameters.get(REPORT_SLUG_PARAMETER, "report")
        response["Content-Disposition"] = f'attachment; filename="{slug}.csv"'
        response[PROVENANCE_HEADER] = job.parameters.get(PROVENANCE_PARAMETER, "")
        return response


class ThemeView(View):
    """Record which of the three themes a reader wants, and send them back.

    **Not role-gated, and it is the one surface in this product that is not.**
    `CPM-AD-13` scopes access to *evidence*, and a theme is not evidence -- it is a
    property of the screen somebody is looking at. Requiring a role here would buy
    nothing (a reader with no role cannot reach a page carrying the control anyway)
    and would cost something later: `CPM-APP-S12` brings the sign-in and error pages
    into this product's shell, and the control goes with them. A reader meets this
    product on the sign-in page, before they hold any role at all, and a control that
    was visible and inert there would be worse than no control.

    **`POST` only.** A `GET` that set a cookie would let a prefetch, a link checker or
    a shared URL change somebody's preference, and the last of those is the one that
    actually happens: a reader sends a colleague a link to a screen and changes their
    theme.

    **The redirect target is validated.** `next` comes from the form on whatever page
    the reader was on, and a value from a request is a value an attacker can supply --
    `url_has_allowed_host_and_scheme` is what keeps this from being an open redirect
    somebody can hang a phishing page off.
    """

    def post(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Store the choice and return the reader to where they were.

        Args:
            request: The request, carrying the chosen theme and where to go back to.
            *args: Django's positional URL arguments.
            **kwargs: Django's keyword URL arguments.

        Returns:
            A redirect to the page the control was on, carrying the cookie.

        """
        chosen = request.POST.get(THEME_PARAMETER, "")
        target = request.POST.get(REDIRECT_FIELD_NAME, "")
        # A relative URL from this host, or the product's home. Not the referer and
        # not the raw field: both are attacker-supplied, and the check is what makes
        # the difference between a redirect and an open one.
        allowed = url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
        response = redirect(target if allowed else "conda_sentinel:home")

        if chosen in THEMES:
            response.set_cookie(
                THEME_COOKIE,
                chosen,
                max_age=THEME_COOKIE_MAX_AGE,
                samesite="Lax",
                secure=request.is_secure(),
                # Readable by script, and deliberately: `httponly` protects a
                # credential from being read, and this is a colour. Marking it
                # would say something untrue about what it holds, and would stop a
                # later story doing anything client-side with it.
                httponly=False,
            )
        else:
            # A value outside the three is discarded rather than stored (AC 5). The
            # reader still goes back where they were: a preference that will not take
            # is not worth an error page, and the control cannot produce one -- only a
            # hand-made request can.
            response.delete_cookie(THEME_COOKIE)
        return response
