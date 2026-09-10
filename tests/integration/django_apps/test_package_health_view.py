"""`CPM-APP-S02`'s five acceptance criteria, through a real request against real rows.

Every case here drives `execute_policy_run` rather than writing rollup rows by hand,
and that is the decision the module turns on. A test that inserted `PackageHealth`
rows directly would be asserting that the view renders whatever it is given -- true,
uninteresting, and unable to fail when a pass changes what it writes. Driving the run
means the rows under test are the rows the product produces, including the ones the
confidence gate wrote and the ones no evidence supported.

**Which is why most statuses here are sentinels, and why that is the point rather
than a limitation.** No collector has run, so every pass concludes `unknown` or
`not_found` -- which is exactly the state AC 4 is written about: "a status of
`unknown`, `not_found`, `not_applicable` or `error` renders as itself and never as
blank or as clean". A fixture that arranged for tidy verdicts would have skipped the
criterion.
`tests/integration/django_apps/test_health_projection.py` builds derived rows with
evidence behind them and checks the dating.

**AC 5 is two assertions and only one of them is a stopwatch.** The query count is
bounded and asserted exactly, because it is structural: a regression there is an N+1
and shows up as a number. The latency budget is asserted against
`CPM_HEALTH_VIEW_P95_BUDGET_MS`, and is deliberately the weaker of the two -- a timing
assertion on a shared runner is a flake generator, so it is written to fail on an
order of magnitude rather than on a slow morning, and the query bound beside it is
what actually catches a regression.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from conda_sentinel.core.clock import FixedClock
from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.core.pagination import DEFAULT_PAGE_SIZE
from conda_sentinel.core.policy_run import execute_policy_run
from conda_sentinel.core.runs import RunState
from conda_sentinel.identity.models import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.policies.models import PackageVulnerability
from conda_sentinel.policies.outcomes import PRIORITY_STATUS_UNKNOWN
from conda_sentinel.surface.health import COLUMNS
from conda_sentinel.surface.search import MAX_TERM_LENGTH
from conda_sentinel.surface.tone import PLAIN
from conda_sentinel.surface.tone import tone_of
from conda_sentinel.surface.views import SORT_PARAM
from tests.factories import UserFactory
from tests.policy_parameters import recorded_policy_parameters

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path

    from django.http import HttpResponse

    from django_service.users.models import User

pytestmark = pytest.mark.integration

#: The fixture run's version and instants, on the shape `test_rollup.py` uses.
A_POLICY_VERSION: Final[str] = "cpm-app-s02-fixture-policy"
A_COLLECTOR: Final[str] = "cpm-app-s02-fixture-collector"
A_FIXTURE_INACTIVITY: Final[int] = 365

#: How many pages `A_PAGE_AND_ONE` packages fill, which is what the paging cases
#: walk. Two, and it is named rather than written inline because the cases read it
#: as "every page" rather than as a number.
TWO_PAGES: Final[int] = 2

#: How many packages the filter cases build. Two rather than one, so a filter that
#: returned exactly one row whatever it was asked would fail rather than pass.
A_SMALL_INVENTORY: Final[int] = 2

#: More packages than a page holds, so pagination is about a boundary rather than a
#: response that happened to fit. One over is the smallest inventory that pages.
A_PAGE_AND_ONE: Final[int] = DEFAULT_PAGE_SIZE + 1

#: What the whole request may cost, in queries, however many rows are on the page.
#:
#: **Asserted exactly rather than as a ceiling**, which is the only version of this
#: assertion that catches the regression it exists for: a page of fifty rows and a
#: page of one must cost the same, and a `<=` would pass on an N+1 that stayed under
#: the bound at fixture size and blew past it at `CPM-NFR-1`'s ten thousand packages.
#:
#: The composition, so the number is readable rather than magic:
#:
#: 1. the session, 2. the signed-in user, 3. the transaction's savepoint
#: (`ATOMIC_REQUESTS`), 4. the user's groups, which is `granted_roles` deciding the
#: role check, 5. the paginator's `COUNT`, 6. the page of rollup rows, 7-12. one read
#: of each of the six derived tables the projection joins, and 13. the savepoint's
#: release.
#:
#: A seventh derived read would mean a pass had grown a second table; a second read
#: of the page would mean the queryset was being evaluated twice; a fourteenth of
#: anything is worth reading the list in the failure message for.
EXPECTED_QUERIES: Final[int] = 13

#: How much slower than the budget a case is allowed to be before it fails.
#:
#: The budget is a p95 over real traffic; a single request on a CI runner sharing a
#: box with three other jobs is not that, and asserting one against the other
#: directly would produce a test that fails on a busy afternoon. Ten times the budget
#: catches an order-of-magnitude regression -- a full table scan, an N+1, a join that
#: multiplied rows -- and nothing else, which is the honest thing for a stopwatch in
#: a suite to claim.
BUDGET_HEADROOM: Final[int] = 10


@pytest.fixture(autouse=True)
def _recorded_parameters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Record the fixture policy version, so a run at it can complete.

    Autouse for the reason `tests/integration/django_apps/test_rollup.py` gives:
    adopted passes refuse a version `policies/data/policy-parameters.toml` does not
    record, so without this every run below would fail every package and the view
    would be rendering a failed run's rows -- which is a real state, but not the one
    any case here is about.

    Args:
        monkeypatch: pytest's patcher, which restores the shipped path.
        tmp_path: Where the substituted file is written.

    Yields:
        Nothing; the substitution is the effect.

    """
    with recorded_policy_parameters(monkeypatch, tmp_path, {A_POLICY_VERSION: A_FIXTURE_INACTIVITY}):
        yield


