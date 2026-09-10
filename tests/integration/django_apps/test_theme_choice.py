"""`CPM-APP-S11`: light, dark, or the machine's answer — and the third is a choice.

Five criteria, and the one that shapes the implementation is AC 3: the choice has to
be honoured on the **first paint**. That is why the mechanism is a cookie read by the
server rather than `localStorage` read by a script — a client-side toggle cannot know
the choice before the document loads, so it paints the default and corrects it, which
is the flash of the wrong theme every such implementation has. A test can assert the
attribute is in the delivered HTML; it could not assert the absence of a flash.

**AC 4 is the one worth arguing about.** `auto` renders *no* `data-theme` attribute,
and the absence is the mechanism rather than a shortcut: the stylesheet's
`prefers-color-scheme` block only decides when nothing has overridden it. A case that
asserted `data-theme="auto"` would be asserting the bug.

**AC 2 changed after the first implementation**, at the product owner's direction:
the default is light rather than the machine's answer. The half that is easy to get
wrong is that the default has to *assert itself* -- the dark block is guarded by
`:root:not([data-theme="light"])`, so a default of light that rendered nothing would
still hand a dark-desktop reader the dark palette. The case below asserts the
attribute is present, which is the only version of that claim a test can make.

**AC 5 is about a cookie being client-supplied.** Nothing in the control can produce a
value outside the three; a hand-made request can, and the closed set is what keeps an
arbitrary string out of a rendered attribute.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.test import APIClient

from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER
from conda_sentinel.surface.theming import AUTO
from conda_sentinel.surface.theming import DEFAULT
from conda_sentinel.surface.theming import THEME_COOKIE
from conda_sentinel.surface.theming import THEME_COOKIE_MAX_AGE
from conda_sentinel.surface.theming import THEMES
from tests.factories import UserFactory

if TYPE_CHECKING:
    from django_service.users.models import User

pytestmark = pytest.mark.integration

#: A theme nothing in the product offers, for the case that matters about cookies.
NOT_A_THEME: Final[str] = "neon"

#: A host this deployment is not, for the redirect case.
SOMEBODY_ELSES_HOST: Final[str] = "https://evil.example.com/collect"

#: How many controls a page carries. One: the control is on the base template, and a
#: second would mean a page had grown its own.
ONE_CONTROL: Final[int] = 1


def a_reader() -> APIClient:
    """Return a client signed in as somebody holding every product role.

    Returns:
        The client. Every role, because none of these cases is about scoping and a
        refusal here would be a fixture that forgot a group rather than a finding.

    """
    user: User = UserFactory.create()
    for role in (SECURITY_REVIEWER, PACKAGING_ENGINEER, LEADERSHIP):
        user.groups.add(Group.objects.get(name=getattr(settings.ROLE_CONTRACT, role)))
    client = APIClient()
    client.force_login(user)
    return client


def document_element(response: object) -> str:
    """Return the rendered `<html>` tag.

    Args:
        response: The response to read.

    Returns:
        The opening tag, which is where `data-theme` lives and therefore the only
        thing these cases care about.

    """
    body = response.content.decode()  # type: ignore[attr-defined]
    found = re.search(r"<html[^>]*>", body)
    return found.group(0) if found else ""


def choose(client: APIClient, theme: str, *, then: str = "/home/") -> object:
    """Choose a theme.

    Args:
        client: Who is choosing.
        theme: What they chose.
        then: Where they were.

    Returns:
        The redirect.

    """
    return client.post(reverse("conda_sentinel:theme"), {"theme": theme, "next": then})


# ---------------------------------------------------------------------------
# AC 2 and AC 4: auto is the default, and it asserts nothing.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_reader_who_has_chosen_nothing_gets_light() -> None:
    """AC 2, and the assertion is that the default is *written* rather than implied.

    A default that rendered no attribute would not be a default: the stylesheet's dark
    block is guarded by `:root:not([data-theme="light"])`, so a dark-desktop reader
    who had chosen nothing would get dark. This is the case that catches the
    difference between "we default to light" and "we default to light on machines
    that are already light".
    """
    element = document_element(a_reader().get(reverse("conda_sentinel:home")))

    assert f'data-theme="{DEFAULT}"' in element, element


@pytest.mark.django_db
def test_the_default_is_light_and_the_control_says_so() -> None:
    """The reader can see what they have without having chosen it.

    A control that marked nothing until somebody clicked would leave the default
    looking like an absence, which is exactly what it is not.
    """
    body = a_reader().get(reverse("conda_sentinel:home")).content.decode()

    marked = re.findall(r'value="(\w+)"\s+class="on" aria-current="true"', body)
    assert marked == [DEFAULT]


@pytest.mark.django_db
def test_choosing_auto_again_returns_the_decision_to_the_machine() -> None:
    """AC 4. `auto` is a choice a reader makes, not the state they are left in.

    It is the only one of the three that renders *no* attribute, and that is what
    hands the decision to `prefers-color-scheme`. A third state rendered as
    `data-theme="auto"` would pin the reader to the light palette while they believed
    they had asked to follow the machine -- the stylesheet has no rule for that value.

    Reached from `dark` rather than from the default, so the case shows the attribute
    being *removed* rather than never having been there.
    """
    client = a_reader()
    choose(client, "dark")
    dark = document_element(client.get(reverse("conda_sentinel:home")))

    choose(client, AUTO)
    auto = document_element(client.get(reverse("conda_sentinel:home")))

    assert 'data-theme="dark"' in dark
    assert "data-theme" not in auto, auto


# ---------------------------------------------------------------------------
# AC 3: honoured on the first paint.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chosen", ["light", "dark"])
@pytest.mark.django_db
def test_a_chosen_theme_is_in_the_html_the_server_delivers(chosen: str) -> None:
    """AC 3, and this is what "no flash" reduces to in a test.

    The attribute is in the delivered document rather than applied to it afterwards,
    so there is no moment at which the page is painted in the other theme. A test
    cannot observe a flash; it can observe that the thing which causes one -- a
    correction after load -- is not how this works.

    Args:
        chosen: The theme to choose.

    """
    client = a_reader()

    choose(client, chosen)
    element = document_element(client.get(reverse("conda_sentinel:home")))

    assert f'data-theme="{chosen}"' in element


@pytest.mark.django_db
def test_the_choice_survives_to_the_next_page_and_is_remembered() -> None:
    """A preference nobody has to think about is the point.

    The cookie's lifetime is asserted because the failure it prevents is quiet: a
    session cookie would work in every test and send the reader back to light every
    morning.
    """
    client = a_reader()

    response = choose(client, "dark", then=reverse("conda_sentinel:package-health"))

    assert response.status_code == HTTPStatus.FOUND  # type: ignore[attr-defined]
    assert response["Location"] == reverse("conda_sentinel:package-health")  # type: ignore[index]
    assert client.cookies[THEME_COOKIE]["max-age"] == THEME_COOKIE_MAX_AGE
    assert 'data-theme="dark"' in document_element(client.get(reverse("conda_sentinel:coverage")))


# ---------------------------------------------------------------------------
# AC 1: the control is on every page, and marks what is in force.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["conda_sentinel:home", "conda_sentinel:package-health", "conda_sentinel:coverage"],
)
@pytest.mark.django_db
def test_the_control_is_on_every_page(name: str) -> None:
    """AC 1, over the pages rather than over the base template.

    Asserting the template contains a form would pass while a page that overrode the
    wrong block rendered without it. Walking real pages is what makes "every page"
    mean what it says.

    Args:
        name: The route to open.

    """
    body = a_reader().get(reverse(name)).content.decode()

    assert body.count('class="themeset"') == ONE_CONTROL
    for option in THEMES:
        assert f'value="{option}"' in body, option


@pytest.mark.django_db
def test_the_control_marks_which_theme_is_in_force() -> None:
    """AC 1's second half. A control that showed three identical buttons would leave a
    reader unable to tell what they had chosen.

    `aria-current` as well as the class, because "which one is on" is a fact about the
    control rather than a colour, and a reader using a screen reader needs it too.
    """
    client = a_reader()

    choose(client, "light")
    body = client.get(reverse("conda_sentinel:home")).content.decode()

    marked = re.findall(r'value="(\w+)"\s+class="on" aria-current="true"', body)
    assert marked == ["light"], body[body.find("themeset") : body.find("themeset") + 600]


# ---------------------------------------------------------------------------
# AC 5, and the two refusals a control cannot produce but a request can.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_theme_outside_the_three_falls_back_to_the_default() -> None:
    """AC 5. A cookie is client-supplied, and the closed set is the whole defence.

    Nothing in the control can send this; a hand-made request can, and an arbitrary
    string reaching a rendered attribute is how a preference becomes an injection
    point.
    """
    client = a_reader()
    choose(client, "dark")

    choose(client, NOT_A_THEME)
    element = document_element(client.get(reverse("conda_sentinel:home")))

    assert f'data-theme="{DEFAULT}"' in element, element
    assert NOT_A_THEME not in element


@pytest.mark.django_db
def test_a_stored_cookie_outside_the_three_is_ignored() -> None:
    """The same rule from the other side: what is already in the jar.

    The case above tests the write path. This tests the read, because a cookie set by
    an older version of this product -- or by hand -- is a value the renderer has to
    survive rather than trust.
    """
    client = a_reader()
    client.cookies[THEME_COOKIE] = NOT_A_THEME

    element = document_element(client.get(reverse("conda_sentinel:home")))

    assert f'data-theme="{DEFAULT}"' in element, element
    assert NOT_A_THEME not in element


@pytest.mark.django_db
def test_the_return_path_cannot_be_pointed_at_another_host() -> None:
    """`next` comes from a form field, and a form field is attacker-supplied.

    Without the check this is an open redirect somebody can hang a phishing page off,
    reached through a URL that looks like this product's.
    """
    client = a_reader()

    response = choose(client, "dark", then=SOMEBODY_ELSES_HOST)

    assert response["Location"] == reverse("conda_sentinel:home")  # type: ignore[index]


@pytest.mark.django_db
def test_the_choice_is_not_made_by_a_get() -> None:
    """A GET that set a cookie would let a prefetch or a shared link change it.

    The last of those is the one that actually happens: a reader sends a colleague a
    URL and changes their colours.
    """
    response = a_reader().get(reverse("conda_sentinel:theme"))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_choosing_a_theme_needs_no_role() -> None:
    """The one surface in this product that is not role-gated, and deliberately.

    `CPM-AD-13` scopes access to evidence; a theme is not evidence. `CPM-APP-S12`
    brings the sign-in page into this product's shell and the control goes with it --
    a reader meets this product there, before they hold any role at all.
    """
    user: User = UserFactory.create()
    client = APIClient()
    client.force_login(user)

    response = choose(client, "dark")

    assert response.status_code == HTTPStatus.FOUND  # type: ignore[attr-defined]
    assert client.cookies[THEME_COOKIE].value == "dark"
