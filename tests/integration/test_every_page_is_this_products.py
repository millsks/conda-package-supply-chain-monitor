"""`CPM-APP-S12`: no page this deployment serves names a different product.

`CPM-RENAME-S02` put Conda-Sentinel on every operator-facing surface the *product*
owns and left the inherited ones alone. Eleven templates still extended the
accelerator's shell, and they were exactly the pages somebody reaches when they are
**not** on one of this product's screens: the root, `/about/`, sign-in, account
management, and 403/404/500.

**The error pages were the worst of it.** A reviewer who mistypes a package name is
shown a 404, at the moment they are least able to tell whether they are in the right
place -- and it was branded for a product they have never heard of.

**This module renders pages rather than reading templates**, and the difference is
AC 4's own wording: "the accelerator's own routes... none of them *serves* a page
naming a different product". A grep over `templates/` would flag a file nothing
routes and miss a name that arrives from a setting, a context processor or a
third-party form. What is served is the thing a reader sees.

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
from django.test import Client
from django.urls import reverse

from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER
from tests.factories import UserFactory

if TYPE_CHECKING:
    from django_service.users.models import User

pytestmark = pytest.mark.integration

#: What no served page may say.
#:
#: The accelerator this component was generated from. Matched case-insensitively and
#: as a phrase, because the failure is a *name* reaching a reader -- "accelerator" on
#: its own is an ordinary word that could legitimately appear in prose about
#: performance, and flagging it would make this sweep something people learn to work
#: around.
ANOTHER_PRODUCT: Final[tuple[str, ...]] = (
    "django 15-factor application accelerator",
    "django 15-factor base",
)

#: This product's own name, so the sweep is not satisfied by a page naming nobody.
THIS_PRODUCT: Final[str] = "conda sentinel"

#: The pages a person reaches without knowing a product URL. AC 2's list, verbatim.
#:
#: Written out rather than swept off the resolver: the point is that *these specific
#: pages* were wrong, and a sweep that enumerated routes would quietly stop covering
#: one the day it acquired a parameter.
PAGES_ANYBODY_REACHES: Final[tuple[str, ...]] = ("about", "account_login")


def a_reader() -> Client:
    """Return a client signed in as somebody holding every product role.

    Returns:
        The client.

    """
    user: User = UserFactory.create()
    for role in (SECURITY_REVIEWER, PACKAGING_ENGINEER, LEADERSHIP):
        user.groups.add(Group.objects.get(name=getattr(settings.ROLE_CONTRACT, role)))
    client = Client()
    client.force_login(user)
    return client


def names_another_product(body: str) -> list[str]:
    """Return whichever other-product names a page carries.

    Args:
        body: The rendered page.

    Returns:
        The names found, so a failure says which rather than that one exists.

    """
    lowered = body.lower()
    return [name for name in ANOTHER_PRODUCT if name in lowered]


# ---------------------------------------------------------------------------
# AC 1: the root.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_root_leads_to_this_products_home() -> None:
    """AC 1. It was the accelerator's landing page.

    **Followed rather than asserted on the first hop**, because `CPM-APP-S13` moved
    the pages under `/conda-sentinel/` and left the root leading here. What the
    criterion is about is where a reader who types the bare host ends up, and that is
    unchanged -- which is the reason this case follows redirects rather than being
    rewritten to assert a 302 and stop.
    """
    response = a_reader().get("/", follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.resolver_match is not None
    assert response.resolver_match.view_name == "conda_sentinel:home"


@pytest.mark.django_db
def test_the_home_page_has_one_address_and_the_root_redirects_to_it() -> None:
    """One canonical URL, which is why the root is a redirect and not a second mount.

    Two addresses for one page is what makes a link somebody pastes into a ticket
    disagree with the one in the navigation, and the disagreement is invisible until
    somebody compares them. A redirect has one address; a second `path("")` mounting
    the same view would have two.
    """
    assert reverse("conda_sentinel:home") == "/conda-sentinel/"

    landing = a_reader().get("/")

    assert landing.status_code == HTTPStatus.FOUND
    assert landing["Location"] == reverse("conda_sentinel:home")


# ---------------------------------------------------------------------------
# AC 2: every page a person reaches without knowing a product URL.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PAGES_ANYBODY_REACHES)
@pytest.mark.django_db
def test_a_page_anybody_reaches_carries_this_products_name(name: str) -> None:
    """AC 2, on the pages somebody meets before they know any product URL.

    Both halves: it names this product, and it names no other. Asserting only the
    absence would pass on a page that named nothing at all, which is a different
    failure with the same symptom -- a reader who still cannot tell where they are.

    Args:
        name: The route to open.

    """
    body = Client().get(reverse(name)).content.decode()

    assert names_another_product(body) == []
    assert THIS_PRODUCT in body.lower()


@pytest.mark.django_db
def test_the_sign_in_page_carries_the_products_chrome_and_the_theme_control() -> None:
    """The page somebody meets this product on, and the reason `ThemeView` is ungated.

    `CPM-APP-S11` left the theme control behind no role precisely so it could be
    here. A control that appeared only after signing in would be missing from the one
    screen a reader sees before they have decided whether to trust the product.
    """
    body = Client().get(reverse("account_login")).content.decode()

    assert 'class="app-top"' in body
    assert 'class="themeset"' in body


@pytest.mark.django_db
def test_an_account_page_carries_this_products_name() -> None:
    """`/users/<name>/` is the accelerator's view, in this product's shell now."""
    client = a_reader()
    username = client.session.get("_auth_user_id")
    assert username is not None

    user: User = UserFactory._meta.model.objects.get(pk=username)  # noqa: SLF001 - the model, not a private helper
    body = client.get(reverse("users:detail", kwargs={"username": user.username})).content.decode()

    assert names_another_product(body) == []
    assert THIS_PRODUCT in body.lower()


# ---------------------------------------------------------------------------
# AC 2's hardest case: the pages that render when something has gone wrong.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_page_that_does_not_exist_is_still_this_products() -> None:
    """The 404 is the page this story is most about.

    A reviewer who mistypes a package name is shown it at the moment they are least
    able to tell whether they are in the right place, and it named a product they
    have never heard of.
    """
    response = a_reader().get("/no-such-page-anywhere/")
    body = response.content.decode()

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert names_another_product(body) == []
    assert THIS_PRODUCT in body.lower()


@pytest.mark.django_db
def test_a_refusal_is_still_this_products() -> None:
    """The 403, reached the way readers actually reach it: a queue that is not theirs.

    Rendered rather than fetched from the template, because a refusal goes through
    `RoleRequiredMixin` and Django's handler, and what a reader sees is the end of
    that path rather than the file at the start of it.
    """
    user: User = UserFactory.create()
    user.groups.add(Group.objects.get(name=settings.ROLE_CONTRACT.security_reviewer))
    client = Client()
    client.force_login(user)

    response = client.get(reverse("conda_sentinel:queue", kwargs={"queue": "remediation"}))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert names_another_product(response.content.decode()) == []


# ---------------------------------------------------------------------------
# AC 3: the shell renders for somebody who is not signed in.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_shell_offers_no_navigation_a_signed_out_reader_cannot_use() -> None:
    """AC 3. Every entry behind the nav refuses an anonymous visitor anyway.

    So hiding it protects nothing -- what it avoids is offering somebody five links
    that all go to the same sign-in page, which reads as a broken product rather than
    a locked one.
    """
    body = Client().get(reverse("account_login")).content.decode()

    navigation = re.search(r'<nav class="app-nav">(.*?)</nav>', body, re.S)
    assert navigation is not None, "the chrome rendered without its navigation element at all"
    assert "<a" not in navigation.group(1), navigation.group(1)


@pytest.mark.django_db
def test_the_shell_offers_the_navigation_to_a_reader_who_can_use_it() -> None:
    """The other side, or the case above would pass on a product with no navigation."""
    body = a_reader().get(reverse("conda_sentinel:home")).content.decode()

    navigation = re.search(r'<nav class="app-nav">(.*?)</nav>', body, re.S)
    assert navigation is not None
    assert navigation.group(1).count("<a") > 1


# ---------------------------------------------------------------------------
# AC 4: swept, so the eleven cannot become twelve.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_route_this_deployment_serves_names_another_product() -> None:
    """AC 4, over what is served rather than over what is on disk.

    A grep of `templates/` would flag a file nothing routes -- `pages/home.html` is
    one, unreferenced since the root became this product's -- and would miss a name
    arriving from a setting, a context processor or a third-party form. What a reader
    sees is what is rendered.

    Every route is opened as a reader holding every role, so a page that renders
    differently for somebody signed in is checked in the state most people see it.
    """
    client = a_reader()
    offenders: list[str] = []

    for path in (
        "/",
        "/about/",
        "/accounts/login/",
        reverse("conda_sentinel:package-health"),
        reverse("conda_sentinel:coverage"),
        "/no-such-page/",
    ):
        body = client.get(path, follow=True).content.decode()
        found = names_another_product(body)
        if found:
            offenders.append(f"{path} names {found}")

    assert offenders == [], (
        f"these served pages name a product this deployment is not: {offenders}. CPM-APP-S12: a reader who "
        f"cannot tell which product they are in cannot tell whether they are in the right one."
    )