def an_ended_collection_run(instant: datetime) -> None:
    """Record one ended collection run, so a policy run has a cut-off to choose.

    Args:
        instant: When it started and finished.

    """
    CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=instant,
        finished_at=instant,
        status=RunState.SUCCEEDED,
    )


def an_inventory(count: int, *, confidence: str = IdentityConfidence.VERIFIED) -> list[Package]:
    """Create `count` packages and run the policy engine over them.

    Args:
        count: How many packages.
        confidence: The identity confidence each is resolved at.

    Returns:
        The packages, in creation order.

    """
    from django.utils import timezone  # noqa: PLC0415 - a fixture's own instant, not a module's clock read

    instant = timezone.now()
    an_ended_collection_run(instant)
    packages = [
        Package.objects.create(
            canonical_name=f"fixture-package-{index:04d}",
            resolved_at=instant,
            confidence=confidence,
        )
        for index in range(count)
    ]
    execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=instant))
    return packages


def a_reader() -> APIClient:
    """Return a client signed in as somebody who may read the health view.

    Returns:
        An authenticated client holding the leadership role.

    """
    user: User = UserFactory.create()
    user.groups.add(Group.objects.get(name=settings.ROLE_CONTRACT.leadership))
    client = APIClient()
    client.force_login(user)
    return client


def health_url(**query: object) -> str:
    """Return the health view's URL with a query string.

    Args:
        **query: Query parameters.

    Returns:
        The path, with the parameters appended when there are any.

    """
    path = reverse("conda_sentinel:package-health")
    if not query:
        return path
    encoded = "&".join(f"{key}={value}" for key, value in query.items())
    return f"{path}?{encoded}"


def tables_read(captured: CaptureQueriesContext) -> list[str]:
    """Return which table each captured query read, in order.

    The failure message a query-count assertion needs. A bare count says a number
    changed; this says *which* read appeared, which is the difference between
    diagnosing an N+1 in a minute and reading fifty lines of SQL.

    Args:
        captured: The captured queries.

    Returns:
        One table name per query, `?` where the statement names none.

    """
    return [
        match.group(1) if (match := re.search(r'FROM "([a-z_]+)"', query["sql"])) else "?"
        for query in captured.captured_queries
    ]


