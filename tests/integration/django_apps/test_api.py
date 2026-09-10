"""`CPM-APP-S07`: the same reads over HTTP, with a published schema and two writes.

The contract-shaped criteria -- "the only writes are two", "every collection is
paginated", "a status is never null" -- are swept in
`tests/unit/django_apps/test_api_contract_audit.py`, because a claim about the API as
a whole is not tested by testing one endpoint. What is here is the other half: that
the endpoints work, that they refuse what they should, and above all that they agree
with the screens.

**The agreement cases are the point of the module.** `CPM-AD-24` says every read
surface projects the same values and names the failure: a status reaching the API but
not the governed view. So the cases below do not check the API against a fixture --
they check it against the *screen* and against the *export*, which is the only
comparison that can fail when the two drift.

**`unknown` is asserted by name.** It is one of `CPM-FR-5`'s five states and it is
the one every ordinary serialization habit destroys. A package whose identity is
unmapped has it on every status, so that is what the AC 5 case seeds -- an assertion
that a *verdict* survived would pass on a serializer that turned every sentinel into
`null`.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.test import APIClient

from conda_sentinel.collectors.match_confidence import MatchConfidence
from conda_sentinel.collectors.models import KevFinding
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import LISTED
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.pagination import DEFAULT_PAGE_SIZE
from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER
from conda_sentinel.identity.models import IdentityConfidence
from conda_sentinel.identity.models import IdentityOverride
from conda_sentinel.identity.models import Package
from conda_sentinel.policies.models import PackageVulnerability
from conda_sentinel.surface.health import COLUMNS
from conda_sentinel.surface.reports import REPORTS
from conda_sentinel.workflow.models import WorkflowItem
from conda_sentinel.workflow.services import open_item
from conda_sentinel.workflow.states import ItemState
from conda_sentinel.workflow.states import Queue
from tests.factories import UserFactory

if TYPE_CHECKING:
    from django_service.users.models import User

pytestmark = pytest.mark.integration

NOW: Final[datetime] = datetime(2026, 9, 8, 9, 30, tzinfo=UTC)
A_POLICY_VERSION: Final[str] = "cpm-app-s07-fixture-policy"

#: A reason long enough to be a reason. `CPM-AD-14` requires one and the service
#: refuses a blank; a fixture reading "x" would satisfy the rule and say nothing
#: about whether it is stored verbatim.
A_REASON: Final[str] = "confirmed against the upstream project page during the September review"

#: More than one page would hold, so the paging case is about paging.
OVER_ONE_PAGE: Final[int] = DEFAULT_PAGE_SIZE + 3

#: How many moves the happy-path case makes, named so the assertion reads as "both
#: were recorded" rather than as a number.
TWO_MOVES: Final[int] = 2

#: A page size no client may ask for. `BoundedPageNumberPagination` sets
#: `page_size_query_param = None`, so this is asserted to be *ignored* rather than
#: refused -- the bound is unreachable by construction and not by validation.
AN_UNREASONABLE_PAGE_SIZE: Final[int] = 5_000


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


def a_rollup(run: PolicyRun, package: Package, **statuses: str) -> PackageHealth:
    """Return one rollup row for a package.

    Args:
        run: The run it belongs to.
        package: The package.
        **statuses: Any status columns to set.

    Returns:
        The saved row.

    """
    return PackageHealth.objects.create(
        package=package,
        policy_run=run,
        computed_at=NOW,
        evidence_cutoff=NOW,
        confidence=package.confidence,
        policy_versions={"fixture": A_POLICY_VERSION},
        **statuses,
    )


def a_kev_package(run: PolicyRun, name: str) -> Package:
    """Return a package the KEV report selects, with the finding behind it.

    Args:
        run: The run.
        name: Its canonical name.

    Returns:
        The saved package.

    """
    package = a_package(name)
    a_rollup(run, package)
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
    # The KEV membership needs the cross-reference row that established it, by
    # constraint: `kev_membership_names_its_cross_reference` forbids `listed` without
    # one. Building the finding here rather than setting the column is what makes
    # this fixture a package the product could actually have produced.
    kev = KevFinding.objects.create(
        package=package,
        vulnerability_finding=finding,
        observed_at=NOW,
        state=LISTED,
        source="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        catalog_date_added=NOW,
    )
    PackageVulnerability.objects.create(
        package=package,
        policy_run=run,
        vulnerability_status="advisories_matched",
        kev_membership="listed",
        risk_level="critical",
        vulnerability_finding=finding,
        kev_finding=kev,
        policy_version=A_POLICY_VERSION,
        evidence_cutoff=NOW,
    )
    return package


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


def a_reader() -> APIClient:
    """Return a client holding every product role.

    Returns:
        The client. Used wherever the case is not about scoping, so a refusal in one
        of those cases is a real finding rather than a fixture that forgot a group.

    """
    return a_client(SECURITY_REVIEWER, PACKAGING_ENGINEER, LEADERSHIP)


def body(response: Any) -> Any:
    """Return a response's parsed JSON.

    Args:
        response: The response.

    Returns:
        The decoded body.

    """
    return json.loads(response.content)


# ---------------------------------------------------------------------------
# AC 1: the three reads, and a schema generated from the implementation.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_current_health_is_available_and_carries_every_column_the_screen_shows() -> None:
    """AC 1, and the column count is `CPM-AD-24` rather than decoration.

    The failure the decision names is "a new derived status reaching the API but not
    the governed view". Asserting the cell count against `COLUMNS` is what makes a
    seventh column appear on both surfaces or neither -- a fixed number here would
    pass while the API fell a column behind.
    """
    run = a_run()
    a_rollup(run, a_package("numpy"))

    answer = a_reader().get(reverse("api:package-health"))

    assert answer.status_code == HTTPStatus.OK
    row = body(answer)["results"][0]
    assert row["canonical_name"] == "numpy"
    assert len(row["cells"]) == len(COLUMNS)
    assert row["policy_versions"] == {"fixture": A_POLICY_VERSION}


@pytest.mark.django_db
def test_package_detail_traces_every_status_to_its_evidence() -> None:
    """AC 1's second read: the reasoning, not a narrower table.

    Asserted through the identity block as well as the traces, because a detail
    response that carried verdicts without saying who the package *is* would leave a
    caller unable to tell a confident match from a guess -- which is the question
    `CPM-AD-14` makes the whole point of the screen.
    """
    run = a_run()
    package = a_kev_package(run, "aiohttp")

    answer = a_reader().get(reverse("api:package-detail", kwargs={"canonical_name": package.canonical_name}))

    assert answer.status_code == HTTPStatus.OK
    detail = body(answer)
    assert detail["canonical_name"] == "aiohttp"
    assert detail["identity"]["confidence"] == IdentityConfidence.VERIFIED
    assert [trace["label"] for trace in detail["traces"]]
    assert any(trace["observations"] for trace in detail["traces"])


@pytest.mark.django_db
def test_the_report_roster_names_every_report_the_application_has() -> None:
    """AC 1's third read, and the roster is data rather than a hand-kept list.

    A seventh report appears here the moment `REPORTS` grows one, which is what lets
    an integrator discover it without a client release.
    """
    answer = a_reader().get(reverse("api:report-roster"))

    assert answer.status_code == HTTPStatus.OK
    assert [entry["slug"] for entry in body(answer)["results"]] == [report.slug for report in REPORTS]


@pytest.mark.django_db
def test_a_report_states_the_cut_off_and_the_policy_versions_it_came_from() -> None:
    """`CPM-APP-S06`'s AC 2 survives the trip to HTTP.

    A report a caller cannot date is one that gets read as current a month later, and
    an API response is the form most likely to be stored and re-read.
    """
    run = a_run()
    a_kev_package(run, "aiohttp")

    answer = a_reader().get(reverse("api:report", kwargs={"slug": "kev"}))

    assert answer.status_code == HTTPStatus.OK
    page = body(answer)
    assert page["evidence_cutoff"] is not None
    assert page["policy_versions"] == [f"fixture@{A_POLICY_VERSION}"]
    assert page["columns"][:2] == ["Package", "Confidence"]


@pytest.mark.django_db
def test_an_empty_report_says_it_was_produced_from_nothing() -> None:
    """`null`, not a stale stamp borrowed from somewhere else.

    A report of nothing was produced from nothing, and inventing a cut-off for it
    would be the one lie an empty report is able to tell.
    """
    answer = a_reader().get(reverse("api:report", kwargs={"slug": "kev"}))

    page = body(answer)
    assert page["results"] == []
    assert page["evidence_cutoff"] is None
    assert page["policy_versions"] == []


@pytest.mark.django_db
def test_a_url_naming_no_report_is_refused_and_told_which_exist() -> None:
    """404 rather than an empty report, which would read as "nothing matched"."""
    answer = a_reader().get(reverse("api:report", kwargs={"slug": "not-a-report"}))

    assert answer.status_code == HTTPStatus.NOT_FOUND
    assert "kev" in body(answer)["detail"]


@pytest.mark.django_db
def test_the_schema_is_generated_from_the_implementation(admin_client: Any) -> None:
    """AC 1's second half: generated, not maintained by hand.

    Asserted by finding this story's own paths in the published document. A schema
    kept by hand passes every test that only checks it parses.
    """
    answer = admin_client.get(reverse("api-schema"), headers={"accept": "application/json"})

    assert answer.status_code == HTTPStatus.OK
    paths = json.loads(answer.content)["paths"]
    assert "/api/packages/" in paths
    assert "/api/reports/{slug}/" in paths
    assert "post" in paths["/api/workflow-items/{item_id}/transition/"]


# ---------------------------------------------------------------------------
# `CPM-AD-24`: the API, the screen and the export project the same values.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_api_and_the_screen_report_the_same_statuses_for_the_same_package() -> None:
    """The decision's named failure, tested as a comparison rather than as a fixture.

    Checking the API against expected values would pass while the screen drifted.
    The only comparison that fails on drift is API against screen, so that is what
    this is -- and it is the reason both read `health_rows` rather than each building
    a projection.
    """
    run = a_run()
    a_kev_package(run, "aiohttp")
    client = a_reader()

    api = body(client.get(reverse("api:package-health")))["results"][0]
    screen = client.get(reverse("conda_sentinel:package-health")).context["rows"][0]

    assert api["canonical_name"] == screen.canonical_name
    assert api["confidence"] == screen.confidence
    assert [cell["status"] for cell in api["cells"]] == [cell.status for cell in screen.cells]


@pytest.mark.django_db
def test_a_report_over_http_and_the_same_report_as_csv_carry_the_same_rows() -> None:
    """The export is the artifact that leaves; the API is what automation reads.

    Two surfaces over one report is how a board pack and a dashboard come to disagree
    about the same week. They share a projection precisely so they cannot, and this
    is the case that would fail if one grew its own query.
    """
    run = a_run()
    a_kev_package(run, "aiohttp")
    client = a_reader()

    api = body(client.get(reverse("api:report", kwargs={"slug": "kev"})))
    export = client.get(reverse("conda_sentinel:report-export", kwargs={"slug": "kev"}))
    rows = list(csv.reader(io.StringIO(export.content.decode())))

    assert rows[0] == api["columns"]
    assert rows[1:] == [list(row) for row in api["results"]]


# ---------------------------------------------------------------------------
# AC 5 / `APP.07-API-001`: a derived status is emitted verbatim.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_unknown_status_is_emitted_as_unknown_and_not_as_null() -> None:
    """`APP.07-API-001`, on the value the whole rule exists to protect.

    An unmapped package has `unknown` on every status, because `CPM-AD-4`'s gate
    stops its evidence being evaluated at all. That is a *finding* -- the product
    saying nobody established anything here -- and a response that rendered it as
    `null` or `""` would let a client read it as clean.

    Seeded as a sentinel rather than a verdict deliberately: a case asserting that
    `advisories_matched` survived would pass on a serializer that dropped every
    sentinel.
    """
    run = a_run()
    a_rollup(run, a_package("orphan", confidence=IdentityConfidence.UNMAPPED))

    row = body(a_reader().get(reverse("api:package-health")))["results"][0]

    assert row["confidence"] == IdentityConfidence.UNMAPPED
    assert all(cell["status"] == OutcomeState.UNKNOWN.value for cell in row["cells"])
    assert all(cell["status"] not in (None, "", False) for cell in row["cells"])


@pytest.mark.django_db
def test_no_status_anywhere_in_a_report_response_is_blank() -> None:
    """`CPM-AD-24` names the export; the API is the same artifact with a different
    content type.

    Walked across every report rather than asserted on one, because the rule is about
    the product and a report added tomorrow inherits it.
    """
    run = a_run()
    a_kev_package(run, "aiohttp")
    a_rollup(run, a_package("orphan", confidence=IdentityConfidence.UNMAPPED))
    client = a_reader()

    for report in REPORTS:
        page = body(client.get(reverse("api:report", kwargs={"slug": report.slug})))
        assert page["columns"], report.slug
        for row in page["results"]:
            assert all(value is not None for value in row), (report.slug, row)


# ---------------------------------------------------------------------------
# AC 2: paginated, with a maximum page size.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_collection_is_paginated_and_a_client_cannot_ask_for_more() -> None:
    """AC 2, both halves, and the second is what makes the first a bound.

    `CPM-NFR-1` sizes the inventory at ten thousand packages. A paginator whose size
    the caller chooses is not a bound -- so `?page_size=` is asserted to be *ignored*
    rather than refused, which is what `page_size_query_param = None` means.
    """
    run = a_run()
    for index in range(OVER_ONE_PAGE):
        a_rollup(run, a_package(f"package-{index:03d}"))
    client = a_reader()

    first = body(client.get(reverse("api:package-health")))
    greedy = body(client.get(reverse("api:package-health"), {"page_size": AN_UNREASONABLE_PAGE_SIZE}))

    assert first["count"] == OVER_ONE_PAGE
    assert len(first["results"]) == DEFAULT_PAGE_SIZE
    assert first["next"] is not None
    assert len(greedy["results"]) == DEFAULT_PAGE_SIZE


@pytest.mark.django_db
def test_a_filter_value_outside_its_vocabulary_is_refused_as_json() -> None:
    """A 400 that a client can read, which took running the endpoint to get right.

    `health_queryset` raises Django's `BadRequest`, which DRF does not handle -- so
    the first version answered 400 with a page of HTML from a JSON API. The status
    was never wrong, which is exactly why no assertion about the status would have
    caught it.
    """
    answer = a_reader().get(reverse("api:package-health"), {"vuln": "nonsense"})

    assert answer.status_code == HTTPStatus.BAD_REQUEST
    assert answer["Content-Type"].startswith("application/json")
    assert "vocabulary" in answer.content.decode()


# ---------------------------------------------------------------------------
# AC 4: the same role scoping as the application.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_queue_that_is_not_yours_is_refused_and_never_returned_empty() -> None:
    """AC 4, and the difference between the two answers is the whole criterion.

    An empty list says there is no work. An integrator whose credential quietly lost
    a role would report calm where there is a backlog -- which is the failure the UX
    contract states for the screen and which matters more for automation, because
    nobody is looking at it.
    """
    run = a_run()
    package = a_kev_package(run, "aiohttp")
    finding = VulnerabilityFinding.objects.filter(package=package).first()
    open_item(evidence=finding, package=package, queue=Queue.REMEDIATION.value, clock=FixedClock(instant=NOW))

    owner = a_client(PACKAGING_ENGINEER).get(reverse("api:queue", kwargs={"queue": Queue.REMEDIATION.value}))
    stranger = a_client(SECURITY_REVIEWER).get(reverse("api:queue", kwargs={"queue": Queue.REMEDIATION.value}))

    assert owner.status_code == HTTPStatus.OK
    assert len(body(owner)["results"]) == 1
    assert stranger.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_a_url_naming_no_queue_is_a_404_even_for_somebody_who_owns_none() -> None:
    """The ordering, which an earlier version of the screen had backwards.

    An unknown queue owns no role, so checking the role first makes the 404
    unreachable -- and tells a caller who mistyped a real queue's name that a queue
    exists which does not.
    """
    answer = a_client(SECURITY_REVIEWER).get(reverse("api:queue", kwargs={"queue": "not-a-queue"}))

    assert answer.status_code == HTTPStatus.NOT_FOUND
    assert Queue.REMEDIATION.value in body(answer)["detail"]


@pytest.mark.django_db
def test_a_reader_holding_no_product_role_is_refused_every_read() -> None:
    """The state the platform's `IsAuthenticated` floor lets straight through.

    Somebody signed in and in none of the three groups is a real case -- the
    zero-groups sign-in -- and `CPM-AD-13` exists because being authenticated says
    nothing about what somebody may see.
    """
    run = a_run()
    a_rollup(run, a_package("numpy"))
    client = a_client()

    for name in ("api:package-health", "api:report-roster"):
        assert client.get(reverse(name)).status_code == HTTPStatus.FORBIDDEN


# ---------------------------------------------------------------------------
# AC 3: the two writes, exercised.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_identity_override_records_who_corrected_what_and_why() -> None:
    """`CPM-AD-14`'s governed write, and the audit row is the deliverable.

    The row rather than the package is returned, on `override_identity`'s own terms:
    a caller handed only the package could not tell an override that changed nothing
    from one that was never recorded.
    """
    package = a_package("nummpy")

    answer = a_client(LEADERSHIP).post(
        reverse("api:package-identity-override", kwargs={"package_id": package.pk}),
        data={"reason": A_REASON, "canonical_name": "numpy"},
        format="json",
    )

    assert answer.status_code == HTTPStatus.CREATED
    recorded = body(answer)
    assert recorded["prior_canonical_name"] == "nummpy"
    assert recorded["new_canonical_name"] == "numpy"
    assert recorded["reason"] == A_REASON
    package.refresh_from_db()
    assert package.canonical_name == "numpy"
    assert IdentityOverride.objects.count() == 1


@pytest.mark.django_db
def test_an_override_without_the_role_is_refused_and_writes_nothing() -> None:
    """AC 4 on the one write that mutates governed reference data.

    `core/roles.py` grants the override permission to leadership alone, and the
    refusal has to leave nothing behind -- every check in the service precedes its
    first write, and this is the case that would notice if one stopped doing.
    """
    package = a_package("numpy")

    answer = a_client(SECURITY_REVIEWER).post(
        reverse("api:package-identity-override", kwargs={"package_id": package.pk}),
        data={"reason": A_REASON, "canonical_name": "renamed"},
        format="json",
    )

    assert answer.status_code == HTTPStatus.FORBIDDEN
    package.refresh_from_db()
    assert package.canonical_name == "numpy"
    assert IdentityOverride.objects.count() == 0


@pytest.mark.django_db
def test_an_override_with_no_reason_is_refused() -> None:
    """`CPM-AD-14` makes the justification part of the decision, not metadata.

    A correction with no reason is not a correction this product accepts, and the
    schema says so as well -- which is why the field is required in the serializer
    and checked again in the service.
    """
    package = a_package("numpy")

    answer = a_client(LEADERSHIP).post(
        reverse("api:package-identity-override", kwargs={"package_id": package.pk}),
        data={"canonical_name": "renamed"},
        format="json",
    )

    assert answer.status_code == HTTPStatus.BAD_REQUEST
    assert "reason" in body(answer)
    assert IdentityOverride.objects.count() == 0


@pytest.mark.django_db
def test_an_override_of_a_package_that_does_not_exist_is_a_404() -> None:
    """The URL points at nothing, which is a different failure from a bad body.

    It answered 400 until this was run against a stale package id and the response
    told the caller their *reason* was wrong. `CPM-AD-25` makes
    `resolve_package_shell` the only creator of a package, so the endpoint refuses
    rather than creating -- but it refuses with the code that says which part was
    wrong.
    """
    answer = a_client(LEADERSHIP).post(
        reverse("api:package-identity-override", kwargs={"package_id": 999_999}),
        data={"reason": A_REASON},
        format="json",
    )

    assert answer.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_a_correction_onto_a_name_another_package_holds_is_refused() -> None:
    """The refusal that is about the correction rather than about the actor.

    `canonical_name` is unique, so a correction onto a name already taken would put
    the product's one governed reference datum into a state it cannot hold. It is a
    400 -- the actor was allowed, the body was wrong -- which is the split the view
    makes and the reason `override_identity` grew typed refusals.
    """
    a_package("numpy")
    duplicate = a_package("nummpy")

    answer = a_client(LEADERSHIP).post(
        reverse("api:package-identity-override", kwargs={"package_id": duplicate.pk}),
        data={"reason": A_REASON, "canonical_name": "numpy"},
        format="json",
    )

    assert answer.status_code == HTTPStatus.BAD_REQUEST
    duplicate.refresh_from_db()
    assert duplicate.canonical_name == "nummpy"
    assert IdentityOverride.objects.count() == 0


@pytest.mark.django_db
def test_the_service_refuses_an_actor_the_declared_role_let_through() -> None:
    """The inner of two gates, asserted by removing the outer one's grounds.

    `CPM-AD-13` puts the role on the surface and `CPM-AD-14` puts the permission on
    the service, and the docstrings claim both are load-bearing. That claim is only
    worth something if the second refuses somebody the first admitted -- so this
    strips the override permission from the leadership group and sends a request from
    somebody who is still in it.

    A service that trusted its caller would let this through, and the caller it would
    be trusting is whichever surface somebody writes next.
    """
    package = a_package("numpy")
    client = a_client(LEADERSHIP)
    group = Group.objects.get(name=settings.ROLE_CONTRACT.leadership)
    group.permissions.clear()

    answer = client.post(
        reverse("api:package-identity-override", kwargs={"package_id": package.pk}),
        data={"reason": A_REASON, "canonical_name": "renamed"},
        format="json",
    )

    assert answer.status_code == HTTPStatus.FORBIDDEN
    package.refresh_from_db()
    assert package.canonical_name == "numpy"
    assert IdentityOverride.objects.count() == 0


@pytest.mark.django_db
def test_a_queue_action_moves_an_item_and_records_the_move() -> None:
    """The second write. `CPM-AD-23` puts the item and its transition in one commit.

    Two moves rather than one, and the second is why: `in_progress` is the state the
    model's own constraint ties a claim to, and `apply_transition` sets `claimed_by`
    rather than leaving it to the caller. A single move to `triaged` would exercise
    the write and say nothing about the claim.

    `open -> in_progress` is not a declared move, which this fixture found by trying
    it: the machine sends an item through `triaged` first, because acknowledging a
    finding and picking it up are two acts and the audit trail records both.
    """
    run = a_run()
    package = a_kev_package(run, "aiohttp")
    finding = VulnerabilityFinding.objects.filter(package=package).first()
    item = open_item(
        evidence=finding,
        package=package,
        queue=Queue.REMEDIATION.value,
        clock=FixedClock(instant=NOW),
    ).item

    client = a_client(PACKAGING_ENGINEER)
    move = reverse("api:workflow-item-transition", kwargs={"item_id": item.pk})

    triaged = client.post(
        move,
        data={"expected_state": ItemState.OPEN.value, "to_state": ItemState.TRIAGED.value},
        format="json",
    )
    claimed = client.post(
        move,
        data={"expected_state": ItemState.TRIAGED.value, "to_state": ItemState.IN_PROGRESS.value},
        format="json",
    )

    assert triaged.status_code == HTTPStatus.OK
    assert body(triaged)["state"] == ItemState.TRIAGED.value
    assert claimed.status_code == HTTPStatus.OK
    assert body(claimed)["claimed_by"] is not None
    item.refresh_from_db()
    assert item.state == ItemState.IN_PROGRESS.value
    assert item.transitions.count() == TWO_MOVES


@pytest.mark.django_db
def test_a_move_against_a_state_the_item_is_no_longer_in_is_a_conflict() -> None:
    """409, and the code is the useful half.

    A body the API cannot read is the client's mistake; a move the machine will not
    make on an item in the state it is actually in is a fact about the world, usually
    one that changed under a caller who read the item a moment ago. An integrator
    retrying a queue has to be able to tell those apart, and one code for both makes
    that impossible.
    """
    run = a_run()
    package = a_kev_package(run, "aiohttp")
    finding = VulnerabilityFinding.objects.filter(package=package).first()
    item = open_item(
        evidence=finding,
        package=package,
        queue=Queue.REMEDIATION.value,
        clock=FixedClock(instant=NOW),
    ).item

    answer = a_client(PACKAGING_ENGINEER).post(
        reverse("api:workflow-item-transition", kwargs={"item_id": item.pk}),
        data={"expected_state": ItemState.RESOLVED.value, "to_state": ItemState.TRIAGED.value},
        format="json",
    )

    assert answer.status_code == HTTPStatus.CONFLICT
    item.refresh_from_db()
    assert item.state == ItemState.OPEN.value


@pytest.mark.django_db
def test_a_state_outside_the_vocabulary_is_a_400_rather_than_a_conflict() -> None:
    """The other side of the split above, so 409 means what it says.

    A typo in a state name is the client's mistake and should not read as "somebody
    moved this item".
    """
    run = a_run()
    package = a_kev_package(run, "aiohttp")
    finding = VulnerabilityFinding.objects.filter(package=package).first()
    item = open_item(
        evidence=finding,
        package=package,
        queue=Queue.REMEDIATION.value,
        clock=FixedClock(instant=NOW),
    ).item

    answer = a_client(PACKAGING_ENGINEER).post(
        reverse("api:workflow-item-transition", kwargs={"item_id": item.pk}),
        data={"expected_state": item.state, "to_state": "not-a-state"},
        format="json",
    )

    assert answer.status_code == HTTPStatus.BAD_REQUEST
    assert "to_state" in body(answer)


@pytest.mark.django_db
def test_a_move_on_a_queue_that_is_not_yours_is_refused() -> None:
    """AC 4 on the write. The role that may move an item is the one that owns its queue.

    Checked against the item's *current* queue rather than the target, because
    sending work to another role is an act performed by the role holding it now.
    """
    run = a_run()
    package = a_kev_package(run, "aiohttp")
    finding = VulnerabilityFinding.objects.filter(package=package).first()
    item = open_item(
        evidence=finding,
        package=package,
        queue=Queue.REMEDIATION.value,
        clock=FixedClock(instant=NOW),
    ).item

    answer = a_client(SECURITY_REVIEWER).post(
        reverse("api:workflow-item-transition", kwargs={"item_id": item.pk}),
        data={"expected_state": item.state, "to_state": ItemState.TRIAGED.value},
        format="json",
    )

    assert answer.status_code == HTTPStatus.FORBIDDEN
    item.refresh_from_db()
    assert item.state == ItemState.OPEN.value


@pytest.mark.django_db
def test_a_move_on_an_item_that_does_not_exist_is_a_404() -> None:
    """And it is a 404 for everybody, since the queue is what decides the role.

    There is no role to require until there is an item to read one from, so the
    answer is the same either way -- which is also the honest one: an id naming
    nothing is not a permission problem.
    """
    answer = a_client(PACKAGING_ENGINEER).post(
        reverse("api:workflow-item-transition", kwargs={"item_id": 999_999}),
        data={"expected_state": ItemState.OPEN.value, "to_state": ItemState.TRIAGED.value},
        format="json",
    )

    assert answer.status_code == HTTPStatus.NOT_FOUND
    assert WorkflowItem.objects.count() == 0


@pytest.mark.django_db
def test_a_read_endpoint_refuses_a_post() -> None:
    """AC 3 from the caller's side, so the sweep is not the only thing asserting it.

    `test_api_contract_audit.py` proves no read view *implements* a write; this
    proves the deployment answers accordingly, which is what an integrator would
    discover.
    """
    answer = a_reader().post(reverse("api:package-health"), data={}, format="json")

    assert answer.status_code == HTTPStatus.METHOD_NOT_ALLOWED
