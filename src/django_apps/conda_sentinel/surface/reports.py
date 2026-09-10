"""`CPM-FR-26`'s six recurring reports, declared once so none can forget its provenance.

A report is a question somebody asks on a schedule: what is exploited today, what has
drifted this week, what nobody has identified. The six `CPM-APP-S06` names are
different questions over the same rollup, and the temptation is to write six views.

**They are one mechanism and a roster, and the reason is AC 2.** Every report has to
state the evidence cut-off and the policy version it was produced from -- and a rule
that six views each have to remember is a rule five of them keep. Here the freshness
comes from the projection rather than from the report, so a seventh report added
tomorrow states its provenance because it cannot do otherwise.

**A report is a queryset and a column list, and nothing else.** No report computes a
verdict: `CPM-AD-10` gives that to the policy engine, and a report that derived
anything would be a second opinion nobody could reconcile with the health view. What
a report chooses is *which rows* and *which columns* -- a filter and a projection.

**Statuses are emitted verbatim, and blank is reserved.** `CPM-AD-24` says a derived
status appears as its `OutcomeState` value on every surface, and names the failure it
prevents: "the export rendering `unknown` as a blank cell -- destroying the five
states in the one artifact that leaves the system". An export is the artifact that
leaves, so this is where that rule matters most. `EMPTY` exists to be asserted
against rather than used.

**The export is the same rows as the page.** Not a second query with its own filters
-- that is how an export comes to disagree with the screen somebody exported it from,
which is the disagreement nobody notices until it is in a board pack.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Final
from typing import cast

from django.db.models import Q

from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.surface.search import name_condition

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from django.db.models import QuerySet


__all__ = [
    "EMPTY",
    "REPORTS",
    "REPORTS_BY_SLUG",
    "Report",
    "ReportColumn",
    "ReportPage",
    "report_page",
    "report_rows",
    "report_values",
]

#: What a *field with no value* renders as, and what a status never renders as.
#:
#: `CPM-AD-24` reserves blank for the first and forbids it for the second. Declared so
#: `tests/unit/django_apps/test_report_projection.py` can assert against it rather than
#: against a literal written twice.
EMPTY: Final[str] = ""

#: How often each report is meant to be read, as the schedule `CPM-FR-26` names.
#:
#: Carried on the report rather than in a scheduler, because it is the *reader's*
#: cadence and not the system's: nothing here fires on a timer. `CPM-AD-20` puts
#: cadences in `django_celery_beat` for collection and policy runs; a report is
#: produced when somebody opens it, and this is what the page tells them it is for.
DAILY: Final[str] = "daily"
WEEKLY: Final[str] = "weekly"
ON_DEMAND: Final[str] = "on demand"


@dataclass(frozen=True, slots=True)
class ReportColumn:
    """One column of a report: a heading, and where the value comes from.

    `source` is an ORM field path read with `values_list`, never a callable. A
    callable column would let a report compute something, and a report that computed
    anything would be a second opinion about a package that nobody could reconcile
    with the health view.
    """

    heading: str
    source: str

    #: Whether the value is a derived status. Statuses are emitted verbatim and are
    #: never blank; everything else may legitimately have no value. The flag is what
    #: lets one assertion cover every report rather than one per column.
    is_status: bool = False


#: The columns every report carries, whatever else it shows.
#:
#: `CPM-APP-S06`'s AC 3: an export "carries the same freshness and confidence columns
#: the application shows". Prepended to every report's own columns by construction --
#: a report cannot omit them, which is the point. `CPM-AD-11` requires the same of
#: every view, so this is that rule reaching the artifact that leaves the system.
COMMON_COLUMNS: Final[tuple[ReportColumn, ...]] = (
    ReportColumn(heading="Package", source="package__canonical_name"),
    ReportColumn(heading="Confidence", source="confidence", is_status=True),
    ReportColumn(heading="Evidence cut-off", source="evidence_cutoff"),
    ReportColumn(heading="Computed at", source="computed_at"),
)


@dataclass(frozen=True, slots=True)
class Report:
    """One recurring question, as a filter and a set of columns."""

    #: What the URL calls it.
    slug: str

    #: What the heading says.
    title: str

    #: What question it answers, in a sentence a reader who did not commission it
    #: can act on. Shown on the page: a report nobody can interpret is a report
    #: somebody exports and misreads.
    asks: str

    #: How often it is meant to be read.
    cadence: str

    #: Which rollup rows it selects.
    condition: Q

    #: Its own columns, after the common ones.
    columns: tuple[ReportColumn, ...] = ()

    def all_columns(self) -> tuple[ReportColumn, ...]:
        """Return every column, common ones first.

        Returns:
            The freshness and confidence columns, then the report's own. Composed
            here rather than written into each report, so none can omit them.

        """
        return COMMON_COLUMNS + self.columns


#: The six reports `CPM-APP-S06` names.
#:
#: Six, and the list is the acceptance criterion restated as data -- so a report
#: dropped in a refactor fails a test that names the requirement rather than one that
#: counts entries.
REPORTS: Final[tuple[Report, ...]] = (
    Report(
        slug="kev",
        title="Known-exploited vulnerabilities",
        asks="Which packages carry an advisory the CISA catalogue lists as exploited?",
        cadence=DAILY,
        condition=Q(package__vulnerability_policy_findings__kev_membership="listed"),
        columns=(
            ReportColumn(
                heading="Vulnerability",
                source="package__vulnerability_policy_findings__vulnerability_status",
                is_status=True,
            ),
            ReportColumn(heading="Risk", source="package__vulnerability_policy_findings__risk_level"),
        ),
    ),
    Report(
        slug="feedstock-lag",
        title="Feedstock lag and gaps",
        asks="Which packages are behind upstream, or have a feedstock nobody is maintaining?",
        cadence=WEEKLY,
        condition=Q(currency_status="behind") | ~Q(feedstock_presence_status="present_and_maintained"),
        columns=(
            ReportColumn(heading="Currency", source="currency_status", is_status=True),
            ReportColumn(heading="Feedstock", source="feedstock_presence_status", is_status=True),
        ),
    ),
    Report(
        slug="python-314",
        title="Python 3.14 readiness",
        asks="What is not ready for Python 3.14, and did a build say so or did metadata?",
        cadence=ON_DEMAND,
        condition=Q(
            package__python_readiness_policy_findings__readiness__in=("verified_not_ready", "inferred_not_ready"),
        ),
        columns=(
            ReportColumn(
                heading="Readiness",
                source="package__python_readiness_policy_findings__readiness",
                is_status=True,
            ),
            ReportColumn(heading="Evidence", source="package__python_readiness_policy_findings__evidence_type"),
        ),
    ),
    Report(
        slug="licence-exceptions",
        title="Licence exceptions pending",
        asks="Which licences the policy did not clear are waiting on somebody?",
        cadence=WEEKLY,
        condition=Q(package__license_policy_findings__license_outcome__in=("manual_review", "restricted", "forbidden")),
        columns=(
            ReportColumn(
                heading="Licence",
                source="package__license_policy_findings__license_outcome",
                is_status=True,
            ),
            ReportColumn(heading="Rule", source="package__license_policy_findings__matched_rule"),
        ),
    ),
    Report(
        slug="unmapped-identities",
        title="Unmapped identities",
        asks="Which packages has nothing identified, so every verdict on them is unknown?",
        cadence=DAILY,
        condition=Q(confidence=IdentityConfidence.UNMAPPED),
        columns=(ReportColumn(heading="Resolved from", source="package__identity_source"),),
    ),
    Report(
        slug="stale-evidence",
        title="Stale evidence and collector failures",
        asks="What has the monitor been unable to see, and where did a lookup break?",
        cadence=DAILY,
        # The four sentinels across the rollup's own columns. A report of what the
        # product *could not establish*, which is the one `CPM-FR-5` makes
        # load-bearing and the one a happy dashboard never shows.
        condition=(
            Q(currency_status__in=(OutcomeState.UNKNOWN.value, OutcomeState.ERROR.value))
            | Q(feedstock_presence_status__in=(OutcomeState.UNKNOWN.value, OutcomeState.ERROR.value))
        ),
        columns=(
            ReportColumn(heading="Currency", source="currency_status", is_status=True),
            ReportColumn(heading="Feedstock", source="feedstock_presence_status", is_status=True),
        ),
    ),
)

#: The roster by slug, for a URL.
REPORTS_BY_SLUG: Final[dict[str, Report]] = {report.slug: report for report in REPORTS}


@dataclass(frozen=True, slots=True)
class ReportPage:
    """One report, produced: its rows and the provenance they came from."""

    report: Report
    columns: tuple[ReportColumn, ...]

    #: One tuple per row, in `columns` order, already rendered to strings.
    rows: tuple[tuple[str, ...], ...]

    #: AC 2. Read off the rows rather than passed in, so a report cannot be produced
    #: without them -- and `None` where there are no rows at all, which is honest: a
    #: report of nothing was produced from nothing.
    evidence_cutoff: datetime | None
    policy_versions: tuple[str, ...]


def report_values(report: Report, *, search: str = "") -> QuerySet[PackageHealth, tuple[object, ...]]:
    """Return one report's raw rows, ordered and unbounded, as a values queryset.

    Split out from `report_page` by `CPM-APP-S07`, which paginates a report over
    HTTP: a paginator needs something it can count and slice, and it must be the
    *same* thing the page and the export read. A second queryset built for the API
    is `CPM-AD-24`'s named failure with an extra step.

    `CPM-APP-S18` adds the name search **here** for that same reason. The export view
    states the principle plainly -- "the same rows as the page, from the same
    projection with a different bound, not a second query with its own filters" -- so
    a search the page honoured and the export did not would be exactly the
    disagreement that module was written to prevent, in the one artifact that leaves
    the system.

    Args:
        report: Which report.
        search: A package-name fragment, already normalised by `search_term`. An
            empty one narrows nothing.

    Returns:
        One tuple per row -- the report's columns in order, then the row's version
        map. Not evaluated: the caller slices it.

    """
    columns = report.all_columns()
    return (
        PackageHealth.objects.filter(report.condition & name_condition(search, field="package__canonical_name"))
        .order_by("package__canonical_name", "pk")
        .values_list(*(column.source for column in columns), "policy_versions")
        .distinct()
    )


def report_rows(report: Report, values: Sequence[tuple[object, ...]]) -> ReportPage:
    """Project settled rows into the report the surfaces render.

    Args:
        report: Which report.
        values: The rows, already sliced by a paginator or a cap. A sequence rather
            than a queryset because it must not be re-evaluated -- the shape
            `health_rows` takes, and for the same reason.

    Returns:
        The rendered rows and the provenance *of these rows*. Per page rather than
        per report, which is the honest read when a caller is walking one: the
        envelope says what the rows in this response were produced from, and every
        row carries its own stamps besides.

    """
    columns = report.all_columns()
    return ReportPage(
        report=report,
        columns=columns,
        rows=tuple(
            tuple(_rendered(value, column) for value, column in zip(row[:-1], columns, strict=True)) for row in values
        ),
        evidence_cutoff=_cutoff(values, columns),
        policy_versions=_versions(values),
    )


def report_page(report: Report, *, limit: int | None = None, search: str = "") -> ReportPage:
    """Produce one report.

    Args:
        report: Which report.
        limit: How many rows to take, for a page. `None` for all of them, which is
            what an export wants -- and what `CPM-APP-S08` bounds with a row cap.
        search: A package-name fragment, already normalised. An empty one narrows
            nothing.

    Returns:
        The rows and the provenance.

    """
    values = report_values(report, search=search)
    return report_rows(report, list(values[:limit] if limit is not None else values))


def _rendered(value: object, column: ReportColumn) -> str:
    """Return one cell as the report emits it.

    Args:
        value: What the database returned.
        column: Which column it is.

    Returns:
        The status verbatim for a status column -- `CPM-AD-24` -- and the value's
        string form otherwise. `None` becomes blank, which is what blank is *for*: a
        field with no value. A status is never `None`, because every status column
        this product declares is non-null with a default.

    """
    if value is None:
        return EMPTY
    return str(value)


def _cutoff(values: Sequence[tuple[object, ...]], columns: Sequence[ReportColumn]) -> datetime | None:
    """Return the evidence cut-off the rows were produced from.

    Args:
        values: The raw rows.
        columns: The columns, to find the cut-off's position.

    Returns:
        The newest cut-off among the rows, or `None` for an empty report -- which is
        honest rather than a gap: a report of nothing was produced from nothing.

    """
    position = next(index for index, column in enumerate(columns) if column.source == "evidence_cutoff")
    instants = [cast("datetime", row[position]) for row in values if row[position] is not None]
    return max(instants) if instants else None


def _versions(values: Sequence[tuple[object, ...]]) -> tuple[str, ...]:
    """Return the policy versions the rows were produced at.

    Args:
        values: The raw rows, whose last element is each row's version map.

    Returns:
        Every distinct `domain@version`, sorted. **Every** one rather than a single
        version, because `CPM-AD-11` stamps a *map* per domain and a replay can leave
        rows from more than one run -- a report claiming one version over rows
        produced at two would be stating something false about its own provenance.

    """
    seen = {
        f"{domain}@{version}" for row in values for domain, version in cast("dict[str, str]", row[-1] or {}).items()
    }
    return tuple(sorted(seen))