def body_of(response: HttpResponse) -> str:
    """Return a response's rendered HTML.

    Args:
        response: The response.

    Returns:
        The decoded body.

    """
    return response.content.decode()


# ---------------------------------------------------------------------------
# AC 1: every derived status, and when the rollup was computed.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_view_carries_every_derived_status() -> None:
    """AC 1: the row shows what every pass concluded, not a summary of it.

    Each column is asserted by its own header, because the failure this catches is a
    column quietly dropped from the template -- which looks like a tidier table and
    reads as a package with nothing wrong in that domain.
    """
    an_inventory(1)

    body = body_of(a_reader().get(health_url()))

    for column in COLUMNS:
        assert column.label in body, column.key
    assert "Confidence" in body
    assert "Work" in body


@pytest.mark.django_db
def test_the_view_states_when_the_rollup_was_recomputed() -> None:
    """AC 1's second half, and `CPM-AD-11`'s requirement on every view.

    All three stamps, because each answers a different question: `computed_at` is
    how old the conclusion is, the cut-off is how old the evidence behind it was,
    and the version map is which rules produced it. A screen with the first alone
    cannot be audited.
    """
    an_inventory(1)

    body = body_of(a_reader().get(health_url()))

    assert "rollup computed" in body
    assert "evidence cut-off" in body
    assert "policy versions" in body
    assert A_POLICY_VERSION in body


@pytest.mark.django_db
def test_the_rollup_row_the_view_renders_is_the_one_the_run_wrote() -> None:
    """The view is a projection, not a second computation.

    `CPM-AD-10` gives the application layer no write path to a derived status, so
    what a reader sees has to be what the policy run concluded -- asserted against
    the row rather than against a fixture constant, so a view that recomputed
    anything would disagree with the table.
    """
    packages = an_inventory(1)
    row = PackageHealth.objects.get(package=packages[0])

    body = body_of(a_reader().get(health_url()))

    assert row.currency_status in body
    assert row.work_type_status in body
    assert row.confidence in body


# ---------------------------------------------------------------------------
# AC 2: ten thousand packages, and no request that returns them all.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_inventory_larger_than_a_page_is_paginated() -> None:
    """AC 2, at the smallest inventory that can show it.

    `CPM-NFR-1` sizes the product at ten thousand packages; a test at that size
    would take minutes to build and prove nothing this does not. What matters is
    that the page is bounded and the boundary is the configured one.
    """
    an_inventory(A_PAGE_AND_ONE)

    response = a_reader().get(health_url())

    assert response.status_code == status.HTTP_200_OK
    assert len(response.context["rows"]) == DEFAULT_PAGE_SIZE
    assert response.context["paginator"].count == A_PAGE_AND_ONE
    assert response.context["page_obj"].has_next()


@pytest.mark.django_db
def test_the_second_page_holds_the_rest_and_repeats_nothing() -> None:
    """The half of pagination that a non-deterministic ordering breaks.

    A queryset ordered by a non-unique column can return a row on two pages and
    another on none, which is invisible on page one and is why `ORDERINGS`
    terminates every ordering with `package_id`.
    """
    an_inventory(A_PAGE_AND_ONE)
    client = a_reader()

    first = {row.canonical_name for row in client.get(health_url()).context["rows"]}
    second = {row.canonical_name for row in client.get(health_url(page=2)).context["rows"]}

    assert len(first) == DEFAULT_PAGE_SIZE
    assert len(second) == A_PAGE_AND_ONE - DEFAULT_PAGE_SIZE
    assert first & second == set()


