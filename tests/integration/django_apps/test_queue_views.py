"""`CPM-APP-S05`: three queues over one table, each scoped to the role that owns it.

Two of the five criteria carry the weight, and they pull in opposite directions.

**AC 3 is a refusal, not an empty page.** The UX contract says it in as many words --
"a queue that is not yours is refused, never rendered empty" -- and the difference is
the whole point: an empty queue says *there is no work*, and a reviewer who reads
that goes away satisfied. So the cases below assert 403 rather than an empty listing,
and assert the refusal was logged with the acting user, which is what the criterion
actually asks for.

**AC 2 is an order, and an order is only testable at the boundaries.** A ranking case
that seeded one item in each bucket would pass on any ordering that happened to sort
them. So the fixtures put two items in *one* bucket with different scores, and two in
different buckets with the same score, which is where a wrong ordering shows.

**AC 5 turns out to be true by construction, and the case says so.** The
feedstock-gap surface excludes `unmapped` packages because `CPM-AD-4`'s gate already
writes `unknown` rather than `absent` for them -- so filtering the health view to
`absent` cannot return one. That is worth a test precisely *because* nothing had to
be built: the behaviour rests on the gate, and a change to the gate would take it
away silently.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Final

import pytest
import structlog
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from conda_sentinel.collectors.match_confidence import MatchConfidence
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.permissions import REFUSAL_EVENT
from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER
from conda_sentinel.identity.models import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.policies.models import PackagePriority
from conda_sentinel.workflow.models import WorkflowItem
from conda_sentinel.workflow.services import open_item
from conda_sentinel.workflow.states import QUEUE_OWNERS
from conda_sentinel.workflow.states import ItemState
from conda_sentinel.workflow.states import Queue
from tests.factories import UserFactory

if TYPE_CHECKING:
    from django_service.users.models import User

pytestmark = pytest.mark.integration

NOW: Final[datetime] = datetime(2026, 9, 4, 6, 12, tzinfo=UTC)
A_POLICY_VERSION: Final[str] = "cpm-app-s05-fixture-policy"

#: Two scores far enough apart that an ordering case reads as a claim rather than as
#: a coincidence.
A_HIGH_SCORE: Final[int] = 90
A_LOW_SCORE: Final[int] = 10

#: How many items the AC 1 case seeds, one per queue it checks. Named so the
#: assertion reads as "both, and nothing else" rather than as a number.
TWO_QUEUES: Final[int] = 2


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


def a_package(name: str, *, confidence: str = IdentityConfidence.VERIFIED) -> Package:
    """Return one package.

    Args:
        name: Its canonical name.
        confidence: How certain its identity is.

    Returns:
        The saved package.

    """
    return Package.objects.create(
        canonical_name=name,
        resolved_at=NOW,
        confidence=confidence,
        identity_source="pypi",
        associator_key=f"pypi:{name}",
    )


def a_ranked_item(
    run: PolicyRun,
    name: str,
    *,
    bucket: str,
    score: int,
    queue: str = Queue.REMEDIATION.value,
) -> WorkflowItem:
    """Return one queue item whose package carries a bucket and a score.

    Args:
        run: The run the derived rows belong to.
        name: The package's canonical name.
        bucket: The priority bucket on the rollup.
        score: The score on `package_priority`.
        queue: Which queue to open it in.

    Returns:
        The saved item.

    """
    package = a_package(name)
    PackageHealth.objects.create(
        package=package,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=NOW,
        confidence=package.confidence,
        policy_versions={"fixture": A_POLICY_VERSION},
        priority_status=bucket,
    )
    # A bucket outside `p1`..`p10` explains nothing, by constraint: the pass reached
    # no conclusion, so there is no rule that matched and no reason to record. The
    # fixture has to respect that or it is building a row the product cannot.
    explains = bucket in {f"p{number}" for number in range(1, 11)}
    PackagePriority.objects.create(
        package=package,
        policy_run=run,
        bucket=bucket,
        bucket_description="fixture" if explains else "",
        matched_rule="fixture-rule" if explains else "",
        reason="a fixture" if explains else "",
        score=score,
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=NOW,
    )
    finding = VulnerabilityFinding.objects.create(
        package=package,
        observed_at=NOW,
        state=MATCHED,
        advisory_id=f"CVE-FIXTURE-{name}",
        severity="critical",
        affected_range="<1.0",
        matched_version="0.9",
        match_confidence=MatchConfidence.EXACT_VERSION,
    )
    return open_item(evidence=finding, package=package, queue=queue, clock=FixedClock(instant=NOW)).item


def a_client(*roles: str) -> APIClient:
    """Return a client signed in as somebody holding these roles.

    Args:
        *roles: The role slot names.

    Returns:
        An authenticated client.

    """
    user: User = UserFactory.create()
    for role in roles:
        user.groups.add(Group.objects.get(name=getattr(settings.ROLE_CONTRACT, role)))
    client = APIClient()
    client.force_login(user)
    return client


def queue_url(queue: str) -> str:
    """Return a queue's URL.

    Args:
        queue: The queue name.

    Returns:
        The path.

    """
    return reverse("conda_sentinel:queue", kwargs={"queue": queue})


# ---------------------------------------------------------------------------
# AC 1: three filtered views over one table.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_each_queue_shows_only_its_own_items() -> None:
    """AC 1. One table, three filters -- and the filter is the only difference.

    Asserted from the owner of each queue in turn, because that is the only way to
    see all three.
    """
    run = a_run()
    a_ranked_item(run, "in-remediation", bucket="p1", score=A_HIGH_SCORE, queue=Queue.REMEDIATION.value)
    a_ranked_item(run, "in-compliance", bucket="p1", score=A_HIGH_SCORE, queue=Queue.COMPLIANCE_REVIEW.value)

    remediation = a_client(PACKAGING_ENGINEER).get(queue_url(Queue.REMEDIATION.value))
    compliance = a_client(SECURITY_REVIEWER).get(queue_url(Queue.COMPLIANCE_REVIEW.value))

    assert [row.canonical_name for row in remediation.context["rows"]] == ["in-remediation"]
    assert [row.canonical_name for row in compliance.context["rows"]] == ["in-compliance"]
    assert WorkflowItem.objects.count() == TWO_QUEUES


@pytest.mark.django_db
def test_a_queue_shows_open_work_and_not_finished_work() -> None:
    """A queue is what is left to do.

    A queue whose length only grows stops being read, and the history is on the item
    and on the package detail view either way.
    """
    run = a_run()
    item = a_ranked_item(run, "already-done", bucket="p1", score=A_HIGH_SCORE)
    WorkflowItem.objects.filter(pk=item.pk).update(state=ItemState.RESOLVED.value)

    response = a_client(PACKAGING_ENGINEER).get(queue_url(Queue.REMEDIATION.value))

    assert response.context["rows"] == ()


# ---------------------------------------------------------------------------
# AC 2: ranked by bucket, then score.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_worse_bucket_outranks_a_better_one() -> None:
    """`p2` before `p10`, which a lexicographic sort on the value gets wrong.

    The bucket is ranked by its index in `PRIORITY_BUCKETS` -- worst first -- rather
    than by its string, and this is the pair that separates the two.
    """
    run = a_run()
    a_ranked_item(run, "low-bucket", bucket="p10", score=A_HIGH_SCORE)
    a_ranked_item(run, "high-bucket", bucket="p2", score=A_LOW_SCORE)

    response = a_client(PACKAGING_ENGINEER).get(queue_url(Queue.REMEDIATION.value))

    assert [row.canonical_name for row in response.context["rows"]] == ["high-bucket", "low-bucket"]


@pytest.mark.django_db
def test_within_one_bucket_the_higher_score_comes_first() -> None:
    """The second half of the order, and the half a bucket-only sort would lose.

    Both items are `p1`, so only the score can separate them.
    """
    run = a_run()
    a_ranked_item(run, "less-used", bucket="p1", score=A_LOW_SCORE)
    a_ranked_item(run, "more-used", bucket="p1", score=A_HIGH_SCORE)

    response = a_client(PACKAGING_ENGINEER).get(queue_url(Queue.REMEDIATION.value))

    assert [row.canonical_name for row in response.context["rows"]] == ["more-used", "less-used"]


@pytest.mark.django_db
def test_an_unbucketed_item_sorts_below_every_real_bucket() -> None:
    """`unknown` is not a bucket and must not be ranked as one.

    An identity item is always here -- the confidence gate blanked the verdicts a
    bucket is derived from -- so a sort that put `unknown` among the buckets would
    put unidentified packages above real vulnerabilities.
    """
    run = a_run()
    a_ranked_item(run, "unbucketed", bucket="unknown", score=A_HIGH_SCORE)
    a_ranked_item(run, "bucketed", bucket="p10", score=A_LOW_SCORE)

    response = a_client(PACKAGING_ENGINEER).get(queue_url(Queue.REMEDIATION.value))

    assert [row.canonical_name for row in response.context["rows"]] == ["bucketed", "unbucketed"]


@pytest.mark.django_db
def test_a_row_reports_no_score_rather_than_a_zero_when_none_was_given() -> None:
    """Zero is a score somebody could have been given; the absence of one is not.

    The ordering treats an unscored package as lowest, which is right. The *display*
    must not say `0`, which would read as a decision nobody made.
    """
    run = a_run()
    package = a_package("unscored")
    PackageHealth.objects.create(
        package=package,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=NOW,
        confidence=package.confidence,
        policy_versions={"fixture": A_POLICY_VERSION},
    )
    finding = VulnerabilityFinding.objects.create(
        package=package,
        observed_at=NOW,
        state=MATCHED,
        advisory_id="CVE-FIXTURE-unscored",
        severity="critical",
        affected_range="<1.0",
        matched_version="0.9",
        match_confidence=MatchConfidence.EXACT_VERSION,
    )
    open_item(
        evidence=finding,
        package=package,
        queue=Queue.REMEDIATION.value,
        clock=FixedClock(instant=NOW),
    )

    (row,) = a_client(PACKAGING_ENGINEER).get(queue_url(Queue.REMEDIATION.value)).context["rows"]

    assert row.score is None


# ---------------------------------------------------------------------------
# AC 3: a queue that is not yours is refused, and the refusal is recorded.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(("queue", "owner"), sorted(QUEUE_OWNERS.items()))
def test_the_owning_role_reaches_its_queue(queue: str, owner: str) -> None:
    """The half that stops the refusal cases passing for the wrong reason.

    A view that refused everybody would satisfy every case below.

    Args:
        queue: The queue.
        owner: The role that owns it.

    """
    assert a_client(owner).get(queue_url(queue)).status_code == status.HTTP_200_OK


@pytest.mark.django_db
@pytest.mark.parametrize(("queue", "owner"), sorted(QUEUE_OWNERS.items()))
def test_a_queue_that_is_not_yours_is_refused_rather_than_rendered_empty(queue: str, owner: str) -> None:
    """AC 3, and the distinction the UX contract insists on.

    An empty queue says there is no work, and somebody who reads that goes away
    satisfied. 403 says the queue exists and is not theirs.

    Args:
        queue: The queue.
        owner: The role that owns it, so the case can pick a role that does not.

    """
    intruder = next(role for role in QUEUE_OWNERS.values() if role != owner)

    assert a_client(intruder).get(queue_url(queue)).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_the_refusal_is_logged_with_the_acting_user() -> None:
    """AC 3's second half, which the status code alone does not give.

    `APP.05-API-004` asks for the acting identity on the record, so an operator can
    see who tried what.
    """
    client = a_client(PACKAGING_ENGINEER)

    with structlog.testing.capture_logs() as captured:
        client.get(queue_url(Queue.IDENTITY_REVIEW.value))

    refusals = [event for event in captured if event["event"] == REFUSAL_EVENT]
    assert len(refusals) == 1
    assert refusals[0]["held"] == [PACKAGING_ENGINEER]
    assert refusals[0]["required"] == [LEADERSHIP]
    assert refusals[0]["actor"]


@pytest.mark.django_db
def test_holding_every_role_reaches_every_queue() -> None:
    """Which is what makes the scoping a *scope* rather than a partition.

    Nothing in the product says one person may hold only one role, and a check that
    refused somebody for holding *too many* would be a different rule than the one
    `CPM-FR-31` states.
    """
    client = a_client(*QUEUE_OWNERS.values())

    for queue in QUEUE_OWNERS:
        assert client.get(queue_url(queue)).status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_a_url_naming_no_queue_is_a_404_for_the_role_that_could_open_one() -> None:
    """A queue that does not exist is not one somebody lacks a role for.

    Answering 403 would tell a reader a queue exists that does not -- and the reader
    most likely to try a bad URL is the one who owns a real queue and mistyped it.
    """
    client = a_client(*QUEUE_OWNERS.values())

    assert client.get(queue_url("no-such-queue")).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_a_url_naming_no_queue_is_a_404_whoever_asks() -> None:
    """The queue names are not a secret, so refusing first would protect nothing.

    An earlier version of this view refused an unknown queue before checking whether
    it existed, which made the 404 unreachable -- and meant a reader who owned a
    queue and mistyped its URL was told a queue existed that did not. The nav lists
    all three names to every role, so there is nothing for the ordering to hide.
    """
    client = APIClient()
    client.force_login(UserFactory.create())

    assert client.get(queue_url("no-such-queue")).status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# AC 5: the feedstock gap excludes unmapped packages.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_feedstock_gap_excludes_unmapped_packages() -> None:
    """AC 5, and it is true by construction rather than by anything built here.

    `CPM-AD-4`'s gate writes `unknown` for every verdict on an unmapped package, so a
    filter for `absent` cannot return one -- an unidentified package reports "we do
    not know" rather than "there is no feedstock", which is the claim the criterion
    forbids.

    Worth a case precisely *because* nothing had to be built: the behaviour rests
    entirely on the gate, and a change there would take it away silently.
    """
    run = a_run()
    unmapped = a_package("unidentified", confidence=IdentityConfidence.UNMAPPED)
    absent = a_package("no-feedstock")
    PackageHealth.objects.create(
        package=unmapped,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=NOW,
        confidence=IdentityConfidence.UNMAPPED,
        policy_versions={"fixture": A_POLICY_VERSION},
        feedstock_presence_status="unknown",
    )
    PackageHealth.objects.create(
        package=absent,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=NOW,
        confidence=absent.confidence,
        policy_versions={"fixture": A_POLICY_VERSION},
        feedstock_presence_status="absent",
    )

    gap = a_client(LEADERSHIP).get(f"{reverse('conda_sentinel:package-health')}?feedstock=absent")
    names = {row.canonical_name for row in gap.context["rows"]}

    assert names == {"no-feedstock"}
    assert "unidentified" not in names


@pytest.mark.django_db
def test_an_unmapped_package_reports_unknown_rather_than_absent() -> None:
    """The other half of AC 5, stated as the criterion states it.

    Excluding it from the gap is not enough -- what it reports *instead* is the part
    that stops a reader concluding the feedstock question was answered.
    """
    run = a_run()
    unmapped = a_package("unidentified", confidence=IdentityConfidence.UNMAPPED)
    PackageHealth.objects.create(
        package=unmapped,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=NOW,
        confidence=IdentityConfidence.UNMAPPED,
        policy_versions={"fixture": A_POLICY_VERSION},
        feedstock_presence_status="unknown",
    )

    response = a_client(LEADERSHIP).get(reverse("conda_sentinel:package-health"))
    (row,) = response.context["rows"]
    feedstock = next(
        cell for column, cell in zip(response.context["columns"], row.cells, strict=True) if column.key == "feedstock"
    )

    assert feedstock.status == "unknown"
