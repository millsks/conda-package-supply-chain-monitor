"""Every surface that lists packages reads the same search, spelled the same way.

`CPM-APP-S18` AC 4. The per-surface cases live beside the surfaces they are about --
`test_package_health_view.py`, `test_queue_views.py`, `test_reports.py` -- and each
proves its own page narrows. What none of them can prove is the property that only
exists *across* them: that a URL a reviewer sends a colleague means the same thing
wherever it is pasted.

**The roster is read off the code rather than written here**, so a report or a queue
added later is covered by this file the day it exists rather than the day somebody
remembers to add it. That is the difference between an audit and a list.

`tests/unit/django_apps/test_search_parameter_audit.py` is the static half: no module
and no template but one may spell the parameter itself. This is the behavioural half:
every surface actually reads it. Both are needed -- a view can import `SEARCH_PARAM`
faithfully and never pass it to a queryset, which is a page with a search box that
does nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from conda_sentinel.core.permissions import PRODUCT_ROLES
from conda_sentinel.surface.reports import REPORTS
from conda_sentinel.surface.search import SEARCH_PARAM
from conda_sentinel.workflow.states import Queue
from tests.factories import UserFactory

if TYPE_CHECKING:
    from django_service.users.models import User

pytestmark = pytest.mark.integration

#: A fragment chosen to match nothing, so a surface that ignored it would come back
#: with rows and fail rather than agreeing by accident on an empty database.
A_FRAGMENT: Final[str] = "no-package-is-called-this"


def every_listing_url() -> list[str]:
    """Return every URL that lists packages and therefore must take a search.

    Enumerated from `REPORTS` and `Queue` rather than written out, so the sweep grows
    with the product.

    Returns:
        The paths, health table first.

    """
    return [
        reverse("conda_sentinel:package-health"),
        *(reverse("conda_sentinel:queue", kwargs={"queue": queue.value}) for queue in Queue),
        *(reverse("conda_sentinel:report", kwargs={"slug": report.slug}) for report in REPORTS),
    ]


def a_reader_of_everything() -> APIClient:
    """Return a client holding every product role.

    The three queues are scoped one role each (`CPM-AD-13`), so a sweep across all of
    them needs somebody who can open all of them -- which is what the local
    `operations` persona exists for outside the suite.

    Returns:
        An authenticated client.

    """
    user: User = UserFactory.create()
    for role in PRODUCT_ROLES:
        user.groups.add(Group.objects.get(name=getattr(settings.ROLE_CONTRACT, role)))
    client = APIClient()
    client.force_login(user)
    return client


def test_the_sweep_covers_every_surface_the_story_names() -> None:
    """Because an enumeration that returned nothing would pass every case below.

    Ten: the health table, three queues, six reports. The number is asserted so that
    a report or a queue *disappearing* fails here too, not only an added one being
    covered.
    """
    expected = 1 + len(Queue) + len(REPORTS)

    assert len(every_listing_url()) == expected
    assert len(set(every_listing_url())) == expected


@pytest.mark.django_db
@pytest.mark.parametrize("path", every_listing_url(), ids=lambda path: path.strip("/").replace("/", "-"))
def test_every_listing_surface_answers_a_search_rather_than_refusing_it(path: str) -> None:
    """The rule `CPM-APP-S17` set, held on every surface it now reaches.

    A name is not a closed vocabulary, so a fragment nothing matches is a result. A
    surface that had wired the box but passed the raw parameter to a facet reader
    would 400 here, which is the shape of the mistake this prevents.

    Args:
        path: The surface under test.

    """
    response = a_reader_of_everything().get(f"{path}?{SEARCH_PARAM}={A_FRAGMENT}")

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
@pytest.mark.parametrize("path", every_listing_url(), ids=lambda path: path.strip("/").replace("/", "-"))
def test_every_listing_surface_offers_the_search_control(path: str) -> None:
    """A view that read the parameter and rendered no box would be a URL-only feature.

    Asserted through the rendered page rather than the context, because the box is
    what a reader can actually reach -- and it is an `include`, so a template that
    forgot it is invisible to everything else.

    Args:
        path: The surface under test.

    """
    body = a_reader_of_everything().get(path).content.decode()

    assert 'type="search"' in body, f"{path} reads the search but offers no way to enter one"
    assert f'name="{SEARCH_PARAM}"' in body


@pytest.mark.django_db
@pytest.mark.parametrize("path", every_listing_url(), ids=lambda path: path.strip("/").replace("/", "-"))
def test_every_listing_surface_puts_the_fragment_back_in_the_box(path: str) -> None:
    """So a reader can see what is in force, and correct it without retyping it.

    This is the case that catches a view which reads `?q=` for its queryset and never
    passes it to the template: the page narrows, and the box beside it is empty.

    Args:
        path: The surface under test.

    """
    response = a_reader_of_everything().get(f"{path}?{SEARCH_PARAM}=aiohttp")

    assert response.context["search"] == "aiohttp"
    assert 'value="aiohttp"' in response.content.decode()