@pytest.mark.django_db
@pytest.mark.parametrize("ordering", ["name", "rank"])
def test_both_orderings_page_without_losing_a_row(ordering: str) -> None:
    """Every ordering is a paging contract, not just the default one.

    `rank` orders by an annotation over a column with ten legal values and a
    sentinel, so it is the ordering most likely to be non-deterministic -- and the
    one a reviewer actually uses.

    Args:
        ordering: The sort key.

    """
    an_inventory(A_PAGE_AND_ONE)
    client = a_reader()
    seen: list[str] = []

    for page in range(1, TWO_PAGES + 1):
        response = client.get(health_url(page=page, **{SORT_PARAM: ordering}))
        seen.extend(row.canonical_name for row in response.context["rows"])

    assert len(seen) == A_PAGE_AND_ONE
    assert len(set(seen)) == A_PAGE_AND_ONE


# ---------------------------------------------------------------------------
# AC 3: filtering by anything the policy engine decided.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_rollup_column_filter_narrows_the_result() -> None:
    """AC 3 over a contributed column, which is the direct half.

    Every fixture package is `unknown` in priority -- no rule set is recorded -- so
    filtering to it returns everything and filtering to `p1` returns nothing. Both
    directions, because a filter that returned everything whatever it was given
    would pass the first assertion alone.
    """
    an_inventory(A_SMALL_INVENTORY)
    client = a_reader()

    everything = client.get(health_url(priority=PRIORITY_STATUS_UNKNOWN))
    nothing = client.get(health_url(priority="p1"))

    assert everything.context["paginator"].count == A_SMALL_INVENTORY
    assert nothing.context["paginator"].count == 0


@pytest.mark.django_db
def test_a_derived_table_filter_narrows_the_result() -> None:
    """AC 3 over a status that is *not* a rollup column, which is the harder half.

    Vulnerability lives on `package_vulnerability`, keyed `(package, policy_run)`,
    and the filter is a correlated `Exists` rather than a join. The count assertion
    is what proves it: a join to a table with one row per package per run would
    multiply rows, and the paginator would report a number that is not the number of
    packages.
    """
    an_inventory(A_SMALL_INVENTORY)
    row = PackageHealth.objects.first()
    assert row is not None
    # Read the verdict off the derived table rather than naming a value: what the
    # vulnerability pass concludes for a package with no advisory evidence is the
    # pass's business, and a case that hard-coded it would fail the day that
    # changed for a reason with nothing to do with filtering.
    verdict = PackageVulnerability.objects.get(
        package_id=row.package_id,
        policy_run_id=row.policy_run_id,
    ).vulnerability_status

    response = a_reader().get(health_url(vuln=verdict))

    assert response.context["paginator"].count == A_SMALL_INVENTORY


@pytest.mark.django_db
def test_two_facets_narrow_together() -> None:
    """Facets combine with AND, which is what makes the counts beside them mean anything.

    A vulnerability status every package has, and a priority bucket none has: the
    conjunction is empty even though one side matches everything.
    """
    an_inventory(A_SMALL_INVENTORY)

    response = a_reader().get(health_url(priority="p1", confidence=IdentityConfidence.VERIFIED))

    assert response.context["paginator"].count == 0


@pytest.mark.django_db
def test_a_filter_value_no_vocabulary_holds_is_refused() -> None:
    """A stale bookmark gets an answer rather than the whole inventory.

    Silently dropping an unrecognised value returns every package under a URL that
    says it is filtered, and a reader cannot tell that from a genuinely empty
    result. `CPM-AD-24`'s vocabularies are closed, so a value outside one is a typo.
    """
    an_inventory(1)

    response = a_reader().get(health_url(vuln="criticl"))

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_a_parameter_that_is_not_a_facet_is_ignored() -> None:
    """The other side of that decision, and it is not the same case.

    Analytics tools append parameters, and so does a mail client. Refusing those
    would make a shared link fail for the person it was sent to.
    """
    an_inventory(1)

    response = a_reader().get(health_url(utm_source="an-email"))

    assert response.status_code == status.HTTP_200_OK
    assert response.context["paginator"].count == 1


