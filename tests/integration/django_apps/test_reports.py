"""`CPM-APP-S06`: six recurring reports, each stating what it was produced from.

The criteria look like three and are really two rules applied six times, which is
why the roster is data and the cases below are mostly parameterized over it: **every**
report states its provenance, and **every** report emits a status verbatim. A rule
that six views each have to keep is a rule five of them keep, and the sixth is the
one somebody exports into a board pack.

**The export cases are the ones that matter most.** `CPM-AD-24` names this exact
artifact when it says what the rule is for: "the export rendering `unknown` as a
blank cell -- destroying the five states in the one artifact that leaves the system".
A CSV outlives the screen it came from, so a blank where a status should be is a
number somebody quotes six months later with no way to tell it was a gap.

**AC 1 is checked against the requirement, not against the roster's length.** Six
slugs written out, so a report dropped in a refactor fails a case that names what was
asked for rather than one that counts entries and still passes at five.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.identity.models import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.surface.reports import EMPTY
from conda_sentinel.surface.reports import REPORTS
from conda_sentinel.surface.reports import REPORTS_BY_SLUG
from conda_sentinel.surface.views import PROVENANCE_HEADER
from tests.factories import UserFactory

if TYPE_CHECKING:
    from django.http import HttpResponse

pytestmark = pytest.mark.integration

NOW: Final[datetime] = datetime(2026, 9, 4, 6, 12, tzinfo=UTC)
A_POLICY_VERSION: Final[str] = "cpm-app-s06-fixture-policy"

#: AC 1, restated as data. Written out rather than read from `REPORTS`, because this
#: is the *claim*: these six were asked for, and a case reading the roster would pass
#: at five.
REQUIRED_REPORTS: Final[frozenset[str]] = frozenset(
    {"kev", "feedstock-lag", "python-314", "licence-exceptions", "unmapped-identities", "stale-evidence"},
)

#: A header row plus one capped data row, which is what an export truncated at one
#: row looks like. Named so the assertion reads as the claim rather than as a number.
HEADER_AND_ONE_ROW: Final[int] = 2


def a_run() -> PolicyRun:
    """Return one finished policy run.

    Returns:
        The saved run.

    """
    return PolicyRun.objects.create(
        policy_version=A_POLICY_VERSION,
        started_at=NOW,
        finished_at=NOW,
        evidence_cutoff=NOW,
    )


def a_rollup_row(
    run: PolicyRun, name: str, *, confidence: str = IdentityConfidence.VERIFIED, **columns: str
) -> PackageHealth:
    """Return one package with a rollup row.

    Args:
        run: The run.
        name: The package's canonical name.
        confidence: Its identity confidence.
        **columns: Contributed columns to override.

    Returns:
        The saved rollup row.

    """
    package = Package.objects.create(
        canonical_name=name,
        resolved_at=NOW,
        confidence=confidence,
        identity_source="pypi",
        associator_key=f"pypi:{name}",
    )
    return PackageHealth.objects.create(
        package=package,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=NOW,
        confidence=confidence,
        policy_versions={"currency": A_POLICY_VERSION},
        **columns,
    )


def a_reader() -> APIClient:
    """Return a client signed in as somebody who may read a report.

    Returns:
        An authenticated client.

    """
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=settings.ROLE_CONTRACT.leadership))
    client = APIClient()
    client.force_login(user)
    return client


def report_url(slug: str) -> str:
    """Return a report's URL.

    Args:
        slug: The report.

    Returns:
        The path.

    """
    return reverse("conda_sentinel:report", kwargs={"slug": slug})


def export_url(slug: str) -> str:
    """Return a report's export URL.

    Args:
        slug: The report.

    Returns:
        The path.

    """
    return reverse("conda_sentinel:report-export", kwargs={"slug": slug})


def exported(response: HttpResponse) -> list[list[str]]:
    """Return an export parsed back out of CSV.

    Parsed rather than string-matched, because what the criterion is about is the
    *cell* -- and a blank cell and a missing column look identical in a raw line.

    Args:
        response: The export response.

    Returns:
        Every row, header first.

    """
    return list(csv.reader(io.StringIO(response.content.decode())))


# ---------------------------------------------------------------------------
# AC 1: the six reports exist and are readable.
# ---------------------------------------------------------------------------


def test_every_report_the_criterion_names_exists() -> None:
    """AC 1, checked against the requirement rather than against the roster's length."""
    missing = REQUIRED_REPORTS - set(REPORTS_BY_SLUG)

    assert missing == set(), f"the story names reports this product does not have: {sorted(missing)}"


