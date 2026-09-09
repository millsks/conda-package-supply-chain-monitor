"""`CPM-APP-X01`: what the monitor cannot see, and a home that dates the picture.

**The story these cases test is invented.** No PRD requirement and no epic entry
commissions these two screens; the acceptance criteria were written for them. See the
warning at the top of
`_bmad-output/implementation-artifacts/stories/cpm-app-x01-coverage-and-home.md`.

Every case here is about a *gap* rather than a total, because that is the screen's
whole reason to exist. A coverage view that reported "9,842 packages monitored" would
be true and useless; what an operator needs to know is which of them nothing has
looked at, and which collector stopped running three days ago without anybody
noticing.

**The collector-roster cases are the load-bearing ones.** A dashboard with a
hand-written roster gives a clean bill of health to a collector nobody added to it,
and the omission is invisible precisely because the screen looks complete. So the
roster is the registry's, and `test_every_registered_collector_appears` is what stops
it drifting back.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Final

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.registry import registered_collectors
from conda_sentinel.core.runs import RunState
from conda_sentinel.identity.models import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.surface.coverage import ROLLUP_STATUS_COLUMNS
from conda_sentinel.surface.coverage import collector_health
from tests.factories import UserFactory

pytestmark = pytest.mark.integration

NOW: Final[datetime] = datetime(2026, 9, 4, 6, 12, tzinfo=UTC)
CUTOFF: Final[datetime] = NOW - timedelta(minutes=32)
A_POLICY_VERSION: Final[str] = "cpm-app-x01-fixture-policy"

#: A collector that exists, so a case can record runs against a real name rather than
#: a made-up one the registry would not recognise.
A_REGISTERED_COLLECTOR: Final[str] = "inventory"

#: The fixture inventories these cases build, named so an assertion reads as the
#: claim it makes rather than as a number.
THREE_PACKAGES: Final[int] = 3
TWO_PACKAGES: Final[int] = 2
ONE_PACKAGE: Final[int] = 1
FOUR_RUNS: Final[int] = 4
HALF_OF_FOUR: Final[int] = 2

#: One package of two with no verdict, as a percentage. Spelled out because it is
#: the assertion that the share and the denominator agree with each other.
HALF: Final[float] = 50.0


def a_run() -> PolicyRun:
    """Return one finished policy run.

    Returns:
        The saved run.

    """
    return PolicyRun.objects.create(
        policy_version=A_POLICY_VERSION,
        started_at=NOW,
        finished_at=NOW,
        evidence_cutoff=CUTOFF,
    )


def a_package(name: str, *, confidence: str = IdentityConfidence.VERIFIED) -> Package:
    """Return one package.

    Args:
        name: Its canonical name.
        confidence: How certain its identity is.

    Returns:
        The saved package.

    """
    return Package.objects.create(canonical_name=name, resolved_at=CUTOFF, confidence=confidence)


def a_rollup_row(package: Package, run: PolicyRun, **columns: str) -> PackageHealth:
    """Return one rollup row.

    Args:
        package: The package.
        run: The run.
        **columns: Contributed columns to override.

    Returns:
        The saved row.

    """
    return PackageHealth.objects.create(
        package=package,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=CUTOFF,
        confidence=package.confidence,
        policy_versions={"fixture": A_POLICY_VERSION},
        **columns,
    )


def a_reader() -> APIClient:
    """Return a client signed in as somebody who may read the coverage view.

    Returns:
        An authenticated client.

    """
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=settings.ROLE_CONTRACT.leadership))
    client = APIClient()
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# AC 1: what the inventory does not know.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_coverage_view_counts_packages_with_no_established_identity() -> None:
    """AC 1: the number that bounds every other number on the screen.

    `CPM-AD-4` gates every verdict on identity confidence, so an unmapped package is
    `unknown` in every column -- and a coverage screen that did not lead with this
    would report gaps without their cause.
    """
    run = a_run()
    for index, confidence in enumerate(
        (IdentityConfidence.VERIFIED, IdentityConfidence.UNMAPPED, IdentityConfidence.UNMAPPED),
    ):
        a_rollup_row(a_package(f"package-{index}", confidence=confidence), run)

    coverage = a_reader().get(reverse("conda_sentinel:coverage")).context["coverage"]

    assert coverage.inventory == THREE_PACKAGES
    assert coverage.unmapped == TWO_PACKAGES
    assert coverage.identity[IdentityConfidence.VERIFIED.value] == ONE_PACKAGE


@pytest.mark.django_db
def test_a_status_gap_carries_its_denominator() -> None:
    """AC 1: a percentage with no denominator beside it is the shape a dashboard lies in.

    "40% of statuses are unknown" means something different across ten packages and
    across ten thousand, and a screen that showed only the share would read the same
    either way.
    """
    run = a_run()
    a_rollup_row(a_package("known"), run, currency_status="behind")
    a_rollup_row(a_package("unknown-one"), run)

    coverage = a_reader().get(reverse("conda_sentinel:coverage")).context["coverage"]
    currency = next(gap for gap in coverage.gaps if gap.label == ROLLUP_STATUS_COLUMNS["currency_status"])

    assert currency.inconclusive == 1
    assert currency.total == TWO_PACKAGES
    assert currency.share == HALF


@pytest.mark.django_db
def test_an_adverse_verdict_is_not_counted_as_a_gap() -> None:
    """`behind` is something the product *knows*, and knowing it is not a gap.

    The distinction this screen turns on: a gap is the absence of a verdict, not the
    presence of a bad one. Counting adverse verdicts here would make the number go up
    as the product got *better* at finding problems.
    """
    run = a_run()
    a_rollup_row(a_package("lagging"), run, currency_status="behind")

    coverage = a_reader().get(reverse("conda_sentinel:coverage")).context["coverage"]
    currency = next(gap for gap in coverage.gaps if gap.label == ROLLUP_STATUS_COLUMNS["currency_status"])

    assert currency.inconclusive == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "sentinel",
    [
        OutcomeState.UNKNOWN.value,
        OutcomeState.NOT_FOUND.value,
        OutcomeState.NOT_APPLICABLE.value,
        OutcomeState.ERROR.value,
    ],
)
def test_every_sentinel_counts_as_a_gap(sentinel: str) -> None:
    """All four, because all four mean the product formed no opinion.

    They are told apart on the per-package screen; here an operator wants one number
    for how much of the estate that is.

    Args:
        sentinel: The status to record.

    """
    run = a_run()
    a_rollup_row(a_package("a-package"), run, currency_status=sentinel)

    coverage = a_reader().get(reverse("conda_sentinel:coverage")).context["coverage"]
    currency = next(gap for gap in coverage.gaps if gap.label == ROLLUP_STATUS_COLUMNS["currency_status"])

    assert currency.inconclusive == 1


@pytest.mark.django_db
def test_an_empty_inventory_reports_no_gaps_rather_than_dividing_by_zero() -> None:
    """A product watching nothing has no gaps, which is true and is the honest answer."""
    coverage = a_reader().get(reverse("conda_sentinel:coverage")).context["coverage"]

    assert coverage.inventory == 0
    assert all(gap.share == 0.0 for gap in coverage.gaps)


# ---------------------------------------------------------------------------
# AC 2 and AC 3: the collector roster.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_registered_collector_appears() -> None:
    """AC 2, and the case the whole screen rests on.

    A dashboard with a hand-written roster gives a clean bill of health to a
    collector nobody added to it, and the omission is invisible because the screen
    looks complete. The roster is the registry's.
    """
    shown = {entry.name for entry in a_reader().get(reverse("conda_sentinel:coverage")).context["collectors"]}
    adopted = {collector.name for collector in registered_collectors()}

    assert shown == adopted
    assert adopted != set()


@pytest.mark.django_db
def test_a_collector_that_has_never_run_says_so() -> None:
    """AC 3: the row a dashboard renders blank, and blank next to green rows reads as fine.

    No run has been recorded for any collector, so every row is this case -- which
    is also the state a fresh deployment is in for its first cycle.
    """
    response = a_reader().get(reverse("conda_sentinel:coverage"))
    body = response.content.decode()

    assert all(not entry.has_ever_run for entry in response.context["collectors"])
    assert all(entry.last_status == "never_run" for entry in response.context["collectors"])
    assert all(not entry.inside_target for entry in response.context["collectors"])
    assert "never run" in body


@pytest.mark.django_db
def test_a_collector_is_judged_against_the_target_it_declares() -> None:
    """AC 2's second half: each collector's own target, not one number for all of them.

    The targets genuinely differ -- two days for an advisory sweep, thirty for a
    Python 3.14 verification build -- so a single threshold would call one of them
    stale while it was on time.
    """
    collector = next(entry for entry in registered_collectors() if entry.name == A_REGISTERED_COLLECTOR)
    target = collector.freshness_target
    assert target is not None
    CollectionRun.objects.create(
        collector=A_REGISTERED_COLLECTOR,
        started_at=NOW - target - timedelta(hours=1),
        finished_at=NOW - target - timedelta(hours=1),
        status=RunState.SUCCEEDED,
    )

    inside = collector_health(now=NOW)
    just_after = collector_health(now=NOW - target - timedelta(hours=1) + target - timedelta(minutes=1))

    assert next(e for e in inside if e.name == A_REGISTERED_COLLECTOR).inside_target is False
    assert next(e for e in just_after if e.name == A_REGISTERED_COLLECTOR).inside_target is True


@pytest.mark.django_db
def test_a_collector_failing_half_its_runs_is_not_reported_as_healthy() -> None:
    """The last outcome alone can be green on a collector failing every other run.

    Which is why the row carries the failure count rather than a single status: an
    operator acts on "9 runs, 4 failed", and a screen showing only the most recent
    outcome would show them whichever of the two happened last.
    """
    for index in range(FOUR_RUNS):
        CollectionRun.objects.create(
            collector=A_REGISTERED_COLLECTOR,
            started_at=NOW - timedelta(hours=index),
            finished_at=NOW - timedelta(hours=index),
            status=RunState.FAILED if index % 2 else RunState.SUCCEEDED,
        )

    entry = next(e for e in collector_health(now=NOW) if e.name == A_REGISTERED_COLLECTOR)

    assert entry.runs == FOUR_RUNS
    assert entry.failures == HALF_OF_FOUR
    assert entry.last_status == "failing"


@pytest.mark.django_db
def test_never_run_is_not_spelled_as_unknown() -> None:
    """A collector nobody asked is a different thing from a lookup that concluded nothing.

    `unknown` is an `OutcomeState` value with a meaning of its own, and reusing it
    here would put a status vocabulary on something that is not a status.
    """
    entry = next(e for e in collector_health(now=NOW) if e.name == A_REGISTERED_COLLECTOR)

    assert entry.last_status == "never_run"
    assert entry.last_status not in set(OutcomeState.values)


# ---------------------------------------------------------------------------
# AC 4 and AC 5: the home view.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_home_view_says_when_no_policy_run_has_completed() -> None:
    """AC 4: counts with no run behind them must not read as conclusions.

    The state every fresh deployment starts in, and the one a dashboard is most
    likely to render as a confident row of zeroes.
    """
    body = a_reader().get(reverse("conda_sentinel:home")).content.decode()

    assert "no policy run has completed yet" in body


@pytest.mark.django_db
def test_the_home_view_dates_the_picture_once_a_run_has_completed() -> None:
    """`CPM-AD-11` on the first screen a reader sees.

    A dashboard nobody can date is one that goes on being believed after it stops
    being true.
    """
    a_rollup_row(a_package("a-package"), a_run())

    response = a_reader().get(reverse("conda_sentinel:home"))

    assert response.context["coverage"].computed_at == NOW
    assert "rollup computed" in response.content.decode()


@pytest.mark.django_db
def test_a_home_counter_links_to_the_packages_it_counted() -> None:
    """AC 5: a dashboard whose counters do not lead anywhere is read once.

    The unmapped counter is the one that matters -- it is the identity queue's input
    -- and it links to the health view already filtered to them.
    """
    a_rollup_row(a_package("unidentified", confidence=IdentityConfidence.UNMAPPED), a_run())

    body = a_reader().get(reverse("conda_sentinel:home")).content.decode()

    assert f"{reverse('conda_sentinel:package-health')}?confidence=unmapped" in body


@pytest.mark.django_db
def test_the_home_view_lists_only_the_collectors_worth_looking_at() -> None:
    """The panel is "what the monitor could not see", not a second full roster.

    Ten healthy rows on a home page is noise; the coverage view is where the whole
    roster lives, and this links to it.
    """
    response = a_reader().get(reverse("conda_sentinel:home"))
    body = response.content.decode()

    assert reverse("conda_sentinel:coverage") in body
    assert "has never run" in body


# ---------------------------------------------------------------------------
# Both screens are read surfaces.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["conda_sentinel:home", "conda_sentinel:coverage"])
def test_a_reader_holding_no_role_is_refused(route: str) -> None:
    """`CPM-AD-13`. A dashboard is still a surface.

    Args:
        route: The route under test.

    """
    client = APIClient()
    client.force_login(UserFactory.create())

    assert client.get(reverse(route)).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["conda_sentinel:home", "conda_sentinel:coverage"])
def test_an_anonymous_visitor_is_sent_to_sign_in(route: str) -> None:
    """A credential is the thing that would help, so the answer says so.

    Args:
        route: The route under test.

    """
    response = APIClient().get(reverse(route))

    assert response.status_code == status.HTTP_302_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["conda_sentinel:home", "conda_sentinel:coverage"])
def test_the_view_offers_no_write_method(route: str) -> None:
    """`CPM-AD-10`, asserted at the HTTP boundary.

    Args:
        route: The route under test.

    """
    assert a_reader().post(reverse(route)).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