# ---------------------------------------------------------------------------
# AC 4: the four sentinels render as themselves.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_sentinel_status_renders_as_itself() -> None:
    """AC 4, and it is the criterion this whole fixture arrangement is shaped around.

    No collector has run, so the passes conclude sentinels -- which is the state
    `CPM-FR-5` says must never read as clean. The assertion is over the *cells* the
    view built rather than over the HTML alone, so a template that printed the value
    into a `title` attribute and left the cell empty would still fail.
    """
    an_inventory(1)

    response = a_reader().get(health_url())
    row = response.context["rows"][0]
    body = body_of(response)

    assert len(row.cells) == len(COLUMNS)
    for column, cell in zip(COLUMNS, row.cells, strict=True):
        assert cell.status != "", column.key
        assert cell.status in body, column.key


@pytest.mark.django_db
def test_every_rendered_status_carries_a_tone_that_is_not_reassuring() -> None:
    """The other half of "never as clean", which printing the value does not give.

    A value the stylesheet does not recognise gets the undecorated tone, never the
    one that means fine. Asserted here as well as in `test_tone.py` because this is
    where the values are the ones a real run produced rather than the ones a
    vocabulary declares.
    """
    an_inventory(1)

    row = a_reader().get(health_url()).context["rows"][0]

    for cell in row.cells:
        tone = tone_of(cell.status)
        assert tone != ""
        assert tone != "tone-ok" or cell.status not in dict.fromkeys(OutcomeState.values) - {OutcomeState.OK.value}


@pytest.mark.django_db
def test_an_unmapped_package_appears_rather_than_being_filtered_away() -> None:
    """`CPM-AD-11`: one row per package, "including `unmapped` ones".

    The package the confidence gate blanked is the one a reader most needs to see --
    it is the identity queue's entire input -- and a health view that showed only
    evaluable packages would hide the work.
    """
    an_inventory(1, confidence=IdentityConfidence.UNMAPPED)

    response = a_reader().get(health_url())
    row = response.context["rows"][0]

    assert response.context["paginator"].count == 1
    assert row.confidence == IdentityConfidence.UNMAPPED
    assert all(cell.status == OutcomeState.UNKNOWN.value for cell in row.cells)


@pytest.mark.django_db
def test_no_cell_renders_blank_even_where_nothing_was_evaluated() -> None:
    """`CPM-AD-24`: blank is reserved for a field with no value, and a status has one.

    The empty-string check is the whole assertion. A cell that rendered `""` would
    look, on the screen, exactly like a column with nothing to report.
    """
    an_inventory(1, confidence=IdentityConfidence.UNMAPPED)

    row = a_reader().get(health_url()).context["rows"][0]

    assert [cell.status for cell in row.cells if not cell.status] == []
    assert [cell.note for cell in row.cells if not cell.note] == []
    assert tone_of("a-value-no-vocabulary-declares") == PLAIN


# ---------------------------------------------------------------------------
# AC 5: the budget, and the query count that is what actually catches a regression.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_query_count_does_not_grow_with_the_page() -> None:
    """AC 5's second half, and the assertion with teeth.

    Exactly equal at two very different page sizes. `<=` would pass on an N+1 that
    stayed under a generous bound at fixture size, which is precisely the regression
    that only appears at `CPM-NFR-1`'s ten thousand packages.
    """
    an_inventory(A_PAGE_AND_ONE)
    client = a_reader()

    with CaptureQueriesContext(connection) as full_page:
        client.get(health_url())
    with CaptureQueriesContext(connection) as last_page:
        client.get(health_url(page=2))

    assert tables_read(full_page) == tables_read(last_page)
    assert len(full_page) == EXPECTED_QUERIES, tables_read(full_page)


