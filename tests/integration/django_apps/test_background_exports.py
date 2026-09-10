"""`CPM-APP-S08`: an export beyond the cap leaves the request and can be looked at.

The audit in `tests/unit/django_apps/test_request_boundary_audit.py` holds the rule --
nothing a request reaches may make an outbound call, run a collector or run a policy
pass. What is here is the one path the rule actually has work on today: an export
larger than `CPM_SYNC_EXPORT_MAX_ROWS`.

**The three cases that matter are the three states a reader can be left in.** In
progress, ready, and failed. The third is the one that gets left out, and leaving it
out is what makes a status page say "running" for ever about work that broke -- which
is `CPM-FR-5`'s five-states problem arriving somewhere new.

**The cap is moved rather than the fixture being large.** Seeding five thousand
packages to cross the default would make this module the slowest in the suite and
would assert nothing extra: what is under test is the comparison, and a cap of one
tests it exactly as well as a cap of five thousand.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from celery import current_app
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from kombu.exceptions import OperationalError
from rest_framework.test import APIClient

from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.jobs import JobState
from conda_sentinel.core.jobs import finish_job
from conda_sentinel.core.jobs import job_runner_registrations
from conda_sentinel.core.jobs import request_job
from conda_sentinel.core.models import BackgroundJob
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.queues import EXPORT_JOB_TASK_NAME
from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER
from conda_sentinel.core.tasks import run_job
from conda_sentinel.identity.models import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.surface.exports import EXPORT_JOB_KIND
from conda_sentinel.surface.exports import REPORT_SLUG_PARAMETER
from conda_sentinel.surface.exports import over_the_cap
from conda_sentinel.surface.reports import REPORTS_BY_SLUG
from tests.factories import UserFactory

if TYPE_CHECKING:
    from django_service.users.models import User

pytestmark = pytest.mark.integration

NOW: Final[datetime] = datetime(2026, 9, 8, 11, 15, tzinfo=UTC)
A_POLICY_VERSION: Final[str] = "cpm-app-s08-fixture-policy"

#: The report these cases export. Every unmapped package is in it, which makes a
#: fixture of two rows a report of two rows without seeding any evidence.
A_REPORT: Final[str] = "unmapped-identities"

#: A cap of one, so two rows cross it. See the module docstring.
A_TINY_CAP: Final[int] = 1

#: How many rows the fixture seeds, and therefore what a finished export must hold.
TWO_ROWS: Final[int] = 2

#: The header row plus the fixture's rows.
HEADER_AND_TWO_ROWS: Final[int] = TWO_ROWS + 1


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


def an_unmapped_package(run: PolicyRun, name: str) -> Package:
    """Return one package the report selects, with its rollup row.

    Args:
        run: The run the rollup row belongs to.
        name: Its canonical name.

    Returns:
        The saved package.

    """
    package = Package.objects.create(
        canonical_name=name,
        resolved_at=NOW,
        confidence=IdentityConfidence.UNMAPPED,
        identity_source="pypi",
        associator_key=f"pypi:{name}",
    )
    PackageHealth.objects.create(
        package=package,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=NOW,
        confidence=package.confidence,
        policy_versions={"fixture": A_POLICY_VERSION},
    )
    return package


def two_unmapped_packages() -> None:
    """Seed the two rows every case below exports."""
    run = a_run()
    an_unmapped_package(run, "first")
    an_unmapped_package(run, "second")


def a_client(*roles: str) -> APIClient:
    """Return a client signed in as somebody holding these roles.

    Args:
        *roles: The role slot names.

    Returns:
        An authenticated client, and the user is reachable as `.handle`.

    """
    user: User = UserFactory.create()
    for role in roles:
        user.groups.add(Group.objects.get(name=getattr(settings.ROLE_CONTRACT, role)))
    client = APIClient()
    client.force_login(user)
    client.handle = user  # type: ignore[attr-defined]
    return client


def a_reader() -> APIClient:
    """Return a client holding every product role.

    Returns:
        The client.

    """
    return a_client(SECURITY_REVIEWER, PACKAGING_ENGINEER, LEADERSHIP)


def export_url() -> str:
    """Return the report's export URL.

    Returns:
        The path.

    """
    return reverse("conda_sentinel:report-export", kwargs={"slug": A_REPORT})


# ---------------------------------------------------------------------------
# AC 2: one constant, and it is what decides.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_cap_decides_which_path_an_export_takes(settings: Any) -> None:
    """AC 2 as behaviour rather than as a grep.

    The audit counts who reads the constant. This asserts the reading *does*
    something: move the number and the same report changes paths, which is the only
    way to tell a constant that is honoured from one that is merely present.

    Args:
        settings: pytest-django's settings fixture, which restores the cap.

    """
    two_unmapped_packages()
    report = REPORTS_BY_SLUG[A_REPORT]

    settings.CPM_SYNC_EXPORT_MAX_ROWS = A_TINY_CAP
    over = over_the_cap(report)
    settings.CPM_SYNC_EXPORT_MAX_ROWS = TWO_ROWS
    at = over_the_cap(report)

    assert over is True
    assert at is False, "a report exactly at the cap fits inside a request; the boundary is *beyond* the cap."


# ---------------------------------------------------------------------------
# AC 1: the work is enqueued and the request returns an in-progress state.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_asking_for_a_large_export_hands_the_work_off_and_returns_somewhere_to_look(settings: Any) -> None:
    """AC 1. The redirect *is* the in-progress state.

    A 202 with a body would leave a reader on a page that never changes, which is
    work handed off and then dropped as far as they can tell. The whole point of a
    job row is that the boundary can be looked back across.

    Args:
        settings: pytest-django's settings fixture.

    """
    settings.CPM_SYNC_EXPORT_MAX_ROWS = A_TINY_CAP
    two_unmapped_packages()
    client = a_reader()

    response = client.post(export_url())

    job = BackgroundJob.objects.get()
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == reverse("conda_sentinel:export-job", kwargs={"pk": job.pk})
    assert job.state == JobState.QUEUED.value
    assert job.kind == EXPORT_JOB_KIND
    assert job.parameters[REPORT_SLUG_PARAMETER] == A_REPORT
    assert job.requested_by == client.handle


@pytest.mark.django_db
def test_the_synchronous_export_refuses_a_report_beyond_the_cap(settings: Any) -> None:
    """It never truncates, which is the behaviour this story replaced.

    A CSV in somebody's downloads folder outlives the response header that qualified
    it, and reads as complete the moment the header is forgotten.

    Args:
        settings: pytest-django's settings fixture.

    """
    settings.CPM_SYNC_EXPORT_MAX_ROWS = A_TINY_CAP
    two_unmapped_packages()

    response = a_reader().get(export_url())

    assert response.status_code == HTTPStatus.CONFLICT
    assert BackgroundJob.objects.count() == 0, "a GET must not enqueue: a bookmark or a prefetch would create jobs."


@pytest.mark.django_db
def test_a_report_that_fits_is_still_produced_in_the_request() -> None:
    """`CPM-AD-9` bounds what a request will do; it does not send every export away.

    A product where the small case also required a round trip through a worker would
    have taken the cost of the boundary everywhere to get its benefit somewhere.
    """
    two_unmapped_packages()

    response = a_reader().get(export_url())

    assert response.status_code == HTTPStatus.OK
    assert len(list(csv.reader(io.StringIO(response.content.decode())))) == HEADER_AND_TWO_ROWS
    assert BackgroundJob.objects.count() == 0


# ---------------------------------------------------------------------------
# The worker's half, and the three states a reader can be left in.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_job_produces_the_whole_report_and_not_a_capped_one(settings: Any) -> None:
    """The cap is the boundary of a *request*, not a limit on the product.

    Work that left the request and then truncated itself would have taken the cost of
    the boundary without the benefit -- which is the failure worth asserting, because
    a runner that passed the cap through would look correct in every other case.

    Args:
        settings: pytest-django's settings fixture, left at one for the whole case.

    """
    settings.CPM_SYNC_EXPORT_MAX_ROWS = A_TINY_CAP
    two_unmapped_packages()
    job = request_job(
        kind=EXPORT_JOB_KIND,
        parameters={REPORT_SLUG_PARAMETER: A_REPORT},
        requested_by=a_reader().handle,  # type: ignore[attr-defined]
        clock=FixedClock(instant=NOW),
    )

    rows = run_job(job.pk)

    job.refresh_from_db()
    assert rows == TWO_ROWS
    assert job.state == JobState.SUCCEEDED.value
    assert job.row_count == TWO_ROWS
    assert len(list(csv.reader(io.StringIO(job.artifact)))) == HEADER_AND_TWO_ROWS


@pytest.mark.django_db
def test_a_job_whose_report_no_longer_exists_fails_and_says_so() -> None:
    """A report can be removed between a job being enqueued and a worker taking it.

    A deploy is all it takes, so this is a real sequence rather than a defensive
    branch. The job has to reach a terminal state: one stuck at `running` is
    indistinguishable to a reader from work that hung, and the page would say "in
    progress" for ever.
    """
    job = request_job(
        kind=EXPORT_JOB_KIND,
        parameters={REPORT_SLUG_PARAMETER: "not-a-report"},
        requested_by=a_reader().handle,  # type: ignore[attr-defined]
        clock=FixedClock(instant=NOW),
    )

    rows = run_job(job.pk)

    job.refresh_from_db()
    assert rows == 0
    assert job.state == JobState.FAILED.value
    assert "not-a-report" in job.detail
    assert job.finished_at is not None


@pytest.mark.django_db
def test_a_job_naming_a_kind_nothing_runs_fails_rather_than_waiting() -> None:
    """The registry's refusal, reaching a reader as a failed job rather than silence.

    A job whose kind has no runner would otherwise sit at `queued` for ever, which is
    the one outcome a status page cannot explain.
    """
    job = request_job(
        kind="nobody.registered.this",
        parameters={REPORT_SLUG_PARAMETER: A_REPORT},
        requested_by=a_reader().handle,  # type: ignore[attr-defined]
        clock=FixedClock(instant=NOW),
    )

    run_job(job.pk)

    job.refresh_from_db()
    assert job.state == JobState.FAILED.value
    assert EXPORT_JOB_KIND in job.detail, "the refusal names the kinds that *are* registered."


@pytest.mark.django_db
def test_a_task_for_a_job_that_is_gone_reports_rather_than_raising() -> None:
    """A real state after a rollback, and not this task's to repair.

    Raising would have celery retry into the same absence; the row a request wrote is
    simply not there.
    """
    assert run_job(999_999) == 0


@pytest.mark.django_db
def test_the_export_runner_is_registered_by_adoption() -> None:
    """The seam is filled, which is what makes the cases above about something.

    `surface/apps.py` registers the runner at `ready()`. If adoption stopped doing
    it, every enqueued export would fail with "no runner registered" -- so the fact
    of registration is asserted rather than assumed, exactly as
    `tests/unit/django_apps/test_after_run_seam.py` asserts the opening step's.
    """
    assert EXPORT_JOB_KIND in job_runner_registrations()


# ---------------------------------------------------------------------------
# The status page and the file.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_status_page_polls_while_running_and_stops_when_it_is_not() -> None:
    """A poll with no stopping condition is a request every few seconds for a week.

    Somebody leaves a status page open on a second monitor; the page has to know when
    to stop asking.
    """
    client = a_reader()
    job = request_job(
        kind=EXPORT_JOB_KIND,
        parameters={REPORT_SLUG_PARAMETER: A_REPORT},
        requested_by=client.handle,  # type: ignore[attr-defined]
        clock=FixedClock(instant=NOW),
    )
    page = reverse("conda_sentinel:export-job", kwargs={"pk": job.pk})

    running = client.get(page)
    finish_job(job, clock=FixedClock(instant=NOW), artifact="a,b\n1,2\n", rows=1)
    finished = client.get(page)

    assert running.context["refresh_seconds"] is not None
    assert finished.context["refresh_seconds"] is None


@pytest.mark.django_db
def test_a_finished_export_can_be_downloaded_and_carries_its_report_name() -> None:
    """A CSV rendered in the browser is one nobody can hand to anybody."""
    client = a_reader()
    job = request_job(
        kind=EXPORT_JOB_KIND,
        parameters={REPORT_SLUG_PARAMETER: A_REPORT},
        requested_by=client.handle,  # type: ignore[attr-defined]
        clock=FixedClock(instant=NOW),
    )
    finish_job(job, clock=FixedClock(instant=NOW), artifact="Package\nfirst\n", rows=1)

    response = client.get(reverse("conda_sentinel:export-job-download", kwargs={"pk": job.pk}))

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Disposition"] == f'attachment; filename="{A_REPORT}.csv"'
    assert response.content.decode() == "Package\nfirst\n"


@pytest.mark.django_db
def test_an_unfinished_export_has_no_file_to_download() -> None:
    """404 rather than a redirect to the page.

    A script that follows redirects would otherwise save an HTML document as a
    `.csv`, which is the download that looks like it worked.
    """
    client = a_reader()
    job = request_job(
        kind=EXPORT_JOB_KIND,
        parameters={REPORT_SLUG_PARAMETER: A_REPORT},
        requested_by=client.handle,  # type: ignore[attr-defined]
        clock=FixedClock(instant=NOW),
    )

    response = client.get(reverse("conda_sentinel:export-job-download", kwargs={"pk": job.pk}))

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_somebody_elses_export_is_not_yours_to_see_or_download() -> None:
    """A job is somebody's request, and a shared list of everybody's downloads is not
    something anybody asked for.

    404 rather than 403, which is the honest answer: you cannot be refused something
    whose existence is not yours to know. It is scoped by queryset rather than by a
    check in the view, so the two answers cannot drift apart.
    """
    owner = a_reader()
    stranger = a_reader()
    job = request_job(
        kind=EXPORT_JOB_KIND,
        parameters={REPORT_SLUG_PARAMETER: A_REPORT},
        requested_by=owner.handle,  # type: ignore[attr-defined]
        clock=FixedClock(instant=NOW),
    )
    finish_job(job, clock=FixedClock(instant=NOW), artifact="Package\nfirst\n", rows=1)

    page = stranger.get(reverse("conda_sentinel:export-job", kwargs={"pk": job.pk}))
    download = stranger.get(reverse("conda_sentinel:export-job-download", kwargs={"pk": job.pk}))

    assert page.status_code == HTTPStatus.NOT_FOUND
    assert download.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_a_broker_that_will_not_take_the_work_fails_the_job_rather_than_the_request(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    """Found by running this with no broker reachable, and it is worth the case.

    The job row is committed by the time `on_commit` fires, so an exception out of
    the publish propagated past the redirect: the reader got a 500 that told them
    nothing, and a job sat at `queued` that nothing would ever pick up. The page
    would have said "in progress" for ever.

    Now the refusal is recorded where the reader is already being sent. That is not
    log-and-continue -- the job's own page says the work could not be handed off,
    which is a louder report than a traceback nobody sees.

    **The publish is `on_commit`**, so this case has to make a commit happen. Every
    case in this module runs inside a transaction that is rolled back, which means
    `send_task` is never called at all -- and a case that simply monkeypatched it
    would pass while asserting nothing. That is also why the other cases can assert
    `queued` after `request_job`: they are asserting the row, not the hand-off.

    Args:
        monkeypatch: pytest's, to make the publish fail the way an unreachable broker
            does.
        django_capture_on_commit_callbacks: pytest-django's, to run the callback the
            surrounding transaction would otherwise discard.

    """

    def refuse(*args: Any, **kwargs: Any) -> None:
        message = "connection refused"
        raise OperationalError(message)

    monkeypatch.setattr(current_app, "send_task", refuse)
    client = a_reader()

    with django_capture_on_commit_callbacks(execute=True):
        job = request_job(
            kind=EXPORT_JOB_KIND,
            parameters={REPORT_SLUG_PARAMETER: A_REPORT},
            requested_by=client.handle,  # type: ignore[attr-defined]
            clock=FixedClock(instant=NOW),
        )

    job.refresh_from_db()
    assert job.state == JobState.FAILED.value
    assert "connection refused" in job.detail
    assert "ask for the export again" in job.detail, "the reader is told what to do, not only what went wrong."


@pytest.mark.django_db
def test_the_work_is_published_by_name_after_the_row_is_committed(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    """The two decisions the hand-off rests on, asserted rather than described.

    **By name.** `core/tasks.py` imports the policy-run orchestrator and, through it,
    the collectors, so reaching for `run_job.delay` would pull every one of them into
    the web process's import graph -- which is what
    `tests/unit/django_apps/test_request_boundary_audit.py` refuses. The name is a
    string and `send_task` needs nothing else.

    **After the commit.** A task published inside the transaction that created the
    row reaches a worker that may read the database before the commit lands, and
    finds nothing: a job queued for ever while a worker log says the id does not
    exist, on some requests and not others.

    Both are invisible when they are wrong -- the first is a slow import, the second
    is intermittent -- which is why they are a case rather than a comment.

    Args:
        monkeypatch: pytest's, to record the publish.
        django_capture_on_commit_callbacks: pytest-django's, to run the callback the
            surrounding transaction would otherwise discard.

    """
    published: list[tuple[Any, ...]] = []

    def record(name: str, **kwargs: Any) -> None:
        # The row has to exist by now; that is the half `on_commit` is here for.
        assert BackgroundJob.objects.filter(pk=kwargs["args"][0]).exists()
        published.append((name, kwargs.get("args"), kwargs.get("ignore_result")))

    monkeypatch.setattr(current_app, "send_task", record)
    client = a_reader()

    with django_capture_on_commit_callbacks(execute=True):
        job = request_job(
            kind=EXPORT_JOB_KIND,
            parameters={REPORT_SLUG_PARAMETER: A_REPORT},
            requested_by=client.handle,  # type: ignore[attr-defined]
            clock=FixedClock(instant=NOW),
        )

    assert published == [(EXPORT_JOB_TASK_NAME, [job.pk], True)]
    job.refresh_from_db()
    assert job.state == JobState.QUEUED.value


@pytest.mark.django_db
def test_an_export_of_a_report_that_does_not_exist_is_a_404_on_both_methods() -> None:
    """The same refusal whichever path is taken, because it is the same mistake.

    A `POST` that enqueued a job for a report nobody has would produce a job that can
    only fail, which is a worse answer than refusing before anything is written.
    """
    client = a_reader()
    url = reverse("conda_sentinel:report-export", kwargs={"slug": "not-a-report"})

    assert client.get(url).status_code == HTTPStatus.NOT_FOUND
    assert client.post(url).status_code == HTTPStatus.NOT_FOUND
    assert BackgroundJob.objects.count() == 0


# ---------------------------------------------------------------------------
# AC 3: everything else stays synchronous.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_ordinary_read_enqueues_nothing() -> None:
    """AC 3. A product that sent every read through a queue would be unusable.

    `CPM-AD-9` moves four specific kinds of work; the criterion's other half is that
    it moves nothing else, and a boundary that crept would show up here first.
    """
    two_unmapped_packages()
    client = a_reader()

    for name in ("conda_sentinel:home", "conda_sentinel:package-health", "conda_sentinel:coverage"):
        assert client.get(reverse(name)).status_code == HTTPStatus.OK

    assert BackgroundJob.objects.count() == 0
