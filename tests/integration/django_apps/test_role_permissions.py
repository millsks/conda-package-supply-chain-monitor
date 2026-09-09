"""`CPM-AD-13` and `CPM-AD-12` through a real request, against a real database.

`tests/unit/django_apps/test_permissions.py` drives the check with stub users, and
`tests/unit/django_apps/test_permission_audit.py` sweeps for anybody deciding
authorization on their own. Both are structural. What neither can show is the thing
the story's third acceptance criterion is actually about: that a **request** from a
role without the grant is refused, and that the refusal reaches the log with the
acting user's identity in it.

So this module routes two views, signs a real user in, and reads the response and the
log record. Three layers have to be right for it to pass and each has been wrong in
some codebase: the group memberships must resolve through the role contract's
configured names; DRF must actually consult the declared permission rather than stop
at the global `IsAuthenticated` floor; and the refusal must be logged rather than
merely returned.

**The views are fixtures, and they are fixtures because there are no product views
yet.** `CPM-APP-S02` writes the first. Declaring these here is the same choice
`tests/unit/django_apps/test_task_routing_audit.py` makes for its fixture task names:
a rule proven against nothing is not proven, and waiting for the surface would mean
shipping the mechanism unexercised. They are deliberately the two shapes the product
will have -- a read surface every role may reach, and a scoped queue one role may --
so the case that fails when `CPM-APP-S05` gets its permission wrong is already here.

**`AnyProductRole` on a list view is also what makes `CPM-AD-12` real.** The
pagination case below asks for more rows than a page holds through an ordinary
`ListAPIView` that says nothing at all about pagination, which is the only way to
show that the global setting reaches a view rather than that the setting is present
in a dict.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction, and the
role groups these read were left by a migration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
import structlog
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import path
from rest_framework import serializers
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from conda_sentinel.core import permissions as core_permissions
from conda_sentinel.core.pagination import DEFAULT_PAGE_SIZE
from conda_sentinel.core.permissions import REFUSAL_EVENT
from conda_sentinel.core.permissions import AnyProductRole
from conda_sentinel.core.permissions import requires_roles
from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER
from django_service.users.models import User
from tests.factories import UserFactory

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.integration, pytest.mark.urls(__name__)]

#: Where the two fixture surfaces are mounted. Under `/api/` because that is where
#: this product's surfaces will be, and the path is one of the five fields a refusal
#: records -- so a case asserting the log has to know what it should say.
EVIDENCE_PATH: Final[str] = "/api/evidence/"
QUEUE_PATH: Final[str] = "/api/queues/identity/"

#: The control event the capture emits to prove it is live, on the terms
#: `captured_identity_service_logs` sets in `tests/conftest.py`.
CAPTURE_CONTROL: Final[str] = "permissions-capture-control"

#: More users than a page holds, so the pagination case is about a page boundary
#: rather than about a response that happened to fit. One over is the right number:
#: it is the smallest inventory that pages, so the case fails if the size is read as
#: anything but `DEFAULT_PAGE_SIZE`.
A_PAGE_AND_ONE: Final[int] = DEFAULT_PAGE_SIZE + 1


class UsernameSerializer(serializers.ModelSerializer[User]):
    """The least serializer that renders a row, because the rows are not the subject."""

    class Meta:
        model = User
        fields = ("username",)


class EvidenceView(ListAPIView[User]):
    """A read surface: any of the three roles, and no opinion about pagination.

    `CPM-AD-13` grants read access to evidence to all three roles, so this is the
    shape most of the product's surfaces will take. It declares nothing about
    pagination on purpose -- that is what the global setting is for, and a view that
    declared a page size would be the thing
    `tests/unit/django_apps/test_pagination_audit.py` fails on.
    """

    permission_classes = (AnyProductRole,)
    serializer_class = UsernameSerializer
    queryset = User.objects.order_by("username")


class IdentityQueueView(APIView):
    """A scoped queue: one role, which is where `CPM-FR-31`'s scoping actually lives.

    The UX contract puts it exactly here -- "role scoping happens *below* the nav --
    at the deep queue URL, at the item, and at the transition" -- so this is the
    surface a packaging engineer must not reach.
    """

    permission_classes = (requires_roles(SECURITY_REVIEWER),)

    def get(self, request: Any) -> Response:
        """Return something a reviewer is allowed to see.

        Args:
            request: The authorized request.

        Returns:
            A trivial body; what is under test is reaching it at all.

        """
        return Response({"queue": "identity"})


urlpatterns = [
    path("api/evidence/", EvidenceView.as_view()),
    path("api/queues/identity/", IdentityQueueView.as_view()),
]


@pytest.fixture
def captured_logs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Capture what `core/permissions.py` logs, with the control guard.

    Args:
        monkeypatch: pytest's patcher, which restores the module's own logger.

    Yields:
        The captured events, in order, with the control event already cleared.

    """
    monkeypatch.setattr(core_permissions, "logger", structlog.get_logger(core_permissions.__name__))
    with structlog.testing.capture_logs() as captured:
        core_permissions.logger.warning(CAPTURE_CONTROL)
        assert [event["event"] for event in captured] == [CAPTURE_CONTROL], (
            "structlog.testing.capture_logs() cannot see core.permissions' logger, so every assertion "
            "over what it logged would be vacuous"
        )
        captured.clear()
        yield captured