@pytest.mark.django_db
def test_a_filtered_request_costs_no_more_queries() -> None:
    """A facet is a condition on the one query, never a second pass over the result.

    A filter implemented in Python -- fetch everything, then narrow -- would keep the
    query count identical *and* return the whole inventory, so this is asserted
    beside the paginator's count rather than alone.
    """
    an_inventory(A_PAGE_AND_ONE)
    client = a_reader()

    with CaptureQueriesContext(connection) as filtered:
        response = client.get(health_url(confidence=IdentityConfidence.VERIFIED))

    assert len(filtered) == EXPECTED_QUERIES, tables_read(filtered)
    assert response.context["paginator"].count == A_PAGE_AND_ONE


@pytest.mark.django_db
def test_a_full_page_is_served_inside_the_configured_budget() -> None:
    """AC 5's first half: a budget exists, is configured, and is enforced.

    The value is `CPM_HEALTH_VIEW_P95_BUDGET_MS` and is PROVISIONAL -- the PRD defers
    it to the architecture pass as Open Question 5, and this story is required to
    enforce a budget rather than to choose the number. Read from settings rather
    than written here so answering that question is a settings change.

    Generous by `BUDGET_HEADROOM`, deliberately: a stopwatch on a shared runner
    cannot honestly assert a p95, and the query bound above is what catches the
    regression this would otherwise flake on.
    """
    an_inventory(A_PAGE_AND_ONE)
    client = a_reader()
    client.get(health_url())  # Warm the connection and the template cache.

    started = time.perf_counter()
    response = client.get(health_url(confidence=IdentityConfidence.VERIFIED))
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == status.HTTP_200_OK
    assert elapsed_ms < settings.CPM_HEALTH_VIEW_P95_BUDGET_MS * BUDGET_HEADROOM


def test_the_budget_is_configured_and_is_a_number_of_milliseconds() -> None:
    """The "is configured" half, which the timing case cannot assert about itself.

    A budget that had been deleted would make the case above pass trivially -- it
    would raise `AttributeError` rather than pass, but only where a case reads it,
    and a suite that stopped reading it would go quiet.
    """
    assert isinstance(settings.CPM_HEALTH_VIEW_P95_BUDGET_MS, int)
    assert settings.CPM_HEALTH_VIEW_P95_BUDGET_MS > 0


# ---------------------------------------------------------------------------
# The surface is still a surface: authorization, and no write path.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_reader_holding_no_role_is_refused() -> None:
    """`CPM-AD-13` on the product's first real view, not only on a fixture one.

    The platform's `IsAuthenticated` floor admits this user; `AnyProductRole` is
    what does not.
    """
    client = APIClient()
    client.force_login(UserFactory.create())

    assert client.get(health_url()).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_view_offers_no_write_method(method: str) -> None:
    """`CPM-AD-10`: the application layer holds no write path to a derived status.

    Asserted at the HTTP boundary rather than by reading the class, because that is
    where a mixin added later would open one.

    Args:
        method: The HTTP method to attempt.

    """
    an_inventory(1)

    response = getattr(a_reader(), method)(health_url())

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def a_named_inventory(*names: str, confidence: str = IdentityConfidence.VERIFIED) -> None:
    """Create packages under the names given and run the policy engine over them.

    `an_inventory` above numbers its packages, which is what a pagination or a query
    count wants and exactly what a *search* cannot use: every name it generates
    contains every other name's prefix.

    Args:
        *names: The canonical names to create.
        confidence: The identity confidence each is resolved at.

    """
    from django.utils import timezone  # noqa: PLC0415 - a fixture's own instant, not a module's clock read

    instant = timezone.now()
    an_ended_collection_run(instant)
    for name in names:
        Package.objects.create(canonical_name=name, resolved_at=instant, confidence=confidence)
    execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=instant))