@pytest.mark.django_db
@pytest.mark.parametrize("report", REPORTS, ids=lambda report: report.slug)
def test_every_report_renders(report: object) -> None:
    """Each of the six over real rows, because a report whose query does not resolve
    is a 500 and not a missing feature.

    Two of these were written with guessed reverse-accessor names and raised
    `FieldError` at request time; a roster is only as good as the paths in it.

    Args:
        report: The report under test.

    """
    run = a_run()
    a_rollup_row(run, "aiohttp")

    assert a_reader().get(report_url(report.slug)).status_code == status.HTTP_200_OK  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_a_url_naming_no_report_is_a_404() -> None:
    """And the message names the reports that exist, for whoever mistyped one."""
    assert a_reader().get(report_url("no-such-report")).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_a_report_selects_only_the_rows_it_asks_about() -> None:
    """A filter that matched everything would satisfy every other case here.

    The unmapped-identities report is the clearest one to check: exactly the packages
    nothing has identified, and not the ones that are fine.
    """
    run = a_run()
    a_rollup_row(run, "identified")
    a_rollup_row(run, "unidentified", confidence=IdentityConfidence.UNMAPPED)

    page = a_reader().get(report_url("unmapped-identities")).context["page"]

    assert [row[0] for row in page.rows] == ["unidentified"]


# ---------------------------------------------------------------------------
# AC 2: every report states what it was produced from.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("report", REPORTS, ids=lambda report: report.slug)
def test_every_report_carries_the_freshness_and_confidence_columns(report: object) -> None:
    """AC 3's first half, and the reason the common columns are composed rather than
    written into each report: a report cannot omit them.

    Args:
        report: The report under test.

    """
    run = a_run()
    a_rollup_row(run, "aiohttp")

    page = a_reader().get(report_url(report.slug)).context["page"]  # type: ignore[attr-defined]
    headings = [column.heading for column in page.columns]

    assert headings[:4] == ["Package", "Confidence", "Evidence cut-off", "Computed at"]


@pytest.mark.django_db
def test_a_report_states_the_cut_off_and_versions_it_was_produced_from() -> None:
    """AC 2. Read off the rows by the projection rather than passed in by the view.

    A report that took its provenance from its caller could be handed the wrong one;
    reading it from the rows means it describes the rows it actually contains.
    """
    run = a_run()
    a_rollup_row(run, "unidentified", confidence=IdentityConfidence.UNMAPPED)

    page = a_reader().get(report_url("unmapped-identities")).context["page"]

    assert page.evidence_cutoff == NOW
    assert page.policy_versions == (f"currency@{A_POLICY_VERSION}",)


@pytest.mark.django_db
def test_a_report_over_rows_from_two_runs_names_both_versions() -> None:
    """`CPM-AD-11` stamps a version *map* per row, and a replay leaves rows from two runs.

    A report claiming one version over rows produced at two would be stating
    something false about its own provenance -- and the reader most likely to check
    is the compliance reviewer the whole product exists for.
    """
    first, second = a_run(), a_run()
    a_rollup_row(first, "from-the-first", confidence=IdentityConfidence.UNMAPPED)
    row = a_rollup_row(second, "from-the-second", confidence=IdentityConfidence.UNMAPPED)
    PackageHealth.objects.filter(pk=row.pk).update(policy_versions={"currency": "a-different-version"})

    page = a_reader().get(report_url("unmapped-identities")).context["page"]

    assert page.policy_versions == ("currency@a-different-version", f"currency@{A_POLICY_VERSION}")


@pytest.mark.django_db
def test_an_empty_report_says_it_was_produced_from_nothing() -> None:
    """Rather than showing a stale cut-off, or a blank where provenance should be.

    An empty report with a confident-looking cut-off reads as "nothing is wrong as of
    this morning", which is a claim it is in no position to make.
    """
    a_run()

    response = a_reader().get(report_url("unmapped-identities"))

    assert response.context["page"].evidence_cutoff is None
    assert "produced from nothing" in response.content.decode()


# ---------------------------------------------------------------------------
# AC 3: the export, which is the artifact that leaves.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_export_carries_the_same_columns_as_the_page() -> None:
    """Not a second query with its own idea of what to show.

    An export that disagreed with the screen it came from is the disagreement nobody
    notices until it is in a board pack.
    """
    run = a_run()
    a_rollup_row(run, "unidentified", confidence=IdentityConfidence.UNMAPPED)
    client = a_reader()

    page = client.get(report_url("unmapped-identities")).context["page"]
    rows = exported(client.get(export_url("unmapped-identities")))

    assert rows[0] == [column.heading for column in page.columns]
    assert rows[1:] == [list(row) for row in page.rows]


@pytest.mark.django_db
def test_a_status_is_written_verbatim_in_the_export() -> None:
    """`CPM-AD-24`'s named failure: `unknown` as a blank cell in the one artifact that leaves.

    The status here is `unknown` on purpose -- it is the value most likely to be
    "tidied" into an empty cell by anything that treats a sentinel as a null.
    """
    run = a_run()
    a_rollup_row(run, "nothing-known", currency_status=OutcomeState.UNKNOWN.value)

    rows = exported(a_reader().get(export_url("stale-evidence")))
    headings, body = rows[0], rows[1:]
    currency = headings.index("Currency")

    assert body[0][currency] == OutcomeState.UNKNOWN.value
    assert body[0][currency] != EMPTY