def refusals(captured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the authorization refusals out of everything a request logged.

    `capture_logs` swaps the whole processor chain, so a real request through the
    middleware stack also lands `request_started` and `request_finished` in the list
    -- which is a *feature* of the capture and not noise to be suppressed, since it
    is what proves a request happened at all. Filtering by event here, rather than
    silencing the middleware, keeps both.

    Args:
        captured: Everything logged during the request.

    Returns:
        The `REFUSAL_EVENT` records, in order.

    """
    return [event for event in captured if event["event"] == REFUSAL_EVENT]


def signed_in_as(*roles: str) -> APIClient:
    """Return a client signed in as a user holding these role slots.

    Memberships are added to the groups the migration provisioned rather than to
    groups this test creates: `AD-27` makes `django_service.users.provisioning` the
    one mechanism permitted to create a `Group`, and a test that made its own rows
    would hide a real defect in it.

    Args:
        *roles: The role slot names the user should hold.

    Returns:
        An authenticated client.

    """
    user = UserFactory.create()
    for role in roles:
        user.groups.add(Group.objects.get(name=getattr(settings.ROLE_CONTRACT, role)))
    client = APIClient()
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# The declared role decides the request.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("role", [SECURITY_REVIEWER, PACKAGING_ENGINEER, LEADERSHIP])
def test_every_role_reaches_the_read_surface(role: str) -> None:
    """`CPM-AD-13` grants read access to evidence to all three, through a real request.

    Args:
        role: The one role this user holds.

    """
    response = signed_in_as(role).get(EVIDENCE_PATH)

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_the_scoped_queue_admits_the_role_it_names() -> None:
    """The other half of the refusal below, and the half that stops it being vacuous.

    A permission class that refused everybody would pass every refusal case in this
    module; this is the case it would fail.
    """
    response = signed_in_as(SECURITY_REVIEWER).get(QUEUE_PATH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"queue": "identity"}


@pytest.mark.django_db
def test_the_scoped_queue_refuses_a_role_it_did_not_name() -> None:
    """AC 3, as a request: the leak `CPM-AD-13` exists to prevent, refused.

    A packaging engineer is signed in, authenticated, and holds a real product role.
    The platform's `IsAuthenticated` floor admits them; the declared permission is
    what does not.
    """
    response = signed_in_as(PACKAGING_ENGINEER).get(QUEUE_PATH)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_a_signed_in_user_holding_no_role_is_refused() -> None:
    """`EXPERIENCE.md`'s G-4: the sign-in succeeded and every surface still refuses.

    A real state -- a person whose directory groups this deployment has not mapped --
    and the one the global `IsAuthenticated` default would let through to a read
    surface if `AnyProductRole` were treated as a formality.
    """
    response = signed_in_as().get(EVIDENCE_PATH)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_an_unauthenticated_request_never_reaches_the_role_check() -> None:
    """The floor still does its job, and the status code says which layer refused.

    401 rather than 403: nobody was signed in, so the answer is "authenticate", not
    "you may not". A role check that returned 403 here would tell an anonymous caller
    that a credential would not have helped.
    """
    response = APIClient().get(QUEUE_PATH)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_a_superuser_without_the_role_is_refused() -> None:
    """`CPM-AD-13` is not exempted for superusers, asserted where it would be bypassed.

    Django's own admin checks `is_superuser` and the same line here would be
    invisible in a review. An operator who needs the queue joins the group, which is
    a change somebody can audit.
    """
    superuser = UserFactory.create(is_superuser=True, is_staff=True)
    client = APIClient()
    client.force_login(superuser)

    response = client.get(QUEUE_PATH)

    assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# The refusal is recorded.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_refused_request_is_logged_with_the_acting_user(captured_logs: list[dict[str, Any]]) -> None:
    """AC 3 in full: "a refused request is logged with the acting user identity".

    Read off a real request rather than a constructed one, because three of the five
    fields come from the request DRF built -- and the `path` in particular is the one
    an operator correlates against an access log.

    Args:
        captured_logs: What the module logged.

    """
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=settings.ROLE_CONTRACT.packaging_engineer))
    client = APIClient()
    client.force_login(user)

    response = client.get(QUEUE_PATH)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert refusals(captured_logs) == [
        {
            "event": REFUSAL_EVENT,
            "log_level": "warning",
            "actor": user.username,
            "view": "IdentityQueueView",
            "path": QUEUE_PATH,
            "required": [SECURITY_REVIEWER],
            "held": [PACKAGING_ENGINEER],
        },
    ]


@pytest.mark.django_db
def test_an_admitted_request_leaves_no_refusal_behind(captured_logs: list[dict[str, Any]]) -> None:
    """The refusal event means a refusal, which is what makes it alertable.

    Args:
        captured_logs: What the module logged.

    """
    response = signed_in_as(SECURITY_REVIEWER).get(QUEUE_PATH)

    assert response.status_code == status.HTTP_200_OK
    assert refusals(captured_logs) == []
    assert captured_logs != [], "the request logged nothing at all, so the assertion above proves nothing"


# ---------------------------------------------------------------------------
# The global page bound reaches a view that says nothing about it.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_view_declaring_nothing_is_paginated() -> None:
    """`CPM-AD-12` through a response, which is the only place the setting is real.

    `EvidenceView` says nothing about pagination. The inventory is one row larger
    than a page, so a global default that was not reaching views would return all of
    it -- which is exactly what happened before this story, because neither key
    existed.
    """
    UserFactory.create_batch(A_PAGE_AND_ONE)

    body = signed_in_as(LEADERSHIP).get(EVIDENCE_PATH).json()

    assert body["count"] > DEFAULT_PAGE_SIZE
    assert len(body["results"]) == DEFAULT_PAGE_SIZE
    assert body["next"] is not None


@pytest.mark.django_db
def test_a_client_cannot_ask_for_a_bigger_page() -> None:
    """`page_size_query_param` is `None`, so the parameter is not refused -- it is inert.

    Deliberately stronger than policing a maximum, and asserted through a request
    because "ignored" and "honoured" look identical in a settings dict.
    """
    UserFactory.create_batch(A_PAGE_AND_ONE)

    body = signed_in_as(LEADERSHIP).get(EVIDENCE_PATH, {"page_size": A_PAGE_AND_ONE}).json()

    assert len(body["results"]) == DEFAULT_PAGE_SIZE