def named(response: object) -> set[str]:
    """Return the canonical names a rendered health response is showing.

    Args:
        response: The response, whose context carries the projected rows.

    Returns:
        The names, as a set -- order is `test_the_orderings_are_stable`'s subject.

    """
    return {row.canonical_name for row in response.context["rows"]}  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_a_name_fragment_narrows_the_table() -> None:
    """`CPM-APP-S17` AC 1, and the reason the story exists.

    Nine facets narrow by what the policy engine *decided*, and none of them answers
    "where is django" -- so before this the only way to a package's detail page was
    to page to it. At `CPM-NFR-1`'s ten thousand that is two hundred pages.
    """
    a_named_inventory("django", "djangorestframework", "flask", "scikit-learn")

    response = a_reader().get(health_url(q="django"))

    assert named(response) == {"django", "djangorestframework"}


@pytest.mark.django_db
def test_a_fragment_matches_without_regard_to_case() -> None:
    """Nobody types a package name the way a channel spells it."""
    a_named_inventory("django", "flask")

    assert named(a_reader().get(health_url(q="DJANGO"))) == {"django"}


@pytest.mark.django_db
def test_a_fragment_matches_the_middle_of_a_name() -> None:
    """The half of a name somebody remembers is frequently not the first half."""
    a_named_inventory("scikit-learn", "umap-learn", "imbalanced-learn", "numpy")

    assert named(a_reader().get(health_url(q="learn"))) == {"scikit-learn", "umap-learn", "imbalanced-learn"}


@pytest.mark.django_db
def test_an_underscore_finds_the_hyphenated_name() -> None:
    """The import name a reader has in their head, spelled the way conda-forge spells it."""
    a_named_inventory("scikit-learn", "numpy")

    assert named(a_reader().get(health_url(q="scikit_learn"))) == {"scikit-learn"}


@pytest.mark.django_db
def test_a_fragment_nothing_matches_is_an_empty_result_and_not_a_refusal() -> None:
    """`CPM-APP-S17` AC 3, and the whole design decision in one case.

    `?vuln=criticl` is a 400 because `CPM-AD-24`'s vocabularies are closed and a
    stale bookmark must not read as a filtered all-clear. A package name is not a
    closed vocabulary, so `?q=djangoo` is a search that matched nothing -- which is a
    result, and refusing it would be exactly as wrong as absorbing the other.

    The contrast is asserted here rather than in two cases, so that reconciling the
    two rules in either direction fails.
    """
    a_named_inventory("django")
    client = a_reader()

    found_nothing = client.get(health_url(q="djangoo"))
    refused = client.get(health_url(vuln="criticl"))

    assert found_nothing.status_code == status.HTTP_200_OK
    assert named(found_nothing) == set()
    assert refused.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_a_search_and_a_facet_narrow_the_same_result() -> None:
    """`CPM-APP-S17` AC 4: AND, not replacement.

    A search that discarded the facets -- or facets that discarded the search --
    would leave a reader whose URL says both is in force reading a result that
    honours one, with the summary above it claiming otherwise.
    """
    a_named_inventory("django", "djangorestframework", confidence=IdentityConfidence.VERIFIED)
    a_named_inventory("django-unmapped", confidence=IdentityConfidence.UNMAPPED)
    client = a_reader()

    both = client.get(health_url(q="django", confidence=IdentityConfidence.UNMAPPED))

    assert named(both) == {"django-unmapped"}


@pytest.mark.django_db
def test_the_count_beside_the_table_is_the_number_of_matches() -> None:
    """`CPM-AD-12`: the search narrows the queryset the paginator counts.

    A search applied after pagination would page the whole inventory and then hide
    rows from each page -- so a reader would see "100 packages match" above four
    rows, and page two of a one-page result.
    """
    a_named_inventory("django", "flask", "numpy", "scipy")

    response = a_reader().get(health_url(q="django"))

    assert response.context["paginator"].count == 1
    assert response.context["page_obj"].paginator.num_pages == 1