@pytest.mark.django_db
def test_no_status_column_is_ever_blank_in_an_export() -> None:
    """The rule stated over every status column of every report at once.

    A per-report case would leave the seventh report free to blank a status the day
    somebody adds it.
    """
    run = a_run()
    a_rollup_row(run, "nothing-known", currency_status=OutcomeState.UNKNOWN.value)
    client = a_reader()

    for report in REPORTS:
        rows = exported(client.get(export_url(report.slug)))
        headings, body = rows[0], rows[1:]
        for row in body:
            for column, value in zip(report.all_columns(), row, strict=True):
                assert not (column.is_status and value == EMPTY), f"{report.slug}: {column.heading} was blank"
        assert headings


@pytest.mark.django_db
def test_the_export_carries_its_provenance_with_the_file() -> None:
    """A CSV in somebody's downloads folder next week has to be datable.

    In a header rather than a row: a row is data a spreadsheet sorts into the middle
    of the report.
    """
    run = a_run()
    a_rollup_row(run, "unidentified", confidence=IdentityConfidence.UNMAPPED)

    response = a_reader().get(export_url("unmapped-identities"))

    assert A_POLICY_VERSION in response[PROVENANCE_HEADER]
    assert "evidence_cutoff=" in response[PROVENANCE_HEADER]


@pytest.mark.django_db
def test_an_export_beyond_the_cap_is_refused_rather_than_truncated(settings: object) -> None:
    """`CPM-AD-9`, and this case changed with `CPM-APP-S08` rather than being deleted.

    This story shipped a *truncated* file with a header saying so, which was the best
    of what was available before the work could leave the request. It is still the
    wrong artifact: a CSV in somebody's downloads folder outlives the response header
    that qualified it, and reads as complete the moment the header is forgotten.

    So the synchronous path now refuses, and `tests/integration/django_apps/
    test_background_exports.py` covers what happens instead. The case is kept here,
    pointed at the new behaviour, because what it is really asserting is unchanged:
    nobody is handed a partial report without being told.

    Args:
        settings: pytest-django's settings fixture, which restores the cap.

    """
    settings.CPM_SYNC_EXPORT_MAX_ROWS = 1  # type: ignore[attr-defined]
    run = a_run()
    a_rollup_row(run, "first", confidence=IdentityConfidence.UNMAPPED)
    a_rollup_row(run, "second", confidence=IdentityConfidence.UNMAPPED)

    response = a_reader().get(export_url("unmapped-identities"))

    assert response.status_code == HTTPStatus.CONFLICT
    assert "report page" in response.content.decode()


@pytest.mark.django_db
def test_an_export_under_the_cap_is_still_produced_in_the_request() -> None:
    """The other direction, or the refusal above would be a broken export.

    `CPM-AD-9` bounds what a request will *do*; it does not send every export away.
    A product where the small case also required a round trip through a worker would
    have taken the cost of the boundary everywhere to get its benefit somewhere.
    """
    run = a_run()
    a_rollup_row(run, "unidentified", confidence=IdentityConfidence.UNMAPPED)

    response = a_reader().get(export_url("unmapped-identities"))

    assert response.status_code == HTTPStatus.OK
    assert len(exported(response)) == HEADER_AND_ONE_ROW


@pytest.mark.django_db
def test_the_export_is_offered_as_a_file() -> None:
    """A CSV rendered in the browser is one nobody can hand to anybody."""
    run = a_run()
    a_rollup_row(run, "unidentified", confidence=IdentityConfidence.UNMAPPED)

    response = a_reader().get(export_url("unmapped-identities"))

    assert response["Content-Type"] == "text/csv"
    assert "attachment" in response["Content-Disposition"]


# ---------------------------------------------------------------------------
# A report is still a surface.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("url", [report_url, export_url], ids=["page", "export"])
def test_a_reader_holding_no_role_is_refused(url: object) -> None:
    """`CPM-AD-13`. The export especially: it is the copy that leaves the building.

    Args:
        url: Which URL builder to use.

    """
    client = APIClient()
    client.force_login(UserFactory.create())

    assert client.get(url("kev")).status_code == status.HTTP_403_FORBIDDEN  # type: ignore[operator]


@pytest.mark.django_db
def test_every_role_may_read_a_report() -> None:
    """`CPM-AD-13` grants read access to evidence to all three, and a report is evidence."""
    run = a_run()
    a_rollup_row(run, "aiohttp")

    for role in (LEADERSHIP, "security_reviewer", "packaging_engineer"):
        user = UserFactory.create()
        user.groups.add(Group.objects.get(name=getattr(settings.ROLE_CONTRACT, role)))
        client = APIClient()
        client.force_login(user)

        assert client.get(report_url("kev")).status_code == status.HTTP_200_OK