@pytest.mark.django_db
def test_the_normalised_fragment_is_what_goes_back_into_the_box() -> None:
    """Or the input disagrees with the result and neither says what the URL means.

    A reader who types `scikit_learn` gets `scikit-learn` rows; a box still reading
    `scikit_learn` invites them to conclude the search is matching something other
    than what they asked for.
    """
    a_named_inventory("scikit-learn")

    response = a_reader().get(health_url(q="  scikit_learn  "))

    assert response.context["search"] == "scikit-learn"


@pytest.mark.django_db
def test_a_search_counts_as_a_filter_for_what_the_page_says_about_itself() -> None:
    """The heading says "filtered" and the rail offers "Clear" only when something is.

    `applied` holds the facet selection and nothing else, deliberately -- it is what
    the condition was built from. So a page asking "is anything in force" has to ask
    for both, and a template that asked only the first would show an unfiltered
    heading over a searched table.
    """
    a_named_inventory("django", "flask")

    response = a_reader().get(health_url(q="django"))
    body = response.content.decode()

    assert response.context["applied"] == {}
    assert response.context["search"] == "django"
    assert "filtered" in body
    assert "Clear" in body


@pytest.mark.django_db
def test_the_search_box_is_rendered_carrying_the_current_fragment() -> None:
    """The control exists on the page, in the same form as the facets.

    Being in that form is what makes AC 5 true without any JavaScript: applying a
    facet submits the search with it, and clearing the search submits the ticked
    facets with it, so neither has to be re-entered to change the other.
    """
    a_named_inventory("django")

    body = a_reader().get(health_url(q="django")).content.decode()
    # The *facet* form, not any form: the chrome carries the theme control's own, and
    # a search box that landed in that one would submit the theme and lose the query.
    rail = re.search(r"<form method=\"get\">(.*?)</form>", body, re.DOTALL)

    assert rail is not None, "the facet form is gone, so nothing here is measuring what it says"
    assert 'name="q"' in rail.group(1)
    assert 'value="django"' in rail.group(1)
    assert 'name="vuln"' in rail.group(1), "the search left the form the facets are in"


@pytest.mark.django_db
def test_the_api_spells_the_search_the_same_way_and_means_the_same_thing() -> None:
    """`CPM-APP-S17` AC 2, and `CPM-AD-24` in the small.

    Both surfaces read `?q=` out of the one queryset builder, so there is no way for
    the screen and the API to disagree about whether a request was a search. A URL a
    reviewer sends an integrator works.
    """
    a_named_inventory("django", "djangorestframework", "flask")
    client = a_reader()

    screen = named(client.get(health_url(q="django")))
    api = client.get(f"{reverse('conda_sentinel_api:package-health')}?q=django")

    assert api.status_code == status.HTTP_200_OK
    assert {row["canonical_name"] for row in api.json()["results"]} == screen


@pytest.mark.django_db
def test_the_api_answers_an_unmatched_fragment_with_an_empty_page_not_a_400() -> None:
    """The rule holds on the surface where absorbing it would be worse.

    An integrator reading a 400 for a name that simply is not in the inventory writes
    a retry, or a bug report. `?vuln=criticl` stays a 400 on this surface too, for
    the reason `health_queryset` states.
    """
    a_named_inventory("django")
    client = a_reader()

    empty = client.get(f"{reverse('conda_sentinel_api:package-health')}?q=djangoo")

    assert empty.status_code == status.HTTP_200_OK
    assert empty.json()["results"] == []


@pytest.mark.django_db
def test_the_box_enforces_the_same_length_bound_the_server_does() -> None:
    """Written twice they drift, and the drift is silent in the worse direction.

    An input that accepts more than `search_term` will keep turns a long paste into
    "no search at all" -- the whole inventory comes back, under a box still showing
    the text the reader typed.
    """
    a_named_inventory("django")

    body = a_reader().get(health_url(q="django")).content.decode()

    assert f'maxlength="{MAX_TERM_LENGTH}"' in body
